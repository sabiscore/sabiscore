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


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.mark.parametrize("script", ["evaluate_v21_tier_a_candidates.py", "v21_certification.py"])
def test_v21_report_generators_carry_no_hardcoded_verdicts(script: str) -> None:
    """Both V21 generators once printed PASS, canary readiness and parity they never
    measured. A verdict must come from a computation, never from a literal."""
    text = (SCRIPTS / script).read_text(encoding="utf-8")
    assert '"canary_ready": True' not in text
    assert "LIVE-VERIFIED PARITY" not in text
    assert "permanently retired" not in text
    assert '"verified_at": "20' not in text and '"evaluated_at": "20' not in text
    assert ': "PASS",' not in text, "a gate literal set to PASS, rather than computed"


def test_candidate_evaluator_writes_only_its_own_evidence_file() -> None:
    """It used to overwrite eight shared reports that v21_certification also writes."""
    text = (SCRIPTS / "evaluate_v21_tier_a_candidates.py").read_text(encoding="utf-8")
    assert text.count("write_text(") + text.count("json.dump(") == 1
    assert "v21-candidate-m-evaluation.json" in text
