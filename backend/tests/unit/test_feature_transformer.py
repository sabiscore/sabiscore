import pandas as pd
import pytest

from src.core.exceptions import DataUnavailableError
from src.data.transformers import FEATURE_DEFAULTS, FeatureTransformer
from src.models.feature_registry import CANONICAL_FEATURES_58


def _base_features() -> pd.DataFrame:
    return pd.DataFrame([FEATURE_DEFAULTS]).copy()


def test_apply_enhanced_features_overrides_xg_values():
    transformer = FeatureTransformer()
    features = _base_features()
    match_data = {
        "enhanced_features": {
            "us_home_xg_pg": 1.85,
            "us_away_xg_pg": 1.05,
            "us_home_xg_diff": 0.9,
            "us_away_xg_diff": -0.2,
            "us_home_recent_xg": 1.80,
            "us_away_recent_xg": 1.00,
        }
    }

    updated = transformer._apply_enhanced_features(features, match_data)
    idx = updated.index[0]

    assert updated.at[idx, "home_xg_avg_5"] == pytest.approx(1.85)
    assert updated.at[idx, "away_xg_avg_5"] == pytest.approx(1.05)
    assert updated.at[idx, "xg_differential"] == pytest.approx(1.1)
    assert 0.0 <= updated.at[idx, "home_xg_consistency"] <= 1.0
    assert 0.0 <= updated.at[idx, "away_xg_consistency"] <= 1.0


def test_apply_enhanced_features_handles_whoscored_and_transfermarkt():
    transformer = FeatureTransformer()
    features = _base_features()
    match_data = {
        "enhanced_features": {
            "ws_home_avg_possession": 62.5,
            "ws_away_avg_possession": 47.2,
            "ws_home_win_rate_5": 0.78,
            "ws_away_win_rate_5": 0.34,
            "tm_value_diff_m": 120.0,
            "bf_market_margin_pct": 4.5,
        }
    }

    updated = transformer._apply_enhanced_features(features, match_data)
    idx = updated.index[0]

    assert updated.at[idx, "home_possession_style"] == pytest.approx(0.625)
    assert updated.at[idx, "away_possession_style"] == pytest.approx(0.472)
    assert updated.at[idx, "home_win_rate_5"] == pytest.approx(0.78)
    assert updated.at[idx, "away_win_rate_5"] == pytest.approx(0.34)
    assert updated.at[idx, "squad_value_diff"] == pytest.approx(120.0)
    assert updated.at[idx, "bookmaker_margin"] == pytest.approx(0.045)


def test_apply_enhanced_features_uses_betfair_back_prices_for_odds():
    transformer = FeatureTransformer()
    features = _base_features()
    match_data = {
        "enhanced_features": {
            "bf_home_back": 1.9,
            "bf_draw_back": 3.5,
            "bf_away_back": 4.2,
        }
    }

    updated = transformer._apply_enhanced_features(features, match_data)
    idx = updated.index[0]

    implied_home = 1 / 1.9
    implied_draw = 1 / 3.5
    implied_away = 1 / 4.2
    total = implied_home + implied_draw + implied_away

    assert updated.at[idx, "home_implied_prob"] == pytest.approx(implied_home / total)
    assert updated.at[idx, "bookmaker_margin"] == pytest.approx(total - 1, abs=1e-6)


