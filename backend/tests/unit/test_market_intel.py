"""Unit tests for Market Intelligence and Provenance Layer.

Tests cover provenance capture, de-vigging aggregation, overround computation,
fair probability derivation, edge classification, and fail-closed staking gates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from src.services.market_intel import (
    EdgeClassification,
    MarketDecisionState,
    MarketIntelligenceSummary,
    OutcomeMarketIntel,
    build_market_intelligence,
)


class TestMarketIntelligenceProvenance:
    """Tests for complete audit lineage and provenance metadata."""

    def test_provenance_fields_populated(self):
        """Verify all provenance fields are correctly populated."""
        captured_time = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
        odds = {"home_win": 2.10, "draw": 3.40, "away_win": 3.60}
        model_probs = {"home_win": 0.50, "draw": 0.28, "away_win": 0.22}

        summary = build_market_intelligence(
            odds=odds,
            model_probabilities=model_probs,
            provider="the_odds_api",
            bookmaker="pinnacle",
            captured_at=captured_time,
            staleness_seconds=120,
            is_suspended=False,
            pre_kickoff=True,
            uncertainty_available=True,
        )

        assert isinstance(summary, MarketIntelligenceSummary)
        prov = summary.provenance
        assert prov.provider == "the_odds_api"
        assert prov.bookmaker == "pinnacle"
        assert prov.market_type == "1X2"
        assert prov.captured_at == captured_time
        assert prov.staleness_seconds == 120
        assert prov.is_complete is True
        assert prov.is_suspended is False
        assert prov.pre_kickoff is True
        assert prov.devig_method in ("POWER_METHOD", "PROPORTIONAL")
        assert isinstance(prov.model_version, str)
        assert isinstance(prov.feature_schema_version, str)
        assert isinstance(prov.certification_state, str)
        assert prov.uncertainty_available is True


class TestMarketIntelligenceCalculations:
    """Tests for market overround, fair probabilities, EV, and edges."""

    def test_overround_and_fair_probabilities(self):
        """Overround > 1.0, fair probabilities sum to 1.0, and outcomes are populated."""
        odds = {"home_win": 2.0, "draw": 3.5, "away_win": 4.0}
        model_probs = {"home_win": 0.55, "draw": 0.25, "away_win": 0.20}

        summary = build_market_intelligence(odds=odds, model_probabilities=model_probs)

        # Raw implied: 1/2.0 + 1/3.5 + 1/4.0 = 0.50 + 0.2857 + 0.25 = 1.0357
        assert summary.market_overround > 1.0
        assert summary.margin_percentage > 0.0

        assert "home_win" in summary.outcomes
        assert "draw" in summary.outcomes
        assert "away_win" in summary.outcomes

        fair_sum = sum(o.fair_market_probability for o in summary.outcomes.values())
        assert abs(fair_sum - 1.0) < 0.005

        home_intel = summary.outcomes["home_win"]
        assert isinstance(home_intel, OutcomeMarketIntel)
        assert home_intel.decimal_odds == 2.0
        assert home_intel.raw_implied_probability == 0.5
        assert home_intel.model_probability == 0.55
        assert home_intel.probability_edge is not None
        assert home_intel.expected_value == 0.10  # 0.55 * 2.0 - 1.0 = 0.10
        assert home_intel.classification == EdgeClassification.POSITIVE_EDGE

    def test_edge_classifications(self):
        """Verify positive, negative, and fair edge classifications."""
        odds = {"home_win": 2.0, "draw": 3.5, "away_win": 4.0}
        # Model gives higher home, lower draw, exact away
        summary = build_market_intelligence(
            odds=odds,
            model_probabilities={"home_win": 0.60, "draw": 0.10, "away_win": 0.2414},
        )

        assert summary.outcomes["home_win"].classification == EdgeClassification.POSITIVE_EDGE
        assert summary.outcomes["draw"].classification == EdgeClassification.NEGATIVE_EDGE

    def test_best_edge_selection(self):
        """Verify best edge outcome and value are correctly selected."""
        odds = {"home_win": 2.20, "draw": 3.40, "away_win": 3.40}
        # Home has edge: fair is ~0.43, model is 0.55 -> +0.12 edge
        summary = build_market_intelligence(
            odds=odds,
            model_probabilities={"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
        )
        assert summary.best_edge_outcome == "home_win"
        assert summary.best_edge_value is not None
        assert summary.best_edge_value > 0.05


class TestStakingGateInvariance:
    """Critical invariant: Uncertified model NEVER permits staking."""

    def test_stake_permitted_is_false_when_uncertified(self):
        """Even with huge mathematical edge, uncertified model must fail-closed."""
        odds = {"home_win": 3.0, "draw": 3.5, "away_win": 2.5}
        huge_edge_model_probs = {"home_win": 0.70, "draw": 0.15, "away_win": 0.15}

        # In current repo state, active_generation_is_certified() returns False
        summary = build_market_intelligence(
            odds=odds,
            model_probabilities=huge_edge_model_probs,
        )

        assert summary.provenance.certification_state == "UNVERIFIED"
        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.RESEARCH_ONLY

    @patch("src.services.market_intel.active_generation_is_certified", return_value=True)
    def test_certified_model_with_actionable_edge_permits_stake(self, mock_cert):
        """When certified and edge exceeds actionable threshold with positive EV, staking is permitted."""
        odds = {"home_win": 2.5, "draw": 3.4, "away_win": 3.0}
        # Home fair prob ~ 0.38, model prob 0.50 -> edge ~ +0.12 >= 0.042, EV = 0.50 * 2.5 - 1 = +0.25
        summary = build_market_intelligence(
            odds=odds,
            model_probabilities={"home_win": 0.50, "draw": 0.25, "away_win": 0.25},
        )

        assert summary.provenance.certification_state == "CERTIFIED"
        assert summary.stake_permitted is True
        assert summary.decision == MarketDecisionState.ACTIONABLE

    @patch("src.services.market_intel.active_generation_is_certified", return_value=True)
    def test_certified_model_sub_threshold_edge_holds(self, mock_cert):
        """When certified but edge is sub-threshold (< 0.042), hold without staking."""
        odds = {"home_win": 2.0, "draw": 3.5, "away_win": 4.0}
        # Home fair prob ~ 0.48, model prob 0.50 -> edge ~ +0.02 (< 0.042)
        summary = build_market_intelligence(
            odds=odds,
            model_probabilities={"home_win": 0.50, "draw": 0.25, "away_win": 0.25},
        )

        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.HOLD

    @patch("src.services.market_intel.active_generation_is_certified", return_value=True)
    def test_certified_model_negative_edge_yields_no_bet(self, mock_cert):
        """When certified but all edges are negative, yields NO_BET."""
        odds = {"home_win": 2.0, "draw": 3.5, "away_win": 4.0}
        # Model probabilities strictly below market fair probabilities
        summary = build_market_intelligence(
            odds=odds,
            model_probabilities={"home_win": 0.40, "draw": 0.25, "away_win": 0.20},
        )

        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.NO_BET


class TestMarketFailClosedAndDataGaps:
    """Tests for missing odds, incomplete markets, and suspensions."""

    def test_empty_odds_fail_closed(self):
        """Empty odds mapping returns PARTIAL decision with data gaps."""
        summary = build_market_intelligence(odds={})

        assert summary.outcomes == {}
        assert summary.market_overround == 0.0
        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.PARTIAL
        assert summary.provenance.is_complete is False
        assert "market_odds_unavailable" in summary.data_gaps

    def test_incomplete_1x2_market(self):
        """Partial odds (e.g. only home and draw) flags incomplete market."""
        partial_odds = {"home_win": 2.10, "draw": 3.20}
        summary = build_market_intelligence(odds=partial_odds)

        assert summary.provenance.is_complete is False
        assert "incomplete_1x2_market" in summary.data_gaps
        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.PARTIAL

    def test_missing_model_probabilities(self):
        """Missing model probabilities sets INSUFFICIENT_DATA and data gap."""
        odds = {"home_win": 2.0, "draw": 3.4, "away_win": 3.8}
        summary = build_market_intelligence(odds=odds, model_probabilities=None)

        assert "model_probabilities_unavailable" in summary.data_gaps
        for outcome_intel in summary.outcomes.values():
            assert outcome_intel.model_probability is None
            assert outcome_intel.probability_edge is None
            assert outcome_intel.expected_value is None
            assert outcome_intel.classification == EdgeClassification.INSUFFICIENT_DATA

    def test_suspended_market(self):
        """Suspended market flags data gap and forbids staking."""
        odds = {"home_win": 2.0, "draw": 3.4, "away_win": 3.8}
        summary = build_market_intelligence(
            odds=odds,
            model_probabilities={"home_win": 0.6, "draw": 0.2, "away_win": 0.2},
            is_suspended=True,
        )

        assert summary.provenance.is_suspended is True
        assert "market_suspended" in summary.data_gaps
        assert summary.stake_permitted is False

    def test_post_kickoff_market(self):
        """Post-kickoff market flags in-play gap and forbids pre-match staking."""
        odds = {"home_win": 2.0, "draw": 3.4, "away_win": 3.8}
        summary = build_market_intelligence(
            odds=odds,
            model_probabilities={"home_win": 0.6, "draw": 0.2, "away_win": 0.2},
            pre_kickoff=False,
        )

        assert summary.provenance.pre_kickoff is False
        assert "in_play_or_post_match" in summary.data_gaps
        assert summary.stake_permitted is False


class TestPydanticCompatibility:
    """Tests for Pydantic v2 serialization and protected namespace avoidance."""

    def test_model_dump_serialization(self):
        """Verify summary serializes cleanly to dict without namespace warnings."""
        odds = {"home_win": 2.0, "draw": 3.4, "away_win": 3.8}
        summary = build_market_intelligence(
            odds=odds,
            model_probabilities={"home_win": 0.5, "draw": 0.3, "away_win": 0.2},
        )
        dumped = summary.model_dump()
        assert isinstance(dumped, dict)
        assert "outcomes" in dumped
        assert "provenance" in dumped
        assert dumped["provenance"]["model_version"] == summary.provenance.model_version
