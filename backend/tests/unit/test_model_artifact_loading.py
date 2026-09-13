"""Regression: every committed model artifact must actually load and infer.

`_load_from_disk` selected its deserialiser by file extension — `joblib.load` for
`.joblib`, `pickle.load` for `.pkl`. Every committed artifact is joblib-serialised
regardless of its name, and plain `pickle.load` cannot read one: it misreads the
payload and raises `ModuleNotFoundError: No module named 'random_forest'`.

The load was wrapped in `except Exception: continue`, so the failure was invisible
and `bundle` was simply always `None` — which means `_run_inference` returned
`_fallback_result` for every league, on every request. `model_version="fallback"`
then produced the MODEL_PREDICTION_REDUCED_EVIDENCE critical gap, so no prediction
was ever publishable. The certified model had never run in production.

These tests exercise the real artifacts rather than a mock, because the defect was
in deserialising those specific files — a mocked bundle would have passed throughout.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.models.feature_registry import CANONICAL_FEATURES_68, DEFAULT_FEATURE_VALUES_68
from src.models.prediction import PredictionEngine

_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
_LEAGUES = ["epl", "la_liga", "bundesliga", "serie_a", "ligue_1", "eredivisie"]


def _artifact(league: str) -> Path:
    return _MODELS_DIR / f"{league}_ensemble_v5_phase7.pkl"


def _neutral_vector() -> np.ndarray:
    return np.array(
        [DEFAULT_FEATURE_VALUES_68[f] for f in CANONICAL_FEATURES_68], dtype=np.float32
    )


@pytest.mark.parametrize("league", _LEAGUES)
def test_committed_artifact_deserialises(league: str):
    """The bug was purely in deserialisation — assert it directly."""
    path = _artifact(league)
    if not path.exists():
        pytest.skip(f"{path.name} not present in this checkout")

    engine = PredictionEngine()
    bundle = engine._load_from_disk(league)
    assert bundle is not None, (
        f"{path.name} failed to deserialise — PredictionEngine would fall back to "
        "model_version='fallback' for this league on every request"
    )


@pytest.mark.parametrize("league", _LEAGUES)
def test_artifact_expects_the_registry_vector_width(league: str):
    """A width disagreement makes PredictionEngine refuse to infer (it will not
    zero-pad). The registry and the artifacts must agree exactly."""
    if not _artifact(league).exists():
        pytest.skip("artifact not present in this checkout")

    engine = PredictionEngine()
    bundle = engine._load_from_disk(league)
    assert bundle is not None
    assert bundle.feature_columns is not None
    assert list(bundle.feature_columns) == list(CANONICAL_FEATURES_68), (
        "artifact feature_columns diverged from CANONICAL_FEATURES_68 — inference "
        "indexes positionally, so order matters as much as length"
    )


@pytest.mark.parametrize("league", _LEAGUES)
def test_artifact_exposes_its_trained_meta_model(league: str):
    """Directive v7.3 P5: every committed stacking artifact saves a
    ``meta_model`` (``scripts/train_on_real_matches.py`` line ~1481) — this
    pins that the real on-disk files still have it, on real artifacts rather
    than a mock, for the same reason the rest of this file does: a mocked
    bundle would have passed throughout the session where this was missing."""
    if not _artifact(league).exists():
        pytest.skip("artifact not present in this checkout")

    engine = PredictionEngine()
    bundle = engine._load_from_disk(league)
    assert bundle is not None
    assert bundle.meta_model is not None, (
        f"{_artifact(league).name} has no meta_model — PredictionEngine would "
        "silently serve an equal-weight base-learner average instead of the "
        "trained (and, where calibrator selection ran, calibrated) stacking head"
    )
    assert callable(getattr(bundle.meta_model, "predict_proba", None))


@pytest.mark.asyncio
@pytest.mark.parametrize("league", ["EPL", "LA_LIGA"])
async def test_engine_returns_a_real_prediction_not_the_fallback(league: str):
    """End-to-end guard on the symptom that was actually observed in production."""
    if not _artifact(league.lower()).exists():
        pytest.skip("artifact not present in this checkout")

    result = await PredictionEngine().predict(features=_neutral_vector(), league=league)
    payload = result.to_dict() if hasattr(result, "to_dict") else result

    assert payload["model_version"] != "fallback", (
        "engine fell back — this is exactly the production defect: it yields "
        "MODEL_PREDICTION_REDUCED_EVIDENCE and suppresses the prediction"
    )
    probs = [payload["home_win"], payload["draw"], payload["away_win"]]
    assert all(0.0 <= p <= 1.0 for p in probs)
    # The payload rounds to 4dp, so the sum lands within 5e-4 of 1.0, not on it.
    assert abs(sum(probs) - 1.0) < 1e-3
    # The fallback's signature output; a real inference must not coincide with it.
    assert [round(p, 3) for p in probs] != [0.333, 0.333, 0.334]
    # Directive v7.3 P5: the trained stacking meta-model must have actually
    # run, not a silent equal-weight average of the base learners.
    assert payload["calibration_applied"] is True
