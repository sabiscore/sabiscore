"""The calibrator must survive both loaders, and only run if it actually runs.

Historical context (documented in `docs/DEBT.md` item 122):

1. The cold path (`_wrap_artifact(raw, ...)`) saw serialized calibrators.
2. The startup path (`SabiScoreEnsemble.load_model` -> `prime_cache`) dropped
    the calibrator field, so production always served uncalibrated probabilities.

That two-loader asymmetry is fixed. These tests now enforce durable invariants
that remain true across runtime/version changes:

- both loaders must agree on calibrator admission,
- preflight must never crash startup,
- calibrator screening must never force `model_version="fallback"`.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pytest

from src.models.ensemble import SabiScoreEnsemble
from src.models.prediction import PredictionEngine

_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
_LEAGUES = ["epl", "la_liga", "bundesliga", "serie_a", "ligue_1", "eredivisie"]


def _artifact(league: str) -> Path:
    return _MODELS_DIR / f"{league}_ensemble_v5_phase7.pkl"


def _raw(league: str) -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return joblib.load(_artifact(league))


class _Unusable:
    """A calibrator that deserializes fine and raises on first use.

    This is the real failure mode: a `FittedCalibrator` fitted under one
    scikit-learn and unpickled under another loads cleanly, then raises
    `AttributeError` when its sub-estimator is called.
    """

    method = "sigmoid"

    @property
    def calibrators(self) -> Any:
        raise AttributeError(
            "'LogisticRegression' object has no attribute 'multi_class'"
        )


class _Hostile:
    """Raises on every attribute the preflight could touch."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"hostile calibrator: {name}")


class _Identity:
    """A usable calibrator: returns a valid simplex."""

    method = "identity"
    calibrators = [0, 1, 2]


# --------------------------------------------------------------------------
# The loader asymmetry itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize("league", _LEAGUES)
def test_startup_loader_carries_the_calibrator_key(league: str) -> None:
    """`SabiScoreEnsemble.load_model` must represent the artifact faithfully.

    Before this was fixed the attribute did not exist at all, so `getattr`
    could not distinguish "artifact has no calibrator" from "loader dropped it"
    -- which is exactly why the drop went unnoticed.
    """
    model = SabiScoreEnsemble.load_model(str(_artifact(league)))
    assert hasattr(model, "calibrator")
    assert hasattr(model, "bivariate_poisson_overlay")

    expected = _raw(league).get("calibrator")
    assert (model.calibrator is None) == (expected is None)


@pytest.mark.parametrize("league", _LEAGUES)
def test_both_loaders_agree_on_whether_a_calibrator_is_admitted(league: str) -> None:
    """The cold path and the startup path must reach the same verdict.

    They disagreed for two leagues: the cold path admitted a calibrator that
    the startup path never saw. Either loader may reject it, but they may not
    reject it for *different reasons*, because then production and every
    offline harness are measuring different systems.
    """
    slug = league
    raw = _raw(league)

    cold = PredictionEngine._wrap_artifact(raw, slug, _artifact(league))
    assert cold is not None

    model = SabiScoreEnsemble.load_model(str(_artifact(league)))
    PredictionEngine.clear_cache()
    assert PredictionEngine.prime_cache(league.upper(), model) is True
    startup = PredictionEngine._model_cache[slug]
    PredictionEngine.clear_cache()

    assert (cold.calibrator is None) == (startup.calibrator is None)


@pytest.mark.parametrize("league", _LEAGUES)
def test_committed_artifact_calibrator_admission_matches_preflight(league: str) -> None:
    """The wrapped bundle must reflect the preflight verdict exactly.

    Admission is runtime-dependent (artifact + library version compatibility),
    so this test pins contract behavior, not a fixed per-league outcome.
    """
    raw = _raw(league)
    expected = PredictionEngine._usable_calibrator(
        raw.get("calibrator"), league, _artifact(league)
    )

    bundle = PredictionEngine._wrap_artifact(raw, league, _artifact(league))
    assert bundle is not None
    assert (bundle.calibrator is None) == (expected is None)
    if expected is not None:
        assert bundle.calibrator is expected


