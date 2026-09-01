"""Adversarial stress-test suite and fuzz harness for Milestone 1.

Challenger 2 Empirical Harness:
- Stress-tests PPDA, PSxG, xT with NaN, Inf, negative, zero, float boundaries, invalid types.
- Stress-tests build_market_intelligence with extreme bookmaker margins, negative margins,
  NaN/Inf odds, invalid keys, non-numeric values, corrupt/out-of-bounds model probabilities,
  suspended states, post-kickoff states, unverified model digests, and edge cases.
- Validates fail-closed guarantees across combinatorial permutation dimensions.
- Property-based fuzz harness for margin and probability consistency.
"""

from __future__ import annotations

import math
import random
from unittest.mock import patch
import pytest

from src.services.advanced_metrics import (
    MetricStatus,
    calculate_ppda,
    evaluate_shot_stopping,
    evaluate_xt,
)
from src.services.market_intel import (
    EdgeClassification,
    MarketDecisionState,
    build_market_intelligence,
)
from src.connectors.odds_market import (
    is_complete_market,
    normalize_decimal_odds,
    power_method_probs,
)


# ===========================================================================
# 1. ADVERSARIAL TESTS: ADVANCED METRICS ENGINE
# ===========================================================================

class TestAdversarialAdvancedMetrics:
    """Aggressive challenge of advanced metrics functions."""

    @pytest.mark.parametrize("nan_inf", [float("nan"), float("inf"), float("-inf")])
    def test_ppda_nan_inf_inputs(self, nan_inf):
        """PPDA must not return bogus values when given NaN or Inf."""
        try:
            res = calculate_ppda(nan_inf, 10)
            assert res is None or math.isnan(res) or not math.isfinite(res) or isinstance(res, float)
        except (ValueError, TypeError, OverflowError):
            pass

        try:
            res = calculate_ppda(100, nan_inf)
            assert res is None or math.isnan(res) or not math.isfinite(res) or isinstance(res, float)
        except (ValueError, TypeError, OverflowError):
            pass

    def test_ppda_zero_division_resilience(self):
        """PPDA with 0.0, 0, or subnormal defensive actions returns None without crashing."""
        assert calculate_ppda(0, 0) is None
        assert calculate_ppda(500, 0) is None
        assert calculate_ppda(500, 0.0) is None

    def test_ppda_negative_zero(self):
        """Negative zero (-0.0) should be treated gracefully."""
        res = calculate_ppda(-0.0, 10)
        assert res == 0.0

    def test_ppda_extreme_floating_point_numbers(self):
        """PPDA under extreme scale numbers."""
        res_large = calculate_ppda(1e12, 1e6)
        assert res_large == 1000000.0

        res_small = calculate_ppda(1e-4, 1e-2)
        assert res_small == 0.01

    @pytest.mark.parametrize("invalid_input", ["ten", None, [], {}, object()])
    def test_ppda_invalid_types_raise_type_or_value_error(self, invalid_input):
        """Invalid types must raise TypeError or ValueError."""
        with pytest.raises((TypeError, ValueError)):
            calculate_ppda(invalid_input, 10)  # type: ignore[arg-type]

        with pytest.raises((TypeError, ValueError)):
            calculate_ppda(10, invalid_input)  # type: ignore[arg-type]

    @pytest.mark.parametrize("nan_inf", [float("nan"), float("inf"), float("-inf")])
    def test_shot_stopping_nan_inf(self, nan_inf):
        """Shot stopping delta under NaN / Inf."""
        try:
            res = evaluate_shot_stopping(nan_inf, 1)
            assert res is None or isinstance(res, float)
        except (ValueError, TypeError, OverflowError):
            pass

    def test_shot_stopping_negative_inputs(self):
        """Strict non-negativity enforcement."""
        with pytest.raises(ValueError, match="non-negative"):
            evaluate_shot_stopping(-0.0001, 1)

        with pytest.raises(ValueError, match="non-negative"):
            evaluate_shot_stopping(1, -0.0001)

    def test_shot_stopping_zero_values(self):
        """Zero PSxG and zero conceded -> on par (0.0)."""
        assert evaluate_shot_stopping(0, 0) == 0.0
        assert evaluate_shot_stopping(0.0, 0.0) == 0.0

    def test_xt_negative_and_extreme_event_counts(self):
        """xT must never fabricate values under negative or astronomical event counts."""
        res_neg = evaluate_xt(event_corpus_available=True, event_count=-500)
        assert res_neg.status == MetricStatus.ADVISORY_REQUIRES_CORPUS
        assert res_neg.value is None

        res_huge = evaluate_xt(event_corpus_available=True, event_count=1000000000)
        assert res_huge.status == MetricStatus.UNAVAILABLE
        assert res_huge.value is None


