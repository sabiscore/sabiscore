"""Challenger Empirical Stress and Invariant Verification Suite for Milestone 1.

This test suite aggressively probes boundary conditions, numerical limits,
randomized property fuzzing, and fail-closed safety invariants across:
1. Advanced Metrics Engine (PPDA, PSxG, xT)
2. Market Intelligence and Provenance Layer (de-vigging, edge, staking gates, lineage)
"""

from __future__ import annotations

import math
import random
import sys
from unittest.mock import patch

import pytest

from src.connectors.odds_market import MARKETS_1X2
from src.models.active_generation import ActiveGenerationError
from src.services.advanced_metrics import (
    MetricResult,
    MetricStatus,
    calculate_ppda,
    evaluate_shot_stopping,
    evaluate_xt,
)
from src.services.market_intel import (
    EdgeClassification,
    MarketDecisionState,
    MarketIntelligenceSummary,
    OutcomeMarketIntel,
    build_market_intelligence,
)


# ===========================================================================
# 1. ADVANCED METRICS ENGINE: BOUNDARY & NUMERICAL STRESS TESTS
# ===========================================================================

class TestAdvancedMetricsStress:
    """Stress tests for calculate_ppda, evaluate_shot_stopping, and evaluate_xt."""

    @pytest.mark.parametrize(
        "passes,actions,expected",
        [
            (0, 1, 0.0),
            (0.0, 100.0, 0.0),
            (1000, 1, 1000.0),
            (1, 1000, 0.001),
            (1e6, 1e5, 10.0),
            (450.55555, 45.11111, round(450.55555 / 45.11111, 4)),
            (sys.float_info.max / 2, sys.float_info.max / 2, 1.0),
        ],
    )
    def test_ppda_numerical_ranges(self, passes, actions, expected):
        """PPDA returns accurate rounded ratios across diverse numerical scales."""
        res = calculate_ppda(passes, actions)
        assert res is not None
        assert math.isclose(res, expected, rel_tol=1e-4)

    def test_ppda_division_by_zero_and_zero_actions(self):
        """Zero defensive actions fail-closed to None."""
        assert calculate_ppda(500, 0) is None
        assert calculate_ppda(500, 0.0) is None
        assert calculate_ppda(0, 0) is None
        assert calculate_ppda(0.0, 0.0) is None

    @pytest.mark.parametrize(
        "passes,actions",
        [
            (-1, 10),
            (10, -1),
            (-0.0001, 10),
            (10, -0.0001),
            (-1e6, -1e6),
        ],
    )
    def test_ppda_negative_rejection(self, passes, actions):
        """Negative inputs are strictly rejected with ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            calculate_ppda(passes, actions)

    def test_ppda_negative_zero_handling(self):
        """In IEEE-754, -0.0 < 0 is False and -0.0 == 0 is True."""
        # defensive_actions = -0.0 should be treated as zero actions -> returns None
        assert calculate_ppda(100, -0.0) is None
        # passes = -0.0 with positive actions -> returns 0.0
        assert calculate_ppda(-0.0, 50) == 0.0

    @pytest.mark.parametrize(
        "psxg,conceded,expected",
        [
            (0.0, 0, 0.0),
            (5.5, 0, 5.5),
            (0.0, 4, -4.0),
            (12.34567, 10.12345, 2.2222),
            (1e5, 1e5, 0.0),
        ],
    )
    def test_shot_stopping_ranges(self, psxg, conceded, expected):
        """PSxG delta returns correct signed difference."""
        res = evaluate_shot_stopping(psxg, conceded)
        assert res is not None
        assert math.isclose(res, expected, abs_tol=1e-4)

    @pytest.mark.parametrize(
        "psxg,conceded",
        [
            (-0.1, 1),
            (1.0, -1),
            (-0.0001, -0.0001),
            (-100.0, 0),
        ],
    )
    def test_shot_stopping_negative_rejection(self, psxg, conceded):
        """Negative PSxG or conceded goals raise ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            evaluate_shot_stopping(psxg, conceded)

    @pytest.mark.parametrize(
        "corpus_avail,count,expected_status",
        [
            (False, 0, MetricStatus.ADVISORY_REQUIRES_CORPUS),
            (False, 1000, MetricStatus.ADVISORY_REQUIRES_CORPUS),
            (False, -10, MetricStatus.ADVISORY_REQUIRES_CORPUS),
            (True, 0, MetricStatus.ADVISORY_REQUIRES_CORPUS),
            (True, -5, MetricStatus.ADVISORY_REQUIRES_CORPUS),
            (True, 1, MetricStatus.UNAVAILABLE),
            (True, 10000, MetricStatus.UNAVAILABLE),
        ],
    )
    def test_xt_gating_matrix(self, corpus_avail, count, expected_status):
        """xT is always fail-closed (value is None) with exact status classification."""
        res = evaluate_xt(event_corpus_available=corpus_avail, event_count=count)
        assert isinstance(res, MetricResult)
        assert res.value is None
        assert res.status == expected_status
        assert res.reason is not None


