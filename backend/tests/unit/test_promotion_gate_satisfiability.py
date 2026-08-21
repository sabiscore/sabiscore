"""Is the promotion gate reachable at all? (docs/DEBT.md item 38)

WHY THIS EXISTS
---------------
``promotion_evidence._expected_gate()`` returns PASS only when
``training_defaulted_slots``, ``serving_schema_misaligned_slots`` **and**
``always_data_gap_slots`` are all zero. ``compare_candidate_vs_incumbent.py``
then computes ``promotion_permitted = all(gate == "PASS")``.

But all four ``PHASE7_FEATURES_ALWAYS_DATA_GAP`` features are present as slots
in every 68-wide schema, deliberately and permanently: ``PHASE7_FEATURES_10``'s
own comment records that removing the slots broke every artifact and produced
``model_version="fallback"`` on every inference for two months. So
``always_data_gap_slots`` is structurally 4, never 0, and the gate cannot pass.

⚠️ **These tests PIN the current behaviour; they do not endorse it.** Relaxing
the gate is a certification-threshold change made after seeing a failing
result, which the APEX directive §23 forbids doing autonomously. The decision
is recorded in docs/DEBT.md item 38 and left to a deliberate, separate one.

If a future change makes the gate satisfiable, these tests fail — which is the
intent. Update item 38 in the same change rather than deleting the tests.
"""
from __future__ import annotations

from src.models.feature_registry import (
    APEX_FEATURES_68,
    CANONICAL_FEATURES_68,
    PHASE7_FEATURES_ALWAYS_DATA_GAP,
)
from src.models.promotion_evidence import _expected_gate


def test_every_68_schema_carries_all_four_permanent_data_gap_slots() -> None:
    """The slots are deliberate and unremovable — that is the premise."""
    assert len(PHASE7_FEATURES_ALWAYS_DATA_GAP) == 4
    for schema in (CANONICAL_FEATURES_68, APEX_FEATURES_68):
        present = [f for f in PHASE7_FEATURES_ALWAYS_DATA_GAP if f in schema]
        assert present == list(PHASE7_FEATURES_ALWAYS_DATA_GAP)


def test_promotion_gate_is_currently_unsatisfiable_for_any_68_wide_candidate() -> None:
    """Even a *perfect* candidate fails: zero defaults, zero misalignment.

    This is the whole finding. The only remaining non-zero counter is the one
    that cannot be driven to zero without deleting slots the artifacts require.
    """
    flawless = {
        "features": 68,
        "training_defaulted_slots": 0,
        "non_variable_training_slots": 0,
        "serving_schema_misaligned_slots": 0,
        "always_data_gap_slots": len(PHASE7_FEATURES_ALWAYS_DATA_GAP),
    }
    assert _expected_gate(flawless, training_rows=10_000) == "FAIL", (
        "the availability gate became satisfiable — if that was deliberate, "
        "update docs/DEBT.md item 38 in the same change"
    )


def test_the_gate_would_pass_if_declared_gaps_were_not_counted() -> None:
    """Isolates the cause to exactly one counter, so the fix is unambiguous.

    Same flawless candidate, only `always_data_gap_slots` zeroed -> PASS. That
    localises the deadlock to the declared-gap term and nothing else, which is
    what makes item 38's proposed fix a one-line decision rather than a
    re-audit of the whole gate.
    """
    flawless_without_declared_gaps = {
        "features": 68,
        "training_defaulted_slots": 0,
        "non_variable_training_slots": 0,
        "serving_schema_misaligned_slots": 0,
        "always_data_gap_slots": 0,
    }
    assert _expected_gate(flawless_without_declared_gaps, training_rows=10_000) == "PASS"


def test_genuinely_disqualifying_counters_still_block() -> None:
    """Guards against an over-broad future relaxation.

    Silent training defaults and real train/serve positional disagreement must
    keep failing whatever happens to the declared-gap term.
    """
    for blocker in ("training_defaulted_slots", "serving_schema_misaligned_slots"):
        summary = {
            "features": 68,
            "training_defaulted_slots": 0,
            "non_variable_training_slots": 0,
            "serving_schema_misaligned_slots": 0,
            "always_data_gap_slots": 0,
            blocker: 1,
        }
        assert _expected_gate(summary, training_rows=10_000) == "FAIL", blocker

    assert _expected_gate(
        {
            "features": 68,
            "training_defaulted_slots": 0,
            "non_variable_training_slots": 0,
            "serving_schema_misaligned_slots": 0,
            "always_data_gap_slots": 0,
        },
        training_rows=0,
    ) == "FAIL", "a candidate trained on zero rows must never pass"
