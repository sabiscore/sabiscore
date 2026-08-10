"""Shared derivation helpers must match FeatureTransformer's semantics exactly.

These 16 canonical features need only the kickoff, the competition, and the four
per-side goal averages — all of which the serving projector already holds — yet
they were left at registry defaults on every request, so the artifact saw a
constant where real signal existed.

The risk in fixing that is train/serve skew: FeatureTransformer
(services/prediction.py, insights/engine.py) and UpcomingMatchFeatureProjector
(/upcoming/matches, /full-analysis) feed the SAME artifacts, so the two must
agree bit-for-bit. Both now call these helpers, and these tests pin the
definitions against the values transformers.py has always used.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.models.feature_registry import (
    CANONICAL_FEATURES_58,
    COMBINATION_FEATURES,
    LEAGUE_ONEHOT_FEATURES,
    LEAGUE_RATE_FEATURES,
    MARKET_FEATURES_14,
    TEMPORAL_FEATURES,
    derive_combination_features,
    derive_league_features,
    derive_market_features,
    derive_temporal_features,
)


def test_every_derived_name_is_a_real_canonical_feature():
    """A typo here would silently write a key the artifact never reads."""
    for name in (
        *TEMPORAL_FEATURES, *LEAGUE_ONEHOT_FEATURES,
        *LEAGUE_RATE_FEATURES, *COMBINATION_FEATURES, *MARKET_FEATURES_14,
    ):
        assert name in CANONICAL_FEATURES_58, name


def test_temporal_matches_transformer_definitions():
    # Saturday 2026-08-15.
    out = derive_temporal_features(datetime(2026, 8, 15, 15, 0))
    assert out["day_of_week"] == 5.0
    assert out["is_weekend"] == 1.0
    assert out["month"] == 8.0
    assert out["season_phase"] == pytest.approx((8 - 1) / 11.0)

    midweek = derive_temporal_features(datetime(2026, 1, 14, 20, 0))  # Wednesday
    assert midweek["day_of_week"] == 2.0
    assert midweek["is_weekend"] == 0.0
    assert midweek["season_phase"] == pytest.approx(0.0)


def test_temporal_is_pure_not_wall_clock():
    """Must derive from the fixture's kickoff, never datetime.now()."""
    a = derive_temporal_features(datetime(2026, 3, 7, 12, 0))
    b = derive_temporal_features(datetime(2026, 3, 7, 12, 0))
    assert a == b
    assert a["month"] == 3.0


@pytest.mark.parametrize(
    "league,expected",
    [
        ("EPL", "league_EPL"),
        ("epl", "league_EPL"),
        ("Premier League", "league_EPL"),
        ("LA_LIGA", "league_La_Liga"),
        ("La Liga", "league_La_Liga"),
        ("SERIE_A", "league_Serie_A"),
        ("Ligue 1", "league_Ligue_1"),
        ("BUNDESLIGA", "league_Bundesliga"),
    ],
)
def test_league_onehot_handles_both_vocabularies(league, expected):
    """Both league vocabularies reach this helper (canonical from the API,
    display form from the UI) — neither may silently produce an all-zero
    one-hot for a league that has a column."""
    out = derive_league_features(league)
    assert out[expected] == 1.0
    assert sum(out[n] for n in LEAGUE_ONEHOT_FEATURES) == 1.0


def test_league_without_a_column_is_all_zero_not_fabricated():
    """The 58-feature schema has no Eredivisie/UCL column. An all-zero block is
    correct; inventing a flag would be fabrication."""
    for league in ("EREDIVISIE", "UCL"):
        out = derive_league_features(league)
        assert sum(out[n] for n in LEAGUE_ONEHOT_FEATURES) == 0.0
        # Rates still fall back to the documented neutral prior.
        assert out["league_home_rate"] == 0.42


def test_league_rates_match_transformer_table():
    assert derive_league_features("EPL")["league_avg_goals"] == 2.85
    assert derive_league_features("BUNDESLIGA")["league_avg_goals"] == 3.05
    assert derive_league_features("SERIE_A")["league_draw_rate"] == 0.272


def test_combination_features_match_transformer_arithmetic():
    out = derive_combination_features(
        home_goals_for_avg=2.0, home_goals_against_avg=1.0,
        away_goals_for_avg=1.4, away_goals_against_avg=1.6,
    )
    assert out["combined_attack"] == pytest.approx(3.4)
    assert out["combined_defense_weakness"] == pytest.approx(2.6)
    assert out["home_attack_vs_away_defense"] == pytest.approx(0.4)
    assert out["away_attack_vs_home_defense"] == pytest.approx(0.4)


def test_market_features_match_transformer_arithmetic():
    """WP-A: pins derive_market_features() against the same de-vig/EV formula
    FeatureTransformer._project_to_canonical_features() (data/transformers.py)
    has always used, for the same (2.0, 3.0, 4.0) odds triple — the train/serve
    consistency this file exists to guard."""
    out = derive_market_features(2.0, 3.0, 4.0)
    assert out["market_prob_home"] == pytest.approx(6 / 13)
    assert out["market_prob_draw"] == pytest.approx(4 / 13)
    assert out["market_prob_away"] == pytest.approx(3 / 13)
    assert out["ev_home"] == pytest.approx(out["ev_draw"])
    assert out["ev_draw"] == pytest.approx(out["ev_away"])