def _complete_match_data() -> dict:
    def stats(base: float) -> dict:
        return {
            "squad_value": 500.0 + base,
            "missing_value": 12.0,
            "elo": 1550.0 + base,
            "xg_avg_5": 1.7,
            "xg_conceded_avg_5": 1.1,
            "xg_diff_5": 0.6,
            "xg_overperformance": 0.04,
            "xg_consistency": 0.82,
            "possession_style": 0.55,
            "pressing_intensity": 0.61,
            "first_half_goals_rate": 0.45,
            "defensive_solidity": 0.68,
            "setpiece_goals_rate": 0.24,
            "gd_trend": 0.08,
            "scoring_consistency": 0.74,
        }

    def form(results: list[str]) -> dict:
        return {
            "last_5_games": results,
            "form_10": 0.56,
            "form_20": 0.53,
            "win_streak": 2.0,
            "unbeaten_streak": 4.0,
            "momentum_lambda": 0.58,
            "momentum_weighted": 0.57,
            "days_rest": 6.0,
            "fatigue_index": 0.28,
            "fixtures_14d": 2.0,
            "fixture_congestion": 0.31,
        }

    history = pd.DataFrame(
        [
            {"home_score": 2, "away_score": 1},
            {"home_score": 1, "away_score": 1},
            {"home_score": 3, "away_score": 0},
            {"home_score": 0, "away_score": 1},
            {"home_score": 2, "away_score": 2},
        ]
    )

    return {
        "odds": {
            "home_win": 2.1,
            "draw": 3.25,
            "away_win": 3.6,
            "volatility_1h": 0.03,
            "panic_score": 0.11,
            "drift_home": -0.02,
        },
        "schedule": {
            "league": "EPL",
            "date": "2026-08-15T15:00:00Z",
            "weather": {
                "temperature": 18.0,
                "precipitation": 0.0,
                "wind_speed": 8.0,
                "impact_score": 0.04,
            },
            "home_advantage_win_rate": 0.54,
            "home_goals_advantage": 0.27,
            "away_win_rate_away": 0.32,
            "home_crowd_boost": 0.08,
            "home_advantage_coefficient": 1.12,
            "referee_home_bias": 0.51,
        },
        "historical_stats": history,
        "head_to_head": history.iloc[:3].copy(),
        "current_form": {
            "home": form(["W", "D", "W", "L", "W"]),
            "away": form(["D", "L", "W", "D", "L"]),
        },
        "team_stats": {
            "home": stats(50.0),
            "away": stats(0.0),
        },
        "injuries": pd.DataFrame(),
    }


def test_engineer_features_fail_closed_rejects_missing_evidence():
    transformer = FeatureTransformer()

    with pytest.raises(DataUnavailableError) as exc_info:
        transformer.engineer_features({})

    assert exc_info.value.evidence_type == "feature_evidence"
    assert "odds.1x2" in str(exc_info.value)


def test_engineer_features_fail_closed_accepts_complete_real_evidence():
    transformer = FeatureTransformer()
    transformer.expected_columns = list(CANONICAL_FEATURES_58)

    frame = transformer.engineer_features(_complete_match_data())

    assert list(frame.columns) == list(CANONICAL_FEATURES_58)
    assert frame.isnull().sum().sum() == 0
    assert transformer.feature_completeness == pytest.approx(1.0)


def test_engineer_features_legacy_defaults_require_explicit_opt_in():
    transformer = FeatureTransformer(allow_legacy_defaults=True)
    frame = transformer.engineer_features({})

    assert not frame.empty
    assert set(CANONICAL_FEATURES_58).issubset(set(frame.columns))


# ---------------------------------------------------------------------------
# feature_completeness intermediate-value tests
# These lock the 4-source counting logic (current_form, team_stats,
# historical_stats, head_to_head) against accidental breakage.
# allow_legacy_defaults=True skips the require-all validation so partial
# data reaches the completeness counter.
# ---------------------------------------------------------------------------


def _form_stub() -> dict:
    return {"home": {"last_5_games": []}, "away": {"last_5_games": []}}


def _history_stub() -> pd.DataFrame:
    return pd.DataFrame([{"home_score": 1, "away_score": 0}])


def test_feature_completeness_one_source():
    transformer = FeatureTransformer(allow_legacy_defaults=True)
    transformer.engineer_features({"current_form": _form_stub()})
    assert transformer.feature_completeness == pytest.approx(0.25)


def test_feature_completeness_two_sources():
    transformer = FeatureTransformer(allow_legacy_defaults=True)
    transformer.engineer_features(
        {
            "current_form": _form_stub(),
            "team_stats": {"home": {}, "away": {}},
        }
    )
    assert transformer.feature_completeness == pytest.approx(0.50)


def test_feature_completeness_three_sources():
    transformer = FeatureTransformer(allow_legacy_defaults=True)
    transformer.engineer_features(
        {
            "current_form": _form_stub(),
            "team_stats": {"home": {}, "away": {}},
            "historical_stats": _history_stub(),
        }
    )
    assert transformer.feature_completeness == pytest.approx(0.75)