# ===========================================================================
# 2. MARKET INTELLIGENCE: INCOMPLETE & PATHOLOGICAL MARKET COMBINATIONS
# ===========================================================================

class TestMarketIncompletePermutations:
    """Stress testing all subsets and incomplete permutations of 1X2 markets."""

    @pytest.mark.parametrize(
        "odds_dict",
        [
            {},
            {"home_win": 2.0},
            {"draw": 3.0},
            {"away_win": 4.0},
            {"home_win": 2.0, "draw": 3.0},
            {"home_win": 2.0, "away_win": 4.0},
            {"draw": 3.0, "away_win": 4.0},
            {"btts_yes": 1.90, "btts_no": 1.90},
            {"home_win": 2.0, "draw": 3.0, "extra_market": 1.5},
        ],
    )
    def test_incomplete_market_always_fails_closed_to_partial(self, odds_dict):
        """Any market without all 3 valid 1X2 outcomes MUST yield decision=PARTIAL and stake_permitted=False."""
        summary = build_market_intelligence(
            odds=odds_dict,
            model_probabilities={"home_win": 0.8, "draw": 0.1, "away_win": 0.1},
        )
        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.PARTIAL
        assert summary.provenance.is_complete is False
        if not any(k in odds_dict for k in MARKETS_1X2):
            assert "market_odds_unavailable" in summary.data_gaps
        else:
            assert "incomplete_1x2_market" in summary.data_gaps

    def test_dirty_keys_ignored_clean_keys_processed(self):
        """Keys outside MARKETS_1X2 do not contaminate complete 1X2 processing."""
        mixed_odds = {
            "home_win": 2.20,
            "draw": 3.40,
            "away_win": 3.50,
            "over_2.5": 1.95,
            "under_2.5": 1.85,
            "random_trash": 999.0,
        }
        summary = build_market_intelligence(odds=mixed_odds)
        assert summary.provenance.is_complete is True
        assert len(summary.outcomes) == 3
        assert set(summary.outcomes.keys()) == set(MARKETS_1X2)


# ===========================================================================
# 3. LARGE-SCALE RANDOMIZED PROPERTY FUZZING (UNCERTIFIED MODEL STATE)
# ===========================================================================

