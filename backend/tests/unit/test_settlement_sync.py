"""Unit tests for football_data_api._normalize_result() and
fixture_sync_service.sync_settled_results().

Contracts verified:
  1. _normalize_result: well-formed canonical provider record parses; missing
     event id/score -> None.
  2. sync_settled_results: updates a matched non-settled Match; idempotent on
     re-sync; unmatched results are skipped, never create a row; a malformed
     record is dropped without blocking valid siblings; a provider outage
     returns zero counts without raising.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.data.loaders.football_data_api import FootballDataAPIClient, FootballDataAPIError


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_match(session: AsyncSession, match_id: str, status: str = "scheduled") -> None:
    session.add(
        Match(
            id=match_id,
            home_team_id="team-home",
            away_team_id="team-away",
            league_id="EPL",
            match_date=datetime(2026, 8, 7, 15, 0),
            status=status,
        )
    )
    await session.commit()


def _result(match_id: str, home_score: int, away_score: int) -> dict:
    return {
        "id": match_id,
        "match_date": "2026-08-07T15:00:00Z",
        "home_score": home_score,
        "away_score": away_score,
        "status": "finished",
    }


def _provider_record(
    event_id: str | None,
    home_score: int | None,
    away_score: int | None,
) -> dict:
    return {
        "coherent": True,
        "provider_event_id": event_id,
        "kickoff_utc": "2026-08-07T15:00:00Z",
        "home_score": home_score,
        "away_score": away_score,
    }


def _mock_client(results: list) -> AsyncMock:
    mock = AsyncMock()
    mock.get_recent_results.return_value = results
    return mock


# ---------------------------------------------------------------------------
# _normalize_result
# ---------------------------------------------------------------------------


def test_normalize_result_valid_finished_record() -> None:
    client = FootballDataAPIClient()
    raw = _provider_record("12345", 2, 1)
    assert client._normalize_result(raw) == {
        "id": "fd-12345",
        "match_date": "2026-08-07T15:00:00Z",
        "home_score": 2,
        "away_score": 1,
        "status": "finished",
    }


def test_normalize_result_missing_score_is_none() -> None:
    client = FootballDataAPIClient()
    raw = _provider_record("1", None, None)
    assert client._normalize_result(raw) is None


def test_normalize_result_missing_id_is_none() -> None:
    client = FootballDataAPIClient()
    raw = _provider_record(None, 1, 0)
    assert client._normalize_result(raw) is None


# ---------------------------------------------------------------------------
# sync_settled_results
# ---------------------------------------------------------------------------


async def test_sync_settled_results_updates_matched_match(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_settled_results

    await _seed_match(session, "fd-1", status="scheduled")
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([_result("fd-1", 2, 1)])
        counts = await sync_settled_results(session)

    assert counts == {"updated": 1, "unmatched": 0, "already_settled": 0}
    match = await session.get(Match, "fd-1")
    assert match.status == "finished"
    assert match.home_score == 2
    assert match.away_score == 1


async def test_sync_settled_results_idempotent(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_settled_results

    await _seed_match(session, "fd-2", status="scheduled")
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([_result("fd-2", 1, 1)])
        await sync_settled_results(session)

        MockCls.return_value = _mock_client([_result("fd-2", 1, 1)])
        counts_second = await sync_settled_results(session)

    assert counts_second == {"updated": 0, "unmatched": 0, "already_settled": 1}


async def test_sync_settled_results_unmatched_skipped_no_row_created(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_settled_results

    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([_result("fd-never-synced", 3, 0)])
        counts = await sync_settled_results(session)

    assert counts == {"updated": 0, "unmatched": 1, "already_settled": 0}
    assert await session.get(Match, "fd-never-synced") is None


async def test_sync_settled_results_malformed_record_dropped_sibling_still_updates(
    session: AsyncSession,
) -> None:
    from src.services.fixture_sync_service import sync_settled_results

    await _seed_match(session, "fd-3", status="scheduled")
    malformed = {"id": "", "match_date": "2026-08-07T15:00:00Z", "home_score": None, "away_score": None}
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([malformed, _result("fd-3", 1, 0)])
        counts = await sync_settled_results(session)

    assert counts == {"updated": 1, "unmatched": 0, "already_settled": 0}


async def test_sync_settled_results_provider_outage_returns_zero_counts(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_settled_results

    mock = AsyncMock()
    mock.get_recent_results.side_effect = FootballDataAPIError("rate limited")
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = mock
        counts = await sync_settled_results(session)

    assert counts == {"updated": 0, "unmatched": 0, "already_settled": 0}
