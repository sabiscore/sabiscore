import pytest
from src.insights.calculators import (
    calculate_expected_value,
    calculate_kelly_stake,
    calculate_implied_probability,
    calculate_value_percentage,
    calculate_confidence_interval,
    calculate_betting_edge,
    calculate_roi,
    calculate_sharpe_ratio,
    optimize_bet_size,
    calculate_breakeven_odds,
    assess_bet_quality,
)


class TestCalculators:
    def test_calculate_expected_value(self):
        ev = calculate_expected_value(model_prob=0.6, odds=2.0)
        assert ev == pytest.approx(0.2)

    def test_calculate_expected_value_edge_cases(self):
        # Zero odds
        assert calculate_expected_value(0.5, 0) == 0
        # 100% probability
        assert calculate_expected_value(1.0, 2.0) == 1.0
        # Zero probability should reflect full loss
        assert calculate_expected_value(0.0, 2.0) == -1.0

    def test_calculate_kelly_stake(self):
        kelly = calculate_kelly_stake(prob=0.6, odds=2.0, bankroll=100)
        assert kelly == pytest.approx(20.0)

    def test_calculate_kelly_stake_edge_cases(self):
        # Fractional Kelly
        assert calculate_kelly_stake(0.6, 2.0, 100, 0.5) == 10.0
        # Zero bankroll
        assert calculate_kelly_stake(0.6, 2.0, 0) == 0
        # Negative EV
        assert calculate_kelly_stake(0.4, 2.0, 100) == 0

    def test_calculate_implied_probability(self):
        assert calculate_implied_probability(2.0) == 0.5
        assert calculate_implied_probability(4.0) == 0.25

    def test_calculate_value_percentage(self):
        assert calculate_value_percentage(0.6, 0.5) == 20.0
        assert calculate_value_percentage(0.4, 0.5) == -20.0

    def test_calculate_confidence_interval(self):
        lower, upper = calculate_confidence_interval(
            0.6, sample_size=200, confidence_level=0.95
        )
        assert 0 <= lower <= upper <= 1
        # Degenerate sample size should clamp to original probability
        assert calculate_confidence_interval(0.6, sample_size=0) == (0.6, 0.6)

    def test_calculate_betting_edge(self):
        edges = calculate_betting_edge(
            {"home_win": 0.6, "draw": 0.2, "away_win": 0.2},
            {"home_win": 2.0, "draw": 4.0},
        )
        assert pytest.approx(edges["home_win"], rel=1e-5) == 0.1
        assert "away_win" not in edges

    def test_calculate_roi_and_breakeven(self):
        assert calculate_roi(100, 120, 50) == pytest.approx(40.0)
        assert calculate_roi(100, 80, 0) == 0.0
        assert calculate_breakeven_odds(0.5) == 2.0
        assert calculate_breakeven_odds(0) == float("inf")

    def test_optimize_bet_size(self):
        assert optimize_bet_size(12.0, max_stake=10.0, min_stake=5.0) == 10.0
        assert optimize_bet_size(3.0, max_stake=10.0, min_stake=5.0) == 5.0

    def test_assess_bet_quality(self):
        quality = assess_bet_quality(ev=0.25, confidence=0.75, market_liquidity=0.8)
        assert 0 <= quality["quality_score"] <= 100
        assert quality["tier"] in {"Excellent", "Good", "Fair", "Poor"}
        assert isinstance(quality["recommendation"], str)

    def test_calculate_sharpe_ratio(self):
        # Deterministic positive returns
        ratio = calculate_sharpe_ratio([0.05, 0.04, 0.06, 0.05])
        assert ratio > 0
        # Flat or insufficient returns should zero out
        assert calculate_sharpe_ratio([]) == 0.0
        assert calculate_sharpe_ratio([0.01, 0.01]) == 0.0
