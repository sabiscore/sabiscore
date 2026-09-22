"""Small deterministic tests for v7.3 evidence-harness math and contracts.

These tests deliberately avoid loading model artifacts, Redis, Render or Vercel.
They are safe to run on the 8GB Windows workstation before the expensive evidence
jobs.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(name: str):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_g11_equal_mass_bins_are_balanced_and_deterministic() -> None:
    mod = _load("evaluate_g11_ece.py")
    values = np.asarray([0.1, 0.2, 0.2, 0.4, 0.5, 0.8, 0.9], dtype=np.float32)
    first = mod.equal_mass_bins(values, 3)
    second = mod.equal_mass_bins(values, 3)
    assert [x.tolist() for x in first] == [x.tolist() for x in second]
    assert max(map(len, first)) - min(map(len, first)) <= 1


def test_g11_murphy_decomposition_identity() -> None:
    mod = _load("evaluate_g11_ece.py")
    probs = np.asarray(
        [[0.7, 0.2, 0.1], [0.2, 0.5, 0.3], [0.1, 0.2, 0.7], [0.4, 0.3, 0.3]],
        dtype=np.float32,
    )
    y = np.asarray([0, 1, 2, 0], dtype=np.int8)
    _, bins = mod.adaptive_confidence_ece(probs, y, 2)
    result = mod.murphy_brier(probs, y, bins)
    assert abs(result["decomposition_error"]) <= 1e-6


def test_g18_devig_is_a_probability_simplex() -> None:
    mod = _load("evaluate_g18_bootstrap.py")
    probs = mod.devig((2.0, 3.0, 5.0))
    assert probs.dtype == np.float32
    assert np.all(probs > 0)
    assert np.isclose(float(probs.sum()), 1.0, atol=1e-6)


def test_g18_rps_is_zero_for_perfect_forecasts() -> None:
    mod = _load("evaluate_g18_bootstrap.py")
    y = np.asarray([0, 1, 2], dtype=np.int8)
    p = np.eye(3, dtype=np.float32)
    assert np.allclose(mod.rps(y, p), 0.0)
