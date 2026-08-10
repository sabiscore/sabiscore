"""WP-18/WP-10.3: pure tests on derive_last5_form_features(), the shared
remap formula wired into both data/transformers.py and
services/upcoming_match_feature_service.py. No existing test locked in this
formula's numeric output before this work package — these are the guard."""

import math

import pytest

from src.models.feature_registry import (
    APEX_FEATURES_68,
    APEX_MARKET_FEATURES_14,
    MARKET_FEATURES_14,
    derive_apex_market_features,
    derive_last5_form_features,
    derive_market_features,
)


def test_estimate_path_home():
    result = derive_last5_form_features(1.0, 0.6, is_home=True)
    assert result == {
        "home_form_last5_home": pytest.approx(3.0),
        "home_wins_last5_home": pytest.approx(3.0),
        "home_draws_last5_home": pytest.approx(0.0),
        "home_losses_last5_home": pytest.approx(2.0),
    }


def test_estimate_path_away_keys_and_values():
    result = derive_last5_form_features(0.6, 0.4, is_home=False)
    assert set(result.keys()) == {
        "away_form_last5_away", "away_wins_last5_away",
        "away_draws_last5_away", "away_losses_last5_away",
    }
    assert result["away_form_last5_away"] == pytest.approx(1.8)
    assert result["away_wins_last5_away"] == pytest.approx(2.0)
    assert result["away_draws_last5_away"] == pytest.approx(1.0)
    assert result["away_losses_last5_away"] == pytest.approx(2.0)


def test_real_counts_preferred_over_estimate():
    """Real wins_5/draws_5/losses_5 must win over the round()/estimate split
    — the whole reason this work package prefers them wherever available."""
    result = derive_last5_form_features(
        0.6, 0.4, is_home=False, wins_5=1.0, draws_5=3.0, losses_5=1.0,
    )
    # Estimate from win_rate_5=0.4 alone would give wins=2.0/draws=1.0/losses=2.0.
    assert result["away_wins_last5_away"] == pytest.approx(1.0)
    assert result["away_draws_last5_away"] == pytest.approx(3.0)
    assert result["away_losses_last5_away"] == pytest.approx(1.0)


def test_partial_real_counts_fall_back_to_full_estimate():
    """All-or-nothing: a partial trio (only wins_5 supplied) must not mix
    real and derived values — falls back to the complete estimate."""
    result = derive_last5_form_features(0.6, 0.4, is_home=False, wins_5=1.0)
    assert result["away_wins_last5_away"] == pytest.approx(2.0)  # estimate, not the real 1.0
    assert result["away_draws_last5_away"] == pytest.approx(1.0)
    assert result["away_losses_last5_away"] == pytest.approx(2.0)


# ── WP-A: derive_market_features() ──────────────────────────────────────────
# Same shared train/serve pattern as derive_last5_form_features above — see
# backend/scripts/train_on_real_matches.py and
# backend/src/services/upcoming_match_feature_service.py, the two callers.


def test_market_features_known_odds_pin_expected_values():
    """odds (2.0, 3.0, 4.0) -> de-vigged probs 6/13, 4/13, 3/13 exactly."""
    result = derive_market_features(2.0, 3.0, 4.0)
    assert result["market_prob_home"] == pytest.approx(6 / 13)
    assert result["market_prob_draw"] == pytest.approx(4 / 13)
    assert result["market_prob_away"] == pytest.approx(3 / 13)
    assert sum(result[k] for k in ("market_prob_home", "market_prob_draw", "market_prob_away")) == pytest.approx(1.0)
    assert result["market_edge_home"] == pytest.approx(3 / 13)
    assert result["market_favorite"] == 0.0
    assert result["odds_ratio"] == pytest.approx(0.5)
    assert result["log_odds_home"] == pytest.approx(math.log(2.0))
    assert result["log_odds_draw"] == pytest.approx(math.log(3.0))
    assert result["log_odds_away"] == pytest.approx(math.log(4.0))
    assert result["draw_probability"] == pytest.approx(4 / 13)
    assert result["market_confidence"] == pytest.approx(6 / 13)
    # ev_home == ev_draw == ev_away always, by construction of de-vigged EV.
    assert result["ev_home"] == pytest.approx(-1 / 13)
    assert result["ev_draw"] == pytest.approx(-1 / 13)
    assert result["ev_away"] == pytest.approx(-1 / 13)


def test_market_features_tie_breaks_to_home():
    result = derive_market_features(1.01, 1.01, 1.01)
    assert result["market_prob_home"] == pytest.approx(1 / 3)
    assert result["market_prob_draw"] == pytest.approx(1 / 3)
    assert result["market_prob_away"] == pytest.approx(1 / 3)
    assert result["market_favorite"] == 0.0  # first-index tie-break, matches np.argmax


def test_market_features_reject_sub_floor_odds():
    with pytest.raises(ValueError, match="greater than 1.0"):
        derive_market_features(0.5, 0.0, -3.0)


def test_market_features_returns_exactly_the_14_canonical_keys():
    assert set(derive_market_features(2.0, 3.0, 2.0).keys()) == set(MARKET_FEATURES_14)
    assert len(MARKET_FEATURES_14) == 14


def test_apex_market_block_is_non_redundant_and_versioned():
    result = derive_apex_market_features(2.0, 3.0, 4.0)
    assert set(result) == set(APEX_MARKET_FEATURES_14)
    assert len(APEX_FEATURES_68) == 68
    assert sum(result[key] for key in (
        "market_favorite_home", "market_favorite_draw", "market_favorite_away"
    )) == 1.0
    assert result["market_overround"] == pytest.approx(13 / 12)
    assert 0.0 <= result["market_normalized_entropy"] <= 1.0
    assert not {"ev_home", "ev_draw", "ev_away"}.intersection(APEX_FEATURES_68)


def test_apex_market_block_rejects_invalid_overround():
    with pytest.raises(ValueError, match="overround"):
        derive_apex_market_features(20.0, 20.0, 20.0)
