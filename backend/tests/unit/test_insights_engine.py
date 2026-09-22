"""Tests for insights prediction engine with synthetic data."""

import os
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add backend/src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from src.core.exceptions import DataUnavailableError
from src.insights.engine import InsightsEngine, MAX_KELLY_CAP, _league_kelly_cap

from .test_feature_transformer import _complete_match_data


# Ensure Redis connections are disabled during import
os.environ.setdefault("REDIS_ENABLED", "false")

with patch.dict(
    "sys.modules",
    {
        "great_expectations": MagicMock(),
        "great_expectations.dataset": MagicMock(),
        "sqlalchemy": MagicMock(),
        "sqlalchemy.orm": MagicMock(),
        "redis": MagicMock(),
        "redis.exceptions": MagicMock(),
        "torch": MagicMock(),
        "torchvision": MagicMock(),
        "torchvision.transforms": MagicMock(),
    },
):
    with (
        patch("requests.Session.get") as mock_get,
        patch("time.sleep", return_value=None),
    ):
        mock_response = MagicMock(status_code=200)
        mock_response.raise_for_status.return_value = None
        mock_response.text = ""
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response

        # from src.insights.engine import InsightsEngine
        # from src.models.ensemble import SabiScoreEnsemble
        # from src.data.aggregator import DataAggregator


@pytest.fixture
def mock_model():
    """Mock ML model with fixed predictions."""
    mock = MagicMock()  # Remove spec restriction
    # Return DataFrame format as expected by engine
    mock.predict.return_value = pd.DataFrame(
        [
            {
                "home_win_prob": 0.65,
                "draw_prob": 0.20,
                "away_win_prob": 0.15,
                "prediction": "home_win",
                "confidence": 0.8,
            }
        ]
    )
    # Add other methods that might be called
    mock.transform.return_value = pd.DataFrame([{"feature": 1.0}])
    mock.explain.return_value = {"feature_importance": {"feature": 0.5}}
    mock.get_feature_names.return_value = ["home_goals_avg", "away_goals_avg"]
    mock.predict_proba.return_value = [[0.65, 0.20, 0.15]]
    mock.is_trained = True
    return mock


@pytest.fixture(autouse=True)
def disable_external_calls(monkeypatch):
    """Prevent live HTTP requests and slow sleeps during engine tests."""

    # Patch the fetch_data method to prevent external calls
    monkeypatch.setattr(
        "src.data.scrapers.BaseScraper.fetch_data",
        lambda *args, **kwargs: {"status": "mock", "data": {}},
    )
    monkeypatch.setattr("time.sleep", lambda *_: None)


@pytest.fixture
def sample_match_data():
    """A fully evidenced fixture — the only shape that may produce a prediction.

    Reuses the transformer suite's complete-evidence helper so both suites agree on
    what "sufficient evidence" means. A thinner dict now fails closed by design.
    """
    data = dict(_complete_match_data())
    # The engine aligns to the full canonical schema, which additionally requires the
    # enhanced (StatsBomb-derived) differentials.
    data["enhanced_features"] = {
        "progressive_carry_diff": 0.12,
        "shot_quality_diff": 0.06,
        "key_passes_under_pressure_diff": 0.09,
        "set_piece_xg_diff": 0.03,
    }
    data["metadata"] = {
        "matchup": "TeamA vs TeamB",
        "league": "EPL",
        "home_team": "TeamA",
        "away_team": "TeamB",
    }
    data["team_stats"]["home"].update(
        {"attacking_strength": 0.9, "defensive_strength": 0.75, "elo_trend_5": 0.18}
    )
    data["team_stats"]["away"].update(
        {"attacking_strength": 0.7, "defensive_strength": 0.65, "elo_trend_5": -0.06}
    )
    return data


@pytest.fixture
def thin_match_data():
    """Evidence-free match data — the off-season / no-provider shape."""
    return {
        "metadata": {
            "matchup": "TeamA vs TeamB",
            "league": "EPL",
            "home_team": "TeamA",
            "away_team": "TeamB",
        },
        "team_stats": {"home": {}, "away": {}},
        "odds": {},
    }


def test_engine_with_synthetic_features(mock_model, sample_match_data):
    """Test full prediction flow with supplied match data and odds."""
    engine = InsightsEngine(model=mock_model)
    result = engine.generate_match_insights(
        matchup="TeamA vs TeamB",
        league="EPL",
        match_data=sample_match_data,
        market_odds=sample_match_data["odds"],
    )

    assert result["metadata"]["matchup"] == "TeamA vs TeamB"
    # Check prediction probabilities exist and are valid
    assert "predictions" in result
    assert "home_win_prob" in result["predictions"]
    assert 0 <= result["predictions"]["home_win_prob"] <= 1
    # Check xG analysis structure
    assert "xg_analysis" in result
    assert "home_xg" in result["xg_analysis"]
    # Check value analysis exists
    assert "value_analysis" in result
    assert "summary" in result["value_analysis"]
    # Check monte carlo structure
    assert "monte_carlo" in result
    assert result["monte_carlo"]["simulations"] >= 1000
    # Check risk assessment
    assert result["risk_assessment"]["risk_level"] in {"low", "medium", "high"}
    # Check narrative mentions the teams
    assert "narrative" in result