# --------------------------------------------------------------------------
# The preflight
# --------------------------------------------------------------------------


def test_preflight_rejects_a_calibrator_that_raises_on_use() -> None:
    assert (
        PredictionEngine._usable_calibrator(_Unusable(), "bundesliga", "<test>") is None
    )


def test_preflight_never_raises_on_a_hostile_object() -> None:
    """It runs on the startup path; a preflight that can abort boot is worse
    than the defect it screens for."""
    assert PredictionEngine._usable_calibrator(_Hostile(), "epl", "<test>") is None


def test_preflight_passes_none_through() -> None:
    assert PredictionEngine._usable_calibrator(None, "epl", "<test>") is None


def test_preflight_admits_a_calibrator_that_returns_a_valid_simplex(
    monkeypatch,
) -> None:
    """The screen must not be a blanket refusal -- a good calibrator gets used."""
    monkeypatch.setattr(
        "src.models.prediction._apply_calibrator",
        lambda method, calibrators, proba: np.asarray([[0.5, 0.25, 0.25]]),
    )
    monkeypatch.setattr("src.models.prediction._CAL_AVAILABLE", True)

    calibrator = _Identity()
    assert (
        PredictionEngine._usable_calibrator(calibrator, "epl", "<test>") is calibrator
    )


def test_preflight_rejects_a_calibrator_returning_a_non_simplex(monkeypatch) -> None:
    """Returning numbers is not enough; they have to be probabilities."""
    monkeypatch.setattr(
        "src.models.prediction._apply_calibrator",
        lambda method, calibrators, proba: np.asarray([[0.9, 0.9, 0.9]]),
    )
    monkeypatch.setattr("src.models.prediction._CAL_AVAILABLE", True)

    assert PredictionEngine._usable_calibrator(_Identity(), "epl", "<test>") is None


def test_preflight_rejects_when_the_calibration_runtime_is_absent(monkeypatch) -> None:
    monkeypatch.setattr("src.models.prediction._CAL_AVAILABLE", False)
    assert PredictionEngine._usable_calibrator(_Identity(), "epl", "<test>") is None


def test_wrap_artifact_screens_the_calibrator_it_is_handed() -> None:
    """The preflight sits in `_wrap_artifact` precisely because both loaders
    funnel through it -- fixing it in one place fixes both."""
    raw = _raw("epl")
    raw["calibrator"] = _Unusable()

    bundle = PredictionEngine._wrap_artifact(raw, "epl", "<test>")
    assert bundle is not None
    assert bundle.calibrator is None
    # The rest of the artifact must survive the rejection untouched.
    assert bundle.meta_model is not None
    assert bundle.models_dict


@pytest.mark.parametrize("league", ["bundesliga", "ligue_1"])
def test_artifact_calibrator_screening_never_forces_fallback(league: str) -> None:
    """If an artifact carries a calibrator, screening must remain safe.

    Whether a calibrator is admitted can vary by runtime. The invariant is:
    inference keeps serving model outputs and never degrades to fallback solely
    because of calibrator screening/admission.
    """
    raw = _raw(league)
    assert raw.get("calibrator") is not None, "fixture assumes this artifact has one"

    bundle = PredictionEngine._wrap_artifact(raw, league, "<test>")
    assert bundle is not None
    assert bundle.meta_model is not None
    assert bundle.models_dict

    result = PredictionEngine()._run_inference(
        bundle, np.zeros((68,), dtype=np.float32), league.upper()
    )
    assert result.model_version != "fallback"

    if bundle.calibrator is None:
        if bundle.meta_model is not None and type(bundle.meta_model).__name__ in ["IsotonicMetaModel", "LogisticRegression", "CalibratedClassifierCV", "BetaCalibratedMetaModel", "VectorScaledMetaModel", "TemperatureScaledMetaModel"]:
            assert result.calibration_applied is True
            assert result.calibration_method != "raw"
        else:
            assert result.calibration_applied is False
            assert result.calibration_method == "raw"
    else:
        assert result.calibration_applied is True
        assert result.calibration_method != "raw"