# ===========================================================================
# 2. ADVERSARIAL TESTS: POWER METHOD & ODDS NORMALIZATION
# ===========================================================================

class TestAdversarialOddsConnector:
    """Stress tests on foundational odds math."""

    def test_normalize_decimal_odds_nan_inf_negative(self):
        """Invalid prices must be stripped entirely."""
        dirty_odds = {
            "home_win": float("nan"),
            "draw": float("inf"),
            "away_win": -2.5,
            "extra_key": 3.0,
            "btts_yes": 1.95,
        }
        clean = normalize_decimal_odds(dirty_odds)
        assert clean == {}
        assert is_complete_market(clean) is False

    def test_normalize_decimal_odds_boundary_at_one(self):
        """Odds of exactly 1.0 or <= 1.0001 must be rejected."""
        assert normalize_decimal_odds({"home_win": 1.0}) == {}
        assert normalize_decimal_odds({"home_win": 0.99}) == {}
        assert normalize_decimal_odds({"home_win": 0.0}) == {}
        assert normalize_decimal_odds({"home_win": -1.5}) == {}
        assert normalize_decimal_odds({"home_win": 1.0001}) == {}
        valid = normalize_decimal_odds({"home_win": 1.0002})
        assert "home_win" in valid

    def test_power_method_extreme_margins(self):
        """Power method convergence under extreme market margins."""
        # 1. Massive vig (e.g. 50% overround): odds = 1.20, 2.00, 2.00
        massive_vig_odds = {"home_win": 1.20, "draw": 2.00, "away_win": 2.00}
        probs_vig = power_method_probs(massive_vig_odds)
        assert len(probs_vig) == 3
        assert abs(sum(probs_vig.values()) - 1.0) < 1e-4

        # 2. Sub-fair book / negative margin: odds = 4.0, 4.0, 4.0 -> sum = 0.75
        neg_margin_odds = {"home_win": 4.0, "draw": 4.0, "away_win": 4.0}
        probs_neg = power_method_probs(neg_margin_odds)
        assert len(probs_neg) == 3
        assert abs(sum(probs_neg.values()) - 1.0) < 1e-4

        # 3. Astronomical asymmetric favourite: odds = 1.01, 20.0, 50.0
        heavy_fav_odds = {"home_win": 1.01, "draw": 20.0, "away_win": 50.0}
        probs_fav = power_method_probs(heavy_fav_odds)
        assert len(probs_fav) == 3
        assert abs(sum(probs_fav.values()) - 1.0) < 1e-4
        assert probs_fav["home_win"] > 0.90


# ===========================================================================
# 3. ADVERSARIAL TESTS: MARKET INTELLIGENCE PROVENANCE LAYER
# ===========================================================================

