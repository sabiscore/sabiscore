"""Build a deterministic, read-only repair manifest for historical identity drift.

This module does not mutate ``matches`` or Elo state. It strengthens the existing
semantic identity audit by proving that every affected historical match has enough
source-backed evidence to be repaired safely:

* the original committed football-data.co.uk row exists;
* source league/date/result agree with the persisted match;
* both source team names resolve under today's production ``TeamIndex`` or a
  source-bound deterministic same-league Team creation is explicitly proposed;
* resolution is scoped to the persisted match league;
* the two target team ids are distinct.

Every row carries its own source-evidence SHA-256, explicit repair disposition,
and replay requirement. The resulting manifest is canonicalized and SHA-256
hashed so an eventual Class-C mutation can require the exact reviewed evidence
set rather than re-discovering targets at apply time.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Match, Team
from .historical_backfill_service import TeamIndex, _historical_team_id
from .historical_identity_audit_service import (
    HistoricalSourceIdentity,
    audit_historical_semantic_identity,
    build_historical_source_index,
)


_MANIFEST_SCHEMA_VERSION = 3


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _source_evidence_hash(source: HistoricalSourceIdentity | None) -> str | None:
    """Hash only immutable upstream evidence for one deterministic source row."""
    if source is None:
        return None
    return _canonical_sha256(
        {
            "match_id": source.match_id,
            "league_id": source.league_id,
            "match_date": source.match_date,
            "home_team": source.home_team,
            "away_team": source.away_team,
            "home_score": source.home_score,
            "away_score": source.away_score,
            "source_file": source.source_file,
        }
    )


def _repair_reason(*, home_mismatch: bool, away_mismatch: bool) -> str:
    if home_mismatch and away_mismatch:
        return "home_and_away_cross_league_identity"
    if home_mismatch:
        return "home_cross_league_identity"
    if away_mismatch:
        return "away_cross_league_identity"
    return "historical_identity_invariant_violation"


@dataclass(frozen=True)
class ProposedTeamCreation:
    """A deterministic Team row required by one or more source-backed repairs."""

    team_id: str
    team_name: str
    league_id: str
    participant_references: int
    source_fixture_ids: tuple[str, ...]
    source_evidence_sha256s: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["source_fixture_ids"] = list(self.source_fixture_ids)
        payload["source_evidence_sha256s"] = list(self.source_evidence_sha256s)
        return payload


@dataclass(frozen=True)
class SemanticIdentityRepairEntry:
    match_id: str
    match_league: str
    match_date: str
    stored_home_team_id: str
    stored_home_team_name: str | None
    stored_home_team_league: str | None
    stored_away_team_id: str
    stored_away_team_name: str | None
    stored_away_team_league: str | None
    persisted_home_score: int | None
    persisted_away_score: int | None
    source_file: str | None
    source_fixture_id: str | None
    source_league: str | None
    source_match_date: str | None
    source_home_team: str | None
    source_away_team: str | None
    source_home_score: int | None
    source_away_score: int | None
    source_evidence_sha256: str | None
    target_home_team_id: str | None
    target_away_team_id: str | None
    repair_reason: str
    replay_required: bool
    blockers: tuple[str, ...]

    @property
    def repair_ready(self) -> bool:
        return not self.blockers

    @property
    def repair_status(self) -> str:
        return "READY" if self.repair_ready else "BLOCKED"

    @property
    def blocking_reason(self) -> str | None:
        return ";".join(self.blockers) if self.blockers else None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["blocking_reason"] = self.blocking_reason
        payload["repair_ready"] = self.repair_ready
        payload["repair_status"] = self.repair_status
        return payload


@dataclass(frozen=True)
class SemanticIdentityRepairManifest:
    schema_version: int
    manifest_sha256: str
    summary: dict[str, object]
    proposed_team_creations: tuple[ProposedTeamCreation, ...]
    entries: tuple[SemanticIdentityRepairEntry, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_sha256": self.manifest_sha256,
            "summary": self.summary,
            "proposed_team_creations": [
                proposal.as_dict() for proposal in self.proposed_team_creations
            ],
            "entries": [entry.as_dict() for entry in self.entries],
        }


def _team_indexes_by_league(
    rows: list[tuple[str, str, str | None]],
) -> dict[str, TeamIndex]:
    indexes: dict[str, TeamIndex] = {}
    for team_id, team_name, league_id in rows:
        if not league_id:
            continue
        league = str(league_id)
        index = indexes.get(league)
        if index is None:
            index = TeamIndex(())
            indexes[league] = index
        index.add(str(team_id), str(team_name))
    return indexes


def _canonical_manifest_hash(
    entries: tuple[SemanticIdentityRepairEntry, ...],
    proposed_team_creations: tuple[ProposedTeamCreation, ...],
) -> str:
    # Hash immutable evidence, targets and dispositions, not the derived summary,
    # so presentation-only summary extensions cannot alter authorization identity.
    return _canonical_sha256(
        {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "proposed_team_creations": [
                proposal.as_dict() for proposal in proposed_team_creations
            ],
            "entries": [entry.as_dict() for entry in entries],
        }
    )


def _iso_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return None


def _source_integrity_blockers(
    match: Match | None,
    source: HistoricalSourceIdentity | None,
    *,
    match_league: str,
) -> list[str]:
    blockers: list[str] = []
    if match is None:
        blockers.append("persisted_match_missing")
    if source is None:
        blockers.append("source_record_missing")
    if match is None or source is None:
        return blockers

    if source.league_id != match_league:
        blockers.append("source_league_mismatch")
    if _iso_date(match.match_date) != source.match_date:
        blockers.append("source_match_date_mismatch")
    persisted_home_score = (
        int(match.home_score) if match.home_score is not None else None
    )
    persisted_away_score = (
        int(match.away_score) if match.away_score is not None else None
    )
    if (
        persisted_home_score != source.home_score
        or persisted_away_score != source.away_score
    ):
        blockers.append("source_score_mismatch")
    return blockers


@dataclass(frozen=True)
class _ProposedTeamOccurrence:
    match_id: str
    side: str
    team_id: str
    team_name: str
    league_id: str
    source_evidence_sha256: str


async def build_semantic_identity_repair_manifest(
    session: AsyncSession,
    *,
    cache_dir: Path | None = None,
) -> SemanticIdentityRepairManifest:
    """Return the exact source-backed repair plan without mutating database state."""

    findings = await audit_historical_semantic_identity(session, cache_dir=cache_dir)
    source_index = build_historical_source_index(cache_dir)

    finding_ids = [finding.match_id for finding in findings]
    matches: dict[str, Match] = {}
    if finding_ids:
        persisted = (
            (await session.execute(select(Match).where(Match.id.in_(finding_ids))))
            .scalars()
            .all()
        )
        matches = {str(match.id): match for match in persisted}

    team_rows = (
        (await session.execute(select(Team.id, Team.name, Team.league_id)))
        .tuples()
        .all()
    )
    indexes = _team_indexes_by_league(
        [
            (str(team_id), str(team_name), str(league_id) if league_id else None)
            for team_id, team_name, league_id in team_rows
        ]
    )

    persisted_teams = {
        str(team_id): (
            str(team_name),
            str(league_id) if league_id is not None else None,
        )
        for team_id, team_name, league_id in team_rows
    }
    ordered_findings = sorted(
        findings, key=lambda item: (item.match_date, item.match_id)
    )

    # Only a cross-league mismatched participant may propose a missing target.
    # An unaffected opponent that does not resolve remains a blocker; otherwise
    # this repair would become a general-purpose identity-minting heuristic.
    occurrences_by_team_id: dict[str, list[_ProposedTeamOccurrence]] = {}
    candidate_by_participant: dict[tuple[str, str], str] = {}
    for finding in ordered_findings:
        match = matches.get(finding.match_id)
        source = source_index.get(finding.match_id)
        if match is None or source is None:
            continue
        match_league = str(match.league_id)
        if _source_integrity_blockers(match, source, match_league=match_league):
            continue

        index = indexes.get(match_league)
        if index is None:
            index = TeamIndex(())
            indexes[match_league] = index
        evidence_hash = _source_evidence_hash(source)
        if evidence_hash is None:
            continue

        participants = (
            (
                "home",
                finding.home_league_mismatch
                and finding.stored_home_team_league is not None,
                source.home_team,
            ),
            (
                "away",
                finding.away_league_mismatch
                and finding.stored_away_team_league is not None,
                source.away_team,
            ),
        )
        for side, is_mismatched, source_name in participants:
            if not is_mismatched or index.resolve(source_name) is not None:
                continue
            team_id = _historical_team_id(source_name, match_league)
            occurrence = _ProposedTeamOccurrence(
                match_id=finding.match_id,
                side=side,
                team_id=team_id,
                team_name=source_name,
                league_id=match_league,
                source_evidence_sha256=evidence_hash,
            )
            occurrences_by_team_id.setdefault(team_id, []).append(occurrence)
            candidate_by_participant[(finding.match_id, side)] = team_id

    proposed_team_creations: list[ProposedTeamCreation] = []
    proposal_errors: dict[str, str] = {}
    for team_id in sorted(occurrences_by_team_id):
        occurrences = occurrences_by_team_id[team_id]
        identities = {(item.team_name, item.league_id) for item in occurrences}
        if len(identities) != 1:
            proposal_errors[team_id] = "proposed_team_creation_identity_conflict"
            continue
        team_name, league_id = next(iter(identities))
        if team_id in persisted_teams:
            proposal_errors[team_id] = "proposed_team_id_conflict"
            continue

        proposal = ProposedTeamCreation(
            team_id=team_id,
            team_name=team_name,
            league_id=league_id,
            participant_references=len(occurrences),
            source_fixture_ids=tuple(sorted({item.match_id for item in occurrences})),
            source_evidence_sha256s=tuple(
                sorted({item.source_evidence_sha256 for item in occurrences})
            ),
        )
        proposed_team_creations.append(proposal)
        indexes[league_id].add(team_id, team_name)

    valid_proposed_ids = {proposal.team_id for proposal in proposed_team_creations}

    entries: list[SemanticIdentityRepairEntry] = []
    for finding in ordered_findings:
        match = matches.get(finding.match_id)
        source = source_index.get(finding.match_id)

        match_league = (
            str(match.league_id) if match is not None else finding.match_league
        )
        blockers = _source_integrity_blockers(
            match,
            source,
            match_league=match_league,
        )

        target_home_id: str | None = None
        target_away_id: str | None = None
        if source is not None:
            index = indexes.get(match_league)
            if index is None:
                blockers.append("target_league_has_no_team_index")
            else:
                target_home_id = index.resolve(source.home_team)
                target_away_id = index.resolve(source.away_team)
                home_candidate = candidate_by_participant.get(
                    (finding.match_id, "home")
                )
                away_candidate = candidate_by_participant.get(
                    (finding.match_id, "away")
                )
                if target_home_id is None and home_candidate in valid_proposed_ids:
                    target_home_id = home_candidate
                if target_away_id is None and away_candidate in valid_proposed_ids:
                    target_away_id = away_candidate
                if target_home_id is None:
                    blockers.append("target_home_unresolved")
                    if home_candidate in proposal_errors:
                        blockers.append(proposal_errors[home_candidate])
                if target_away_id is None:
                    blockers.append("target_away_unresolved")
                    if away_candidate in proposal_errors:
                        blockers.append(proposal_errors[away_candidate])
                if (
                    target_home_id is not None
                    and target_away_id is not None
                    and target_home_id == target_away_id
                ):
                    blockers.append("target_identity_collision")

        entries.append(
            SemanticIdentityRepairEntry(
                match_id=finding.match_id,
                match_league=match_league,
                match_date=(
                    match.match_date.isoformat()
                    if match is not None and isinstance(match.match_date, datetime)
                    else finding.match_date
                ),
                stored_home_team_id=finding.stored_home_team_id,
                stored_home_team_name=finding.stored_home_team_name,
                stored_home_team_league=finding.stored_home_team_league,
                stored_away_team_id=finding.stored_away_team_id,
                stored_away_team_name=finding.stored_away_team_name,
                stored_away_team_league=finding.stored_away_team_league,
                persisted_home_score=(
                    int(match.home_score)
                    if match is not None and match.home_score is not None
                    else None
                ),
                persisted_away_score=(
                    int(match.away_score)
                    if match is not None and match.away_score is not None
                    else None
                ),
                source_file=source.source_file if source is not None else None,
                source_fixture_id=source.match_id if source is not None else None,
                source_league=source.league_id if source is not None else None,
                source_match_date=source.match_date if source is not None else None,
                source_home_team=source.home_team if source is not None else None,
                source_away_team=source.away_team if source is not None else None,
                source_home_score=source.home_score if source is not None else None,
                source_away_score=source.away_score if source is not None else None,
                source_evidence_sha256=_source_evidence_hash(source),
                target_home_team_id=target_home_id,
                target_away_team_id=target_away_id,
                repair_reason=_repair_reason(
                    home_mismatch=finding.home_league_mismatch,
                    away_mismatch=finding.away_league_mismatch,
                ),
                replay_required=True,
                blockers=tuple(sorted(set(blockers))),
            )
        )

    frozen_entries = tuple(entries)
    frozen_proposals = tuple(proposed_team_creations)
    blocker_counts = Counter(
        blocker for entry in frozen_entries for blocker in entry.blockers
    )
    ready = sum(entry.repair_ready for entry in frozen_entries)
    summary: dict[str, object] = {
        "affected_matches": len(frozen_entries),
        "repair_ready_matches": ready,
        "repair_blocked_matches": len(frozen_entries) - ready,
        "source_records_found": sum(
            entry.source_file is not None for entry in frozen_entries
        ),
        "source_records_missing": sum(
            entry.source_file is None for entry in frozen_entries
        ),
        "source_evidence_hashed": sum(
            entry.source_evidence_sha256 is not None for entry in frozen_entries
        ),
        "replay_required_matches": sum(
            entry.replay_required for entry in frozen_entries
        ),
        "proposed_team_creations": len(frozen_proposals),
        "proposed_team_creation_references": sum(
            proposal.participant_references for proposal in frozen_proposals
        ),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "first_affected_match": min(
            (entry.match_date for entry in frozen_entries), default=None
        ),
        "last_affected_match": max(
            (entry.match_date for entry in frozen_entries), default=None
        ),
        "complete": ready == len(frozen_entries),
    }

    return SemanticIdentityRepairManifest(
        schema_version=_MANIFEST_SCHEMA_VERSION,
        manifest_sha256=_canonical_manifest_hash(frozen_entries, frozen_proposals),
        summary=summary,
        proposed_team_creations=frozen_proposals,
        entries=frozen_entries,
    )


__all__ = [
    "ProposedTeamCreation",
    "SemanticIdentityRepairEntry",
    "SemanticIdentityRepairManifest",
    "build_semantic_identity_repair_manifest",
]
