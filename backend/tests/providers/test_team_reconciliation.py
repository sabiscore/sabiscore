"""Tests for reconcile_team() (canonical team identity reconciliation).

Run:
    cd backend
    python -m pytest tests/providers/test_team_reconciliation.py -q --no-cov
"""

from __future__ import annotations

from src.providers.reconciliation import (
    AUTO_ACCEPT_THRESHOLD,
    REVIEW_THRESHOLD,
    TeamCandidate,
    reconcile_team,
)


def test_verified_on_exact_name_match():
    decision = reconcile_team("Arsenal", [TeamCandidate(team_id="57", name="Arsenal")])
    assert decision.status == "VERIFIED"
    assert decision.team_id == "57"
    assert decision.confidence >= AUTO_ACCEPT_THRESHOLD


def test_unknown_on_no_candidates():
    decision = reconcile_team("Arsenal", [])
    assert decision.status == "UNKNOWN"
    assert decision.team_id is None
    assert decision.confidence == 0.0


def test_unknown_on_dissimilar_name():
    decision = reconcile_team("Arsenal", [TeamCandidate(team_id="1", name="Watford")])
    assert decision.status == "UNKNOWN"
    assert decision.team_id is None


def test_requires_review_on_partial_match():
    """A common abbreviation lands in REQUIRES_REVIEW, not auto-VERIFIED or UNKNOWN."""
    decision = reconcile_team(
        "Man United", [TeamCandidate(team_id="33", name="Manchester United")]
    )
    assert decision.status == "REQUIRES_REVIEW"
    assert decision.team_id is None, "REQUIRES_REVIEW must not set team_id"
    assert decision.review_candidate_id == "33"
    assert REVIEW_THRESHOLD <= decision.confidence < AUTO_ACCEPT_THRESHOLD


def test_conflicting_on_ambiguous_candidates():
    """Two distinct candidates tied within AMBIGUITY_BAND → CONFLICTING, no team_id."""
    decision = reconcile_team(
        "Newcastle United",
        [
            TeamCandidate(team_id="1", name="Newcastle Rovers"),
            TeamCandidate(team_id="2", name="Newcastle Albion"),
        ],
    )
    assert decision.status == "CONFLICTING"
    assert decision.team_id is None
    assert decision.review_candidate_id is None
