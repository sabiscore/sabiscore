"""Frozen certification policy (APEX directive section 9).

WHY THIS EXISTS
---------------
Section 9 requires certification thresholds to exist as an authoritative,
versioned, hashed artifact *before* candidate results are reviewed, and for the
certification manifest to cite the policy's version and hash.

Until now the thresholds existed only as inline expressions inside
``scripts/compare_candidate_vs_incumbent.py`` and
``promotion_evidence._expected_gate()``. Code is a fine place to *apply* a
threshold and a poor place to *freeze* one: nothing recorded which version was
in force when a given report was produced, and a one-character edit changed the
bar with no visible trace.

⚠️ **THIS FILE TRANSCRIBES; IT DOES NOT CHOOSE.**
Every threshold here already existed in code before the current candidate was
evaluated (the gate logic dates to 89c1254, 2026-08-10, and f985946,
2026-08-17; the live comparison report was produced against it). Writing them
down is documentation. **Adding or relaxing one after seeing a result is what
section 23 forbids** — if a threshold needs to change, that is a deliberate,
authorized decision recorded in docs/DEBT.md, not an edit made here in passing.

``test_certification_policy.py`` asserts this file and the gate code agree, so
the two cannot drift: change one without the other and the suite fails.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, Mapping

#: Bumped only when a threshold genuinely changes, never for wording. The
#: certification manifest cites this together with POLICY_SHA256 so a report can
#: always be traced to the exact bar it was judged against.
#: 1.0.0 -> 1.1.0 (2026-08-22): docs/DEBT.md item 38, authorized — removed
#: always_data_gap_slots from serving_feature_availability's threshold. See
#: that gate's entry below for the full rationale.
CERTIFICATION_POLICY_VERSION = "1.1.0"

#: Every gate `compare_candidate_vs_incumbent.py` emits, with the rule as
#: applied and the code that applies it. `rule` is prose for a reviewer;
#: `source` is where to verify it. Keys must match the emitted gate keys
#: exactly — pinned by test_certification_policy.py.
PROMOTION_GATES: Dict[str, Dict[str, Any]] = {
    "valid_probability_simplex": {
        "rule": "every candidate holdout probability row is a valid simplex",
        "source": "scripts/compare_candidate_vs_incumbent.py:evaluate()",
        "threshold": None,
    },
    "input_responsiveness": {
        "rule": "every league's candidate responds to >0 of its input features",
        "source": "scripts/compare_candidate_vs_incumbent.py:_served_sensitivity()",
        "threshold": {"min_responsive_features_per_league": 1},
    },
    "coherent_price_perturbation": {
        "rule": (
            "flipping the market favourite moves candidate probabilities in the "
            "correct direction, in every league"
        ),
        "source": "scripts/compare_candidate_vs_incumbent.py:_coherent_price_perturbation()",
        "threshold": {"directionally_coherent": True},
    },
    "serving_feature_availability": {
        "rule": (
            "no silently-defaulted training slot, no positional train/serve "
            "schema mismatch, and a non-empty training set"
        ),
        "source": "src/models/promotion_evidence.py:_expected_gate()",
        "threshold": {
            "training_defaulted_slots": 0,
            "serving_schema_misaligned_slots": 0,
            "min_training_rows": 1,
        },
        # docs/DEBT.md item 38, RESOLVED 2026-08-22 (authorized): this gate
        # used to also require always_data_gap_slots == 0, which made it
        # unsatisfiable for any 68-wide candidate — all four
        # PHASE7_FEATURES_ALWAYS_DATA_GAP features are permanent, declared
        # slots in every 68 schema (removing them broke every artifact and
        # served model_version="fallback" for two months). The term was
        # authorized-removed as a blocker; the count of 4 still surfaces in
        # every evidence summary and rendered report, it just no longer
        # disqualifies. This does not relax any real quality bar — the
        # candidate this was checked against still independently fails
        # no_league_regression and market_baseline (docs/DEBT.md item 38).
    },
    "primary_metric_improvement": {
        "rule": "mean RPS improvement over the incumbent is strictly positive",
        "source": "scripts/compare_candidate_vs_incumbent.py",
        "threshold": {"min_mean_rps_improvement": 0.0, "strict": True},
    },
    "no_league_regression": {
        "rule": "the candidate wins on RPS in every league compared, not a majority",
        "source": "scripts/compare_candidate_vs_incumbent.py",
        "threshold": {"required_league_wins": "all"},
    },
    "market_baseline": {
        "rule": "the candidate beats the market-implied RPS baseline in every league",
        "source": "scripts/compare_candidate_vs_incumbent.py",
        "threshold": {"leagues_beating_market": "all"},
    },
}

#: Promotion requires every gate above. Transcribed from
#: `promotion_permitted = all(gate["status"] == "PASS" for ...)`.
PROMOTION_REQUIRES_ALL_GATES = True

#: Evidence floors enforced elsewhere, recorded so a certification manifest can
#: cite one policy rather than three scattered constants.
EVIDENCE_FLOORS: Dict[str, Dict[str, Any]] = {
    "clv_summary": {
        "min_records": 10,
        "source": "src/services/clv_service.py:_MIN_CLV_SAMPLE_SIZE",
    },
    "walk_forward_validation": {
        "min_records": 10,
        "source": "src/models/model_registry.py:walk_forward_validate()",
    },
    "brier_decomposition": {
        "min_records": 10,
        "source": "src/models/evaluation/metrics.py:brier_score_decomposition()",
    },
    "training_split": {
        "min_holdout_rows": 50,
        "min_pre_holdout_rows": 200,
        "min_calibration_rows": 50,
        "min_core_train_rows": 300,
        "source": "scripts/train_on_real_matches.py:train_league()",
    },
}


def certification_policy() -> Dict[str, Any]:
    """The full frozen policy, as one serialisable mapping.

    Deep-copied. Returning the module dicts by reference would let any caller
    silently rewrite the policy in-process — and since `policy_sha256()` hashes
    the same objects, the digest would move with the mutation and report the
    tampered policy as authentic. "Frozen" has to mean the caller cannot edit
    it, not merely that nobody has.
    """
    return copy.deepcopy(
        {
            "policy_version": CERTIFICATION_POLICY_VERSION,
            "promotion_requires_all_gates": PROMOTION_REQUIRES_ALL_GATES,
            "promotion_gates": PROMOTION_GATES,
            "evidence_floors": EVIDENCE_FLOORS,
        }
    )


def policy_sha256(policy: Mapping[str, Any] | None = None) -> str:
    """Stable digest of the policy, for citation in a certification manifest.

    Sorted and separator-normalised so the digest tracks policy *content*, not
    formatting — the same convention `feature_registry.contract_sha256()` uses.
    """
    payload = json.dumps(
        dict(policy or certification_policy()),
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
