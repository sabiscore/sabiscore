"""docs/DEBT.md item 35(b): the Class C live-fixture identity rebind executor.

These run on SQLite, so the PostgreSQL lock acquisition is bypassed by calling
``apply_fixture_identity_rebind`` through a patched lock helper -- the lock
path itself is asserted separately (it must *refuse* a non-PostgreSQL bind).
Everything else -- digest verification, the optimistic row precondition, both
postconditions, and the ready/blocked split -- is dialect-independent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.db.models import MatchPredictionLog
from src.services.canonical_identity_service import ensure_canonical_fixture
from src.services.fixture_identity_rebind_apply_service import (
    FixtureIdentityRebindApplyResult,
    _assert_ready_entries_are_applicable,
    acquire_fixture_identity_rebind_locks,
    apply_fixture_identity_rebind,
)
from src.services.fixture_identity_rebind_service import (
    FixtureIdentityRebindEntry,
    FixtureIdentityRebindManifest,
    build_fixture_identity_rebind_manifest,
)

_FUTURE = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
_PROVIDER = "football-data.org"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


async def _seed_mismatched_fixture(
    session: AsyncSession,
    *,
    match_id: str,
    league_id: str = "EPL",
    with_prediction: bool = False,
) -> tuple[str, str]:
    """One live fixture whose stored participants differ from the verified
    canonical identity. Returns (stored_home_team_id, stored_away_team_id)."""
    existing_league = await session.get(League, league_id)
    if existing_league is None:
        session.add(League(id=league_id, name=league_id, country="test"))

    stored_home = f"fd-team-{league_id.lower()}:old-{match_id}-home"
    stored_away = f"fd-team-{league_id.lower()}:old-{match_id}-away"
    session.add(Team(id=stored_home, name="Stale Home FC", league_id=league_id))
    session.add(Team(id=stored_away, name="Stale Away FC", league_id=league_id))
    await session.flush()

    session.add(
        Match(
            id=match_id,
            league_id=league_id,
            home_team_id=stored_home,
            away_team_id=stored_away,
            match_date=_FUTURE,
            season="2026/2027",
            status="scheduled",
        )
    )
    await session.flush()
    await ensure_canonical_fixture(
        session,
        provider=_PROVIDER,
        provider_event_id=match_id,
        competition_id=league_id,
        competition_name=league_id,
        home_provider_id=f"{match_id}-home",
        home_name="Verified Home FC",
        away_provider_id=f"{match_id}-away",
        away_name="Verified Away FC",
        kickoff_utc=_FUTURE,
        season="2026/2027",
        status="scheduled",
        evidence={
            "home_provider_team_id": f"{match_id}-home",
            "away_provider_team_id": f"{match_id}-away",
        },
    )

    if with_prediction:
        session.add(
            MatchPredictionLog(
                match_id=match_id,
                model_version="v5_phase7",
                home_probability=0.4,
                draw_probability=0.3,
                away_probability=0.3,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

    await session.commit()
    return stored_home, stored_away


async def _apply(session: AsyncSession, sha: str) -> FixtureIdentityRebindApplyResult:
    """Invoke the executor with the PostgreSQL-only lock step neutralised."""
    with patch(
        "src.services.fixture_identity_rebind_apply_service.acquire_fixture_identity_rebind_locks",
        new=lambda *a, **k: _noop(),
    ):
        return await apply_fixture_identity_rebind(session, expected_manifest_sha256=sha)


async def _noop() -> None:
    return None


async def test_rebind_repoints_only_ready_entries_leaving_blocked_untouched(
    session: AsyncSession,
) -> None:
    ready_home, ready_away = await _seed_mismatched_fixture(session, match_id="fd-ready-1")
    blocked_home, blocked_away = await _seed_mismatched_fixture(
        session, match_id="fd-blocked-1", with_prediction=True
    )

    manifest = await build_fixture_identity_rebind_manifest(session)
    assert manifest.summary["total_mismatched"] == 2
    assert manifest.summary["rebind_ready_count"] == 1
    assert manifest.summary["blocked_count"] == 1

    result = await _apply(session, manifest.manifest_sha256)

    assert result.rebound_count == 1
    assert result.affected_match_ids == ("fd-ready-1",)
    assert result.skipped_blocked_match_ids == ("fd-blocked-1",)

    ready_match = await session.get(Match, "fd-ready-1")
    assert ready_match is not None
    assert ready_match.home_team_id not in (ready_home, ready_away)
    assert ready_match.away_team_id not in (ready_home, ready_away)

    # The blocked fixture's stored identity is completely untouched.
    blocked_match = await session.get(Match, "fd-blocked-1")
    assert blocked_match is not None
    assert blocked_match.home_team_id == blocked_home
    assert blocked_match.away_team_id == blocked_away

    # Residual check: the rebound fixture no longer appears at all on re-review.
    residual = await build_fixture_identity_rebind_manifest(session)
    assert {e.match_id for e in residual.entries} == {"fd-blocked-1"}


async def test_a_stale_manifest_digest_is_refused(session: AsyncSession) -> None:
    await _seed_mismatched_fixture(session, match_id="fd-ready-1")
    with pytest.raises(RuntimeError, match="manifest changed since review"):
        await _apply(session, "0" * 64)


async def test_a_ready_row_that_moved_since_review_fails_the_precondition(
    session: AsyncSession,
) -> None:
    """Someone else repointing the row between review and apply must abort the
    whole run rather than overwrite their change."""
    await _seed_mismatched_fixture(session, match_id="fd-ready-1")
    manifest = await build_fixture_identity_rebind_manifest(session)

    match = await session.get(Match, "fd-ready-1")
    assert match is not None
    match.home_team_id = "someone-elses-value"
    await session.commit()

    # The digest is derived from the entries, so moving the row changes it too;
    # assert we fail closed, whichever guard trips first.
    with pytest.raises(RuntimeError):
        await _apply(session, manifest.manifest_sha256)


async def test_an_all_blocked_manifest_is_refused(session: AsyncSession) -> None:
    """Nothing rebind-ready must be an explicit refusal, never a silent
    no-op that reports success."""
    await _seed_mismatched_fixture(session, match_id="fd-blocked-1", with_prediction=True)
    manifest = await build_fixture_identity_rebind_manifest(session)
    assert manifest.summary["rebind_ready_count"] == 0
    with pytest.raises(RuntimeError, match="no rebind-ready entries"):
        await _apply(session, manifest.manifest_sha256)


async def test_lock_acquisition_refuses_a_non_postgresql_bind(session: AsyncSession) -> None:
    """The real lock path is PostgreSQL-only and must say so rather than
    silently proceeding unlocked on SQLite."""
    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        await acquire_fixture_identity_rebind_locks(session)


def _entry(**overrides: object) -> FixtureIdentityRebindEntry:
    base: dict[str, object] = {
        "match_id": "fd-x",
        "league_id": "EPL",
        "kickoff_utc": _FUTURE.isoformat(),
        "status": "scheduled",
        "stored_home_team_id": "stored-home",
        "stored_home_team_name": "Stored Home FC",
        "stored_away_team_id": "stored-away",
        "stored_away_team_name": "Stored Away FC",
        "verified_home_team_id": "verified-home",
        "verified_home_team_name": "Verified Home FC",
        "verified_away_team_id": "verified-away",
        "verified_away_team_name": "Verified Away FC",
        "blockers": (),
    }
    base.update(overrides)
    return FixtureIdentityRebindEntry(**base)  # type: ignore[arg-type]


def _manifest(*entries: FixtureIdentityRebindEntry) -> FixtureIdentityRebindManifest:
    return FixtureIdentityRebindManifest(
        schema_version=2,
        manifest_sha256="0" * 64,
        summary={},
        entries=tuple(entries),
    )


def test_assert_applicable_refuses_a_self_play_verified_identity() -> None:
    manifest = _manifest(_entry(verified_away_team_id="verified-home"))
    with pytest.raises(RuntimeError, match="self-play"):
        _assert_ready_entries_are_applicable(manifest)


def test_assert_applicable_refuses_a_duplicated_match() -> None:
    manifest = _manifest(_entry(), _entry())
    with pytest.raises(RuntimeError, match="more than once"):
        _assert_ready_entries_are_applicable(manifest)


def test_assert_applicable_refuses_an_empty_ready_set() -> None:
    manifest = _manifest(_entry(blockers=("HAS_EXISTING_PREDICTIONS",)))
    with pytest.raises(RuntimeError, match="no rebind-ready entries"):
        _assert_ready_entries_are_applicable(manifest)


async def test_self_play_postcondition_is_caught(session: AsyncSession) -> None:
    """If the write somehow left a fixture pointing the same team at both
    sides, the postcondition -- not the caller -- must be what refuses it."""
    stored_home, _ = await _seed_mismatched_fixture(session, match_id="fd-ready-1")
    manifest = await build_fixture_identity_rebind_manifest(session)
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]

    # Force the away side to already equal what the home side is about to
    # become, so after the real write both columns hold the same team.
    match = await session.get(Match, "fd-ready-1")
    assert match is not None
    match.away_team_id = entry.verified_home_team_id
    await session.commit()

    # Changing away_team_id modifies the manifest SHA, so whichever guard
    # trips first (stale-digest or self-play postcondition) is fine.
    with pytest.raises(RuntimeError):
        await _apply(session, manifest.manifest_sha256)

    # And the row must not have been left half-written on the failure path.
    reverted = await session.get(Match, "fd-ready-1")
    assert reverted is not None
    assert reverted.home_team_id == stored_home
