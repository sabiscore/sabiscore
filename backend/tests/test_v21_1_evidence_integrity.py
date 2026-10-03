"""V21.1 evidence-integrity guards (ENGINEERING / DATA gates).

These tests inspect *production-reachable* source (API, services, stacked model
package) for fabrication patterns and verify the retired non-canonical
prediction route stays retired. They test behaviour of the source tree itself,
not the mere existence of files.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
PRODUCTION_SCOPES = ("api", "services", "models/stacked")

FORBIDDEN_NAMES = {"synthetic_X", "synthetic_y"}
FORBIDDEN_STRING_CONSTANTS = {"consensus_sharp", "fallback_estimate"}


def _production_files() -> list[Path]:
    files: list[Path] = []
    for scope in PRODUCTION_SCOPES:
        files.extend(sorted((BACKEND_SRC / scope).rglob("*.py")))
    assert files, "production scope discovery found no files"
    return files


def _is_random_attribute(node: ast.AST) -> bool:
    """True for ``np.random.*`` or ``numpy.random.*`` attribute access (prohibited per §3)."""
    if isinstance(node, ast.Attribute):
        # np.random.<func>
        if isinstance(node.value, ast.Attribute):
            if node.value.attr == "random" and isinstance(node.value.value, ast.Name) and node.value.value.id in {"np", "numpy"}:
                return True
        # direct np.random reference
        if node.attr == "random" and isinstance(node.value, ast.Name) and node.value.id in {"np", "numpy"}:
            return True
    return False


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    rel = path.relative_to(BACKEND_SRC).as_posix()
    for node in ast.walk(tree):
        if _is_random_attribute(node):
            found.append(f"{rel}:{node.lineno} uses a random generator")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(f"{rel}:{node.lineno} references {node.id}")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in FORBIDDEN_STRING_CONSTANTS
        ):
            found.append(f"{rel}:{node.lineno} contains fabricated provenance label {node.value!r}")
    return found


def test_no_fabrication_patterns_in_production_scopes() -> None:
    violations = [v for path in _production_files() for v in _violations(path)]
    assert violations == []


def test_retired_predict_live_module_is_not_importable() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.api.endpoints.predict_live")


def test_predict_match_route_is_not_registered() -> None:
    from src.api.endpoints import router

    paths = {getattr(route, "path", "") for route in router.routes}
    assert not any(path.endswith("/predict/match") for path in paths)
