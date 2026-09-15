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
    model.predict_proba.return_value = np.tile(np.asarray(output, dtype=np.float64), (4, 1))
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
