"""Unit tests for clv_capture_service.run_clv_capture_pass().

Contracts verified (docs/adr/0004-clv-capture.md):
  1. A fixture due within the capture window, with coherent bookmaker odds,
     gets one MarketSnapshot(is_closing_line=True) row with de-vigged
     probabilities summing to ~1.0.
  2. A fixture outside the window is left uncaptured.
  3. A fixture already captured is not re-captured on a second pass.
  4. An unsupported league is skipped without a provider call.
  5. Ambiguous event<->fixture matching (two same-league fixtures within the
     kickoff tolerance of one odds-board event) is skipped, not guessed.
  6. A provider returning no records degrades gracefully (outcome="ok").
  7. AsyncSessionLocal is None -> outcome="db_not_ready", no raise.
  8. A genuine unexpected exception yields outcome="error".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db.models import MarketSnapshot
from src.providers.base import ProviderResult, ProviderStatus, TrustTier


@pytest.fixture(autouse=True)
def _reset_clv_capture_module_state():
    from src.services import clv_capture_service

    clv_capture_service._last_result = {"outcome": "never_run"}
    yield


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


def _due_kickoff(minutes_from_now: int = 5) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=minutes_from_now)


async def _seed_match(session_factory, *, match_id: str, league_id: str, kickoff: datetime) -> None:
    async with session_factory() as session:
        session.add(
            Match(
                id=match_id,
                home_team_id="team-home",
                away_team_id="team-away",
                league_id=league_id,
                match_date=kickoff,
                status="scheduled",
            )
        )
        await session.commit()


def _odds_record(event_id: str, kickoff: datetime, *, home=2.0, draw=3.4, away=3.8, coherent=True) -> dict:
    return {
        "canonical_fixture_id": None,
        "provider": "the_odds_api",
        "provider_event_id": event_id,
        "bookmaker": "pinnacle",
        "market_type": "1X2",
        "home_odds": home,
        "draw_odds": draw,
        "away_odds": away,
        "overround": (1 / home) + (1 / draw) + (1 / away),
        "provider_event_timestamp": kickoff.isoformat(),
        "bookmaker_last_update": None,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "coherent": coherent,
        "executable": coherent,
        "rejection_reason": None,
    }


def _provider_result(records: list[dict]) -> ProviderResult:
    return ProviderResult(
        provider="the_odds_api",
        operation="odds",
        status=ProviderStatus.VERIFIED if records else ProviderStatus.PARTIAL,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        records=records,
    )


async def test_capture_writes_snapshot_for_due_fixture_with_coherent_odds(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    kickoff = _due_kickoff(5)
    await _seed_match(factory, match_id="fd-ded-1", league_id="EREDIVISIE", kickoff=kickoff)
    records = [_odds_record("evt-1", kickoff)]

    mock_provider = AsyncMock()
    mock_provider.odds.return_value = _provider_result(records)
    with patch("src.db.session.AsyncSessionLocal", new=factory):
        result = await run_clv_capture_pass(provider=mock_provider)

    assert result["outcome"] == "ok"
    assert result["captured"] == 1

    async with factory() as session:
        from sqlalchemy import select

        rows = (await session.execute(select(MarketSnapshot))).scalars().all()

    assert len(rows) == 1
    snap = rows[0]
    assert snap.match_id == "fd-ded-1"
    assert snap.is_closing_line is True
    assert snap.canonical_fixture_id is None
    assert snap.bookmaker == "pinnacle"
    assert snap.provenance["bookmaker"] == "pinnacle"
    prob_sum = snap.home_implied_prob_devigged + snap.draw_implied_prob_devigged + snap.away_implied_prob_devigged
    assert abs(prob_sum - 1.0) < 1e-6


async def test_capture_skips_fixture_outside_window(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    await _seed_match(factory, match_id="fd-ded-2", league_id="EREDIVISIE", kickoff=_due_kickoff(120))

    mock_provider = AsyncMock()
    with patch("src.db.session.AsyncSessionLocal", new=factory), patch(
        "src.providers.the_odds_api.TheOddsAPIProvider", return_value=mock_provider
    ):
        result = await run_clv_capture_pass()

    assert result["outcome"] == "ok"
    assert result["due"] == 0
    assert result["captured"] == 0
    mock_provider.odds.assert_not_called()


async def test_capture_dedupes_already_captured_fixture(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    kickoff = _due_kickoff(5)
    await _seed_match(factory, match_id="fd-ded-3", league_id="EREDIVISIE", kickoff=kickoff)
    async with factory() as session:
        session.add(
            MarketSnapshot(
                match_id="fd-ded-3",
                provider="the_odds_api",
                bookmaker="consensus",
                market_type="1X2",
                home_odds=2.0,
                draw_odds=3.4,
                away_odds=3.8,
                is_closing_line=True,
                captured_at=datetime.now(timezone.utc),
                coherent=True,
                executable=False,
            )
        )
        await session.commit()

    mock_provider = AsyncMock()
    with patch("src.db.session.AsyncSessionLocal", new=factory), patch(
        "src.providers.the_odds_api.TheOddsAPIProvider", return_value=mock_provider
    ):
        result = await run_clv_capture_pass()

    assert result["already_captured"] == 1
    assert result["captured"] == 0
    mock_provider.odds.assert_not_called()


async def test_capture_skips_unsupported_league(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    await _seed_match(factory, match_id="fd-xx-1", league_id="XX", kickoff=_due_kickoff(5))

    mock_provider = AsyncMock()
    with patch("src.db.session.AsyncSessionLocal", new=factory), patch(
        "src.providers.the_odds_api.TheOddsAPIProvider", return_value=mock_provider
    ):
        result = await run_clv_capture_pass()

    assert result["unsupported_league"] == 1
    assert result["captured"] == 0
    mock_provider.odds.assert_not_called()


async def test_capture_skips_ambiguous_event_match(factory) -> None:
    """Two EREDIVISIE fixtures kicking off within tolerance of the same odds-board
    event: never guess which one it belongs to."""
    from src.services.clv_capture_service import run_clv_capture_pass

    kickoff = _due_kickoff(5)
    await _seed_match(factory, match_id="fd-ded-4a", league_id="EREDIVISIE", kickoff=kickoff)
    await _seed_match(
        factory, match_id="fd-ded-4b", league_id="EREDIVISIE", kickoff=kickoff + timedelta(minutes=2)
    )
    records = [_odds_record("evt-ambiguous", kickoff)]

    mock_provider = AsyncMock()
    mock_provider.odds.return_value = _provider_result(records)
    with patch("src.db.session.AsyncSessionLocal", new=factory), patch(
        "src.providers.the_odds_api.TheOddsAPIProvider", return_value=mock_provider
    ):
        result = await run_clv_capture_pass()

    assert result["captured"] == 0
    assert result["unmatched"] == 2


async def test_capture_provider_returns_no_records_is_graceful(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    await _seed_match(factory, match_id="fd-ded-5", league_id="EREDIVISIE", kickoff=_due_kickoff(5))

    mock_provider = AsyncMock()
    mock_provider.odds.return_value = _provider_result([])
    with patch("src.db.session.AsyncSessionLocal", new=factory), patch(
        "src.providers.the_odds_api.TheOddsAPIProvider", return_value=mock_provider
    ):
        result = await run_clv_capture_pass()

    assert result["outcome"] == "ok"
    assert result["captured"] == 0
    assert result["unmatched"] == 1


async def test_run_clv_capture_pass_db_not_ready() -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    with patch("src.db.session.AsyncSessionLocal", new=None):
        result = await run_clv_capture_pass()

    assert result["outcome"] == "db_not_ready"


async def test_run_clv_capture_pass_genuine_exception_yields_error(factory) -> None:
    from src.services import clv_capture_service

    await _seed_match(factory, match_id="fd-ded-6", league_id="EREDIVISIE", kickoff=_due_kickoff(5))

    with patch("src.db.session.AsyncSessionLocal", new=factory), patch(
        "src.providers.the_odds_api.TheOddsAPIProvider", side_effect=RuntimeError("boom")
    ):
        result = await clv_capture_service.run_clv_capture_pass()

    assert result["outcome"] == "error"
