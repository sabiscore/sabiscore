"""DEBT-83 runtime regression tests for PredictionEngine provenance hardening.

The critical invariant is that a calibrator fitted on meta-model probabilities
must never receive an equal-weight base-ensemble probability vector merely
because the meta-model or calibration runtime failed at serving time.
"""

from unittest.mock import MagicMock, patch

import numpy as np

from src.models.prediction import PredictionEngine, _ArtifactBundle


FEATURES = np.zeros(58, dtype=np.float32)


def _bundle(*, meta_model, calibrator):
    rf = MagicMock()
    rf.n_features_in_ = 58
    rf.predict_proba = MagicMock(return_value=np.array([[0.90, 0.05, 0.05]]))
    xgb = MagicMock()
    xgb.n_features_in_ = 58
    xgb.predict_proba = MagicMock(return_value=np.array([[0.10, 0.05, 0.85]]))
    return _ArtifactBundle(
        direct_model=None,
        models_dict={"rf": rf, "xgb": xgb},
        calibrator=calibrator,
        overlay=None,
        feature_columns=None,
        meta_model=meta_model,
        model_version="v5_phase7",
        generation="debt83-test",
    )


def test_meta_model_failure_with_serialized_calibrator_fails_closed_and_never_calls_calibrator():
    """A failed meta head must not substitute the base-average calibration domain."""

    class BrokenMetaModel:
        def predict_proba(self, X):
            raise ValueError("meta-model shape mismatch")

    calibrator = MagicMock()
    calibrator.method = "sigmoid"
    calibrator.calibrators = MagicMock()
    calibrator.ece_after = {"mean": 0.02}

    bundle = _bundle(meta_model=BrokenMetaModel(), calibrator=calibrator)

    with (
        patch("src.models.prediction._CAL_AVAILABLE", True),
        patch("src.models.prediction._apply_calibrator") as apply_calibrator,
    ):
        result = PredictionEngine()._run_inference(bundle, FEATURES, "EPL")

    assert result.model_version == "fallback"
    assert result.calibration_applied is False
    assert result.calibration_method == "uniform"
    apply_calibrator.assert_not_called()


def test_serialized_calibrator_failure_fails_closed_without_serving_raw_meta_output():
    """A present calibrator is a serving contract, not optional decoration."""

    class ValidMetaModel:
        def predict_proba(self, X):
            return np.array([[0.20, 0.30, 0.50]])

    calibrator = MagicMock()
    calibrator.method = "sigmoid"
    calibrator.calibrators = MagicMock()
    calibrator.ece_after = {"mean": 0.02}

    bundle = _bundle(meta_model=ValidMetaModel(), calibrator=calibrator)

    with (
        patch("src.models.prediction._CAL_AVAILABLE", True),
        patch(
            "src.models.prediction._apply_calibrator",
            side_effect=ValueError("serialized calibrator corrupted"),
        ),
    ):
        result = PredictionEngine()._run_inference(bundle, FEATURES, "EPL")

    assert result.model_version == "fallback"
    assert result.calibration_applied is False
    assert result.calibration_method == "uniform"


def test_serialized_calibrator_requires_runtime_dependency():
    """A serialized calibrator without its runtime must not silently pass raw output."""

    class ValidMetaModel:
        def predict_proba(self, X):
            return np.array([[0.20, 0.30, 0.50]])

    calibrator = MagicMock()
    bundle = _bundle(meta_model=ValidMetaModel(), calibrator=calibrator)

    with (
        patch("src.models.prediction._CAL_AVAILABLE", False),
        patch("src.models.prediction._apply_calibrator", None),
    ):
        result = PredictionEngine()._run_inference(bundle, FEATURES, "EPL")

    assert result.model_version == "fallback"
    assert result.calibration_applied is False
    assert result.calibration_method == "uniform"
