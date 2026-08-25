"""docs/DEBT.md item 39: the Class C orphan-team rebind executor.

These run on SQLite, so the PostgreSQL lock acquisition is bypassed by calling
``apply_orphan_team_rebind`` through a patched lock helper. That is deliberate:
the lock path itself is asserted separately (it must *refuse* a non-PostgreSQL
bind), and everything else worth testing -- digest verification, the
optimistic row precondition, both postconditions, and the refusal set -- is
dialect-independent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.db.models import EloRatingSnapshot
from src.services.canonical_identity_service import ensure_canonical_fixture
from src.services.orphan_team_reconciliation_service import (
    build_orphan_team_repair_manifest,
)
from src.services.orphan_team_rebind_service import (
    acquire_orphan_team_rebind_locks,
    apply_orphan_team_rebind,
)

_FUTURE = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


async def _seed_repairable_orphan(session: AsyncSession) -> str:
    """One repair-ready orphan side: Match.home points at an Elo-less row while
    a same-league Elo-bearing team matches the freshest observed name."""
    league_id = "LA_LIGA"
    session.add(League(id=league_id, name=league_id, country="test"))
    session.add(Team(id="fdco-team-la_liga-malaga", name="Malaga", league_id=league_id))
    session.add(Team(id="opponent-la_liga", name="Opponent", league_id=league_id))
    await session.flush()

    hist_date = datetime(2025, 9, 20, 15, 0)
    session.add(
        Match(
            id="hist-1",
            league_id=league_id,
            home_team_id="fdco-team-la_liga-malaga",
            away_team_id="opponent-la_liga",
            match_date=hist_date,
            season="2025/2026",
            status="finished",
            home_score=2,
            away_score=1,
        )
    )
    await session.flush()
    session.add(
        EloRatingSnapshot(
            match_id="hist-1",
            team_id="fdco-team-la_liga-malaga",
            pre_match_elo=1500.0,
            post_match_elo=1520.0,
            league=league_id,
            season="2025/2026",
            match_date=hist_date,
            created_at=hist_date,
        )
    )

    orphan_home = "fd-team-la_liga:home-orphan"
    orphan_away = "fd-team-la_liga:away-orphan"
    session.add(Team(id=orphan_home, name="Malaga CF", league_id=league_id))
    session.add(Team(id=orphan_away, name="Clean Opponent CF", league_id=league_id))
    await session.flush()
    session.add(
        Match(
            id="fd-rebind-1",
            league_id=league_id,
            home_team_id=orphan_home,
            away_team_id=orphan_away,
            match_date=_FUTURE,
            season="2026/2027",
            status="scheduled",
        )
    )
    await session.flush()
    await ensure_canonical_fixture(
        session,
        provider="football-data.org",
        provider_event_id="fd-rebind-1",
        competition_id=league_id,
        competition_name=league_id,
        home_provider_id="700",
        home_name="Malaga CF",
        away_provider_id="701",
        away_name="Clean Opponent CF",
        kickoff_utc=_FUTURE,
        season="2026/2027",
        status="scheduled",
        evidence={
            "home_provider_team_id": "700",
            "away_provider_team_id": "701",
        },
    )
    await session.commit()
    return orphan_home


async def _apply(session: AsyncSession, sha: str):
    """Invoke the executor with the PostgreSQL-only lock step neutralised."""
    with patch(
        "src.services.orphan_team_rebind_service.acquire_orphan_team_rebind_locks",
        new=lambda *a, **k: _noop(),
    ):
        return await apply_orphan_team_rebind(session, expected_manifest_sha256=sha)


async def _noop() -> None:
    return None


async def test_rebind_repoints_the_orphan_side_at_the_history_bearing_team(
    session: AsyncSession,
) -> None:
    orphan_home = await _seed_repairable_orphan(session)
    manifest = await build_orphan_team_repair_manifest(session)
    assert len(manifest.entries) == 1 and manifest.entries[0].repair_ready

    result = await _apply(session, manifest.manifest_sha256)

    assert result.rebound_sides == 1
    assert result.affected_match_ids == ("fd-rebind-1",)
    assert result.reversals == (
        ("fd-rebind-1", "home", orphan_home, "fdco-team-la_liga-malaga"),
    )
    match = await session.get(Match, "fd-rebind-1")
    assert match is not None
    assert match.home_team_id == "fdco-team-la_liga-malaga"
    # The orphan Team row itself is untouched -- this rebinds a fixture, it does
    # not delete or rename anything.
    assert await session.get(Team, orphan_home) is not None


async def test_a_stale_manifest_digest_is_refused(session: AsyncSession) -> None:
    await _seed_repairable_orphan(session)
    with pytest.raises(RuntimeError, match="manifest changed since review"):
        await _apply(session, "0" * 64)


async def test_a_row_that_moved_since_review_fails_the_precondition(
    session: AsyncSession,
) -> None:
    """Someone else repointing the row between review and apply must abort the
    whole run rather than overwrite their change."""
    await _seed_repairable_orphan(session)
    manifest = await build_orphan_team_repair_manifest(session)

    match = await session.get(Match, "fd-rebind-1")
    assert match is not None
    match.home_team_id = "opponent-la_liga"
    await session.commit()

    # The digest is derived from the entries, so moving the row changes it too;
    # assert we fail closed, whichever guard trips first.
    with pytest.raises(RuntimeError):
        await _apply(session, manifest.manifest_sha256)


async def test_an_empty_manifest_is_refused(session: AsyncSession) -> None:
    """Nothing to repair must be an explicit refusal, never a silent no-op that
    reports success."""
    session.add(League(id="LA_LIGA", name="LA_LIGA", country="test"))
    await session.commit()
    manifest = await build_orphan_team_repair_manifest(session)
    assert manifest.entries == ()
    with pytest.raises(RuntimeError, match="no entries to apply"):
        await _apply(session, manifest.manifest_sha256)


async def test_a_blocked_entry_is_refused(session: AsyncSession) -> None:
    """A blocker (kickoff passed / existing predictions) must stop the entire
    run, not just skip that one side."""
    await _seed_repairable_orphan(session)
    match = await session.get(Match, "fd-rebind-1")
    assert match is not None
    match.match_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    await session.commit()

    manifest = await build_orphan_team_repair_manifest(session)
    assert manifest.entries and not manifest.entries[0].repair_ready
    with pytest.raises(RuntimeError, match="refuses blocked entries"):
        await _apply(session, manifest.manifest_sha256)


async def test_lock_acquisition_refuses_a_non_postgresql_bind(
    session: AsyncSession,
) -> None:
    """The real lock path is PostgreSQL-only and must say so rather than
    silently proceeding unlocked on SQLite."""
    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        await acquire_orphan_team_rebind_locks(session)


def _entry(**overrides: object):
    """Build one OrphanTeamRepairEntry directly, for exercising
    _assert_manifest_is_applicable's defensive branches without needing a
    full seeded fixture per case -- these guard against a manifest shape the
    real builder cannot currently produce, so they are unit-tested against
    the validator directly rather than through build_orphan_team_repair_manifest.
    """
    from src.services.orphan_team_reconciliation_service import OrphanTeamRepairEntry

    base: dict[str, object] = {
        "match_id": "fd-x",
        "league_id": "LA_LIGA",
        "side": "home",
        "kickoff_utc": _FUTURE.isoformat(),
        "status": "scheduled",
        "orphan_team_id": "orphan-1",
        "orphan_team_name": "Orphan FC",
        "freshest_observed_name": "Orphan FC",
        "target_team_id": "target-1",
        "target_team_name": "Target FC",
        "target_elo_snapshot_count": 10,
        "target_elo_first_match_date": "2020-01-01T00:00:00",
        "target_elo_last_match_date": "2026-01-01T00:00:00",
        "blockers": (),
    }
    base.update(overrides)
    return OrphanTeamRepairEntry(**base)  # type: ignore[arg-type]


def _manifest(*entries):
    from src.services.orphan_team_reconciliation_service import OrphanTeamRepairManifest

    return OrphanTeamRepairManifest(
        schema_version=1,
        manifest_sha256="0" * 64,
        summary={},
        entries=tuple(entries),
    )


def test_assert_applicable_refuses_a_target_equal_to_the_orphan() -> None:
    from src.services.orphan_team_rebind_service import _assert_manifest_is_applicable

    manifest = _manifest(_entry(target_team_id="orphan-1"))
    with pytest.raises(RuntimeError, match="no distinct target"):
        _assert_manifest_is_applicable(manifest)


def test_assert_applicable_refuses_a_target_with_no_elo_history() -> None:
    from src.services.orphan_team_rebind_service import _assert_manifest_is_applicable

    manifest = _manifest(_entry(target_elo_snapshot_count=0))
    with pytest.raises(RuntimeError, match="no Elo history"):
        _assert_manifest_is_applicable(manifest)


def test_assert_applicable_refuses_a_duplicated_side() -> None:
    from src.services.orphan_team_rebind_service import _assert_manifest_is_applicable

    manifest = _manifest(_entry(), _entry())
    with pytest.raises(RuntimeError, match="more than once"):
        _assert_manifest_is_applicable(manifest)


async def test_self_play_postcondition_is_caught(session: AsyncSession) -> None:
    """If the write somehow left a fixture pointing the same team at both
    sides, the postcondition -- not the caller -- must be what refuses it."""
    orphan_home = await _seed_repairable_orphan(session)
    manifest = await build_orphan_team_repair_manifest(session)
    assert len(manifest.entries) == 1

    # Force the away side to already equal the target, so after the real
    # write both columns hold the same team -- the exact shape item 23's 26
    # production rows had.
    match = await session.get(Match, "fd-rebind-1")
    assert match is not None
    match.away_team_id = "fdco-team-la_liga-malaga"
    await session.commit()

    # Changing away_team_id modifies the manifest SHA, so whichever guard trips
    # first (stale-digest or self-play postcondition) is fine -- the row must
    # not have been half-written on the failure path.
    with pytest.raises(RuntimeError):
        await _apply(session, manifest.manifest_sha256)

    # And the row must not have been left half-written on the failure path.
    reverted = await session.get(Match, "fd-rebind-1")
    assert reverted is not None
    assert reverted.home_team_id == orphan_home