def test_engine_untrained_model_falls_back_to_labelled_baseline(
    mock_model, sample_match_data
):
    """An untrained model degrades to a labelled baseline — evidence is still present."""
    mock_model.is_trained = False
    engine = InsightsEngine(model=mock_model)
    result = engine.generate_match_insights(
        matchup="TeamA vs TeamB",
        league="EPL",
        match_data=sample_match_data,
    )

    assert result["metadata"]["matchup"] == "TeamA vs TeamB"
    assert result["predictions"]["is_baseline"] is True


def test_engine_fails_closed_when_evidence_is_missing(mock_model, thin_match_data):
    """Missing required evidence must raise, never infer on FEATURE_DEFAULTS.

    Regression guard for the live defect where an off-season matchup returned
    home_win_prob 0.852 and a 35% Kelly stake from a pure-defaults feature vector.
    """
    engine = InsightsEngine(model=mock_model)

    with pytest.raises(DataUnavailableError):
        engine.generate_match_insights(
            matchup="TeamA vs TeamB",
            league="EPL",
            match_data=thin_match_data,
        )


def test_value_bets_are_skipped_without_a_market(mock_model):
    """No live book means no edge and no stake — never a default price."""
    engine = InsightsEngine(model=mock_model)
    predictions = {
        "home_win_prob": 0.85,
        "draw_prob": 0.15,
        "away_win_prob": 0.0,
        "confidence": 0.85,
    }

    result = engine._calculate_value_bets(predictions, {}, "EPL")

    assert result["bets"] == []
    assert result["best_bet"] is None


def test_kelly_stake_is_a_capped_fraction(mock_model):
    """kelly_stake is a bankroll fraction bounded by the league policy cap."""
    engine = InsightsEngine(model=mock_model)
    # A 0.85 model probability against evens is a ~70% full-Kelly edge; uncapped
    # half-Kelly on a 100 bankroll previously emitted 35.21 here.
    predictions = {
        "home_win_prob": 0.85,
        "draw_prob": 0.15,
        "away_win_prob": 0.0,
        "confidence": 0.85,
    }

    result = engine._calculate_value_bets(
        predictions, {"home_win": 2.0, "draw": 3.2, "away_win": 3.5}, "EPL"
    )

    assert result["bets"], "a positive-EV bet was expected for this input"
    for bet in result["bets"]:
        assert 0 <= bet["kelly_stake"] <= _league_kelly_cap("EPL")
        assert bet["kelly_stake"] <= MAX_KELLY_CAP


def test_league_kelly_cap_normalises_display_names():
    """Insights leagues arrive display-form ("La Liga"); policy keys are LA_LIGA."""
    assert _league_kelly_cap("La Liga") == _league_kelly_cap("LA_LIGA")
    # An unknown league must not silently inherit a calibrated cap.
    assert _league_kelly_cap("Nowhere League") <= 0.02


def test_engine_uses_aggregator_when_no_match_data(mock_model, sample_match_data):
    """Verify aggregator is invoked when match_data not provided."""
    with patch(
        "src.insights.engine.DataAggregator.fetch_match_data",
        return_value=sample_match_data,
    ) as mock_fetch:
        engine = InsightsEngine(model=mock_model)
        engine.generate_match_insights(matchup="TeamA vs TeamB", league="EPL")
        assert mock_fetch.call_count == 1


def test_engine_risk_assessment_varies_with_confidence(mock_model, sample_match_data):
    """Risk assessment should adjust tier based on probabilities."""
    engine = InsightsEngine(model=mock_model)
    custom_predictions = {
        "home_win_prob": 0.9,
        "draw_prob": 0.05,
        "away_win_prob": 0.05,
        "prediction": "home_win",
        "confidence": 0.85,
    }

    # No bets available -> should be high risk
    risk = engine._assess_risk(
        custom_predictions,
        {"bets": [], "best_bet": None},
        {"distribution": {"home_win": 0.9}},
    )
    assert risk["risk_level"] == "high"

    # Provide positive-EV bet to trigger low risk branch
    value_analysis = {
        "bets": [
            {
                "quality": {"quality_score": 90},
                "market_odds": 2.0,
                "expected_value": 0.2,
            }
        ],
        "best_bet": {
            "quality": {"quality_score": 90},
            "market_odds": 2.0,
            "expected_value": 0.2,
        },
    }
    low_risk = engine._assess_risk(
        custom_predictions, value_analysis, {"distribution": {"home_win": 0.9}}
    )
    assert low_risk["risk_level"] == "low"

    # Low confidence scenario should be high risk regardless of bets
    low_conf_predictions = dict(custom_predictions, confidence=0.4)
    risk_low = engine._assess_risk(
        low_conf_predictions, value_analysis, {"distribution": {"home_win": 0.3}}
    )
    assert risk_low["risk_level"] == "high"
