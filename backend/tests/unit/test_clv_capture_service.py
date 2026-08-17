"""Unit tests for the CLV scheduler + market lifecycle integration."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, OddsHistory, Team
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


def _due_kickoff(minutes_from_now: int = 4) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=minutes_from_now)


async def _seed_match(
    session_factory,
    *,
    match_id: str,
    league_id: str,
    kickoff: datetime,
    home_id: str = "team-home",
    home_name: str = "Ajax FC",
    away_id: str = "team-away",
    away_name: str = "PSV",
) -> None:
    async with session_factory() as session:
        if await session.get(League, league_id) is None:
            session.add(League(id=league_id, name=league_id, country="test"))
        if await session.get(Team, home_id) is None:
            session.add(Team(id=home_id, name=home_name, league_id=league_id))
        if await session.get(Team, away_id) is None:
            session.add(Team(id=away_id, name=away_name, league_id=league_id))
        session.add(
            Match(
                id=match_id,
                home_team_id=home_id,
                away_team_id=away_id,
                league_id=league_id,
                match_date=kickoff,
                season="2026",
                status="scheduled",
            )
        )
        await session.commit()


def _odds_record(
    event_id: str,
    kickoff: datetime,
    *,
    home: float = 2.0,
    draw: float = 3.4,
    away: float = 3.8,
    coherent: bool = True,
    home_team: str = "Ajax",
    away_team: str = "PSV",
) -> dict:
    return {
        "canonical_fixture_id": None,
        "provider": "the_odds_api",
        "provider_event_id": event_id,
        "home_team": home_team,
        "away_team": away_team,
        "bookmaker": "pinnacle",
        "market_type": "1X2",
        "home_odds": home,
        "draw_odds": draw,
        "away_odds": away,
        "overround": (1 / home) + (1 / draw) + (1 / away),
        "provider_event_timestamp": kickoff.replace(tzinfo=timezone.utc).isoformat(),
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


async def test_capture_writes_closing_and_odds_history_for_due_fixture(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    kickoff = _due_kickoff(4)
    await _seed_match(factory, match_id="fd-ded-1", league_id="EREDIVISIE", kickoff=kickoff)
    records = [_odds_record("evt-1", kickoff)]

    mock_provider = AsyncMock()
    mock_provider.odds.return_value = _provider_result(records)
    with patch("src.db.session.AsyncSessionLocal", new=factory):
        result = await run_clv_capture_pass(provider=mock_provider)

    assert result["outcome"] == "ok"
    assert result["captured"] == 1
    assert result["closing"] == 1
    assert result["opening"] == 0

    async with factory() as session:
        snapshots = (await session.execute(select(MarketSnapshot))).scalars().all()
        history = (await session.execute(select(OddsHistory))).scalars().all()

    assert len(snapshots) == 1
    assert len(history) == 1
    snap = snapshots[0]
    assert snap.match_id == "fd-ded-1"
    assert snap.is_closing_line is True
    assert snap.bookmaker == "pinnacle"
    assert snap.provenance["evidence_class"] == "PRE_MATCH_CLOSING"
    assert history[0].market_type == "match_odds"
    prob_sum = (
        snap.home_implied_prob_devigged
        + snap.draw_implied_prob_devigged
        + snap.away_implied_prob_devigged
    )
    assert abs(prob_sum - 1.0) < 1e-6


async def test_capture_skips_fixture_outside_network_trigger_window(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    await _seed_match(
        factory,
        match_id="fd-ded-2",
        league_id="EREDIVISIE",
        kickoff=_due_kickoff(120),
    )
    mock_provider = AsyncMock()

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        result = await run_clv_capture_pass(provider=mock_provider)

    assert result["outcome"] == "ok"
    assert result["due"] == 0
    assert result["captured"] == 0
    mock_provider.odds.assert_not_called()


async def test_current_closing_does_not_trigger_provider_request_by_itself(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    kickoff = _due_kickoff(4)
    await _seed_match(factory, match_id="fd-ded-3", league_id="EREDIVISIE", kickoff=kickoff)
    async with factory() as session:
        session.add(
            MarketSnapshot(
                match_id="fd-ded-3",
                provider="the_odds_api",
                bookmaker="pinnacle",
                market_type="1X2",
                home_odds=2.0,
                draw_odds=3.4,
                away_odds=3.8,
                is_closing_line=True,
                captured_at=datetime.now(timezone.utc).replace(tzinfo=None),
                coherent=True,
                executable=False,
                provenance={"evidence_class": "PRE_MATCH_CLOSING"},
            )
        )
        await session.commit()

    mock_provider = AsyncMock()
    with patch("src.db.session.AsyncSessionLocal", new=factory):
        result = await run_clv_capture_pass(provider=mock_provider)

    assert result["already_captured"] == 1
    assert result["captured"] == 0
    mock_provider.odds.assert_not_called()


async def test_capture_skips_unsupported_league_without_provider_call(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    await _seed_match(factory, match_id="fd-xx-1", league_id="XX", kickoff=_due_kickoff(4))
    mock_provider = AsyncMock()

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        result = await run_clv_capture_pass(provider=mock_provider)

    assert result["unsupported_league"] == 1
    assert result["captured"] == 0
    mock_provider.odds.assert_not_called()


async def test_capture_uses_team_identity_to_disambiguate_same_kickoff(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    kickoff = _due_kickoff(4)
    await _seed_match(factory, match_id="fd-ded-4a", league_id="EREDIVISIE", kickoff=kickoff)
    await _seed_match(
        factory,
        match_id="fd-ded-4b",
        league_id="EREDIVISIE",
        kickoff=kickoff,
        home_id="team-home-2",
        home_name="Feyenoord",
        away_id="team-away-2",
        away_name="AZ Alkmaar",
    )
    records = [_odds_record("evt-identity", kickoff, home_team="Ajax", away_team="PSV")]

    mock_provider = AsyncMock()
    mock_provider.odds.return_value = _provider_result(records)
    with patch("src.db.session.AsyncSessionLocal", new=factory):
        result = await run_clv_capture_pass(provider=mock_provider)

    assert result["captured"] == 1
    assert result["unmatched"] == 1

    async with factory() as session:
        snapshots = (await session.execute(select(MarketSnapshot))).scalars().all()
    assert len(snapshots) == 1
    assert snapshots[0].match_id == "fd-ded-4a"


async def test_capture_fails_closed_on_same_team_identity_ambiguity(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    kickoff = _due_kickoff(4)
    await _seed_match(factory, match_id="fd-ded-5a", league_id="EREDIVISIE", kickoff=kickoff)
    await _seed_match(
        factory,
        match_id="fd-ded-5b",
        league_id="EREDIVISIE",
        kickoff=kickoff + timedelta(minutes=1),
        home_id="team-home-3",
        home_name="Ajax FC",
        away_id="team-away-3",
        away_name="PSV",
    )
    records = [_odds_record("evt-ambiguous", kickoff)]

    mock_provider = AsyncMock()
    mock_provider.odds.return_value = _provider_result(records)
    with patch("src.db.session.AsyncSessionLocal", new=factory):
        result = await run_clv_capture_pass(provider=mock_provider)

    assert result["captured"] == 0
    assert result["unmatched"] == 2
    assert result["ambiguous_market"] == 1


async def test_capture_provider_returns_no_records_is_graceful(factory) -> None:
    from src.services.clv_capture_service import run_clv_capture_pass

    await _seed_match(factory, match_id="fd-ded-6", league_id="EREDIVISIE", kickoff=_due_kickoff(4))

    mock_provider = AsyncMock()
    mock_provider.odds.return_value = _provider_result([])
    with patch("src.db.session.AsyncSessionLocal", new=factory):
        result = await run_clv_capture_pass(provider=mock_provider)

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

    await _seed_match(factory, match_id="fd-ded-7", league_id="EREDIVISIE", kickoff=_due_kickoff(4))
    exploding_provider = AsyncMock()
    exploding_provider.odds.side_effect = RuntimeError("boom")

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        result = await clv_capture_service.run_clv_capture_pass(provider=exploding_provider)

    assert result["outcome"] == "error"


def test_utc_naive_converts_offset_aware_datetime_to_same_utc_instant() -> None:
    from src.services.clv_capture_service import _utc_naive

    plus_one = timezone(timedelta(hours=1))
    source = datetime(2026, 8, 16, 21, 12, tzinfo=plus_one)

    assert _utc_naive(source) == datetime(2026, 8, 16, 20, 12)
    assert _utc_naive(source).tzinfo is None


def test_utc_naive_preserves_existing_naive_utc_contract() -> None:
    from src.services.clv_capture_service import _utc_naive

    source = datetime(2026, 8, 16, 20, 12)
    assert _utc_naive(source) is source


async def test_capture_pass_explicitly_rolls_back_failed_transaction() -> None:
    from src.services import clv_capture_service

    class FakeSession:
        def __init__(self) -> None:
            self.rollback = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_session = FakeSession()

    def factory():
        return fake_session

    with patch("src.db.session.AsyncSessionLocal", new=factory), patch.object(
        clv_capture_service,
        "_capture_due_fixtures",
        new=AsyncMock(side_effect=RuntimeError("database write failed")),
    ):
        result = await clv_capture_service.run_clv_capture_pass()

    assert result["outcome"] == "error"
    fake_session.rollback.assert_awaited_once()
