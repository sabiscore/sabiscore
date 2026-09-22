"""DEBT-83 calibration data-path regression tests.

These tests intentionally exercise the same helper used by the artifact
remediation script. The critical invariant is that a serialized calibrator is
fit on the exact probability domain that PredictionEngine serves immediately
before calibration.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inject_platt_calibrator.py"
_SPEC = importlib.util.spec_from_file_location("debt83_inject", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class _NamedMetaModel:
    def __init__(self, output: tuple[float, float, float]) -> None:
        self.output = output

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.tile(np.asarray(self.output, dtype=np.float64), (len(X), 1))


def _learner(output: tuple[float, float, float]) -> MagicMock:
    model = MagicMock()
    model.predict_proba.return_value = np.tile(
        np.asarray(output, dtype=np.float64), (4, 1)
    )
    return model


def test_meta_model_output_is_the_calibration_domain() -> None:
    """A present meta-model wins over the base-learner average."""
    models = {
        "rf": _learner((0.80, 0.10, 0.10)),
        "xgb": _learner((0.10, 0.20, 0.70)),
    }
    meta = _NamedMetaModel((0.55, 0.30, 0.15))
    probabilities, serving_head, serving_domain = _MODULE._served_probabilities(
        {"models": models, "meta_model": meta}, np.zeros((4, 3), dtype=np.float32)
    )

    assert serving_head == "meta_model"
    assert serving_domain == "_NamedMetaModel"
    np.testing.assert_allclose(probabilities[0], [0.55, 0.30, 0.15])
    # Explicitly prove we did not accidentally calibrate the equal-weight base average.
    assert not np.allclose(probabilities[0], [0.45, 0.15, 0.40])


def test_base_average_is_domain_only_when_no_meta_model() -> None:
    """The base average remains canonical only for artifacts without a meta head."""
    models = {
        "rf": _learner((0.80, 0.10, 0.10)),
        "xgb": _learner((0.10, 0.20, 0.70)),
    }
    probabilities, serving_head, serving_domain = _MODULE._served_probabilities(
        {"models": models, "meta_model": None}, np.zeros((4, 3), dtype=np.float32)
    )

    assert serving_head == "base_equal_weight"
    assert serving_domain == "base_learners"
    np.testing.assert_allclose(probabilities[0], [0.45, 0.15, 0.40])


def test_invalid_meta_model_output_fails_closed() -> None:
    """A malformed meta head must never produce a certifiable calibration artifact."""
    bad_meta = _NamedMetaModel((0.80, 0.80, -0.60))
    models = {"rf": _learner((0.50, 0.25, 0.25))}

    with pytest.raises(ValueError, match="invalid probability simplex"):
        _MODULE._served_probabilities(
            {"models": models, "meta_model": bad_meta},
            np.zeros((4, 3), dtype=np.float32),
        )


class _SizedLearner:
    """Base learner whose output length tracks the input, unlike the MagicMock."""

    def __init__(self, output: tuple[float, float, float]) -> None:
        self.output = output

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.tile(np.asarray(self.output, dtype=np.float64), (len(X), 1))


def _confident_bundle() -> dict:
    """A meta-model artifact that is badly over-confident on the home class."""
    return {
        "models": {"a": _SizedLearner((0.60, 0.25, 0.15))},
        "meta_model": _NamedMetaModel((0.90, 0.05, 0.05)),
    }


def _split(n: int, home_in_ten: int) -> tuple[np.ndarray, np.ndarray]:
    """n rows whose home-win rate is ``home_in_ten``/10.

    The calibration and holdout sets deliberately carry *different* base rates.
    A constant-output head's ECE depends only on the label distribution, so
    identical splits would make the in-sample and holdout figures numerically
    equal and no assertion could tell the two apart.
    """
    rest = 10 - home_in_ten
    pattern = [0] * home_in_ten + [1] * (rest // 2) + [2] * (rest - rest // 2)
    y = np.array((pattern * (n // 10 + 1))[:n], dtype=np.int64)
    return np.zeros((n, 3), dtype=np.float32), y


def _fit(bundle: dict, n: int = 60, cal_home: int = 6, hold_home: int = 4):
    from datetime import date

    X_cal, y_cal = _split(n, cal_home)
    X_hold, y_hold = _split(n, hold_home)
    return _MODULE._fit_platt(
        bundle,
        X_cal,
        y_cal,
        X_hold,
        y_hold,
        "TESTLEAGUE",
        calibration_start=date(2023, 8, 1),
        calibration_end=date(2024, 5, 1),
        holdout_start=date(2024, 8, 1),
        holdout_end=date(2025, 5, 1),
    )


def test_serving_head_guard_does_not_reject_a_meta_model_artifact() -> None:
    """Regression: the guard compared hold_head against serving_domain.

    ``_served_probabilities`` returns ``(proba, head, domain)`` where a
    meta-model artifact yields head ``"meta_model"`` and domain equal to the
    meta-model's class name. Comparing the two across calls made the guard
    raise unconditionally for every meta-model artifact, so the hardened
    injector could never fit anything.
    """
    calibrator, outcome = _fit(_confident_bundle())
    assert outcome != "error", (
        "meta-model artifact must not trip the serving-head guard"
    )
    assert outcome in {"accepted", "declined"}


def test_headline_evidence_is_measured_on_the_holdout_not_the_fit_rows() -> None:
    """ece_after must never be the optimistic fitted-on-rows figure."""
    calibrator, outcome = _fit(_confident_bundle())
    if outcome != "accepted":
        pytest.skip("calibrator declined; headline-field check needs an accepted fit")
    mc = calibrator.method_comparison
    assert mc["evidence_basis"] == "holdout"
    assert calibrator.ece_after == mc["holdout_ece_after"]
    assert calibrator.ece_before == mc["holdout_ece_before"]
    assert calibrator.brier_after == mc["holdout_brier_after"]
    # The in-sample figures are retained, but only as labelled diagnostics.
    assert "insample_ece_after" in mc


def test_a_calibrator_that_worsens_the_holdout_is_declined() -> None:
    """Directive §19: a calibrator is never forced into production."""
    # Already well calibrated: each class occurs a third of the time and the
    # head says so, leaving a fitted calibrator nothing to win and noise to lose.
    bundle = {
        "models": {"a": _SizedLearner((0.4, 0.3, 0.3))},
        "meta_model": _NamedMetaModel((0.4, 0.3, 0.3)),
    }
    calibrator, outcome = _fit(bundle, cal_home=4, hold_home=4)
    if outcome == "accepted":
        assert calibrator.ece_after["mean"] < calibrator.ece_before["mean"]
        assert calibrator.brier_after <= calibrator.brier_before
    else:
        assert outcome == "declined"
        assert calibrator is None
