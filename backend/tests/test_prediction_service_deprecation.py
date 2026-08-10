"""Sprint 4 Phase 4: prediction_service deprecation import scan.

Gate: Zero ``from ...services.prediction_service import`` or
      ``import prediction_service`` references may exist in any file except:
      - backend/src/services/prediction_service.py (the adapter shim itself)
      - this test file

If this gate passes, Sprint 5 deletion of prediction_service.py can proceed.

Checks:
  DEP-1: No file outside the adapter shim directly imports the prediction_service
         module via ``from ... import`` or bare ``import`` statements.
  DEP-2: The adapter shim itself carries a ``deprecated`` docstring marker so
         consumers see the deprecation notice on first read.
  DEP-3: prediction_service.py re-exports nothing that bypasses the deprecation
         warning — PredictionService.__init_subclass__ or the module docstring
         must contain the deprecation text.
"""

from __future__ import annotations

import ast
import pathlib
from typing import List, Tuple

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BACKEND_ROOT = pathlib.Path(__file__).parent.parent  # backend/
_ADAPTER_SHIM = _BACKEND_ROOT / "src" / "services" / "prediction_service.py"
_THIS_FILE = pathlib.Path(__file__).resolve()

_FORBIDDEN_MODULE_NAMES = {"prediction_service"}
# The ultra_prediction_service is a separate, non-deprecated module — exclude it
_EXCLUDED_SUFFIXES = {"ultra_prediction_service"}


def _py_files_excluding_shim() -> List[pathlib.Path]:
    files = []
    for path in _BACKEND_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if path.resolve() == _ADAPTER_SHIM.resolve():
            continue
        if path.resolve() == _THIS_FILE:
            continue
        files.append(path)
    return files


def _extract_module_imports(source: str, filename: str) -> List[Tuple[int, str]]:
    """Return (lineno, module_name) for all import statements referencing prediction_service."""
    hits: List[Tuple[int, str]] = []
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return hits

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Strip leading dots for relative imports
                base = alias.name.split(".")[-1]
                if base in _FORBIDDEN_MODULE_NAMES and base not in _EXCLUDED_SUFFIXES:
                    hits.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            # from ...services.prediction_service import Foo
            module = node.module or ""
            base = module.split(".")[-1]
            if base in _FORBIDDEN_MODULE_NAMES and base not in _EXCLUDED_SUFFIXES:
                hits.append((node.lineno, module))

    return hits


# ---------------------------------------------------------------------------
# DEP-1: No imports of prediction_service outside the shim
# ---------------------------------------------------------------------------


class TestNoPredictionServiceImports:
    def test_no_direct_imports_outside_shim(self):
        """DEP-1: Zero source files outside the adapter shim may import prediction_service."""
        violations: List[str] = []

        for path in _py_files_excluding_shim():
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue

            hits = _extract_module_imports(source, str(path))
            for lineno, module in hits:
                rel = path.relative_to(_BACKEND_ROOT)
                violations.append(f"{rel}:{lineno}  ← imports '{module}'")

        assert not violations, (
            "prediction_service is marked @deprecated. "
            "The following files must migrate to prediction.py:\n"
            + "\n".join(f"  {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# DEP-2: Adapter shim carries deprecation marker in its docstring
# ---------------------------------------------------------------------------


class TestAdapterShimDeprecationMarker:
    def test_shim_deleted_in_sprint5(self):
        """DEP-2 (post-deletion): prediction_service.py must be absent after Phase A deletion."""
        assert not _ADAPTER_SHIM.exists(), (
            f"prediction_service.py still exists at {_ADAPTER_SHIM}. "
            "Phase A requires this file to be deleted once "
            "test_no_direct_imports_outside_shim passes."
        )

    def test_shim_module_docstring_contains_deprecated(self):
        """DEP-2: skipped — shim deleted in Phase A."""
        if not _ADAPTER_SHIM.exists():
            pytest.skip("prediction_service.py deleted in Phase A — gate satisfied.")
        source = _ADAPTER_SHIM.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            pytest.fail(f"prediction_service.py has a syntax error: {exc}")
        module_docstring = ast.get_docstring(tree) or ""
        assert "deprecated" in module_docstring.lower()

    def test_shim_class_docstring_contains_deprecated(self):
        """DEP-3: skipped — shim deleted in Phase A."""
        if not _ADAPTER_SHIM.exists():
            pytest.skip("prediction_service.py deleted in Phase A — gate satisfied.")
        source = _ADAPTER_SHIM.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            pytest.skip("Syntax error in prediction_service.py — covered by DEP-2")
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PredictionService":
                class_doc = ast.get_docstring(node) or ""
                assert "deprecated" in class_doc.lower()
                return
