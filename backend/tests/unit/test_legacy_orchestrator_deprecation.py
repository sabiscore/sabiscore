"""Regression tests proving deprecation of legacy services/orchestrator.py.

Directive V18.0 Section 8.1 & Gate A.
"""

from pathlib import Path
import pytest

from src.services.orchestrator import MockModelOrchestrator, ProductionOrchestrator


def test_api_directory_does_not_import_legacy_orchestrator():
    """Verify backend/src/api has zero imports of legacy services/orchestrator.py."""
    api_dir = Path(__file__).resolve().parents[2] / "src" / "api"
    
    violating_files = []
    for py_file in api_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if "services.orchestrator" in text or "from ..services.orchestrator" in text:
            violating_files.append(str(py_file))
            
    assert not violating_files, f"Production API references deprecated orchestrator: {violating_files}"


def test_mock_model_orchestrator_predict_fails_closed():
    """Verify MockModelOrchestrator raises RuntimeError under zero-fabrication contract."""
    mock_orch = MockModelOrchestrator()
    with pytest.raises(RuntimeError, match="MockModelOrchestrator is deprecated and prohibited"):
        mock_orch.predict(league="epl", match_data={})
