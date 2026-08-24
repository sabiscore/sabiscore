"""WP-18/WP-10.3: pure tests on derive_last5_form_features(), the shared
remap formula wired into both data/transformers.py and
services/upcoming_match_feature_service.py. No existing test locked in this
formula's numeric output before this work package — these are the guard."""

import math

import pytest

from src.models.feature_registry import (
    APEX_FEATURES_68,
    APEX_MARKET_FEATURES_14,
    DEFAULT_FEATURE_VALUES_68,
    MARKET_FEATURES_14,
    derive_apex_market_features,
    derive_goals_gd_features,
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


# ── Apex vs legacy market block: the docs/DEBT.md item 37 deadlock ──────────


def test_apex_and_canonical_68_differ_at_exactly_eleven_positions() -> None:
    """Pins the schema disagreement docs/DEBT.md item 37 records.

    ``train_on_real_matches.py`` trains on APEX_FEATURES_68 while
    ``active_generation.json`` declares ``phase7_68`` (CANONICAL_FEATURES_68).
    ``promotion_evidence._expected_gate()`` blocks on the resulting
    ``serving_schema_misaligned_slots``, which the live comparison report reads
    as 11 — so this number is load-bearing for the promotion verdict, not a
    curiosity.

    If this count changes, either someone resolved the deadlock (good — update
    item 37) or a market block was edited without noticing it moves the
    promotion gate (bad). Either way it should not change silently.
    """
    from src.models.feature_registry import APEX_FEATURES_68, CANONICAL_FEATURES_68

    assert len(APEX_FEATURES_68) == len(CANONICAL_FEATURES_68) == 68
    mismatched = [
        index
        for index, (canonical, apex) in enumerate(
            zip(CANONICAL_FEATURES_68, APEX_FEATURES_68)
        )
        if canonical != apex
    ]
    assert mismatched == list(range(20, 31)), (
        "the apex/legacy market disagreement moved; docs/DEBT.md item 37 and "
        f"the promotion gate both describe indices 20-30, got {mismatched}"
    )


def test_the_seven_shared_market_names_are_why_name_keyed_checks_pass() -> None:
    """A name-keyed comparison cannot see the item 37 disagreement.

    Guards the reasoning, not just the count: if these seven ever stop
    overlapping, a name-based check would start catching the mismatch and the
    contract's schema-keyed market attribution (_is_apex_schema) could be
    simplified.
    """
    from src.models.feature_registry import APEX_MARKET_FEATURES_14, MARKET_FEATURES_14

    shared = set(MARKET_FEATURES_14) & set(APEX_MARKET_FEATURES_14)
    assert shared == {
        "market_prob_home", "market_prob_draw", "market_prob_away",
        "log_odds_home", "log_odds_draw", "log_odds_away", "odds_ratio",
    }


def test_apex_market_block_now_has_a_real_serving_attribution() -> None:
    """docs/DEBT.md item 37's serving wire-up, recorded in the contract.

    Before the wire-up ``derive_apex_market_features()`` had zero callers in
    ``backend/src`` (scripts/ only), so the contract correctly said
    ``UNDECLARED`` for every apex market slot -- claiming a source there would
    have been fabrication. Both serving implementations now dispatch on the
    active generation's ``feature_schema_version``, so the attribution is real
    and must name the apex helper, never the legacy one (the seven shared
    names are exactly why a name-keyed lookup would get this wrong).
    """
    from src.models.feature_registry import build_feature_contract

    contract = build_feature_contract("apex_v1_68")
    market_rows = [row for row in contract["features"] if 17 <= row["index"] <= 30]

    assert len(market_rows) == 14
    for row in market_rows:
        assert row["serving_source"] != "UNDECLARED", row["index"]
        assert "derive_apex_market_features" in row["serving_source"], row["index"]
        assert "derive_market_features()" not in row["serving_source"], row["index"]


def test_legacy_schema_market_attribution_is_unchanged() -> None:
    """The active phase7_68 contract must still name the legacy helper.

    This is the regression half of the test above: the wire-up is additive,
    so nothing about what serves today may move.
    """
    from src.models.feature_registry import build_feature_contract

    contract = build_feature_contract("phase7_68")
    market_rows = [row for row in contract["features"] if 17 <= row["index"] <= 30]

    assert len(market_rows) == 14
    for row in market_rows:
        assert "derive_market_features()" in row["serving_source"], row["index"]
        assert "derive_apex_market_features" not in row["serving_source"], row["index"]


# --- derive_goals_gd_features (docs/DEBT.md item 36(a)) ----------------------
# The four replicated assignments this replaced each had their own
# missing-value policy, and item 36(b) declares that divergence deliberate.
# The helper therefore owns the key mapping and the registry defaults but not
# the lookup — these tests pin exactly that split.


def test_goals_gd_reads_the_side_prefixed_source_keys():
    stats = {
        "home_goals_per_match_5": 2.1,
        "home_goals_conceded_per_match_5": 0.7,
        "home_gd_avg_5": 1.4,
    }
    assert derive_goals_gd_features(stats.get, is_home=True) == {
        "home_goals_for_avg": pytest.approx(2.1),
        "home_goals_against_avg": pytest.approx(0.7),
        "home_gd_recent": pytest.approx(1.4),
    }


def test_goals_gd_away_side_uses_away_keys_only():
    stats = {
        "away_goals_per_match_5": 1.1,
        "away_goals_conceded_per_match_5": 1.9,
        "away_gd_avg_5": -0.8,
        # A home-side key must not leak into the away result.
        "home_goals_per_match_5": 99.0,
    }
    result = derive_goals_gd_features(stats.get, is_home=False)
    assert set(result) == {
        "away_goals_for_avg", "away_goals_against_avg", "away_gd_recent",
    }
    assert result["away_goals_for_avg"] == pytest.approx(1.1)


def test_goals_gd_defaults_come_from_the_registry_not_a_hand_copy():
    """The projector's old literals (1.5/1.2/0.0, home values reused for away)
    had drifted from the registry. Sourcing them here is what stops that."""
    for is_home in (True, False):
        side = "home" if is_home else "away"
        result = derive_goals_gd_features({}.get, is_home=is_home)
        for canonical in ("goals_for_avg", "goals_against_avg", "gd_recent"):
            name = f"{side}_{canonical}"
            assert result[name] == pytest.approx(DEFAULT_FEATURE_VALUES_68[name])
    # And the two sides genuinely differ, which the old literals did not.
    assert (
        DEFAULT_FEATURE_VALUES_68["home_goals_for_avg"]
        != DEFAULT_FEATURE_VALUES_68["away_goals_for_avg"]
    )


def test_goals_gd_propagates_a_raising_lookup_unchanged():
    """FeatureTransformer's fail-closed get_num must still raise through the
    helper rather than silently landing on a default."""

    class _Boom(Exception):
        pass

    def raising(_name, _default):
        raise _Boom

    with pytest.raises(_Boom):
        derive_goals_gd_features(raising, is_home=True)


def test_goals_gd_propagates_a_strict_lookup_keyerror():
    """The training builder drops an incomplete row instead of imputing."""
    stats = {"home_goals_per_match_5": 1.0}
    with pytest.raises(KeyError):
        derive_goals_gd_features(lambda k, _d: stats[k], is_home=True)


def test_goals_gd_coerces_to_float():
    stats = {
        "home_goals_per_match_5": 2,
        "home_goals_conceded_per_match_5": 1,
        "home_gd_avg_5": 1,
    }
    result = derive_goals_gd_features(stats.get, is_home=True)
    assert all(isinstance(value, float) for value in result.values())