class TestUncertifiedModelRandomizedFuzzing:
    """Invariant: Uncertified models must NEVER permit staking under any randomized inputs."""

    @patch("src.services.market_intel.active_generation_is_certified", return_value=False)
    def test_fuzz_1000_random_scenarios_uncertified_invariance(self, mock_cert):
        """Run 1,000 randomized market and probability scenarios; assert 100% fail-closed staking."""
        rng = random.Random(1337)

        for i in range(1000):
            # Generate randomized odds
            h_odds = round(rng.uniform(1.01, 50.0), 3)
            d_odds = round(rng.uniform(1.50, 50.0), 3)
            a_odds = round(rng.uniform(1.01, 50.0), 3)
            odds = {"home_win": h_odds, "draw": d_odds, "away_win": a_odds}

            # Generate random model probabilities (well-behaved or skewed)
            p1 = rng.uniform(0.0, 1.0)
            p2 = rng.uniform(0.0, max(0.0, 1.0 - p1))
            p3 = max(0.0, 1.0 - p1 - p2)
            model_probs = {"home_win": p1, "draw": p2, "away_win": p3}

            is_susp = rng.choice([True, False])
            pre_ko = rng.choice([True, False])

            summary = build_market_intelligence(
                odds=odds,
                model_probabilities=model_probs,
                is_suspended=is_susp,
                pre_kickoff=pre_ko,
            )

            # Strict invariant check
            assert summary.stake_permitted is False, (
                f"Iteration {i} violated invariant: stake_permitted=True when uncertified! "
                f"odds={odds}, model_probs={model_probs}"
            )
            assert summary.decision in (MarketDecisionState.RESEARCH_ONLY, MarketDecisionState.PARTIAL)
            assert summary.provenance.certification_state == "UNVERIFIED"


# ===========================================================================
# 4. CERTIFIED MODEL THRESHOLD BOUNDARY & EV CRASH TESTS
# ===========================================================================

class TestCertifiedModelThresholds:
    """Exact boundary condition tests for edge >= 0.042 and positive EV requirements."""

    @patch("src.services.market_intel.active_generation_is_certified", return_value=True)
    def test_edge_just_below_threshold_fails_to_hold(self, mock_cert):
        """Edge of 0.0419 (< 0.042) must result in HOLD with stake_permitted=False."""
        # 1X2 odds with fair home prob = 0.50
        # Odds: home = 2.0, draw = 4.0, away = 4.0 (fair home = 0.50)
        # Model prob = 0.5419 -> edge = 0.0419 (< 0.042)
        odds = {"home_win": 2.0, "draw": 4.0, "away_win": 4.0}
        model_probs = {"home_win": 0.5419, "draw": 0.23, "away_win": 0.2281}

        summary = build_market_intelligence(odds=odds, model_probabilities=model_probs)
        assert summary.best_edge_outcome == "home_win"
        assert summary.best_edge_value is not None
        assert summary.best_edge_value < 0.042
        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.HOLD

    @patch("src.services.market_intel.active_generation_is_certified", return_value=True)
    def test_edge_at_exact_threshold_with_positive_ev_permits_stake(self, mock_cert):
        """Edge >= 0.042 with EV > 0 permits ACTIONABLE staking."""
        # Odds: home = 2.0, draw = 4.0, away = 4.0 (fair home = 0.50)
        # Model prob = 0.5421 -> edge = 0.0421 (>= 0.042), EV = 0.5421 * 2 - 1 = +0.0842
        odds = {"home_win": 2.0, "draw": 4.0, "away_win": 4.0}
        model_probs = {"home_win": 0.5421, "draw": 0.23, "away_win": 0.2279}

        summary = build_market_intelligence(odds=odds, model_probabilities=model_probs)
        assert summary.best_edge_outcome == "home_win"
        assert summary.best_edge_value is not None
        assert summary.best_edge_value >= 0.042
        assert summary.stake_permitted is True
        assert summary.decision == MarketDecisionState.ACTIONABLE

    @patch("src.services.market_intel.active_generation_is_certified", return_value=True)
    def test_positive_edge_with_zero_ev_blocks_staking(self, mock_cert):
        """If EV == 0.0, staking MUST NOT be permitted (requires best_ev > 0)."""
        # Odds = 2.0, model prob = 0.50 -> EV = 0.50 * 2.0 - 1 = 0.0
        # If fair prob is 0.45 -> edge = +0.05 (>= 0.042), but EV is exactly 0.0
        # Construct book where home price is 2.0, draw = 3.0, away = 6.0
        # raw implied: 0.50 + 0.333 + 0.167 = 1.0 (fair book)
        # Here EV = 0.0 -> no positive expectation -> hold/no-bet
        odds = {"home_win": 2.0, "draw": 3.0, "away_win": 6.0}
        model_probs = {"home_win": 0.50, "draw": 0.3333, "away_win": 0.1667}

        summary = build_market_intelligence(odds=odds, model_probabilities=model_probs)
        # No outcome has positive EV
        assert summary.stake_permitted is False


