"""Regression tests for certification evidence schema compatibility."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "compile_certification_report.py"
)
_SPEC = importlib.util.spec_from_file_location("certification_compiler", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_g11_accepts_current_nested_harness_shape() -> None:
    result = _MODULE.evaluate_g11({"metrics": {"ece": {"ece": 0.012}}})
    assert result["status"] == "PASS"
    assert result["value"] == 0.012


def test_g11_accepts_legacy_scalar_shape() -> None:
    result = _MODULE.evaluate_g11({"metrics": {"ece": 0.012}})
    assert result["status"] == "PASS"
    assert result["value"] == 0.012


def test_g15_accepts_current_nested_harness_shape() -> None:
    result = _MODULE.evaluate_g15({"metrics": {"brier": {"decomposition_error": 1e-9}}})
    assert result["status"] == "PASS"


def test_g11_invalid_shape_is_explicit_not_keyerror() -> None:
    try:
        _MODULE.evaluate_g11({"metrics": {"ece": {"wrong": 0.1}}})
    except ValueError as exc:
        assert "G11" in str(exc)
    else:
        raise AssertionError("invalid G11 evidence must fail closed")
