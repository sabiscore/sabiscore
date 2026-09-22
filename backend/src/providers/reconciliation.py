"""Canonical fixture and team identity reconciliation helpers.

Reconciliation statuses (Section 8 of the production contract):

    VERIFIED         ≥ AUTO_ACCEPT (0.94) confidence, unambiguous match.
    REQUIRES_REVIEW  ≥ REVIEW_THRESHOLD (0.68) confidence, single winner, but
                     below auto-accept. The match is plausible — a human or
                     automated review queue should confirm it before the fixture
                     is used for execution-eligible evidence. This status was
                     absent from the prior version; ambiguous-but-reviewable
                     candidates were silently collapsed into UNKNOWN, hiding
                     high-quality near-matches.
    CONFLICTING      Top two candidates within AMBIGUITY_BAND (0.03) of each
                     other. Cannot auto-resolve; both candidates compete.
    UNKNOWN          No candidate above REVIEW_THRESHOLD, or no candidates at all.

Thresholds are intentionally exposed as module-level constants so tests can
override them without monkeypatching deep internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

AUTO_ACCEPT_THRESHOLD: float = 0.94
"""Confidence at or above which a single winning candidate is auto-VERIFIED."""

REVIEW_THRESHOLD: float = 0.68
"""Confidence at or above which a single winner earns REQUIRES_REVIEW instead
of UNKNOWN. Below this the match is too weak to queue for review.
Tuned to capture common single-field abbreviations with an otherwise exact
match (e.g. "Man United" vs "Manchester United" with the away team and
kickoff matching exactly scores ~0.90 with SequenceMatcher). Multi-field
nicknames (e.g. "Spurs" for "Tottenham Hotspur") score much lower and need
alias resolution, not threshold tuning, to be captured — not yet implemented."""

AMBIGUITY_BAND: float = 0.03
"""Maximum gap between the top two candidates before the decision is CONFLICTING
rather than VERIFIED or REQUIRES_REVIEW."""

DEFAULT_KICKOFF_TOLERANCE_MINUTES: int = 90


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixtureCandidate:
    fixture_id: str
    competition: str
    home_team: str
    away_team: str
    kickoff_utc: datetime
    provider: str
    provider_event_id: str


@dataclass(frozen=True)
class ReconciliationDecision:
    status: str
    """One of: VERIFIED | REQUIRES_REVIEW | CONFLICTING | UNKNOWN"""
    confidence: float
    """Normalised score in [0, 1]. Present even for UNKNOWN to aid triage."""
    fixture_id: str | None
    """Populated only for VERIFIED. None for all other statuses."""
    reason: str
    """Machine-readable reason code for logging and alerting."""
    review_candidate_id: str | None = None
    """For REQUIRES_REVIEW: the candidate fixture_id that should be reviewed.
    The caller must not use this as a production fixture_id — it requires
    confirmation before being promoted to VERIFIED."""


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.lower().strip(), right.lower().strip()).ratio()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def reconcile_fixture(
    provider_record: FixtureCandidate,
    candidates: list[FixtureCandidate],
    *,
    kickoff_tolerance_minutes: int = DEFAULT_KICKOFF_TOLERANCE_MINUTES,
    auto_accept_threshold: float = AUTO_ACCEPT_THRESHOLD,
    review_threshold: float = REVIEW_THRESHOLD,
    ambiguity_band: float = AMBIGUITY_BAND,
) -> ReconciliationDecision:
    """Reconcile a provider record against canonical fixture candidates.

    Returns a ``ReconciliationDecision`` whose ``status`` is one of:
    VERIFIED | REQUIRES_REVIEW | CONFLICTING | UNKNOWN.

    Algorithm:
    1. Filter candidates by competition and kickoff within tolerance.
    2. Score each by team name similarity (80 %) + time proximity (20 %).
    3. Apply status logic (see module docstring).
    """
    scored: list[tuple[float, FixtureCandidate]] = []
    provider_kickoff = _aware(provider_record.kickoff_utc)

    for candidate in candidates:
        if candidate.competition != provider_record.competition:
            continue
        candidate_kickoff = _aware(candidate.kickoff_utc)
        delta_minutes = abs((candidate_kickoff - provider_kickoff).total_seconds()) / 60
        if delta_minutes > kickoff_tolerance_minutes:
            continue

        score = round(
            _similarity(provider_record.home_team, candidate.home_team) * 0.40
            + _similarity(provider_record.away_team, candidate.away_team) * 0.40
            + max(0.0, 1.0 - delta_minutes / kickoff_tolerance_minutes) * 0.20,
            4,
        )
        scored.append((score, candidate))

    scored.sort(key=lambda item: item[0], reverse=True)

    # No candidates in this competition + time window.
    if not scored:
        return ReconciliationDecision(
            status="UNKNOWN",
            confidence=0.0,
            fixture_id=None,
            reason="no_candidate",
        )

    top_score, top_candidate = scored[0]

    # Ambiguous: two candidates are too close to auto-resolve.
    if len(scored) > 1 and abs(top_score - scored[1][0]) < ambiguity_band:
        return ReconciliationDecision(
            status="CONFLICTING",
            confidence=top_score,
            fixture_id=None,
            reason="ambiguous_candidate",
        )

    # Strong enough to auto-accept.
    if top_score >= auto_accept_threshold:
        return ReconciliationDecision(
            status="VERIFIED",
            confidence=top_score,
            fixture_id=top_candidate.fixture_id,
            reason="matched_by_identity_and_kickoff",
        )

    # Plausible but not conclusive: queue for review.
    # review_candidate_id is the best guess — NOT an approved fixture_id.
    if top_score >= review_threshold:
        return ReconciliationDecision(
            status="REQUIRES_REVIEW",
            confidence=top_score,
            fixture_id=None,
            reason="below_auto_accept_threshold_but_reviewable",
            review_candidate_id=top_candidate.fixture_id,
        )

    # Below the review floor: genuinely unknown.
    return ReconciliationDecision(
        status="UNKNOWN",
        confidence=top_score,
        fixture_id=None,
        reason="below_auto_accept_threshold",
    )


# ---------------------------------------------------------------------------
# Team identity reconciliation
# ---------------------------------------------------------------------------
#
# Same status taxonomy and thresholds as fixture reconciliation, but scored on
# name similarity alone — teams carry no kickoff signal to blend in.


@dataclass(frozen=True)
class TeamCandidate:
    team_id: str
    name: str


@dataclass(frozen=True)
class TeamReconciliationDecision:
    status: str
    """One of: VERIFIED | REQUIRES_REVIEW | CONFLICTING | UNKNOWN"""
    confidence: float
    team_id: str | None
    """Populated only for VERIFIED. None for all other statuses."""
    reason: str
    review_candidate_id: str | None = None
    """For REQUIRES_REVIEW: the candidate team_id that should be reviewed.
    The caller must not use this as a resolved team_id without confirmation."""


def reconcile_team(
    provider_team_name: str,
    candidates: list[TeamCandidate],
    *,
    auto_accept_threshold: float = AUTO_ACCEPT_THRESHOLD,
    review_threshold: float = REVIEW_THRESHOLD,
    ambiguity_band: float = AMBIGUITY_BAND,
) -> TeamReconciliationDecision:
    """Reconcile a provider team name against canonical/provider team candidates.

    Returns a ``TeamReconciliationDecision`` whose ``status`` is one of:
    VERIFIED | REQUIRES_REVIEW | CONFLICTING | UNKNOWN — same semantics as
    ``reconcile_fixture`` (module docstring), applied to a single field
    (team name) instead of a blended team+kickoff score.
    """
    scored: list[tuple[float, TeamCandidate]] = [
        (round(_similarity(provider_team_name, candidate.name), 4), candidate)
        for candidate in candidates
    ]
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        return TeamReconciliationDecision(
            status="UNKNOWN",
            confidence=0.0,
            team_id=None,
            reason="no_candidate",
        )

    top_score, top_candidate = scored[0]

    if len(scored) > 1 and abs(top_score - scored[1][0]) < ambiguity_band:
        return TeamReconciliationDecision(
            status="CONFLICTING",
            confidence=top_score,
            team_id=None,
            reason="ambiguous_candidate",
        )

    if top_score >= auto_accept_threshold:
        return TeamReconciliationDecision(
            status="VERIFIED",
            confidence=top_score,
            team_id=top_candidate.team_id,
            reason="matched_by_name_similarity",
        )

    if top_score >= review_threshold:
        return TeamReconciliationDecision(
            status="REQUIRES_REVIEW",
            confidence=top_score,
            team_id=None,
            reason="below_auto_accept_threshold_but_reviewable",
            review_candidate_id=top_candidate.team_id,
        )

    return TeamReconciliationDecision(
        status="UNKNOWN",
        confidence=top_score,
        team_id=None,
        reason="below_auto_accept_threshold",
    )
