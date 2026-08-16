"""Unit tests for fixture_sync_service.sync_upcoming_fixtures().

Contracts verified:
  1. Idempotency — re-syncing the same data inserts 0 new rows.
  2. Unsupported competition — unknown league names are silently dropped.
  3. Malformed date — un-parseable match_date skips that match; valid ones still insert.
  4. Provider reschedules update mutable kickoff metadata without changing
     canonical identity and safely remove only unreferenced legacy duplicates.
  5. True identity conflicts roll back all canonical side effects while the
     raw provider fixture and later batch entries still commit.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db import models as _db_models  # noqa: F401
from src.db.models import CanonicalFixture


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _match(n: int, league: str = "EPL", date: str = "2026-07-15T15:00:00Z") -> dict:
    return {
        "id": f"fd-match-{n}",
        "league": league,
        "home_team": f"TeamA {n}",
        "away_team": f"TeamB {n}",
        "match_date": date,
    }


def _mock_client(matches: list) -> AsyncMock:
    mock = AsyncMock()
    mock.get_upcoming_matches.return_value = matches
    return mock


async def test_idempotent_resync(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [_match(1), _match(2)]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count_first = await sync_upcoming_fixtures(session)

        MockCls.return_value = _mock_client(matches)
        count_second = await sync_upcoming_fixtures(session)

    assert count_first == 2
    assert count_second == 0


async def test_unsupported_competition_skipped(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [
        _match(10, league="EPL"),
        _match(11, league="FIFA World Cup"),
        _match(12, league="EPL"),
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count = await sync_upcoming_fixtures(session)

    assert count == 2


async def test_malformed_date_skipped(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [
        _match(20, league="EPL"),
        _match(21, league="EPL", date="not-a-date"),
        _match(22, league="EPL"),
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count = await sync_upcoming_fixtures(session)

    assert count == 2


async def test_synced_league_id_is_canonical(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [
        _match(30, league="EPL"),
        _match(31, league="Eredivisie"),
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        await sync_upcoming_fixtures(session)

    rows = (await session.execute(text("SELECT id FROM leagues"))).fetchall()
    stored_ids = {row[0] for row in rows}
    assert "EPL" in stored_ids, f"Expected canonical 'EPL', got: {stored_ids}"
    assert "EREDIVISIE" in stored_ids, f"Expected canonical 'EREDIVISIE', got: {stored_ids}"
    assert "PL" not in stored_ids
    assert "DED" not in stored_ids

    match_rows = (await session.execute(text("SELECT league_id FROM matches"))).fetchall()
    match_league_ids = {row[0] for row in match_rows}
    assert match_league_ids <= {"EPL", "EREDIVISIE"}


async def test_provider_reschedule_updates_kickoff_without_identity_drift(
    session: AsyncSession,
) -> None:
    """Same provider event + same participants remains one canonical fixture."""
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([_match(40, date="2026-07-15T15:00:00Z")])
        await sync_upcoming_fixtures(session)

    original_mapping = (
        await session.execute(
            text(
                "SELECT canonical_fixture_id FROM provider_event_mappings "
                "WHERE provider='football-data.org' AND provider_event_id='fd-match-40'"
            )
        )
    ).scalar_one()
    original_fixture = await session.get(CanonicalFixture, original_mapping)
    assert original_fixture is not None

    # Reproduce the exact legacy side effect observed in production: the old
    # code staged a kickoff-derived duplicate before discovering the provider
    # event was already mapped, and the caller later committed that orphan.
    legacy_orphan_id = "fixture-legacy-reschedule-orphan"
    session.add(
        CanonicalFixture(
            id=legacy_orphan_id,
            competition_id=original_fixture.competition_id,
            season=original_fixture.season,
            home_team_id=original_fixture.home_team_id,
            away_team_id=original_fixture.away_team_id,
            kickoff_utc=datetime(2026, 8, 1, 18, 0),
            status="scheduled",
            reconciliation_status="VERIFIED",
            reconciliation_confidence=1.0,
            evidence={"provider_event_id": "fd-match-40", "source": "football-data.org"},
        )
    )
    await session.commit()

    matches = [
        _match(40, date="2026-08-01T18:00:00Z"),
        _match(41),
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count = await sync_upcoming_fixtures(session)

    assert count == 1

    # Use typed SQLAlchemy expressions for datetime columns. Raw text() on
    # SQLite returns timestamp text and bypasses the DateTime result processor,
    # which makes this cross-dialect contract assertion compare str to datetime.
    match_kickoff = (
        await session.execute(select(Match.match_date).where(Match.id == "fd-match-40"))
    ).scalar_one()
    assert match_kickoff == datetime(2026, 8, 1, 18, 0)

    refreshed_mapping = (
        await session.execute(
            text(
                "SELECT canonical_fixture_id FROM provider_event_mappings "
                "WHERE provider='football-data.org' AND provider_event_id='fd-match-40'"
            )
        )
    ).scalar_one()
    assert refreshed_mapping == original_mapping

    canonical_kickoff = (
        await session.execute(
            select(CanonicalFixture.kickoff_utc).where(CanonicalFixture.id == original_mapping)
        )
    ).scalar_one()
    assert canonical_kickoff == datetime(2026, 8, 1, 18, 0)
    assert await session.get(CanonicalFixture, legacy_orphan_id) is None

    canonical_count = int(
        (await session.execute(text("SELECT count(*) FROM canonical_fixtures"))).scalar_one()
    )
    assert canonical_count == 2, "reschedule left or minted an orphan canonical fixture"

    rows = (await session.execute(text("SELECT id FROM matches"))).fetchall()
    ids = {row[0] for row in rows}
    assert "fd-match-41" in ids


async def test_identity_conflict_rolls_back_canonical_attempt_only(
    session: AsyncSession,
) -> None:
    """A provider participant conflict cannot leak canonical rows from its savepoint."""
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([_match(50)])
        await sync_upcoming_fixtures(session)

    conflicting = _match(50, date="2026-08-02T18:00:00Z")
    conflicting["home_team"] = "Different Team 50"
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([conflicting, _match(51)])
        count = await sync_upcoming_fixtures(session)

    assert count == 1

    raw_home = (
        await session.execute(
            text(
                "SELECT t.name FROM matches m JOIN teams t ON t.id=m.home_team_id "
                "WHERE m.id='fd-match-50'"
            )
        )
    ).scalar_one()
    assert raw_home == "Different Team 50"
    assert (
        await session.execute(text("SELECT count(*) FROM matches WHERE id='fd-match-51'"))
    ).scalar_one() == 1

    assert (
        await session.execute(
            text(
                "SELECT count(*) FROM provider_event_mappings "
                "WHERE provider='football-data.org' AND provider_event_id='fd-match-50'"
            )
        )
    ).scalar_one() == 1
    assert (
        await session.execute(
            text("SELECT count(*) FROM canonical_teams WHERE name='Different Team 50'")
        )
    ).scalar_one() == 0
    assert (
        await session.execute(text("SELECT count(*) FROM canonical_fixtures"))
    ).scalar_one() == 2
