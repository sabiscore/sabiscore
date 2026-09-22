from __future__ import annotations

import numpy as np
import pytest

from src.core.meta_model import (
    BetaCalibratedMetaModel,
    IsotonicMetaModel,
    SoftmaxMetaModel,
    TemperatureScaledMetaModel,
    VectorScaledMetaModel,
)


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
    calibrated = TemperatureScaledMetaModel(_base(), temperature=2.0).predict_proba(
        [[1.0]]
    )
    assert calibrated.max() < base.max()


@pytest.mark.parametrize("temperature", [0.0, -1.0, float("nan")])
def test_invalid_temperature_rejected(temperature: float) -> None:
    with pytest.raises(ValueError):
        TemperatureScaledMetaModel(_base(), temperature)


# ── IsotonicMetaModel (Portfolio A / B3 recalibration candidate) ──────────────
#
# This head can be selected by scripts/train_on_real_matches.py::_select_calibrator
# and pickled into a served artifact, so its output contract is load-bearing:
# every prediction path assumes a valid simplex.


def _isotonic_calibrators(n_classes: int = 3):
    """One fitted IsotonicRegression per class, on a deliberately biased mapping."""
    from sklearn.isotonic import IsotonicRegression

    raw = np.linspace(0.0, 1.0, 25)
    calibrators = []
    for _ in range(n_classes):
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        # Systematic overconfidence: predicted p maps to a lower empirical rate.
        iso.fit(raw, raw * 0.6)
        calibrators.append(iso)
    return calibrators


def test_isotonic_calibration_preserves_probability_simplex() -> None:
    model = IsotonicMetaModel(_base(), _isotonic_calibrators())
    probabilities = model.predict_proba([[1.0], [-1.0], [0.0]])
    assert probabilities.shape == (3, 3)
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    assert np.all(probabilities >= 0.0)
    assert np.all(np.isfinite(probabilities))


def test_isotonic_predict_matches_argmax_of_predict_proba() -> None:
    model = IsotonicMetaModel(_base(), _isotonic_calibrators())
    x = [[1.0], [-1.0], [0.0]]
    expected = model.classes_[np.argmax(model.predict_proba(x), axis=1)]
    assert np.array_equal(model.predict(x), expected)


def test_isotonic_degenerate_row_falls_back_to_uniform() -> None:
    """A calibrator set that maps everything to 0 must not divide by zero.

    Renormalising an all-zero row is the one case where the simplex cannot be
    recovered from the data; the contract is a uniform row, never NaN.
    """
    from sklearn.isotonic import IsotonicRegression

    zeros = []
    for _ in range(3):
        iso = IsotonicRegression(y_min=0.0, y_max=0.0, out_of_bounds="clip")
        iso.fit(np.linspace(0.0, 1.0, 10), np.zeros(10))
        zeros.append(iso)

    probabilities = IsotonicMetaModel(_base(), zeros).predict_proba([[1.0]])
    assert np.allclose(probabilities, 1.0 / 3.0)
    assert np.all(np.isfinite(probabilities))


def test_isotonic_rejects_calibrator_count_mismatch() -> None:
    with pytest.raises(ValueError):
        IsotonicMetaModel(_base(), _isotonic_calibrators(n_classes=2))


# ── VectorScaledMetaModel (Portfolio A / B2 recalibration candidate #2) ───────


def test_vector_scaling_preserves_probability_simplex() -> None:
    model = VectorScaledMetaModel(
        _base(), scale=np.array([1.5, 1.0, 0.5]), bias=np.array([0.1, 0.0, -0.1])
    )
    probabilities = model.predict_proba([[1.0], [-1.0]])
    assert probabilities.shape == (2, 3)
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    assert np.all(np.isfinite(probabilities))


def test_vector_scaling_reduces_to_temperature_when_scale_and_bias_are_shared() -> None:
    """A degenerate vector-scaled model (equal scale = 1/T, zero bias, every
    class) is exactly temperature scaling -- the two must agree bit-for-bit,
    since vector scaling is meant to strictly generalise it (§20 B2)."""
    base = _base()
    temperature_value = 2.0
    vector = VectorScaledMetaModel(
        base, scale=np.full(3, 1.0 / temperature_value), bias=np.zeros(3)
    )
    temperature = TemperatureScaledMetaModel(base, temperature=temperature_value)
    x = [[1.0], [-1.0], [0.0]]
    assert np.allclose(vector.predict_proba(x), temperature.predict_proba(x))


def test_vector_scaling_predict_matches_argmax_of_predict_proba() -> None:
    model = VectorScaledMetaModel(
        _base(), scale=np.array([2.0, 1.0, 0.5]), bias=np.zeros(3)
    )
    x = [[1.0], [-1.0], [0.0]]
    expected = model.classes_[np.argmax(model.predict_proba(x), axis=1)]
    assert np.array_equal(model.predict(x), expected)


def test_vector_scaling_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError):
        VectorScaledMetaModel(_base(), scale=np.array([1.0, 1.0]), bias=np.zeros(3))


@pytest.mark.parametrize(
    "scale,bias",
    [
        (np.array([np.nan, 1.0, 1.0]), np.zeros(3)),
        (np.ones(3), np.array([np.inf, 0.0, 0.0])),
    ],
)
def test_vector_scaling_rejects_non_finite_parameters(
    scale: np.ndarray, bias: np.ndarray
) -> None:
    with pytest.raises(ValueError):
        VectorScaledMetaModel(_base(), scale=scale, bias=bias)


# ── BetaCalibratedMetaModel (Portfolio A / B2 recalibration candidate #4) ─────


def _beta_params(n_classes: int = 3) -> list[tuple[float, float, float]]:
    """One (a, b, c) triple per class: a mild, well-behaved calibration map."""
    return [(1.2, -0.8, 0.0) for _ in range(n_classes)]


def test_beta_calibration_preserves_probability_simplex() -> None:
    model = BetaCalibratedMetaModel(_base(), _beta_params())
    probabilities = model.predict_proba([[1.0], [-1.0], [0.0]])
    assert probabilities.shape == (3, 3)
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    assert np.all(probabilities >= 0.0)
    assert np.all(np.isfinite(probabilities))


def test_beta_calibration_predict_matches_argmax_of_predict_proba() -> None:
    model = BetaCalibratedMetaModel(_base(), _beta_params())
    x = [[1.0], [-1.0], [0.0]]
    expected = model.classes_[np.argmax(model.predict_proba(x), axis=1)]
    assert np.array_equal(model.predict(x), expected)


def test_beta_calibration_degenerate_row_falls_back_to_uniform() -> None:
    """(a, b, c) = (0, 0, -30) drives sigmoid(z) -> 0 for every class -- the
    same all-zero-row case IsotonicMetaModel guards against."""
    zeros = [(0.0, 0.0, -30.0) for _ in range(3)]
    probabilities = BetaCalibratedMetaModel(_base(), zeros).predict_proba([[1.0]])
    assert np.allclose(probabilities, 1.0 / 3.0)
    assert np.all(np.isfinite(probabilities))


def test_beta_calibration_rejects_calibrator_count_mismatch() -> None:
    with pytest.raises(ValueError):
        BetaCalibratedMetaModel(_base(), _beta_params(n_classes=2))
