from __future__ import annotations

import numpy as np
import pytest

from src.core.meta_model import SoftmaxMetaModel, TemperatureScaledMetaModel


def _base() -> SoftmaxMetaModel:
    return SoftmaxMetaModel(
        coef=np.asarray([[2.0], [0.0], [-2.0]]),
        intercept=np.zeros(3),
        classes=np.asarray([0, 1, 2]),
        feature_names=["signal"],
    )


def test_temperature_calibration_preserves_probability_simplex() -> None:
    model = TemperatureScaledMetaModel(_base(), temperature=1.5)
    probabilities = model.predict_proba([[1.0], [-1.0]])
    assert probabilities.shape == (2, 3)
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    assert np.all(np.isfinite(probabilities))


def test_larger_temperature_softens_confidence() -> None:
    base = _base().predict_proba([[1.0]])
    calibrated = TemperatureScaledMetaModel(_base(), temperature=2.0).predict_proba([[1.0]])
    assert calibrated.max() < base.max()


@pytest.mark.parametrize("temperature", [0.0, -1.0, float("nan")])
def test_invalid_temperature_rejected(temperature: float) -> None:
    with pytest.raises(ValueError):
        TemperatureScaledMetaModel(_base(), temperature)
