"""Is the promotion gate reachable at all? (docs/DEBT.md item 38)

WHY THIS EXISTS
---------------
``promotion_evidence._expected_gate()`` used to return PASS only when
``training_defaulted_slots``, ``serving_schema_misaligned_slots`` **and**
``always_data_gap_slots`` were all zero. ``compare_candidate_vs_incumbent.py``
computes ``promotion_permitted = all(gate == "PASS")``.

But all four ``PHASE7_FEATURES_ALWAYS_DATA_GAP`` features are present as slots
in every 68-wide schema, deliberately and permanently: ``PHASE7_FEATURES_10``'s
own comment records that removing the slots broke every artifact and produced
``model_version="fallback"`` on every inference for two months. So
``always_data_gap_slots`` was structurally 4, never 0, and the gate could never
pass — a certification-threshold conflation, not a real quality bar.

⚠️ **RESOLVED 2026-08-22, authorized.** ``always_data_gap_slots`` was removed
from the gate's blockers (and from ``certification_policy.py``'s threshold in
the same change) — a deliberate, authorized decision recorded in docs/DEBT.md
item 38, not made autonomously after seeing a failing result. The declared-gap
count still surfaces in every evidence summary; it just no longer disqualifies.

These tests now PIN the repair: if a future change makes the gate
unsatisfiable again, they fail — update item 38 in the same change rather than
deleting the tests.
"""
from __future__ import annotations

from src.models.feature_registry import (
    APEX_FEATURES_68,
    CANONICAL_FEATURES_68,
    PHASE7_FEATURES_ALWAYS_DATA_GAP,
)
from src.models.promotion_evidence import _expected_gate, _summary_from_features


def test_every_68_schema_carries_all_four_permanent_data_gap_slots() -> None:
    """The slots are deliberate and unremovable — that is the premise."""
    assert len(PHASE7_FEATURES_ALWAYS_DATA_GAP) == 4
    for schema in (CANONICAL_FEATURES_68, APEX_FEATURES_68):
        present = [f for f in PHASE7_FEATURES_ALWAYS_DATA_GAP if f in schema]
        assert present == list(PHASE7_FEATURES_ALWAYS_DATA_GAP)


def test_promotion_gate_is_satisfiable_after_the_authorized_item_38_fix() -> None:
    """A *perfect* candidate now passes even while carrying the 4 permanent
    declared-gap slots — those stop being disqualifying (docs/DEBT.md item 38,
    authorized 2026-08-22). Zero training defaults and zero misalignment are
    still required.
    """
    flawless = {
        "features": 68,
        "training_defaulted_slots": 0,
        "non_variable_training_slots": 0,
        "serving_schema_misaligned_slots": 0,
        "always_data_gap_slots": len(PHASE7_FEATURES_ALWAYS_DATA_GAP),
    }
    assert _expected_gate(flawless, training_rows=10_000) == "PASS", (
        "the availability gate became unsatisfiable again — if that was "
        "deliberate, update docs/DEBT.md item 38 in the same change"
    )


def test_the_gate_would_pass_if_declared_gaps_were_not_counted() -> None:
    """Post-fix, `always_data_gap_slots` is fully inert either way — this pins
    that explicitly (zeroed here vs. `len(...)` in the test above; both PASS),
    rather than leaving the term's irrelevance implicit.
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


# ---------------------------------------------------------------------------
# docs/DEBT.md item 49 — item 38's defect survived in a sibling counter.
# `_column_is_default_only()` marks a policy-gapped feature defaulted in every
# candidate by definition, so `training_defaulted_slots` carried a hard floor
# of 4 and the gate stayed unsatisfiable. Authorized 2026-09-03.
# ---------------------------------------------------------------------------

def _row(feature: str, *, defaulted: bool) -> dict:
    return {
        "feature": feature,
        "defaulted_training_slot": defaulted,
        "variable_in_training": not defaulted,
        "candidate_position_matches_current_serving_schema": True,
    }


def test_policy_gapped_slots_do_not_count_as_training_defaults() -> None:
    """The item 49 defect: a candidate whose ONLY defaulted slots are the four
    permanent policy gaps must read 0, not 4 — otherwise the counter can never
    reach the 0 the gate requires, for any candidate however good.
    """
    rows = [_row(f, defaulted=True) for f in PHASE7_FEATURES_ALWAYS_DATA_GAP]
    rows += [
        _row(f, defaulted=False)
        for f in APEX_FEATURES_68
        if f not in PHASE7_FEATURES_ALWAYS_DATA_GAP
    ]

    summary = _summary_from_features(rows)
    assert summary["training_defaulted_slots"] == 0, (
        "policy-gapped slots are counting as training defaults again — this is "
        "the exact hard floor docs/DEBT.md item 49 removed"
    )
    assert summary["always_data_gap_slots"] == 4, "the declared gaps must still surface"
    assert _expected_gate(summary, training_rows=10_000) == "PASS"


def test_unexpectedly_defaulted_slots_still_count() -> None:
    """The correction must not become a blanket exemption: a default on a
    feature that is *not* policy-gapped is still a real quality failure.
    """
    rows = [_row(f, defaulted=True) for f in PHASE7_FEATURES_ALWAYS_DATA_GAP]
    genuine = [f for f in APEX_FEATURES_68 if f not in PHASE7_FEATURES_ALWAYS_DATA_GAP][:3]
    rows += [_row(f, defaulted=True) for f in genuine]

    summary = _summary_from_features(rows)
    assert summary["training_defaulted_slots"] == 3
    assert _expected_gate(summary, training_rows=10_000) == "FAIL"


def test_counter_is_keyed_on_feature_name_not_a_stored_row_flag() -> None:
    """`_summary_from_features` also runs in the validator path against stored
    report rows. A report written before the `always_data_gap` key existed must
    produce the same count, or builder and validator disagree and every stored
    report fails validation. Keyed on the name, this holds by construction.
    """
    rows = [_row(f, defaulted=True) for f in PHASE7_FEATURES_ALWAYS_DATA_GAP]
    with_flag = [{**r, "always_data_gap": True} for r in rows]

    assert (
        _summary_from_features(rows)["training_defaulted_slots"]
        == _summary_from_features(with_flag)["training_defaulted_slots"]
        == 0
    )
