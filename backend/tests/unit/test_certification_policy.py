"""The frozen certification policy must not drift from the code that applies it.

A policy artifact nobody checks is worse than none: it reads as a guarantee
while enforcing nothing — the same asymmetry docs/DEBT.md item 36 recorded for
`feature_schema_version`. These tests keep `certification_policy.py` and the
real gate code in agreement, so changing one without the other fails the suite.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.models.certification_policy import (
    CERTIFICATION_POLICY_VERSION,
    EVIDENCE_FLOORS,
    PROMOTION_GATES,
    certification_policy,
    policy_sha256,
)

#: The gate keys `compare_candidate_vs_incumbent.py` emits.
EMITTED_GATE_KEYS = {
    "valid_probability_simplex",
    "input_responsiveness",
    "coherent_price_perturbation",
    "serving_feature_availability",
    "primary_metric_improvement",
    "no_league_regression",
    "market_baseline",
}


def test_policy_covers_exactly_the_emitted_gates() -> None:
    """No gate applied without a policy entry, and none declared without a gate."""
    assert set(PROMOTION_GATES) == EMITTED_GATE_KEYS


def test_policy_gate_keys_match_the_live_comparison_report() -> None:
    """Cross-check against the committed report, not just the constant above.

    If a future run emits a new gate this catches it even when
    EMITTED_GATE_KEYS was updated carelessly — the report is produced by the
    real script, so it is the more authoritative of the two.
    """
    report_path = (
        Path(__file__).resolve().parents[2]
        / "models" / "candidate" / "comparison_report.json"
    )
    if not report_path.exists():  # pragma: no cover - candidate is optional
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert set(report.get("gates", {})) == set(PROMOTION_GATES)


def test_every_gate_cites_where_it_is_applied() -> None:
    """A threshold with no source cannot be verified, only believed."""
    for name, gate in PROMOTION_GATES.items():
        assert gate.get("rule"), name
        assert gate.get("source"), name
        assert ".py" in gate["source"], name


def test_serving_availability_threshold_matches_the_gate_function() -> None:
    """Transcription accuracy for the one gate with real numeric terms.

    Meeting exactly the declared slot-count terms (plus non-empty training)
    must PASS, and breaching any one of them must FAIL — proving the policy's
    numbers describe `_expected_gate`'s actual behaviour rather than an
    aspiration about it.
    """
    from src.models.promotion_evidence import _expected_gate

    threshold = PROMOTION_GATES["serving_feature_availability"]["threshold"]
    blockers = [key for key in threshold if key.endswith("_slots")]
    assert blockers, "fixture assumption: the gate has slot-count terms"

    at_threshold = {"features": 68, "non_variable_training_slots": 0}
    at_threshold.update({key: threshold[key] for key in blockers})
    min_rows = threshold["min_training_rows"]
    assert _expected_gate(at_threshold, training_rows=min_rows) == "PASS"

    for blocker in blockers:
        breached = dict(at_threshold)
        breached[blocker] = threshold[blocker] + 1
        assert _expected_gate(breached, training_rows=min_rows) == "FAIL", blocker


def test_evidence_floors_match_their_declared_sources() -> None:
    """The CLV floor is read from the real constant, not a remembered number."""
    from src.services.clv_service import _MIN_CLV_SAMPLE_SIZE

    assert EVIDENCE_FLOORS["clv_summary"]["min_records"] == _MIN_CLV_SAMPLE_SIZE


def test_policy_hash_is_stable_and_content_sensitive() -> None:
    """The certification manifest cites this digest, so it must track content."""
    assert policy_sha256() == policy_sha256(certification_policy())

    mutated = certification_policy()
    mutated["promotion_gates"]["market_baseline"]["threshold"] = {
        "leagues_beating_market": 1
    }
    assert policy_sha256(mutated) != policy_sha256()


def test_policy_version_is_declared() -> None:
    assert CERTIFICATION_POLICY_VERSION.count(".") == 2
    policy = certification_policy()
    assert policy["policy_version"] == CERTIFICATION_POLICY_VERSION
    assert policy["promotion_requires_all_gates"] is True
