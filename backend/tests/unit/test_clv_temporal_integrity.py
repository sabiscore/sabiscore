"""Temporal-integrity regressions for closing-line capture and CLV joins."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db.models import MarketSnapshot, MatchPredictionLog
from src.repositories.fixtures import get_clv_records
from src.services.clv_capture_service import _is_strictly_pre_kickoff, run_clv_capture_pass


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


def test_closing_boundary_is_strictly_before_kickoff() -> None:
    kickoff = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

    assert _is_strictly_pre_kickoff(kickoff - timedelta(microseconds=1), kickoff) is True
    assert _is_strictly_pre_kickoff(kickoff, kickoff) is False
    assert _is_strictly_pre_kickoff(kickoff + timedelta(microseconds=1), kickoff) is False


async def test_capture_does_not_recover_post_kickoff_fixture(factory) -> None:
    kickoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    async with factory() as session:
        session.add(
            Match(
                id="post-kickoff-fixture",
                home_team_id="home",
                away_team_id="away",
                league_id="EREDIVISIE",
                match_date=kickoff,
                status="scheduled",
            )
        )
        await session.commit()

    provider = AsyncMock()
    with patch("src.db.session.AsyncSessionLocal", new=factory):
        result = await run_clv_capture_pass(provider=provider)

    assert result["outcome"] == "ok"
    assert result["due"] == 0
    assert result["captured"] == 0
    provider.odds.assert_not_called()


async def test_clv_join_uses_latest_valid_pre_kickoff_snapshot_only(factory) -> None:
    kickoff = datetime(2026, 8, 17, 15, 0)
    valid_match_id = "temporal-valid"
    invalid_only_match_id = "temporal-invalid-only"

    async with factory() as session:
        session.add_all(
            [
                Match(
                    id=valid_match_id,
                    home_team_id="home",
                    away_team_id="away",
                    league_id="EREDIVISIE",
                    match_date=kickoff,
                    status="finished",
                    home_score=1,
                    away_score=0,
                ),
                MatchPredictionLog(
                    match_id=valid_match_id,
                    canonical_fixture_id=None,
                    model_version="v5_phase7",
                    home_probability=0.5,
                    draw_probability=0.3,
                    away_probability=0.2,
                    created_at=kickoff - timedelta(hours=1),
                ),
                MarketSnapshot(
                    match_id=valid_match_id,
                    canonical_fixture_id=None,
                    provider="the_odds_api",
                    bookmaker="valid-pre",
                    market_type="1X2",
                    home_odds=2.0,
                    draw_odds=3.4,
                    away_odds=3.8,
                    home_implied_prob_devigged=0.45,
                    draw_implied_prob_devigged=0.28,
                    away_implied_prob_devigged=0.27,
                    is_closing_line=True,
                    captured_at=kickoff - timedelta(minutes=1),
                    coherent=True,
                    executable=False,
                ),
                # This row is later, but invalid temporal evidence. The CLV query
                # must fall back to the latest *valid pre-kickoff* row above.
                MarketSnapshot(
                    match_id=valid_match_id,
                    canonical_fixture_id=None,
                    provider="the_odds_api",
                    bookmaker="invalid-post",
                    market_type="1X2",
                    home_odds=1.2,
                    draw_odds=10.0,
                    away_odds=10.0,
                    home_implied_prob_devigged=0.80,
                    draw_implied_prob_devigged=0.10,
                    away_implied_prob_devigged=0.10,
                    is_closing_line=True,
                    captured_at=kickoff + timedelta(minutes=1),
                    coherent=True,
                    executable=False,
                ),
                Match(
                    id=invalid_only_match_id,
                    home_team_id="home-2",
                    away_team_id="away-2",
                    league_id="EREDIVISIE",
                    match_date=kickoff + timedelta(days=1),
                    status="finished",
                    home_score=0,
                    away_score=0,
                ),
                MatchPredictionLog(
                    match_id=invalid_only_match_id,
                    canonical_fixture_id=None,
                    model_version="v5_phase7",
                    home_probability=0.4,
                    draw_probability=0.35,
                    away_probability=0.25,
                    created_at=kickoff + timedelta(days=1, hours=-1),
                ),
                MarketSnapshot(
                    match_id=invalid_only_match_id,
                    canonical_fixture_id=None,
                    provider="the_odds_api",
                    bookmaker="invalid-only",
                    market_type="1X2",
                    home_odds=2.2,
                    draw_odds=3.2,
                    away_odds=3.5,
                    home_implied_prob_devigged=0.42,
                    draw_implied_prob_devigged=0.29,
                    away_implied_prob_devigged=0.29,
                    is_closing_line=True,
                    captured_at=kickoff + timedelta(days=1, minutes=1),
                    coherent=True,
                    executable=False,
                ),
            ]
        )
        await session.commit()
        records = await get_clv_records(session, model_version="v5_phase7")

    assert len(records) == 1
    assert records[0]["model_probs"] == pytest.approx([0.5, 0.3, 0.2])
    assert records[0]["closing_probs"] == pytest.approx([0.45, 0.28, 0.27])
