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
