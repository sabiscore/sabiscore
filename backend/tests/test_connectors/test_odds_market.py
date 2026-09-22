"""Tests for backend/src/connectors/odds_market.py.

Run:
    cd backend && pytest tests/test_connectors/test_odds_market.py -v
"""

from __future__ import annotations

import math

import pytest

from src.connectors.odds_market import (
    bookmaker_margin,
    compute_market_features,
    implied_probabilities,
    is_complete_market,
    normalize_decimal_odds,
    power_method_probs,
)

# ---------------------------------------------------------------------------
# normalize_decimal_odds
# ---------------------------------------------------------------------------


class TestNormalizeDecimalOdds:
    def test_valid_prices_returned(self):
        result = normalize_decimal_odds({"home_win": 2.0, "draw": 3.5, "away_win": 4.0})
        assert result == {"home_win": 2.0, "draw": 3.5, "away_win": 4.0}

    def test_non_numeric_string_dropped(self):
        result = normalize_decimal_odds(
            {"home_win": 2.0, "draw": 1.0, "away_win": "bad"}
        )
        # draw=1.0 is exactly 1 — below min valid price; "bad" is not numeric.
        assert result == {"home_win": 2.0}

    def test_price_exactly_one_dropped(self):
        result = normalize_decimal_odds({"home_win": 1.0, "draw": 3.5, "away_win": 4.0})
        assert "home_win" not in result
        assert "draw" in result

    def test_none_price_dropped(self):
        result = normalize_decimal_odds(
            {"home_win": None, "draw": 3.3, "away_win": 4.0}
        )
        assert "home_win" not in result

    def test_nan_price_dropped(self):
        result = normalize_decimal_odds(
            {"home_win": float("nan"), "draw": 3.3, "away_win": 4.0}
        )
        assert "home_win" not in result

    def test_inf_price_dropped(self):
        result = normalize_decimal_odds(
            {"home_win": float("inf"), "draw": 3.3, "away_win": 4.0}
        )
        assert "home_win" not in result

    def test_unknown_market_keys_ignored(self):
        """Only MARKETS_1X2 keys are kept."""
        result = normalize_decimal_odds({"home_win": 2.0, "btts_yes": 1.9})
        assert list(result.keys()) == ["home_win"]

    def test_empty_input(self):
        assert normalize_decimal_odds({}) == {}


# ---------------------------------------------------------------------------
# implied_probabilities
# ---------------------------------------------------------------------------


class TestImpliedProbabilities:
    def test_vig_removed_sums_to_one(self):
        probs = implied_probabilities({"home_win": 2.0, "draw": 3.5, "away_win": 4.0})
        assert sum(probs.values()) == pytest.approx(1.0)

    def test_ordering_reflects_price(self):
        probs = implied_probabilities({"home_win": 2.0, "draw": 3.5, "away_win": 4.0})
        # Lowest price → highest implied probability.
        assert probs["home_win"] > probs["draw"] > probs["away_win"]

    def test_without_vig_removal(self):
        probs = implied_probabilities(
            {"home_win": 2.0, "draw": 3.5, "away_win": 4.0},
            remove_vig=False,
        )
        # Raw sum > 1 (overround).
        assert sum(probs.values()) > 1.0

    def test_empty_odds_returns_empty(self):
        assert implied_probabilities({}) == {}


# ---------------------------------------------------------------------------
# bookmaker_margin
# ---------------------------------------------------------------------------


class TestBookmakerMargin:
    def test_positive_for_typical_book(self):
        # sum(1/o) = 1/2 + 1/3.5 + 1/4 = 0.5 + 0.2857 + 0.25 ≈ 1.036 → margin ≈ 0.036
        margin = bookmaker_margin({"home_win": 2.0, "draw": 3.5, "away_win": 4.0})
        assert margin == pytest.approx(0.0357, rel=0.01)

    def test_empty_returns_zero(self):
        assert bookmaker_margin({}) == 0.0

    def test_pinnacle_tight_market(self):
        # Very sharp market — margin should be tiny.
        margin = bookmaker_margin({"home_win": 2.05, "draw": 3.60, "away_win": 4.10})
        assert 0.0 < margin < 0.03


class TestIsCompleteMarket:
    def test_all_three_present(self):
        assert (
            is_complete_market({"home_win": 2.0, "draw": 3.5, "away_win": 4.0}) is True
        )

    def test_partial_market_false(self):
        assert is_complete_market({"home_win": 2.0, "draw": 3.5}) is False

    def test_invalid_price_makes_incomplete(self):
        # away_win=1.0 is dropped by normalisation → incomplete.
        assert (
            is_complete_market({"home_win": 2.0, "draw": 3.5, "away_win": 1.0}) is False
        )

    def test_empty_false(self):
        assert is_complete_market({}) is False