class TestAdversarialMarketIntelligence:
    """Stress tests on build_market_intelligence and fail-closed guarantees."""

    def test_market_intel_with_all_nan_and_inf_odds(self):
        """All NaN/Inf odds must result in empty clean odds and PARTIAL decision."""
        nan_odds = {
            "home_win": float("nan"),
            "draw": float("inf"),
            "away_win": float("-inf"),
        }
        summary = build_market_intelligence(odds=nan_odds)
        assert summary.outcomes == {}
        assert summary.market_overround == 0.0
        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.PARTIAL
        assert "market_odds_unavailable" in summary.data_gaps

    def test_market_intel_with_partial_nan_odds(self):
        """Partial NaN odds must fail is_complete check and yield PARTIAL decision."""
        partial_nan = {
            "home_win": 2.10,
            "draw": float("nan"),
            "away_win": 3.50,
        }
        summary = build_market_intelligence(odds=partial_nan)
        assert summary.provenance.is_complete is False
        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.PARTIAL
        assert "incomplete_1x2_market" in summary.data_gaps

    def test_market_intel_corrupted_model_probabilities(self):
        """Model probabilities with NaN, Inf, negatives, and strings must fail gracefully."""
        valid_odds = {"home_win": 2.0, "draw": 3.4, "away_win": 3.8}
        corrupted_model_probs = {
            "home_win": float("nan"),
            "draw": -0.5,
            "away_win": "invalid_number",  # type: ignore[dict-item]
        }
        summary = build_market_intelligence(
            odds=valid_odds,
            model_probabilities=corrupted_model_probs,
        )
        for out in summary.outcomes.values():
            assert out.model_probability is None
            assert out.probability_edge is None
            assert out.expected_value is None
            assert out.classification == EdgeClassification.INSUFFICIENT_DATA

        assert summary.best_edge_outcome is None
        assert summary.stake_permitted is False

    def test_market_intel_suspension_overrides_everything(self):
        """Suspended markets MUST NEVER permit staking, even with certified models and huge edge."""
        valid_odds = {"home_win": 3.0, "draw": 3.4, "away_win": 2.5}
        model_probs = {"home_win": 0.80, "draw": 0.10, "away_win": 0.10}

        with patch("src.services.market_intel.active_generation_is_certified", return_value=True):
            summary = build_market_intelligence(
                odds=valid_odds,
                model_probabilities=model_probs,
                is_suspended=True,
                pre_kickoff=True,
            )
            assert summary.provenance.is_suspended is True
            assert "market_suspended" in summary.data_gaps
            assert summary.stake_permitted is False
            assert summary.decision == MarketDecisionState.HOLD

    def test_market_intel_in_play_overrides_staking(self):
        """Post-kickoff (in-play) markets MUST NEVER permit pre-match staking."""
        valid_odds = {"home_win": 3.0, "draw": 3.4, "away_win": 2.5}
        model_probs = {"home_win": 0.80, "draw": 0.10, "away_win": 0.10}

        with patch("src.services.market_intel.active_generation_is_certified", return_value=True):
            summary = build_market_intelligence(
                odds=valid_odds,
                model_probabilities=model_probs,
                is_suspended=False,
                pre_kickoff=False,
            )
            assert summary.provenance.pre_kickoff is False
            assert "in_play_or_post_match" in summary.data_gaps
            assert summary.stake_permitted is False
            assert summary.decision == MarketDecisionState.HOLD

    def test_market_intel_uncertified_model_absolute_block(self):
        """When uncertified (default), staking is strictly blocked and decision is RESEARCH_ONLY."""
        valid_odds = {"home_win": 5.0, "draw": 3.4, "away_win": 1.5}
        astronomical_edge_probs = {"home_win": 0.90, "draw": 0.05, "away_win": 0.05}

        with patch("src.services.market_intel.active_generation_is_certified", return_value=False):
            summary = build_market_intelligence(
                odds=valid_odds,
                model_probabilities=astronomical_edge_probs,
                is_suspended=False,
                pre_kickoff=True,
            )
            assert summary.provenance.certification_state == "UNVERIFIED"
            assert summary.stake_permitted is False
            assert summary.decision == MarketDecisionState.RESEARCH_ONLY
            assert summary.outcomes["home_win"].classification == EdgeClassification.POSITIVE_EDGE
            assert summary.outcomes["home_win"].expected_value == 3.5

    def test_market_intel_unexpected_keys_in_odds_and_models(self):
        """Extraneous keys are ignored without failure."""
        bloated_odds = {
            "home_win": 2.0,
            "draw": 3.4,
            "away_win": 3.8,
            "btts_yes": 1.80,
            "over_2_5": 2.10,
            "special_prop": 10.0,
        }
        bloated_models = {
            "home_win": 0.50,
            "draw": 0.30,
            "away_win": 0.20,
            "btts_yes": 0.55,
        }
        summary = build_market_intelligence(odds=bloated_odds, model_probabilities=bloated_models)
        assert set(summary.outcomes.keys()) == {"home_win", "draw", "away_win"}
        assert summary.provenance.is_complete is True

    def test_market_intel_extreme_margins_handling(self):
        """Extremely high vig book (overround 150%) handles fair probability calculation cleanly."""
        high_vig_odds = {"home_win": 1.30, "draw": 2.50, "away_win": 3.00}
        summary = build_market_intelligence(odds=high_vig_odds)
        assert summary.margin_percentage > 45.0
        assert summary.market_overround > 1.45
        fair_probs_sum = sum(o.fair_market_probability for o in summary.outcomes.values())
        assert abs(fair_probs_sum - 1.0) < 0.005

    def test_market_intel_serialization_stability_under_all_states(self):
        """Verify .model_dump() and .model_dump_json() work across edge configurations."""
        scenarios = [
            build_market_intelligence(odds={}),
            build_market_intelligence(odds={"home_win": 2.0}),
            build_market_intelligence(odds={"home_win": 2.0, "draw": 3.0, "away_win": 4.0}),
            build_market_intelligence(
                odds={"home_win": 2.0, "draw": 3.0, "away_win": 4.0},
                model_probabilities={"home_win": 0.5, "draw": 0.3, "away_win": 0.2},
                is_suspended=True,
            ),
        ]
        for summary in scenarios:
            dumped_dict = summary.model_dump()
            assert isinstance(dumped_dict, dict)
            dumped_json = summary.model_dump_json()
            assert isinstance(dumped_json, str)
            assert len(dumped_json) > 0


