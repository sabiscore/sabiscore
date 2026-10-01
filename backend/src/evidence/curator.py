"""Offline Evidence Curation and Provenance Precedence Engine.

Directive V18.0 Section 7.
Enforces:
    - Precedence graph: Primary Structured -> Corroborating Structured ->
      Verified Secondary -> Derived Metric -> LLM Extracted Claim -> Human Review.
    - Zero fabrication: Contradictions transition to CONFLICTED, never averaged or guessed.
    - Structured lineage for LLM-extracted claims (offline queue only, prohibited from
      silently becoming production numeric features).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

from .envelope import EvidenceState


class PrecedenceTier(IntEnum):
    """Precedence hierarchy for evidence sources (Directive V18 Section 7.3)."""
    PRIMARY_STRUCTURED = 1
    CORROBORATING_STRUCTURED = 2
    VERIFIED_SECONDARY = 3
    DERIVED_METRIC = 4
    LLM_EXTRACTED_CLAIM = 5
    HUMAN_REVIEW = 6


@dataclass(frozen=True)
class LLMExtractedClaim:
    """Offline LLM-extracted claim metadata (Directive V18 Section 7.2).
    
    Must retain complete provenance. Prohibited from silently becoming
    a production numeric feature.
    """
    source: str
    source_url_or_id: str
    published_at: str  # ISO-8601 UTC
    retrieved_at: str  # ISO-8601 UTC
    claim: str
    evidence_span_or_reference: str
    model_name: str
    prompt_version: str
    extraction_version: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "source_url_or_id": self.source_url_or_id,
            "published_at": self.published_at,
            "retrieved_at": self.retrieved_at,
            "claim": self.claim,
            "evidence_span_or_reference": self.evidence_span_or_reference,
            "model_name": self.model_name,
            "prompt_version": self.prompt_version,
            "extraction_version": self.extraction_version,
            "is_production_numeric_feature": False,  # Explicit contract: Never a production numeric feature
        }


@dataclass
class SourceObservation:
    source_id: str
    tier: PrecedenceTier
    observed_value: Any
    observed_at: datetime
    effective_at: datetime
    confidence_weight: float = 1.0


class EvidenceReconciliationError(ValueError):
    """Raised when evidence cannot be reconciled deterministically."""


class EvidenceCurator:
    """Coordinates offline evidence discovery, reconciliation, and contradiction handling."""

    @staticmethod
    def reconcile_field(
        field_name: str,
        observations: List[SourceObservation],
        tolerance: float = 0.0,
    ) -> Tuple[Any, EvidenceState, Optional[str]]:
        """Reconcile multiple source observations for a single field.
        
        Rules (Directive V18 Section 7.4):
        1. If no observations exist -> UNAVAILABLE.
        2. If one observation exists -> COMPLETE (or ADVISORY depending on tier).
        3. If multiple observations exist and agree -> COMPLETE.
        4. If multiple observations from same tier disagree -> CONFLICTED.
           Never average, never guess, never select convenient value.
        5. If observations from different tiers disagree, higher precedence takes precedence
           ONLY if corroboration passes; otherwise flagged as CONFLICTED.
        """
        if not observations:
            return None, EvidenceState.UNAVAILABLE, f"No observations for '{field_name}'"

        if len(observations) == 1:
            obs = observations[0]
            state = (
                EvidenceState.COMPLETE
                if obs.tier <= PrecedenceTier.CORROBORATING_STRUCTURED
                else EvidenceState.ADVISORY_GAPS
            )
            return obs.observed_value, state, None

        # Sort by precedence tier (lower number = higher priority), then by recency
        sorted_obs = sorted(observations, key=lambda x: (x.tier, -x.effective_at.timestamp()))
        primary = sorted_obs[0]
        secondary = sorted_obs[1]

        # Check for disagreement
        val1 = primary.observed_value
        val2 = secondary.observed_value

        if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
            diff = abs(val1 - val2)
            if diff <= tolerance:
                # Numerical agreement within tolerance
                return val1, EvidenceState.COMPLETE, None
        elif val1 == val2:
            return val1, EvidenceState.COMPLETE, None

        # Conflicting observations!
        if primary.tier == secondary.tier:
            # Same tier disagreement -> Strictly CONFLICTED. Never average!
            reason = (
                f"Contradiction between equal-tier sources for '{field_name}': "
                f"'{primary.source_id}' ({val1}) vs '{secondary.source_id}' ({val2})"
            )
            return None, EvidenceState.CONFLICTED, reason

        # Different tiers: If higher precedence is primary, but secondary strongly conflicts
        reason = (
            f"Precedence discrepancy for '{field_name}': "
            f"Tier {primary.tier.name} '{primary.source_id}' ({val1}) disagrees with "
            f"Tier {secondary.tier.name} '{secondary.source_id}' ({val2})"
        )
        return None, EvidenceState.CONFLICTED, reason
