"""Unit tests for fixture_sync_service.sync_upcoming_fixtures().

Three contracts verified:
  1. Idempotency — re-syncing the same data inserts 0 new rows.
  2. Unsupported competition — unknown league names are silently dropped.
  3. Malformed date — un-parseable match_date skips that match; valid ones still insert.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base


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


def _mock_client(matches: list) -> tuple:
    """Return (patch target, configured mock) for FootballDataAPIClient."""
    mock = AsyncMock()
    mock.get_upcoming_matches.return_value = matches
    return mock


async def test_idempotent_resync(session: AsyncSession) -> None:
    """Re-syncing identical data inserts 0 rows on the second call."""
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [_match(1), _match(2)]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count_first = await sync_upcoming_fixtures(session)

        MockCls.return_value = _mock_client(matches)
        count_second = await sync_upcoming_fixtures(session)

    assert count_first == 2
    assert count_second == 0  # idempotent — nothing new to insert


async def test_unsupported_competition_skipped(session: AsyncSession) -> None:
    """Matches whose league is not in the 7-competition closed set are dropped."""
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [
        _match(10, league="EPL"),           # supported
        _match(11, league="FIFA World Cup"), # unsupported — must be skipped
        _match(12, league="EPL"),           # supported
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count = await sync_upcoming_fixtures(session)

    assert count == 2  # only the two EPL matches inserted


async def test_malformed_date_skipped(session: AsyncSession) -> None:
    """A match with an un-parseable match_date is skipped; valid neighbours still insert."""
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [
        _match(20, league="EPL"),                               # good
        _match(21, league="EPL", date="not-a-date"),            # bad date → skip
        _match(22, league="EPL"),                               # good
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count = await sync_upcoming_fixtures(session)

    assert count == 2  # bad-date match dropped, two valid matches inserted


async def test_synced_league_id_is_canonical(session: AsyncSession) -> None:
    """WP-A regression: stored league_id must be canonical ("EPL"), not a fd.org code ("PL").

    Before WP-A, _LEAGUE_META stored fd.org codes which caused LEAGUE_POLICY_UNAVAILABLE
    on every synced fixture. Downstream systems (league_policy, full_analysis, model_fetcher,
    capability probe) all expect canonical IDs.
    """
    from sqlalchemy import text
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [
        _match(30, league="EPL"),
        _match(31, league="Eredivisie"),
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        await sync_upcoming_fixtures(session)

    # Leagues table must store canonical IDs, never fd.org codes
    rows = (await session.execute(text("SELECT id FROM leagues"))).fetchall()
    stored_ids = {row[0] for row in rows}
    assert "EPL" in stored_ids, f"Expected canonical 'EPL', got: {stored_ids}"
    assert "EREDIVISIE" in stored_ids, f"Expected canonical 'EREDIVISIE', got: {stored_ids}"
    # fd.org codes must not be present
    assert "PL" not in stored_ids, "fd.org code 'PL' leaked into leagues table"
    assert "DED" not in stored_ids, "fd.org code 'DED' leaked into leagues table"

    # Match rows must also carry canonical league_id
    match_rows = (await session.execute(text("SELECT league_id FROM matches"))).fetchall()
    match_league_ids = {row[0] for row in match_rows}
    assert match_league_ids <= {"EPL", "EREDIVISIE"}, (
        f"Match league_ids contain non-canonical values: {match_league_ids}"
    )


async def test_canonical_identity_conflict_does_not_wedge_the_batch(session: AsyncSession) -> None:
    """A rescheduled fixture (same provider_event_id, new kickoff_utc) recomputes a
    different canonical fixture_id and ensure_canonical_fixture() correctly refuses
    to repoint the existing mapping. Before the fix, that ValueError propagated out
    of the loop, aborted session.commit() for the whole tick, and silently dropped
    every other fixture in the same batch too — observed in production 2026-08-16.
    """
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    # First sync establishes the canonical mapping for fd-match-40 at its initial kickoff.
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([_match(40, date="2026-07-15T15:00:00Z")])
        await sync_upcoming_fixtures(session)

    # Second sync: fd-match-40 comes back rescheduled (different kickoff_utc — the
    # exact trigger for the conflict) alongside an unrelated new fixture, fd-match-41.
    matches = [
        _match(40, date="2026-08-01T18:00:00Z"),  # reschedule — triggers the conflict
        _match(41),                                 # must still sync despite the above
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count = await sync_upcoming_fixtures(session)  # must not raise

    assert count == 1  # fd-match-41 inserted; fd-match-40 already existed as a Match row
    from sqlalchemy import text

    rows = (await session.execute(text("SELECT id FROM matches"))).fetchall()
    ids = {row[0] for row in rows}
    assert "fd-match-41" in ids, "batch was wedged — the fixture after the conflict never committed"
