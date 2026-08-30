"""Unit tests for the Advanced Insights endpoint and service (R4 of v5 directive)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.db.models import Match, MatchContext, Odds, RefereeProfile
from src.db.session import get_async_session
from src.schemas.advanced_insights import AdvancedInsightsResponse
from src.services.advanced_insights_service import AdvancedInsightsService
from src.services.advanced_metrics import MetricStatus
from src.services.odds_service import get_odds_service


@pytest.fixture
def mock_async_session():
    session = AsyncMock()
    return session


@pytest.fixture
def sample_match():
    now = datetime.now(timezone.utc)
    match = Match(
        id="match_test_001",
        home_team_id="team_arsenal",
        away_team_id="team_chelsea",
        league_id="epl",
        match_date=now,
        venue="Emirates Stadium",
        referee="Michael Oliver",
        status="scheduled",
    )
    match.home_team = MagicMock()
    match.home_team.name = "Arsenal"
    match.away_team = MagicMock()
    match.away_team.name = "Chelsea"
    return match


class TestAdvancedInsightsService:
    """Test AdvancedInsightsService aggregation logic."""

    @pytest.mark.asyncio
    async def test_match_not_found_returns_none(self, mock_async_session):
        exec_mock = MagicMock()
        exec_mock.scalar_one_or_none.return_value = None
        mock_async_session.execute = AsyncMock(return_value=exec_mock)

        with patch("src.core.cache.cache_manager.get", return_value=None), \
             patch("src.core.cache.cache_manager.set"):
            service = AdvancedInsightsService()
            result = await service.get_advanced_insights(match_id="nonexistent", db=mock_async_session)
            assert result is None

    @pytest.mark.asyncio
    async def test_match_found_returns_valid_payload_with_fail_closed_staking(
        self, mock_async_session, sample_match
    ):
        now = datetime.now(timezone.utc)
        ctx = MatchContext(
            match_id=sample_match.id,
            weather_condition="Clear, 18C",
            ppda_home=8.5,
            ppda_away=11.2,
            psxg_home=1.2,
            psxg_away=-0.4,
            created_at=now,
            updated_at=now,
        )
        ref = RefereeProfile(
            name="Michael Oliver",
            avg_yellow_cards=3.8,
            avg_red_cards=0.12,
            penalties_awarded=5,
            strictness_index=0.75,
            sample_size=25,
            source="fbref",
            observed_at=now,
            created_at=now,
            updated_at=now,
        )
        # Column names must match the real Odds table (src/core/database.py):
        # home_win / draw / away_win / timestamp. Using home_odds/updated_at here
        # is what let five stacked defects reach a mounted route undetected.
        odds = Odds(
            match_id=sample_match.id,
            home_win=1.85,
            draw=3.60,
            away_win=4.20,
            bookmaker="Betfair",
            timestamp=now,
        )

        call_idx = 0
        def execute_side_effect(stmt):
            nonlocal call_idx
            res = MagicMock()
            if call_idx == 0:
                res.scalar_one_or_none.return_value = sample_match
            elif call_idx == 1:
                res.scalar_one_or_none.return_value = ctx
            elif call_idx == 2:
                res.scalar_one_or_none.return_value = ref
            else:
                res.scalars.return_value.first.return_value = odds
            call_idx += 1
            return res

        mock_async_session.execute = AsyncMock(side_effect=execute_side_effect)

        with patch("src.core.cache.cache_manager.get", return_value=None), \
             patch("src.core.cache.cache_manager.set"):
            service = AdvancedInsightsService()
            result = await service.get_advanced_insights(match_id=sample_match.id, db=mock_async_session)

            assert isinstance(result, AdvancedInsightsResponse)
            assert result.match_id == sample_match.id
            assert result.home_team == "Arsenal"
            assert result.away_team == "Chelsea"
            assert result.league == "epl"

            # Check advanced metrics
            assert result.advanced_metrics.ppda_home == 8.5
            assert result.advanced_metrics.ppda_status == MetricStatus.AVAILABLE.value
            assert result.advanced_metrics.xt_status == MetricStatus.ADVISORY_REQUIRES_CORPUS.value

            # Check context
            assert result.match_context.weather_condition == "Clear, 18C"
            assert result.match_context.referee is not None
            assert result.match_context.referee.name == "Michael Oliver"
            assert result.match_context.referee.avg_yellow_cards == 3.8

            # Invariant: Uncertified model MUST have stake_permitted == False
            assert result.decision_state.stake_permitted is False
            assert result.decision_state.research_only is True

            # The odds branch must actually execute against the real Odds schema.
            # Before the fix this raised (bad columns / bad kwargs) and the endpoint's
            # broad `except Exception` turned it into an opaque HTTP 500.
            mi = result.market_intelligence
            assert mi is not None, "odds branch did not execute"
            assert mi.provenance.bookmaker == "Betfair"
            assert mi.market_overround > 1.0

            # Zero-fabrication: no model prediction is linked on this read path, so
            # no model probability, edge, or EV may be published for any outcome.
            for name, outcome in mi.outcomes.items():
                assert outcome.model_probability is None, name
                assert outcome.probability_edge is None, name
                assert outcome.expected_value is None, name
            assert mi.best_edge_value is None
            assert mi.stake_permitted is False


class TestAdvancedInsightsEndpoint:
    """Test HTTP endpoint integration."""

    @pytest.mark.asyncio
    async def test_get_advanced_insights_404_for_missing_match(self, mock_async_session):
        exec_mock = MagicMock()
        exec_mock.scalar_one_or_none.return_value = None
        mock_async_session.execute = AsyncMock(return_value=exec_mock)

        app.dependency_overrides[get_async_session] = lambda: mock_async_session
        # app.state.odds_service is set in the real lifespan (api/main.py); the test
        # ASGI app never runs it, so provide the dependency directly.
        app.dependency_overrides[get_odds_service] = lambda: MagicMock()
        try:
            with patch("src.core.cache.cache_manager.get", return_value=None), \
                 patch("src.core.cache.cache_manager.set"):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/v1/matches/nonexistent_id_9999/advanced-insights")
                    assert resp.status_code == 404
                    data = resp.json()
                    assert "detail" in data
        finally:
            app.dependency_overrides.pop(get_async_session, None)
            app.dependency_overrides.pop(get_odds_service, None)
