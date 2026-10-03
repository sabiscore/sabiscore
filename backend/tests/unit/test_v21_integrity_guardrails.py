from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.scripts.v21_market_protocol import compare_cohorts, evaluate_market_rows
from backend.serving.feature_bridge import (
    FeatureBridge,
    FeatureBridgeRejected,
    persisted_candidate_schema_hash,
)
import backend.serving.feature_bridge as feature_bridge_module


VALID = {
    "fixture_id": "fixture-1",
    "outcome": 0,
    "candidate_m_probabilities": [0.6, 0.2, 0.2],
    "opening_market_probabilities": [0.5, 0.3, 0.2],
    "closing_market_probabilities": [0.55, 0.25, 0.2],
}


@pytest.mark.parametrize("field", [
    "candidate_m_probabilities",
    "opening_market_probabilities",
    "closing_market_probabilities",
])
@pytest.mark.parametrize("bad_probability", [float("nan"), float("inf"), float("-inf"), True])
def test_market_rows_reject_non_finite_and_boolean_probabilities(field, bad_probability):
    invalid_vector = (
        [bad_probability, 0.0, 0.0]
        if isinstance(bad_probability, bool)
        else [bad_probability, 0.0, 1.0]
    )
    row = {**VALID, field: invalid_vector}
    with pytest.raises(ValueError, match="valid 1X2 probability simplex"):
        evaluate_market_rows([row])


@pytest.mark.parametrize("candidate_rps,market_rps", [
    (float("nan"), 0.2),
    (float("inf"), 0.2),
    (0.2, float("-inf")),
    (True, 0.2),
])
def test_market_comparison_rejects_non_finite_or_boolean_scores(candidate_rps, market_rps):
    with pytest.raises(ValueError, match="finite non-negative"):
        compare_cohorts(
            candidate_fixture_ids=["fixture-1"],
            candidate_outcomes=[0],
            market_fixture_ids=["fixture-1"],
            market_outcomes=[0],
            candidate_rps=candidate_rps,
            market_rps=market_rps,
            benchmark="closing_market",
        )


def test_market_rows_reject_boolean_outcomes():
    with pytest.raises(ValueError, match="integer 0/1/2"):
        evaluate_market_rows([{**VALID, "outcome": True}])


def test_market_comparison_accepts_finite_paired_scores():
    result = compare_cohorts(
        candidate_fixture_ids=["fixture-1"],
        candidate_outcomes=[0],
        market_fixture_ids=["fixture-1"],
        market_outcomes=[0],
        candidate_rps=0.18,
        market_rps=0.2,
        benchmark="closing_market",
    )
    assert result["gate_7"] == "PASS"


def _write_schema_manifest(path: Path, schema_hash: str) -> None:
    path.write_text(
        json.dumps({
            "features": {
                "feature_contract_sha256": schema_hash,
                "feature_schema_version": "test_schema",
                "feature_count": 1,
            }
        }),
        encoding="utf-8",
    )


def test_persisted_candidate_manifest_matches_registered_candidate_schema():
    bridge = FeatureBridge(schema_id="apex_v1_89")
    assert persisted_candidate_schema_hash() == bridge.schema_hash


def test_feature_bridge_rejects_manifest_registry_mismatch(tmp_path, monkeypatch):
    contract_hash = "a" * 64
    contract = {
        "feature_contract_sha256": contract_hash,
        "features": [{
            "feature_name": "elo_difference",
            "semantic_definition": "home Elo minus away Elo",
            "unit": "rating_points",
            "serving_source": "elo:fixture_snapshot",
        }],
    }
    monkeypatch.setattr(feature_bridge_module, "build_feature_contract", lambda _: contract)
    bridge = FeatureBridge(schema_id="test_schema")
    manifest_path = tmp_path / "training_manifest.json"
    _write_schema_manifest(manifest_path, "b" * 64)
    expected_hash = persisted_candidate_schema_hash(
        schema_id="test_schema",
        feature_count=1,
        manifest_path=manifest_path,
    )

    evidence = {
        "elo_difference": {
            "feature_name": "elo_difference",
            "source": "elo:fixture_snapshot",
            "semantics": "home Elo minus away Elo",
            "unit": "rating_points",
            "feature_timestamp": "2026-10-01T10:00:00Z",
            "effective_at": "2026-10-01T10:00:00Z",
            "max_age_seconds": 60,
        }
    }
    with pytest.raises(FeatureBridgeRejected, match="schema_hash"):
        bridge.validate(
            features={"elo_difference": 1.0},
            feature_schema_id="test_schema",
            schema_hash=bridge.schema_hash,
            expected_schema_hash=expected_hash,
            feature_evidence=evidence,
            feature_cutoff="2026-10-01T10:00:30Z",
        )


def test_candidate_endpoint_uses_persisted_manifest_hash_and_image_includes_manifest():
    backend_root = Path(__file__).resolve().parents[2]
    endpoint = (backend_root / "src/api/endpoints/full_analysis.py").read_text(encoding="utf-8")
    dockerfile = (backend_root / "Dockerfile").read_text(encoding="utf-8")
    assert "persisted_candidate_schema_hash(" in endpoint
    assert "expected_schema_hash=expected_candidate_schema_hash" in endpoint
    assert "COPY models/candidates/v6_phase8-candidate/training_manifest_v6_phase8.json" in dockerfile
