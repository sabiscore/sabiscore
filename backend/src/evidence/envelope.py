"""Canonical Evidence Envelope and State Machine for SabiScore.

Directive V18.0 Section 2.1 & 2.4.
Enforces immutable raw-to-normalized evidence encapsulation, explicit temporal
distinctions, and independent evidence states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional


class EvidenceState(str, Enum):
    """Explicit orthogonal evidence states (Directive V18 Section 2.4)."""
    COMPLETE = "COMPLETE"
    ADVISORY_GAPS = "ADVISORY_GAPS"
    CRITICAL_GAPS = "CRITICAL_GAPS"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"
    UNVERIFIED = "UNVERIFIED"
    UNAVAILABLE = "UNAVAILABLE"


class ReconciliationStatus(str, Enum):
    """Reconciliation state between source observation and canonical fixture identity."""
    RECONCILED = "RECONCILED"
    UNRECONCILED = "UNRECONCILED"
    CONFLICTED = "CONFLICTED"
    QUARANTINED = "QUARANTINED"


class ProviderStatus(str, Enum):
    """Health and connection status of provider gateway."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    RATE_LIMITED = "RATE_LIMITED"


@dataclass(frozen=True)
class FieldProvenance:
    """Lineage definition for an individual extracted evidence field."""
    field_name: str
    source_value: Any
    source_id: str
    observed_at: str  # ISO-8601 UTC
    effective_at: str  # ISO-8601 UTC
    payload_hash: str
    transformation: Optional[str] = None
    is_critical: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "source_value": self.source_value,
            "source_id": self.source_id,
            "observed_at": self.observed_at,
            "effective_at": self.effective_at,
            "payload_hash": self.payload_hash,
            "transformation": self.transformation,
            "is_critical": self.is_critical,
        }


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Canonical normalized evidence object for every meaningful fixture observation.
    
    Directive V18.0 Section 2.1.
    Never collapses published_at, observed_at, retrieved_at, effective_at,
    information_cutoff, or evaluation_timestamp into a single field.
    """
    # Identifiers
    fixture_id: str
    canonical_fixture_id: str
    competition_id: str
    league_id: str
    home_team_id: str
    away_team_id: str

    # Source Provenance
    source_id: str
    source_name: str
    source_record_id: str
    source_version: str

    # Immutable Temporal Milestones (ISO-8601 UTC strings)
    retrieved_at: str
    observed_at: str
    effective_at: str
    information_cutoff: str
    evaluation_timestamp: str
    kickoff_timestamp: str

    # Hashes & Schema
    raw_payload_sha256: str
    normalized_payload_sha256: str
    schema_version: str

    # Operational & Quality States
    reconciliation_status: ReconciliationStatus
    provider_status: ProviderStatus
    freshness_seconds: float
    coverage_state: EvidenceState
    quality_state: str

    # Licensing & Governance
    license_class: str
    terms_reference: str

    # Granular Field Provenance
    field_provenance: List[FieldProvenance] = field(default_factory=list)

    def validate_temporal_integrity(self) -> bool:
        """Enforces PIT: effective_at <= information_cutoff < kickoff_timestamp."""
        eff = datetime.fromisoformat(self.effective_at.replace("Z", "+00:00"))
        cutoff = datetime.fromisoformat(self.information_cutoff.replace("Z", "+00:00"))
        kickoff = datetime.fromisoformat(self.kickoff_timestamp.replace("Z", "+00:00"))
        
        if eff > cutoff:
            return False
        if cutoff >= kickoff:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "canonical_fixture_id": self.canonical_fixture_id,
            "competition_id": self.competition_id,
            "league_id": self.league_id,
            "home_team_id": self.home_team_id,
            "away_team_id": self.away_team_id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_record_id": self.source_record_id,
            "source_version": self.source_version,
            "retrieved_at": self.retrieved_at,
            "observed_at": self.observed_at,
            "effective_at": self.effective_at,
            "information_cutoff": self.information_cutoff,
            "evaluation_timestamp": self.evaluation_timestamp,
            "kickoff_timestamp": self.kickoff_timestamp,
            "raw_payload_sha256": self.raw_payload_sha256,
            "normalized_payload_sha256": self.normalized_payload_sha256,
            "schema_version": self.schema_version,
            "reconciliation_status": self.reconciliation_status.value,
            "provider_status": self.provider_status.value,
            "freshness_seconds": self.freshness_seconds,
            "coverage_state": self.coverage_state.value,
            "quality_state": self.quality_state,
            "license_class": self.license_class,
            "terms_reference": self.terms_reference,
            "field_provenance": [fp.to_dict() for fp in self.field_provenance],
        }

    @classmethod
    def compute_sha256(cls, data: Any) -> str:
        """Compute stable SHA-256 for a payload."""
        if isinstance(data, (bytes, bytearray)):
            return hashlib.sha256(data).hexdigest()
        serialized = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()
