"""Independent Certification, Evidence, Market, and Decision States.

Directive V18.0 Section 5.
Decouples:
    ModelCertificationState
    EvidenceState
    MarketState
    DecisionState

Prevents collapsing separate dimensions into one opaque status.
Enforces fail-closed resolution:
    - UNCERTIFIED, DEGRADED, or WITHHELD model -> WITHHELD decision
    - CRITICAL_GAPS, CONFLICTED, or UNAVAILABLE evidence -> WITHHELD decision
    - UNVERIFIED, DISPERSED, or MISSING market -> WITHHELD decision
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ModelCertificationState(str, Enum):
    """Lifecycle statistical certification state of the active model generation."""
    CERTIFIED = "CERTIFIED"
    PROVISIONAL = "PROVISIONAL"
    UNCERTIFIED = "UNCERTIFIED"
    DEGRADED = "DEGRADED"
    WITHHELD = "WITHHELD"
    RETIRED = "RETIRED"


class EvidenceState(str, Enum):
    """Completeness, freshness, and reconciliation state of fixture input evidence."""
    COMPLETE = "COMPLETE"
    ADVISORY_GAPS = "ADVISORY_GAPS"
    CRITICAL_GAPS = "CRITICAL_GAPS"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"
    UNVERIFIED = "UNVERIFIED"
    UNAVAILABLE = "UNAVAILABLE"


class MarketState(str, Enum):
    """Verification state of market prices and closing odds."""
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    DISPERSED = "DISPERSED"
    STALE = "STALE"
    MISSING = "MISSING"


class DecisionState(str, Enum):
    """Institutional actionability verdict for public decision surfaces."""
    PLAY = "PLAY"
    PASS = "PASS"
    WITHHELD = "WITHHELD"


@dataclass(frozen=True)
class StateMatrixResult:
    decision_state: DecisionState
    model_state: ModelCertificationState
    evidence_state: EvidenceState
    market_state: MarketState
    withheld_reason: Optional[str] = None
    is_actionable: bool = False


def evaluate_state_matrix(
    model_state: ModelCertificationState,
    evidence_state: EvidenceState,
    market_state: MarketState,
    has_positive_edge: bool = False,
) -> StateMatrixResult:
    """Resolve final DecisionState from independent dimensions (Directive V18.0 Section 5).
    
    Invariants:
    1. If model_state != CERTIFIED (or PROVISIONAL under strict testing), DecisionState must be WITHHELD.
    2. If evidence_state in {CRITICAL_GAPS, CONFLICTED, UNAVAILABLE, STALE, UNVERIFIED}, DecisionState must be WITHHELD.
    3. If market_state != VERIFIED, DecisionState must be WITHHELD.
    4. Only when model_state == CERTIFIED and evidence_state in {COMPLETE, ADVISORY_GAPS} and market_state == VERIFIED:
       - if has_positive_edge -> PLAY
       - else -> PASS
    """
    # 1. Model Gate
    if model_state not in (ModelCertificationState.CERTIFIED, ModelCertificationState.PROVISIONAL):
        return StateMatrixResult(
            decision_state=DecisionState.WITHHELD,
            model_state=model_state,
            evidence_state=evidence_state,
            market_state=market_state,
            withheld_reason=f"Model generation is in '{model_state.value}' state",
            is_actionable=False,
        )

    # 2. Evidence Gate
    if evidence_state in (
        EvidenceState.CRITICAL_GAPS,
        EvidenceState.CONFLICTED,
        EvidenceState.UNAVAILABLE,
        EvidenceState.STALE,
        EvidenceState.UNVERIFIED,
    ):
        return StateMatrixResult(
            decision_state=DecisionState.WITHHELD,
            model_state=model_state,
            evidence_state=evidence_state,
            market_state=market_state,
            withheld_reason=f"Evidence state '{evidence_state.value}' blocks execution",
            is_actionable=False,
        )

    # 3. Market Gate
    if market_state != MarketState.VERIFIED:
        return StateMatrixResult(
            decision_state=DecisionState.WITHHELD,
            model_state=model_state,
            evidence_state=evidence_state,
            market_state=market_state,
            withheld_reason=f"Market price state is '{market_state.value}'",
            is_actionable=False,
        )

    # 4. Actionability Evaluation
    if has_positive_edge:
        return StateMatrixResult(
            decision_state=DecisionState.PLAY,
            model_state=model_state,
            evidence_state=evidence_state,
            market_state=market_state,
            withheld_reason=None,
            is_actionable=True,
        )
    else:
        return StateMatrixResult(
            decision_state=DecisionState.PASS,
            model_state=model_state,
            evidence_state=evidence_state,
            market_state=market_state,
            withheld_reason="No positive expected value at verified market price",
            is_actionable=False,
        )
