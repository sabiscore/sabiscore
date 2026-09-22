"""ServedPredictionAdapter.predict_proba must renormalise float32 rounding
noise rather than reject it, and must still reject genuine garbage.

docs/DEBT.md item 127: the served path sums a base-ensemble average through a
per-class sigmoid calibrator then renormalises -- several float32 operations
deep -- so a row's raw sum can land up to ~1e-4 away from 1.0 with nothing
wrong. The adapter's own pre-MAPIE check must not reject that, and its output
must be renormalised tightly enough that MAPIE's internal validation
(rtol=1e-05, atol=0) accepts it -- loosening this adapter's own tolerance is
not sufficient, since MAPIE's check lives inside the mapie package and cannot
be relaxed from here.

No real model, no MAPIE import: this isolates predict_proba's validation and
renormalisation logic with a stub engine, so it runs without models/ or a
network call.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from evaluate_g16_uncertainty import ServedPredictionAdapter  # noqa: E402


@dataclass
class _FakeResult:
    home_win: float
    draw: float
    away_win: float
    model_version: str = "v5_phase7"
    calibration_applied: bool = True
    calibration_method: str = "sigmoid"
    generation: str | None = "v5_phase7-20260808"
    feature_schema_version: str | None = "phase7_68"
    artifact_sha256: str | None = "deadbeef"


class _FakeEngine:
    """Returns one pre-programmed result per call, in order."""

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self._calls = 0

    def _run_inference(self, bundle, row, league):  # noqa: ANN001
        result = self._results[self._calls]
        self._calls += 1
        return result


def _adapter(results: list[_FakeResult]) -> ServedPredictionAdapter:
    return ServedPredictionAdapter(_FakeEngine(results), bundle=object(), league="EPL")


def test_float32_rounding_noise_is_renormalised_not_rejected():
    """The exact class of row item 127 found: sums to 1.0001 / 0.9999."""
    results = [
        _FakeResult(0.4379, 0.2648, 0.2974),  # sums to 1.0001
        _FakeResult(0.4378, 0.2647, 0.2974),  # sums to 0.9999
    ]
    output = _adapter(results).predict_proba(np.zeros((2, 3), dtype=np.float32))
    assert output.dtype == np.float64
    row_sums = output.sum(axis=1)
    assert np.allclose(row_sums, 1.0, atol=1e-9), (
        "output must sum to (effectively) exactly 1.0 in float64 -- MAPIE's "
        "own internal check is rtol=1e-05, atol=0 and cannot be loosened "
        "from this adapter"
    )


def test_a_negative_probability_still_raises():
    results = [
        _FakeResult(1.05, 0.10, -0.15)
    ]  # sums to 1.0, but a component is negative
    with pytest.raises(RuntimeError, match="invalid probability simplex"):
        _adapter(results).predict_proba(np.zeros((1, 3), dtype=np.float32))


def test_nan_still_raises():
    results = [_FakeResult(float("nan"), 0.5, 0.5)]
    with pytest.raises(RuntimeError, match="invalid probability simplex"):
        _adapter(results).predict_proba(np.zeros((1, 3), dtype=np.float32))


def test_a_sum_far_from_one_still_raises():
    """Not just rounding noise -- e.g. a genuinely broken calibrator output."""
    results = [_FakeResult(0.3, 0.3, 0.3)]  # sums to 0.9, outside atol=0.05
    with pytest.raises(RuntimeError, match="invalid probability simplex"):
        _adapter(results).predict_proba(np.zeros((1, 3), dtype=np.float32))


def test_uncalibrated_result_raises_before_the_simplex_check():
    results = [
        _FakeResult(0.5, 0.3, 0.2, calibration_applied=False, calibration_method="raw")
    ]
    with pytest.raises(RuntimeError, match="calibration provenance failed"):
        _adapter(results).predict_proba(np.zeros((1, 3), dtype=np.float32))


def test_fallback_result_raises():
    results = [_FakeResult(0.5, 0.3, 0.2, model_version="fallback")]
    with pytest.raises(RuntimeError, match="served path returned fallback"):
        _adapter(results).predict_proba(np.zeros((1, 3), dtype=np.float32))
