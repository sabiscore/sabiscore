from __future__ import annotations

import numpy as np
import pytest

import src.models.prediction as prediction_module
from src.models.prediction import _ArtifactBundle, PredictionEngine


class BaseModel:
    def __init__(self, proba: list[float]) -> None:
        self.proba = np.asarray([proba], dtype=float)

    def predict_proba(self, X: object) -> np.ndarray:
        return self.proba


class BrokenMetaModel:
    def predict_proba(self, X: object) -> np.ndarray:
        raise RuntimeError("meta-model failure")


class WorkingMetaModel:
    def __init__(self, proba: list[float]) -> None:
        self.proba = np.asarray([proba], dtype=float)

    def predict_proba(self, X: object) -> np.ndarray:
        return self.proba


class SpyCalibrator:
    def __init__(self, proba: list[float], fail: bool = False) -> None:
        self.proba = np.asarray([proba], dtype=float)
        self.fail = fail
        self.calls = 0

    def predict_proba(self, X: object) -> np.ndarray:
        self.calls += 1
        if self.fail:
            raise RuntimeError("calibrator failure")
        return self.proba


@pytest.fixture
def engine() -> PredictionEngine:
    return PredictionEngine()


def make_bundle(meta_model: object, calibrator: object | None) -> _ArtifactBundle:
    return _ArtifactBundle(
        models={
            "base_a": BaseModel([0.70, 0.20, 0.10]),
            "base_b": BaseModel([0.60, 0.30, 0.10]),
        },
        meta_model=meta_model,
        calibrator=calibrator,
    )


def test_meta_model_failure_fails_closed_and_never_calls_calibrator(
    engine: PredictionEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calibrator = SpyCalibrator([0.20, 0.30, 0.50])
    bundle = make_bundle(BrokenMetaModel(), calibrator)

    def unexpected(*args: object, **kwargs: object) -> np.ndarray:
        raise AssertionError("calibrator must not receive base-domain probabilities")

    monkeypatch.setattr(engine, "_apply_calibrator", unexpected)

    served, calibration_applied = engine._run_inference(bundle, X=object())

    assert served is None
    assert calibration_applied is False
    assert calibrator.calls == 0


def test_calibrator_failure_fails_closed_after_valid_meta_model(
    engine: PredictionEngine,
) -> None:
    calibrator = SpyCalibrator([0.20, 0.30, 0.50], fail=True)
    bundle = make_bundle(WorkingMetaModel([0.40, 0.35, 0.25]), calibrator)

    served, calibration_applied = engine._run_inference(bundle, X=object())

    assert served is None
    assert calibration_applied is False
    assert calibrator.calls == 1


def test_missing_calibration_runtime_fails_closed(
    engine: PredictionEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calibrator = SpyCalibrator([0.20, 0.30, 0.50])
    bundle = make_bundle(WorkingMetaModel([0.40, 0.35, 0.25]), calibrator)

    monkeypatch.setattr(prediction_module, "_CAL_AVAILABLE", False)

    served, calibration_applied = engine._run_inference(bundle, X=object())

    assert served is None
    assert calibration_applied is False
    assert calibrator.calls == 0


def test_valid_meta_model_probability_is_the_only_calibrator_input(
    engine: PredictionEngine,
) -> None:
    calibrator = SpyCalibrator([0.30, 0.30, 0.40])
    bundle = make_bundle(WorkingMetaModel([0.40, 0.35, 0.25]), calibrator)

    served, calibration_applied = engine._run_inference(bundle, X=object())

    assert calibration_applied is True
    np.testing.assert_allclose(served, [[0.30, 0.30, 0.40]])
    assert calibrator.calls == 1
