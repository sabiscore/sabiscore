"""The certified artifact must respond to real team strength.

This is the guard that was missing while the platform shipped a model trained on
``np.random.randn()`` noise. That artifact was well-formed — it loaded, returned
valid probabilities, and passed every schema and zero-fabrication check — but it
responded to only 4 of 68 inputs, and those 4 were fed by synthetic-keyed
parquets that never join to a real fixture. Every live fixture therefore received
a byte-identical prediction (0.4162 / 0.4155 / 0.1683), which no contract test
could see.

These tests assert *behaviour*, not shape: a strong home side must not receive
the same probabilities as a weak one, and the direction must be football-sane.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from src.models.feature_registry import (
    CANONICAL_FEATURES_68,
    DEFAULT_FEATURE_VALUES_68,
    derive_combination_features,
    derive_last5_form_features,
    derive_league_features,
    derive_market_features,
    derive_temporal_features,
)
from src.models.prediction import PredictionEngine

MATCH_DATE = datetime(2026, 8, 15)


def _vector(
    *, home_form: float, home_win_rate: float, home_gf: float, home_ga: float,
    away_form: float, away_win_rate: float, away_gf: float, away_ga: float,
    home_odds: float = 2.38, draw_odds: float = 3.85, away_odds: float = 3.13,
    league: str = "EPL",
) -> np.ndarray:
    """Build a serving-shaped vector via the same helpers the projector uses.

    home_odds/draw_odds/away_odds default to the same implied split as
    DEFAULT_FEATURE_VALUES_58's own market_prob_* defaults (~42/26/32) — a
    neutral market read for callers that don't care about it. WP-A:
    _DOMINANT_HOME/_DOMINANT_AWAY below now supply odds coherent with the
    scenario they describe (see the WP-A note there for why that stopped
    being optional).
    """
    f = dict(DEFAULT_FEATURE_VALUES_68)
    f.update(derive_last5_form_features(
        home_form, home_win_rate, is_home=True,
        wins_5=home_win_rate * 5, draws_5=1.0, losses_5=max(0.0, 4.0 - home_win_rate * 5),
    ))
    f["home_goals_for_avg"] = home_gf
    f["home_goals_against_avg"] = home_ga
    f["home_gd_recent"] = home_gf - home_ga
    f.update(derive_last5_form_features(
        away_form, away_win_rate, is_home=False,
        wins_5=away_win_rate * 5, draws_5=1.0, losses_5=max(0.0, 4.0 - away_win_rate * 5),
    ))
    f["away_goals_for_avg"] = away_gf
    f["away_goals_against_avg"] = away_ga
    f["away_gd_recent"] = away_gf - away_ga
    f.update(derive_market_features(home_odds, draw_odds, away_odds))
    f.update(derive_temporal_features(MATCH_DATE))
    f.update(derive_league_features(league))
    f.update(derive_combination_features(home_gf, home_ga, away_gf, away_ga))
    return np.array([f[n] for n in CANONICAL_FEATURES_68], dtype=np.float32)


# WP-A: market odds now carry real, learned signal (docs/DEBT.md item 13), so
# a "dominant home side" fixture that leaves them at the same neutral default
# as a "dominant away side" fixture is no longer internally coherent — real
# markets would price these two scenarios very differently, and the artifact
# correctly leans on that price. Odds below match the described scenario: a
# heavy home favorite / heavy away favorite, mirrored between the two dicts.
_DOMINANT_HOME = dict(
    home_form=0.93, home_win_rate=0.8, home_gf=2.6, home_ga=0.6,
    away_form=0.20, away_win_rate=0.0, away_gf=0.7, away_ga=2.2,
    home_odds=1.30, draw_odds=5.50, away_odds=9.00,
)
_DOMINANT_AWAY = dict(
    home_form=0.20, home_win_rate=0.0, home_gf=0.7, home_ga=2.2,
    away_form=0.93, away_win_rate=0.8, away_gf=2.6, away_ga=0.6,
    home_odds=9.00, draw_odds=5.50, away_odds=1.30,
)


@pytest.mark.asyncio
async def test_team_strength_changes_the_prediction():
    """The regression that matters: two opposite fixtures must not be identical."""
    engine = PredictionEngine()
    strong = await engine.predict(features=_vector(**_DOMINANT_HOME), league="EPL")
    weak = await engine.predict(features=_vector(**_DOMINANT_AWAY), league="EPL")

    assert strong.model_version != "fallback"
    assert abs(strong.home_win - weak.home_win) > 0.10, (
        "home-win probability barely moved between a dominant home side and a "
        "dominant away side — the artifact is not responding to team strength"
    )


@pytest.mark.asyncio
async def test_direction_is_football_sane():
    engine = PredictionEngine()
    strong = await engine.predict(features=_vector(**_DOMINANT_HOME), league="EPL")
    weak = await engine.predict(features=_vector(**_DOMINANT_AWAY), league="EPL")

    assert strong.home_win > strong.away_win, "dominant home side priced below the away side"
    assert weak.away_win > weak.home_win, "dominant away side priced below the home side"


@pytest.mark.asyncio
async def test_probabilities_stay_a_valid_simplex():
    engine = PredictionEngine()
    for profile in (_DOMINANT_HOME, _DOMINANT_AWAY):
        r = await engine.predict(features=_vector(**profile), league="EPL")
        probs = [r.home_win, r.draw, r.away_win]
        assert all(0.0 <= p <= 1.0 for p in probs)
        assert abs(sum(probs) - 1.0) < 1e-3


@pytest.mark.asyncio
async def test_artifact_uses_a_substantial_share_of_its_inputs():
    """Sensitivity sweep. The noise-trained artifact scored 4/68; a model that
    ignores nearly every input cannot differentiate fixtures no matter how good
    the upstream evidence gets."""
    engine = PredictionEngine()
    base_vec = _vector(**_DOMINANT_HOME)
    baseline = await engine.predict(features=base_vec, league="EPL")
    base_probs = np.array([baseline.home_win, baseline.draw, baseline.away_win])

    responsive = 0
    for i in range(len(CANONICAL_FEATURES_68)):
        probe = base_vec.copy()
        probe[i] = probe[i] + (abs(probe[i]) * 2.0 + 1.0)
        r = await engine.predict(features=probe, league="EPL")
        if np.abs(np.array([r.home_win, r.draw, r.away_win]) - base_probs).max() > 1e-6:
            responsive += 1

    assert responsive >= 15, (
        f"only {responsive}/68 features move the prediction — this is the "
        "signature of an artifact trained on constant or synthetic inputs"
    )