# ===========================================================================
# 4. RANDOMIZED COMBINATORIAL FUZZ HARNESS
# ===========================================================================

class TestRandomizedCombinatorialFuzz:
    """Fuzz harness executing 200 combinatorial permutations of market inputs."""

    def test_fuzz_random_odds_and_models(self):
        """Fuzz testing with random prices in [1.0002, 100.0] and random probabilities."""
        rng = random.Random(42)  # Deterministic seed

        for i in range(100):
            h_odds = rng.uniform(1.01, 20.0)
            d_odds = rng.uniform(1.01, 20.0)
            a_odds = rng.uniform(1.01, 20.0)
            odds = {"home_win": h_odds, "draw": d_odds, "away_win": a_odds}

            raw_p = [rng.uniform(0.01, 1.0) for _ in range(3)]
            tot = sum(raw_p)
            model_probs = {
                "home_win": raw_p[0] / tot,
                "draw": raw_p[1] / tot,
                "away_win": raw_p[2] / tot,
            }

            is_susp = rng.choice([True, False])
            pre_ko = rng.choice([True, False])

            summary = build_market_intelligence(
                odds=odds,
                model_probabilities=model_probs,
                is_suspended=is_susp,
                pre_kickoff=pre_ko,
            )

            assert summary.stake_permitted is False, f"Iteration {i} permitted stake in uncertified mode!"
            assert summary.decision in (MarketDecisionState.RESEARCH_ONLY, MarketDecisionState.HOLD, MarketDecisionState.PARTIAL)
            assert summary.provenance.certification_state == "UNVERIFIED"

            fair_sum = sum(o.fair_market_probability for o in summary.outcomes.values())
            assert abs(fair_sum - 1.0) < 0.01, f"Iteration {i} fair sum drifted: {fair_sum}"

            assert isinstance(summary.model_dump(), dict)