# ---------------------------------------------------------------------------
# power_method_probs
# ---------------------------------------------------------------------------


class TestPowerMethodProbs:
    def test_sums_to_one(self):
        probs = power_method_probs({"home_win": 2.0, "draw": 3.5, "away_win": 4.0})
        assert sum(probs.values()) == pytest.approx(1.0, abs=1e-6)

    def test_all_markets_present(self):
        probs = power_method_probs({"home_win": 2.0, "draw": 3.5, "away_win": 4.0})
        assert set(probs.keys()) == {"home_win", "draw", "away_win"}

    def test_ordering_consistent_with_prices(self):
        probs = power_method_probs({"home_win": 2.0, "draw": 3.5, "away_win": 4.0})
        assert probs["home_win"] > probs["draw"] > probs["away_win"]

    def test_empty_returns_empty(self):
        assert power_method_probs({}) == {}

    def test_differs_from_simple_normalisation_for_skewed_market(self):
        # Heavy favourite — power method should differ from simple normalisation.
        odds = {"home_win": 1.25, "draw": 5.0, "away_win": 9.0}
        simple = implied_probabilities(odds)
        power = power_method_probs(odds)
        # Power method should assign slightly different (less vig-polluted) probs.
        assert simple["home_win"] != pytest.approx(power["home_win"], abs=1e-4)

    def test_favourite_gets_uplift_vs_proportional(self):
        """Margin-proportional power method must raise the favourite's
        probability relative to simple proportional de-vigging, and lower
        the longshot's — this is the defining property of the Shin/power
        method correction for favourite-longshot bias. A regression here
        indicates the binary-search direction has been re-inverted."""
        odds = {"home_win": 2.1, "draw": 3.3, "away_win": 3.8}
        simple = implied_probabilities(odds)
        power = power_method_probs(odds)
        assert power["home_win"] > simple["home_win"]
        assert power["away_win"] < simple["away_win"]


# ---------------------------------------------------------------------------
# compute_market_features
# ---------------------------------------------------------------------------


class TestComputeMarketFeatures:
    @pytest.fixture
    def standard_features(self):
        return compute_market_features(
            model_probabilities={"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
            opening_odds={"home_win": 2.1, "draw": 3.4, "away_win": 3.7},
            current_odds={"home_win": 2.2, "draw": 3.2, "away_win": 3.5},
            closing_odds={"home_win": 2.0, "draw": 3.3, "away_win": 4.0},
        )

    def test_ev_home_win_positive(self, standard_features):
        # model_prob=0.55, price=2.2 → EV = 0.55×2.2 - 1 = 0.21 > 0
        assert standard_features["ev_home_win"] == pytest.approx(0.55 * 2.2 - 1.0)

    def test_odds_drift_is_log_ratio(self, standard_features):
        # log-ratio drift: ln(2.2 / 2.1)
        assert standard_features["odds_drift_home_win"] == pytest.approx(
            math.log(2.2 / 2.1)
        )

    def test_clv_present_with_closing_odds(self, standard_features):
        assert standard_features["clv_home_win"] is not None

    def test_clv_absent_without_closing_odds(self):
        features = compute_market_features(
            model_probabilities={"home_win": 0.5, "draw": 0.25, "away_win": 0.25},
            current_odds={"home_win": 2.0, "draw": 3.3, "away_win": 4.0},
        )
        assert features["clv_home_win"] is None
        assert features["clv_draw"] is None
        assert features["clv_away_win"] is None

    def test_max_ev_equals_best_outcome_ev(self, standard_features):
        ev_values = [
            standard_features[k]
            for k in ("ev_home_win", "ev_draw", "ev_away_win")
            if standard_features[k] is not None
        ]
        assert standard_features["max_ev"] == pytest.approx(max(ev_values))

    def test_max_edge_present(self, standard_features):
        assert standard_features["max_edge"] is not None

    def test_max_abs_odds_drift_present(self, standard_features):
        assert standard_features["max_abs_odds_drift"] is not None

    def test_legacy_max_model_edge_alias(self, standard_features):
        """max_model_edge must remain for Phase 8 backward compat."""
        assert standard_features["max_model_edge"] == standard_features["max_edge"]

    def test_odds_drift_none_without_opening_odds(self):
        features = compute_market_features(
            model_probabilities={"home_win": 0.5, "draw": 0.25, "away_win": 0.25},
            current_odds={"home_win": 2.0, "draw": 3.3, "away_win": 4.0},
        )
        assert features["odds_drift_home_win"] is None

    def test_all_none_with_no_current_odds(self):
        features = compute_market_features(
            model_probabilities={"home_win": 0.5, "draw": 0.25, "away_win": 0.25},
        )
        assert features["ev_home_win"] is None
        assert features["edge_home_win"] is None
        assert features["max_ev"] is None
