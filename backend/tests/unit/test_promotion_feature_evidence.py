from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from src.models.feature_registry import APEX_FEATURES_68
from src.models.promotion_evidence import (
    build_promotion_feature_evidence,
    validate_promotion_feature_evidence,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _candidate_dataset() -> dict[str, dict[str, object]]:
    width = len(APEX_FEATURES_68)
    first = np.zeros(width, dtype=np.float64)
    second = np.linspace(0.01, 0.68, width, dtype=np.float64)
    return {
        "EPL": {
            "X": [first.tolist(), second.tolist()],
            "X_incumbent": [],
            "y": [0, 2],
            "seasons": ["2526", "2526"],
            "dates": [],
        }
    }


def test_builds_mechanical_positional_feature_contract() -> None:
    report = build_promotion_feature_evidence(_candidate_dataset())

    assert report["schema"] == "apex_v1_68"
    assert report["training_rows"] == 2
    assert len(report["features"]) == 68
    assert [row["index"] for row in report["features"]] == list(range(68))
    assert [row["feature"] for row in report["features"]] == list(APEX_FEATURES_68)
    assert report["summary"]["serving_schema_misaligned_slots"] == 11
    assert report["summary"]["always_data_gap_slots"] == 4
    assert report["promotion_gate"] == "FAIL"
    assert validate_promotion_feature_evidence(report) is report


def test_checked_in_quarantined_candidate_report_remains_valid_and_failed() -> None:
    path = BACKEND_ROOT / "models" / "candidate" / "feature_availability_matrix.json"
    report = json.loads(path.read_text(encoding="utf-8"))

    validated = validate_promotion_feature_evidence(report)

    assert validated["promotion_gate"] == "FAIL"
    assert validated["summary"]["serving_schema_misaligned_slots"] == 11
    assert validated["summary"]["always_data_gap_slots"] == 4


def test_forged_pass_is_rejected() -> None:
    report = build_promotion_feature_evidence(_candidate_dataset())
    forged = copy.deepcopy(report)
    forged["promotion_gate"] = "PASS"

    with pytest.raises(ValueError, match="contradicts mechanically derived gate"):
        validate_promotion_feature_evidence(forged)


def test_malformed_summary_is_rejected() -> None:
    report = build_promotion_feature_evidence(_candidate_dataset())
    malformed = copy.deepcopy(report)
    malformed["summary"]["training_defaulted_slots"] += 1

    with pytest.raises(ValueError, match="summary mismatch"):
        validate_promotion_feature_evidence(malformed)


def test_reordered_feature_contract_is_rejected() -> None:
    report = build_promotion_feature_evidence(_candidate_dataset())
    reordered = copy.deepcopy(report)
    reordered["features"][0], reordered["features"][1] = (
        reordered["features"][1],
        reordered["features"][0],
    )

    with pytest.raises(ValueError, match="invalid index|order mismatch"):
        validate_promotion_feature_evidence(reordered)


def test_contract_hash_tampering_is_rejected() -> None:
    report = build_promotion_feature_evidence(_candidate_dataset())
    tampered = copy.deepcopy(report)
    tampered["candidate_contract_hash"] = "0" * 64

    with pytest.raises(ValueError, match="candidate feature-contract hash"):
        validate_promotion_feature_evidence(tampered)


def test_serving_comparison_follows_the_active_schema(monkeypatch) -> None:
    """docs/DEBT.md item 37: the gate must compare against what serving
    ACTUALLY produces, not a hardcoded legacy constant.

    Under today's real manifest (phase7_68 -> legacy block) an apex-trained
    candidate is genuinely misaligned at 11 slots -- that FAIL is correct and
    must not change. Under an apex_v1_68 manifest, live serving produces the
    Apex order, so the same candidate is aligned and this particular blocker
    clears. Without this, the counter would report 11 forever and no serving
    fix could ever satisfy the gate.
    """
    import src.models.promotion_evidence as pe

    legacy = build_promotion_feature_evidence(_candidate_dataset())
    assert legacy["summary"]["serving_schema_misaligned_slots"] == 11

    monkeypatch.setattr(pe, "active_feature_schema_version", lambda: "apex_v1_68")
    apex = build_promotion_feature_evidence(_candidate_dataset())
    assert apex["summary"]["serving_schema_misaligned_slots"] == 0
    assert validate_promotion_feature_evidence(apex) is apex
    assert apex["candidate_contract_hash"] == apex["serving_contract_hash"]


def test_candidate_wider_than_active_serving_contract_does_not_crash() -> None:
    """docs/DEBT.md item 56 Finding 5's second prerequisite: promotion_evidence
    was hardwired to APEX_FEATURES_68 in 9 call sites, so any candidate wider
    than what is currently active in production (e.g. a 71-feature xG
    candidate against today's 68-wide serving contract) indexed past the end
    of ``serving_contract`` and raised IndexError before evidence could even
    be built — this is exactly the shape the original 'author a wider
    candidate schema' step needs to exercise.
    """
    candidate = [*APEX_FEATURES_68, "xg_differential", "xg_attack_diff", "xg_defense_diff"]
    width = len(candidate)
    dataset = {
        "EPL": {
            "X": [np.linspace(0.0, 1.0, width, dtype=np.float64).tolist()],
            "X_incumbent": [],
            "y": [0],
            "seasons": ["2526"],
            "dates": [],
        }
    }

    report = build_promotion_feature_evidence(dataset, candidate_features=candidate)

    assert len(report["features"]) == width
    # The three new positions have nothing on the (68-wide) serving side.
    for row in report["features"][-3:]:
        assert row["serving_feature"] is None
        assert row["classification"] == "SCHEMA_MISMATCH"
        assert row["candidate_position_matches_current_serving_schema"] is False
    assert report["promotion_gate"] == "FAIL"
    assert validate_promotion_feature_evidence(report, candidate_features=candidate) is report


def test_serving_contract_falls_back_to_legacy_when_unresolvable(monkeypatch) -> None:
    """Serving's own fallback is phase7_68; the gate must describe that, not raise."""
    import src.models.promotion_evidence as pe
    from src.models.feature_registry import CANONICAL_FEATURES_68

    def _raise() -> str:
        raise pe.ActiveGenerationError("no manifest")

    monkeypatch.setattr(pe, "active_feature_schema_version", _raise)
    assert pe.current_serving_contract() == list(CANONICAL_FEATURES_68)

    monkeypatch.setattr(pe, "active_feature_schema_version", lambda: "not_a_schema")
    assert pe.current_serving_contract() == list(CANONICAL_FEATURES_68)
