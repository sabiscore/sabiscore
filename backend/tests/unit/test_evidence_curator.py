"""Unit tests for EvidenceCurator and Precedence Hierarchy.

Directive V18.0 Section 7 & Gate E.
"""

from datetime import datetime, timezone
import pytest

from src.evidence.curator import (
    EvidenceCurator,
    LLMExtractedClaim,
    PrecedenceTier,
    SourceObservation,
)
from src.evidence.envelope import EvidenceState


def test_reconciliation_identical_observations_complete():
    """Identical observations from primary sources reconcile to COMPLETE."""
    t = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    obs = [
        SourceObservation("football-data", PrecedenceTier.PRIMARY_STRUCTURED, 3, t, t),
        SourceObservation("api-football", PrecedenceTier.CORROBORATING_STRUCTURED, 3, t, t),
    ]
    val, state, reason = EvidenceCurator.reconcile_field("home_wins_last5", obs)
    assert val == 3
    assert state == EvidenceState.COMPLETE
    assert reason is None


def test_contradiction_between_equal_tiers_transitions_to_conflicted_never_averages():
    """Conflicting observations from equal tiers must NOT average or guess; must be CONFLICTED."""
    t = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    obs = [
        SourceObservation("football-data", PrecedenceTier.PRIMARY_STRUCTURED, 2.5, t, t),
        SourceObservation("sportmonks", PrecedenceTier.PRIMARY_STRUCTURED, 1.8, t, t),
    ]
    val, state, reason = EvidenceCurator.reconcile_field("home_goals_avg", obs)
    
    # Must fail closed: val is None, state is CONFLICTED
    assert val is None
    assert state == EvidenceState.CONFLICTED
    assert "Contradiction between equal-tier sources" in (reason or "")
    # Verify it did not average to (2.5 + 1.8) / 2 = 2.15
    assert val != 2.15


def test_llm_extracted_claim_retains_provenance_and_cannot_be_numeric_feature():
    """LLM claims must strictly retain source provenance and are barred from production numeric features."""
    claim = LLMExtractedClaim(
        source="BBC Sport News",
        source_url_or_id="https://bbc.com/sport/football/123",
        published_at="2026-10-05T10:00:00Z",
        retrieved_at="2026-10-05T10:15:00Z",
        claim="Star striker ruled out due to hamstring strain",
        evidence_span_or_reference="confirmed out for 3 weeks by manager in press conference",
        model_name="qwen-2.5-coder",
        prompt_version="v2.1_injury_extractor",
        extraction_version="1.0.0",
    )
    
    as_dict = claim.to_dict()
    assert as_dict["source"] == "BBC Sport News"
    assert as_dict["is_production_numeric_feature"] is False
    assert "Star striker ruled out" in as_dict["claim"]
