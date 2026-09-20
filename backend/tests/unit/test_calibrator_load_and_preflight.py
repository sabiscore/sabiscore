"""The calibrator must survive both loaders, and only run if it actually runs.

`docs/DEBT.md` item 113 recorded two committed facts that appeared to be in
direct contradiction:

1. A fresh, cold `get_artifact_bundle("BUNDESLIGA")` returned a bundle whose
   `.calibrator` was a real `FittedCalibrator` that raised on application.
2. Production's own prediction log showed that calibrator was never applied
   (`calibration_method="raw"`, 100% of rows) and also never crashed into
   `model_version="fallback"`.

Both were true. `SabiScoreEnsemble.load_model` -- the loader the *production
startup* path uses -- copied five of the artifact's six keys and never read
`calibrator`, so `prime_cache`'s `getattr(model, "calibrator", None)` bridge
silently yielded `None`. The cold path deserializes the raw dict instead and
read the key directly, so only it ever saw the calibrator. Same two-loader
asymmetry that dropped `meta_model` (item 87), one field over.

Carrying the key through is only safe alongside the preflight, because
`_run_inference` answers *any* calibrator exception with `_fallback_result()`
-- so admitting an unusable calibrator would not degrade one response, it would
return the fallback on every request for that league, permanently.
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
        raise AttributeError("'LogisticRegression' object has no attribute 'multi_class'")


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
    could not distinguish "artifact has no calibrator" from "loader dropped
    it" -- which is exactly why the drop went unnoticed.
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
def test_no_committed_artifact_admits_a_calibrator_today(league: str) -> None:
    """Measured state of the served generation, pinned so a change is visible.

    Four of the six `v5_phase7` artifacts carry no calibrator at all; the other
    two carry a `sigmoid` one that is unusable in this runtime. So every league
    serves uncalibrated probabilities, `calibration_method` is honestly `"raw"`,
    and G11 fails on real evidence (`docs/DEBT.md` item 113).

    ⚠️ This corrects item 83's claim that *every* `v5_phase7` artifact carries
    a `FittedCalibrator`. Measured: two of six do.

    If a future generation ships a loadable calibrator this test must be
    updated deliberately -- it is a statement about the artifacts, not a
    requirement that calibration stay off.
    """
    bundle = PredictionEngine._wrap_artifact(_raw(league), league, _artifact(league))
    assert bundle is not None
    assert bundle.calibrator is None


# --------------------------------------------------------------------------
# The preflight
# --------------------------------------------------------------------------


def test_preflight_rejects_a_calibrator_that_raises_on_use() -> None:
    assert PredictionEngine._usable_calibrator(_Unusable(), "bundesliga", "<test>") is None


def test_preflight_never_raises_on_a_hostile_object() -> None:
    """It runs on the startup path; a preflight that can abort boot is worse
    than the defect it screens for."""
    assert PredictionEngine._usable_calibrator(_Hostile(), "epl", "<test>") is None


def test_preflight_passes_none_through() -> None:
    assert PredictionEngine._usable_calibrator(None, "epl", "<test>") is None


def test_preflight_admits_a_calibrator_that_returns_a_valid_simplex(monkeypatch) -> None:
    """The screen must not be a blanket refusal -- a good calibrator gets used."""
    monkeypatch.setattr(
        "src.models.prediction._apply_calibrator",
        lambda method, calibrators, proba: np.asarray([[0.5, 0.25, 0.25]]),
    )
    monkeypatch.setattr("src.models.prediction._CAL_AVAILABLE", True)

    calibrator = _Identity()
    assert PredictionEngine._usable_calibrator(calibrator, "epl", "<test>") is calibrator


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


def test_a_rejected_calibrator_leaves_the_league_serving_not_falling_back() -> None:
    """The whole point of screening at load time.

    `_run_inference` returns `_fallback_result()` on any calibrator exception,
    so an admitted-but-broken calibrator means `model_version="fallback"` on
    every request. Rejecting it at load leaves a working bundle that serves
    real, uncalibrated probabilities instead.
    """
    raw = _raw("bundesliga")
    assert raw.get("calibrator") is not None, "fixture assumes this artifact has one"

    bundle = PredictionEngine._wrap_artifact(raw, "bundesliga", "<test>")
    assert bundle is not None
    assert bundle.calibrator is None
    assert bundle.meta_model is not None
    assert bundle.models_dict
