"""docs/DEBT.md item 35: fixture-identity rebind review manifest is read-only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.db.models import MatchPredictionLog
from src.services.canonical_identity_service import ensure_canonical_fixture
from src.services.fixture_identity_rebind_service import (
    build_fixture_identity_rebind_manifest,
)

_FUTURE = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
_PAST = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


async def _seed_league_and_stored_teams(
    session: AsyncSession, *, league_id: str, home_id: str, away_id: str
) -> None:
    session.add(League(id=league_id, name=league_id, country="test"))
    session.add(Team(id=home_id, name="Stored Home", league_id=league_id))
    session.add(Team(id=away_id, name="Stored Away", league_id=league_id))
    await session.flush()


async def _seed_mismatched_match(
    session: AsyncSession,
    *,
    match_id: str,
    league_id: str = "SERIE_A",
    kickoff: datetime = _FUTURE,
    status: str = "scheduled",
) -> None:
    """A match bound to the old deterministic ``fd-team-`` id, with a
    canonical fixture already verified under a *different* (hashed) id — the
    exact drift ``fixture_sync_service`` logs and leaves unchanged.
    """
    stored_home = f"fd-team-{league_id.lower()}:home"
    stored_away = f"fd-team-{league_id.lower()}:away"
    await _seed_league_and_stored_teams(
        session, league_id=league_id, home_id=stored_home, away_id=stored_away
    )
    session.add(
        Match(
            id=match_id,
            league_id=league_id,
            home_team_id=stored_home,
            away_team_id=stored_away,
            match_date=kickoff,
            season="2026/2027",
            status=status,
        )
    )
    await session.flush()
    await ensure_canonical_fixture(
        session,
        provider="football-data.org",
        provider_event_id=match_id,
        competition_id=league_id,
        competition_name=league_id,
        home_provider_id="100",
        home_name="Verified Home",
        away_provider_id="101",
        away_name="Verified Away",
        kickoff_utc=kickoff,
        season="2026/2027",
        status=status,
        evidence={},
    )
    await session.commit()


async def test_manifest_flags_mismatched_unsettled_fixture(session: AsyncSession) -> None:
    await _seed_mismatched_match(session, match_id="fd-1")

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert manifest.summary["total_mismatched"] == 1
    assert manifest.summary["rebind_ready_count"] == 1
    assert manifest.summary["blocked_count"] == 0
    assert manifest.summary["leagues_affected"] == ["SERIE_A"]
    entry = manifest.entries[0]
    assert entry.match_id == "fd-1"
    assert entry.stored_home_team_id == "fd-team-serie_a:home"
    assert entry.stored_home_team_name == "Stored Home"
    assert entry.verified_home_team_name == "Verified Home"
    assert entry.verified_home_team_id != entry.stored_home_team_id
    assert entry.blockers == ()
    assert entry.rebind_ready is True
    assert entry.rebind_status == "READY"


async def test_manifest_omits_fixtures_with_agreeing_identity(session: AsyncSession) -> None:
    league_id = "SERIE_A"
    match_id = "fd-2"
    # First bind the canonical identity, then persist the Match using the
    # exact same resolved ids -- no drift to report.
    canonical_fixture_id = await ensure_canonical_fixture(
        session,
        provider="football-data.org",
        provider_event_id=match_id,
        competition_id=league_id,
        competition_name=league_id,
        home_provider_id="200",
        home_name="Agreeing Home",
        away_provider_id="201",
        away_name="Agreeing Away",
        kickoff_utc=_FUTURE,
        season="2026/2027",
        status="scheduled",
        evidence={},
    )
    from src.db.models import CanonicalFixture

    fixture = await session.get(CanonicalFixture, canonical_fixture_id)
    assert fixture is not None
    session.add(League(id=league_id, name=league_id, country="test"))
    session.add(
        Match(
            id=match_id,
            league_id=league_id,
            home_team_id=fixture.home_team_id,
            away_team_id=fixture.away_team_id,
            match_date=_FUTURE,
            season="2026/2027",
            status="scheduled",
        )
    )
    await session.commit()

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert manifest.entries == ()
    assert manifest.summary["total_mismatched"] == 0


async def test_manifest_excludes_settled_matches(session: AsyncSession) -> None:
    await _seed_mismatched_match(session, match_id="fd-3", status="finished")

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert manifest.entries == ()


async def test_manifest_flags_kickoff_passed_blocker(session: AsyncSession) -> None:
    await _seed_mismatched_match(session, match_id="fd-4", kickoff=_PAST)

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert "KICKOFF_PASSED" in entry.blockers
    assert entry.rebind_ready is False
    assert entry.rebind_status == "BLOCKED"


async def test_manifest_flags_existing_predictions_blocker(session: AsyncSession) -> None:
    await _seed_mismatched_match(session, match_id="fd-5")
    session.add(
        MatchPredictionLog(
            match_id="fd-5",
            model_version="v5_phase7",
            home_probability=0.4,
            draw_probability=0.3,
            away_probability=0.3,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    await session.commit()

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert len(manifest.entries) == 1
    assert "HAS_EXISTING_PREDICTIONS" in manifest.entries[0].blockers


async def test_manifest_sha256_is_deterministic(session: AsyncSession) -> None:
    await _seed_mismatched_match(session, match_id="fd-6")

    first = await build_fixture_identity_rebind_manifest(session)
    second = await build_fixture_identity_rebind_manifest(session)

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.manifest_sha256 != ""
