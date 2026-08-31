"""Frozen uncertainty-certification policy (ADR 0009).

The companion to `certification_policy.py`. That module governs whether a model
*generation* may be promoted; this one governs whether its *uncertainty* may
authorise a stake. The two gates are independent — clearing
`MODEL_GENERATION_UNCERTIFIED` does not clear `MODEL_UNCERTAINTY_UNAVAILABLE`,
and a fixture stays no-bet until both pass on their own evidence.

Same discipline as the certification policy: versioned, deep-copied on read so
a caller cannot rewrite the "frozen" policy in-process, and hashed so a report
can always be traced to the exact bar it was judged against.

⚠️ ON THRESHOLD ORDERING. Stage 7 of the certification directive forbids
inventing a threshold after seeing a result. A feasibility measurement WAS taken
before this module was written (ADR 0009 records it in full: observed
|corr(epistemic, 1-max p)| = 0.28 across base learners, 0.10 across bootstrap
members). Concealing that ordering would be worse than disclosing it, so it is
stated here. The thresholds below are set from the *principle* — a
probability-derived proxy is a deterministic function of the prediction and so
has |corr| -> 1.0 — and are deliberately NOT tightened to sit just above the
observed value. `max_abs_confidence_correlation = 0.70` fails a genuine proxy
decisively while leaving wide margin for an honest signal that happens to
correlate somewhat with confidence, which a real one legitimately may.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, Mapping, Tuple

#: Bumped only when a threshold or semantic genuinely changes, never for wording.
UNCERTAINTY_POLICY_VERSION = "1.0.0"

#: The only method authorised to satisfy the epistemic gate.
UNCERTAINTY_METHOD = "ensemble_dispersion"

#: Mathematical definition, transcribed so a reviewer never has to infer it from
#: code. `m` indexes ensemble members; `H` is Shannon entropy in nats.
UNCERTAINTY_DEFINITION: Dict[str, str] = {
    "total": "H(mean_m p_m) — predictive entropy of the ensemble mean",
    "aleatoric": "mean_m H(p_m) — average within-member entropy",
    "epistemic": "total - aleatoric — mutual information (BALD); >= 0, zero iff members agree",
    "range_nats": "[0, ln(3)] for a 3-outcome task; epistemic <= total by construction",
    "reference": "Depeweg et al. 2018; Houlsby et al. 2011",
}

#: Sources that may NEVER satisfy the epistemic gate (ADR 0009).
#:
#: Every entry is a deterministic function of the model's own final probability
#: vector, so it carries no information the prediction does not already carry.
#: A model using one would be certifying its own confidence with its own answer.
#: They remain permissible as descriptive prediction statistics.
FORBIDDEN_EPISTEMIC_SOURCES: Tuple[str, ...] = (
    "1 - max(p)",
    "entropy(p)",
    "1 - confidence",
    "expected_brier_score(p)",
    "any deterministic function of the aggregate predicted probability vector",
)

#: Where the gates below are exercised. Does not exist until M2 lands — see
#: IMPLEMENTATION_STATUS.
_VALIDATION_TEST = "tests/unit/test_uncertainty_contract.py"

#: Validation gates. Every one must pass before `MODEL_UNCERTAINTY_UNAVAILABLE`
#: may be cleared. Mirrors PROMOTION_GATES' shape: `rule` is prose for a
#: reviewer, `source` is where to verify it, `threshold` is the applied bar.
UNCERTAINTY_GATES: Dict[str, Dict[str, Any]] = {
    "method_is_authorised": {
        "rule": "uncertainty is produced by ensemble dispersion, never a probability transform",
        "source": "src/models/uncertainty_policy.py:FORBIDDEN_EPISTEMIC_SOURCES",
        "threshold": {"method": UNCERTAINTY_METHOD},
    },
    "sufficient_members": {
        "rule": (
            "dispersion is computed over at least this many members. Bootstrap or "
            "resampling variants are preferred over distinct algorithms: they vary "
            "the training sample, which is the sampling uncertainty epistemic "
            "uncertainty is meant to capture, whereas distinct algorithms vary only "
            "model class."
        ),
        "source": "src/models/uncertainty_policy.py",
        "threshold": {"min_members": 3, "preferred_members": 30},
    },
    "non_negative": {
        "rule": "epistemic >= 0 and epistemic <= total on every scored row",
        "source": "mutual information is non-negative by construction; asserted empirically",
        "threshold": {"min_epistemic": 0.0, "tolerance": 1e-9},
    },
    "determinism": {
        "rule": "identical inputs and artifacts reproduce identical uncertainty",
        "source": _VALIDATION_TEST,
        "threshold": {"max_abs_deviation": 1e-12},
    },
    "independence_from_confidence": {
        "rule": (
            "epistemic uncertainty is not a near-deterministic function of final "
            "confidence. A probability-derived proxy has |corr| -> 1.0; this bar "
            "rejects that decisively without demanding zero correlation, which an "
            "honest signal need not have."
        ),
        "source": _VALIDATION_TEST,
        "threshold": {"max_abs_confidence_correlation": 0.70},
    },
    "informative_within_confidence_band": {
        "rule": (
            "within a narrow band of near-identical predicted confidence, epistemic "
            "uncertainty still varies materially. This is the decisive independence "
            "check: any 1-confidence proxy is constant across such a band by "
            "construction, so a proxy scores 1.0x and cannot pass."
        ),
        "source": _VALIDATION_TEST,
        "threshold": {"min_spread_ratio": 2.0, "band_width": 0.02, "min_band_rows": 30},
    },
    "error_association": {
        "rule": (
            "bucketing scored predictions by epistemic uncertainty separates realised "
            "error: the highest-uncertainty bucket must show strictly worse RPS than "
            "the lowest. Deliberately not a monotonicity requirement across all "
            "buckets — the statistical setup does not justify one at these sample sizes."
        ),
        "source": _VALIDATION_TEST,
        "threshold": {"buckets": 4, "min_rps_gap_top_vs_bottom": 0.0, "strict": True},
    },
}

#: Evidence floors for uncertainty validation, mirroring EVIDENCE_FLOORS.
UNCERTAINTY_EVIDENCE_FLOORS: Dict[str, Any] = {
    "min_validation_rows": 200,
    "min_rows_per_error_bucket": 30,
    "rationale": (
        "Below these counts the error-association result is noise. 200 is the "
        "smallest holdout among the six league artifacts, so the floor is set by "
        "what the corpus can actually supply rather than by an aspiration."
    ),
}

#: Availability semantics. `available=true` is permitted ONLY when the certified
#: computation actually succeeded — never as a default, never as a fallback.
AVAILABILITY_SEMANTICS: Dict[str, str] = {
    "available_true": "the certified ensemble-dispersion computation ran and returned finite values",
    "available_false": (
        "anything else — missing members, non-finite output, feature-schema "
        "mismatch, or an unauthorised method. Emits MODEL_UNCERTAINTY_UNAVAILABLE "
        "and the fixture stays no-bet."
    ),
    "no_fallback": (
        "there is no degraded or proxy value. A probability-derived substitute is "
        "forbidden by FORBIDDEN_EPISTEMIC_SOURCES, so absence is the only honest "
        "alternative to a real measurement."
    ),
}

#: Promotion requires every gate above, exactly like the certification policy.
UNCERTAINTY_REQUIRES_ALL_GATES = True

#: ⚠️ Implementation status, stated plainly so this module is never mistaken for
#: a passing result. This is a SPECIFICATION written before the implementation,
#: which is the required order — thresholds declared after seeing a result are
#: exactly what the certification directive forbids.
#:
#: The gates above are DECLARED but NOT YET EXERCISED. `test_uncertainty_contract.py`
#: (cited as several gates' `source`) does not exist until the M2 implementation
#: lands, and `MODEL_UNCERTAINTY_UNAVAILABLE` therefore remains CRITICAL and
#: fail-closed. A feasibility measurement recorded in ADR 0009 shows the method
#: CAN satisfy these bars on the current artifacts; that is not the same as
#: having satisfied them.
IMPLEMENTATION_STATUS: Dict[str, Any] = {
    "state": "SPECIFIED_NOT_IMPLEMENTED",
    "gates_exercised": False,
    "gate_remains_closed": "MODEL_UNCERTAINTY_UNAVAILABLE",
    "blocking_milestone": "M2 — independent uncertainty implementation and validation",
    "feasibility_evidence": "docs/adr/0009-uncertainty-certification-and-epistemic-independence.md",
}


def uncertainty_policy() -> Dict[str, Any]:
    """The full frozen policy, as one serialisable mapping.

    Deep-copied for the same reason `certification_policy()` deep-copies: handing
    back the module dicts by reference would let any caller silently rewrite the
    policy in-process, and since `uncertainty_policy_sha256()` hashes those same
    objects, the digest would move with the mutation and report the tampered
    policy as authentic.
    """
    return copy.deepcopy(
        {
            "policy_version": UNCERTAINTY_POLICY_VERSION,
            "method": UNCERTAINTY_METHOD,
            "definition": UNCERTAINTY_DEFINITION,
            "forbidden_epistemic_sources": list(FORBIDDEN_EPISTEMIC_SOURCES),
            "requires_all_gates": UNCERTAINTY_REQUIRES_ALL_GATES,
            "gates": UNCERTAINTY_GATES,
            "evidence_floors": UNCERTAINTY_EVIDENCE_FLOORS,
            "availability_semantics": AVAILABILITY_SEMANTICS,
            "implementation_status": IMPLEMENTATION_STATUS,
        }
    )


def uncertainty_policy_sha256(policy: Mapping[str, Any] | None = None) -> str:
    """Stable digest of the policy, for citation in a certification manifest.

    Same normalisation as `certification_policy.policy_sha256()` and
    `feature_registry.contract_sha256()`, so the digest tracks content and not
    formatting.
    """
    payload = json.dumps(
        dict(policy or uncertainty_policy()),
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
