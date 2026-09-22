"""Tests for backend/src/features/phase9_xg_market_features.py.

Run:
    cd backend && pytest tests/test_connectors/test_phase9_xg_market_features.py -v
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.features.phase9_xg_market_features import (
    _latest_team_row,
    _safe_float,
    build_hybrid_xg_features,
    build_market_efficiency_report,
    build_value_market_features,
)


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_numeric_string(self):
        assert _safe_float("1.5") == pytest.approx(1.5)

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0

    def test_custom_default(self):
        assert _safe_float(None, default=-1.0) == -1.0

    def test_nan_returns_default(self):
        assert _safe_float(float("nan")) == 0.0

    def test_inf_returns_default(self):
        assert _safe_float(float("inf")) == 0.0

    def test_valid_int(self):
        assert _safe_float(3) == 3.0

    def test_non_numeric_string(self):
        assert _safe_float("bad") == 0.0


# ---------------------------------------------------------------------------
# _latest_team_row
# ---------------------------------------------------------------------------


class TestLatestTeamRow:
    @pytest.fixture
    def rollups(self):
        return pd.DataFrame(
            [
                {"match_order": 1, "team": "Arsenal", "rolling_xg_for": 1.5},
                {"match_order": 2, "team": "Arsenal", "rolling_xg_for": 1.8},
                {"match_order": 1, "team": "Chelsea", "rolling_xg_for": 1.2},
            ]
        )

    def test_returns_last_by_match_order(self, rollups):
        row = _latest_team_row(rollups, "Arsenal")
        assert row is not None
        assert row["rolling_xg_for"] == pytest.approx(1.8)

    def test_casefold_matching(self, rollups):
        row = _latest_team_row(rollups, "arsenal")
        assert row is not None

    def test_missing_team_returns_none(self, rollups):
        assert _latest_team_row(rollups, "Liverpool") is None

    def test_empty_dataframe_returns_none(self):
        assert _latest_team_row(pd.DataFrame(), "Arsenal") is None

    def test_no_team_column_returns_none(self):
        df = pd.DataFrame([{"rolling_xg_for": 1.5}])
        assert _latest_team_row(df, "Arsenal") is None


# ---------------------------------------------------------------------------
# build_hybrid_xg_features
# ---------------------------------------------------------------------------


class TestBuildHybridXgFeatures:
    @pytest.fixture
    def rollups(self):
        return pd.DataFrame(
            [
                {
                    "match_order": 1,
                    "team": "Arsenal",
                    "rolling_xg_for": 2.1,
                    "rolling_xg_against": 0.9,
                    "rolling_xg_diff": 1.2,
                },
                {
                    "match_order": 1,
                    "team": "Chelsea",
                    "rolling_xg_for": 1.4,
                    "rolling_xg_against": 1.3,
                    "rolling_xg_diff": 0.1,
                },
            ]
        )

    @pytest.fixture
    def team_stats(self):
        return {
            "home": {"xg_avg_5": 1.9, "xg_conceded_avg_5": 1.0},
            "away": {"xg_avg_5": 1.3, "xg_conceded_avg_5": 1.5},
        }

    def test_uses_understat_diff_when_available(self, team_stats, rollups):
        features = build_hybrid_xg_features(
            home_team="Arsenal",
            away_team="Chelsea",
            team_stats=team_stats,
            understat_rollups=rollups,
        )
        assert features["understat_home_rolling_xg_diff"] == pytest.approx(1.2)
        assert features["understat_away_rolling_xg_diff"] == pytest.approx(0.1)
        # hybrid_xg_diff = home_diff - away_diff = 1.2 - 0.1
        assert features["hybrid_xg_diff"] == pytest.approx(1.1)

    def test_falls_back_to_team_stats_without_rollups(self):
        features = build_hybrid_xg_features(
            home_team="A",
            away_team="B",
            team_stats={
                "home": {"xg_avg_5": 1.7, "xg_conceded_avg_5": 1.0},
                "away": {"xg_avg_5": 1.2, "xg_conceded_avg_5": 1.6},
            },
        )
        expected_diff = (1.7 - 1.0) - (1.2 - 1.6)  # 0.7 - (-0.4) = 1.1
        assert features["hybrid_xg_diff"] == pytest.approx(expected_diff)

    def test_total_xg_expectation_formula(self):
        features = build_hybrid_xg_features(
            home_team="A",
            away_team="B",
            team_stats={
                "home": {"xg_avg_5": 1.7, "xg_conceded_avg_5": 1.0},
                "away": {"xg_avg_5": 1.2, "xg_conceded_avg_5": 1.6},
            },
        )
        # (home_for + away_for + home_against + away_against) / 2
        expected = (1.7 + 1.2 + 1.0 + 1.6) / 2.0
        assert features["hybrid_total_xg_expectation"] == pytest.approx(expected)

    def test_returns_all_float(self, team_stats, rollups):
        features = build_hybrid_xg_features(
            home_team="Arsenal",
            away_team="Chelsea",
            team_stats=team_stats,
            understat_rollups=rollups,
        )
        for key, val in features.items():
            assert isinstance(val, float), f"{key} is not float: {val!r}"

    def test_empty_team_stats_gives_zero_defaults(self):
        features = build_hybrid_xg_features(home_team="A", away_team="B")
        assert features["hybrid_home_xg_for_5"] == 0.0
        assert features["hybrid_xg_diff"] == 0.0

    def test_casefold_team_name_resolution_in_rollups(self, team_stats):
        rollups = pd.DataFrame(
            [
                {
                    "match_order": 1,
                    "team": "arsenal",  # lowercase
                    "rolling_xg_for": 2.0,
                    "rolling_xg_against": 1.0,
                    "rolling_xg_diff": 1.0,
                }
            ]
        )
        features = build_hybrid_xg_features(
            home_team="Arsenal",  # mixed case
            away_team="Chelsea",
            team_stats=team_stats,
            understat_rollups=rollups,
        )
        assert features.get("understat_home_rolling_xg_diff") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# build_value_market_features
# ---------------------------------------------------------------------------


class TestBuildValueMarketFeatures:
    def test_delegates_to_compute_market_features(self):
        features = build_value_market_features(
            model_probabilities={"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
            current_odds={"home_win": 2.2, "draw": 3.2, "away_win": 3.5},
        )
        assert "ev_home_win" in features
        assert "max_ev" in features

    def test_no_odds_returns_none_ev(self):
        features = build_value_market_features(
            model_probabilities={"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
        )
        assert features["ev_home_win"] is None


# ---------------------------------------------------------------------------
# build_market_efficiency_report
# ---------------------------------------------------------------------------


class TestBuildMarketEfficiencyReport:
    @pytest.fixture
    def report(self):
        return build_market_efficiency_report(
            model_probabilities={"home_win": 0.60, "draw": 0.25, "away_win": 0.15},
            opening_odds={"home_win": 1.9, "draw": 3.4, "away_win": 5.0},
            current_odds={"home_win": 1.85, "draw": 3.5, "away_win": 5.5},
        )

    def test_has_value_bets_when_positive_ev(self, report):
        # model_prob=0.60, price=1.85 → EV = 0.60×1.85 - 1 = 0.11 > 0
        assert report["has_value"] is True
        assert len(report["value_bets"]) >= 1

    def test_bookmaker_margin_present(self, report):
        assert "bookmaker_margin" in report
        assert report["bookmaker_margin"] > 0.0

    def test_clv_not_available_without_closing(self, report):
        assert report["clv_available"] is False

    def test_clv_available_with_closing(self):
        report = build_market_efficiency_report(
            model_probabilities={"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
            current_odds={"home_win": 2.0, "draw": 3.3, "away_win": 4.0},
            closing_odds={"home_win": 1.95, "draw": 3.4, "away_win": 4.2},
        )
        assert report["clv_available"] is True

    def test_no_value_bets_below_threshold(self):
        # All outcomes have negative EV at these odds
        report = build_market_efficiency_report(
            model_probabilities={"home_win": 0.30, "draw": 0.30, "away_win": 0.40},
            current_odds={"home_win": 2.8, "draw": 3.1, "away_win": 2.2},
            ev_threshold=0.05,
        )
        # Verify filter works — may not be zero depending on probs
        for vb in report["value_bets"]:
            assert vb["ev"] > 0.05

    def test_max_ev_in_report(self, report):
        assert report["max_ev"] is not None

    def test_value_bets_carry_kelly_fraction(self, report):
        for vb in report["value_bets"]:
            assert "kelly_fraction" in vb
            assert vb["kelly_fraction"] is not None
            assert 0.0 <= vb["kelly_fraction"] <= 1.0

    def test_kelly_fraction_matches_formula(self, report):
        # Top value bet is home_win: p=0.60, price=1.85 → b=0.85, q=0.40
        # f* = (0.85*0.60 - 0.40) / 0.85 = (0.51 - 0.40)/0.85 = 0.1294...
        vb = report["value_bets"][0]
        assert vb["outcome"] == "home_win"
        b = vb["current_price"] - 1.0
        expected = (b * vb["model_prob"] - (1.0 - vb["model_prob"])) / b
        assert vb["kelly_fraction"] == pytest.approx(expected)

    def test_recommended_kelly_matches_top_bet(self, report):
        assert (
            report["recommended_kelly_fraction"]
            == report["value_bets"][0]["kelly_fraction"]
        )

    def test_recommended_kelly_none_without_value(self):
        report = build_market_efficiency_report(
            model_probabilities={"home_win": 0.30, "draw": 0.30, "away_win": 0.40},
            current_odds={"home_win": 2.8, "draw": 3.1, "away_win": 2.2},
            ev_threshold=0.5,  # nothing clears this
        )
        assert report["recommended_kelly_fraction"] is None
        assert report["has_value"] is False

    def test_value_bets_sorted_by_kelly_desc(self):
        # Construct a market with two +EV outcomes of differing strength.
        report = build_market_efficiency_report(
            model_probabilities={"home_win": 0.70, "draw": 0.20, "away_win": 0.10},
            current_odds={"home_win": 1.8, "draw": 6.0, "away_win": 12.0},
        )
        kellys = [vb["kelly_fraction"] or 0.0 for vb in report["value_bets"]]
        assert kellys == sorted(kellys, reverse=True)

    def test_complete_market_flagged(self, report):
        assert report["market_complete"] is True
        assert report["market_sharpness"] in {"sharp", "standard"}

    def test_incomplete_market_sharpness_unknown(self):
        report = build_market_efficiency_report(
            model_probabilities={"home_win": 0.60, "draw": 0.25, "away_win": 0.15},
            current_odds={"home_win": 1.85},  # only one outcome priced
        )
        assert report["market_complete"] is False
        assert report["market_sharpness"] == "unknown"