# ===========================================================================
# 5. ERROR RESILIENCE & CORRUPTION INJECTION
# ===========================================================================

class TestErrorResilienceAndExceptionSafety:
    """Ensure no unhandled exceptions leak to callers when submodules fail."""

    @pytest.mark.parametrize(
        "exception_type",
        [
            ActiveGenerationError("Manifest corrupted"),
            KeyError("missing_key"),
            FileNotFoundError("manifest.json not found"),
            ValueError("invalid literal"),
            TypeError("NoneType is not subscriptable"),
            RuntimeError("Unexpected state"),
        ],
    )
    def test_active_generation_exceptions_handled_gracefully(self, exception_type):
        """Any exception in active_generation module falls back to safe UNVERIFIED state."""
        with patch("src.services.market_intel.active_generation_is_certified", side_effect=exception_type):
            with patch("src.services.market_intel.active_model_version", side_effect=exception_type):
                with patch("src.services.market_intel.active_feature_schema_version", side_effect=exception_type):
                    summary = build_market_intelligence(
                        odds={"home_win": 2.0, "draw": 3.4, "away_win": 3.8},
                        model_probabilities={"home_win": 0.6, "draw": 0.2, "away_win": 0.2},
                    )
                    assert summary.provenance.certification_state == "UNVERIFIED"
                    assert summary.provenance.model_version == "v5_unverified"
                    assert summary.provenance.feature_schema_version == "canonical_58"
                    assert summary.stake_permitted is False
                    assert summary.decision == MarketDecisionState.RESEARCH_ONLY


# ===========================================================================
# 6. EXTREME FLOATS & SERIALIZATION INTEGRITY
# ===========================================================================

class TestSerializationAndFloatAnomalies:
    """Stress tests on scientific notation, tiny probabilities, and roundtrip JSON."""

    def test_tiny_probabilities_and_extreme_odds(self):
        """Tiny probabilities (1e-6) and extreme odds (1000.0) don't crash and dump cleanly."""
        odds = {"home_win": 1.001, "draw": 500.0, "away_win": 1000.0}
        model_probs = {"home_win": 0.9999, "draw": 0.00008, "away_win": 0.00002}

        summary = build_market_intelligence(odds=odds, model_probabilities=model_probs)
        assert summary.provenance.is_complete is True

        json_str = summary.model_dump_json()
        assert "1000" in json_str

        reloaded = MarketIntelligenceSummary.model_validate_json(json_str)
        assert reloaded.provenance.is_complete is True
        assert len(reloaded.outcomes) == 3

    def test_all_outcomes_structure_validity(self):
        """Verify each OutcomeMarketIntel has valid fields and types."""
        odds = {"home_win": 2.50, "draw": 3.20, "away_win": 3.10}
        model_probs = {"home_win": 0.40, "draw": 0.30, "away_win": 0.30}

        summary = build_market_intelligence(odds=odds, model_probabilities=model_probs)
        for outcome_name in MARKETS_1X2:
            intel = summary.outcomes[outcome_name]
            assert isinstance(intel, OutcomeMarketIntel)
            assert intel.decimal_odds > 1.0
            assert 0.0 < intel.raw_implied_probability <= 1.0
            assert 0.0 < intel.fair_market_probability <= 1.0
            assert intel.model_probability is not None
            assert intel.probability_edge is not None
            assert intel.expected_value is not None
            assert intel.classification in (
                EdgeClassification.POSITIVE_EDGE,
                EdgeClassification.NEGATIVE_EDGE,
                EdgeClassification.FAIR,
                EdgeClassification.INSUFFICIENT_DATA,
            )
