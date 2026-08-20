"""Build a deterministic, read-only repair manifest for historical identity drift.

This module does not mutate ``matches`` or Elo state.  It strengthens the existing
semantic identity audit by proving that every affected historical match has enough
source-backed evidence to be repaired safely:

* the original committed football-data.co.uk row exists;
* source league/date/result agree with the persisted match;
* both source team names resolve under today's production ``TeamIndex``;
* resolution is scoped to the persisted match league;
* the two target team ids are distinct.

The resulting manifest is canonicalized and SHA-256 hashed so an eventual mutation
can require the exact reviewed evidence set rather than re-discovering targets at
apply time.
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
from .historical_backfill_service import TeamIndex
from .historical_identity_audit_service import (
    audit_historical_semantic_identity,
    build_historical_source_index,
)


_MANIFEST_SCHEMA_VERSION = 1


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
    source_league: str | None
    source_match_date: str | None
    source_home_team: str | None
    source_away_team: str | None
    source_home_score: int | None
    source_away_score: int | None
    target_home_team_id: str | None
    target_away_team_id: str | None
    blockers: tuple[str, ...]

    @property
    def repair_ready(self) -> bool:
        return not self.blockers

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["repair_ready"] = self.repair_ready
        return payload


@dataclass(frozen=True)
class SemanticIdentityRepairManifest:
    schema_version: int
    manifest_sha256: str
    summary: dict[str, object]
    entries: tuple[SemanticIdentityRepairEntry, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_sha256": self.manifest_sha256,
            "summary": self.summary,
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


def _canonical_manifest_hash(entries: tuple[SemanticIdentityRepairEntry, ...]) -> str:
    # Hash only immutable evidence/targets, not the derived summary, so the digest
    # remains stable if presentation-only summary fields are later extended.
    payload = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "entries": [entry.as_dict() for entry in entries],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _iso_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return None


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
            await session.execute(select(Match).where(Match.id.in_(finding_ids)))
        ).scalars().all()
        matches = {str(match.id): match for match in persisted}

    team_rows = (
        await session.execute(select(Team.id, Team.name, Team.league_id))
    ).tuples().all()
    indexes = _team_indexes_by_league(
        [(str(team_id), str(team_name), str(league_id) if league_id else None)
         for team_id, team_name, league_id in team_rows]
    )

    entries: list[SemanticIdentityRepairEntry] = []
    for finding in sorted(findings, key=lambda item: (item.match_date, item.match_id)):
        blockers: list[str] = []
        match = matches.get(finding.match_id)
        source = source_index.get(finding.match_id)

        if match is None:
            blockers.append("persisted_match_missing")

        if source is None:
            blockers.append("source_record_missing")

        match_league = str(match.league_id) if match is not None else finding.match_league
        persisted_match_date = _iso_date(match.match_date) if match is not None else None

        if source is not None and match is not None:
            if source.league_id != match_league:
                blockers.append("source_league_mismatch")
            if persisted_match_date != source.match_date:
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

        target_home_id: str | None = None
        target_away_id: str | None = None
        if source is not None:
            index = indexes.get(match_league)
            if index is None:
                blockers.append("target_league_has_no_team_index")
            else:
                target_home_id = index.resolve(source.home_team)
                target_away_id = index.resolve(source.away_team)
                if target_home_id is None:
                    blockers.append("target_home_unresolved")
                if target_away_id is None:
                    blockers.append("target_away_unresolved")
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
                source_league=source.league_id if source is not None else None,
                source_match_date=source.match_date if source is not None else None,
                source_home_team=source.home_team if source is not None else None,
                source_away_team=source.away_team if source is not None else None,
                source_home_score=source.home_score if source is not None else None,
                source_away_score=source.away_score if source is not None else None,
                target_home_team_id=target_home_id,
                target_away_team_id=target_away_id,
                blockers=tuple(sorted(set(blockers))),
            )
        )

    frozen_entries = tuple(entries)
    blocker_counts = Counter(
        blocker for entry in frozen_entries for blocker in entry.blockers
    )
    ready = sum(entry.repair_ready for entry in frozen_entries)
    summary: dict[str, object] = {
        "affected_matches": len(frozen_entries),
        "repair_ready_matches": ready,
        "repair_blocked_matches": len(frozen_entries) - ready,
        "source_records_found": sum(entry.source_file is not None for entry in frozen_entries),
        "source_records_missing": sum(entry.source_file is None for entry in frozen_entries),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "first_affected_match": (
            min((entry.match_date for entry in frozen_entries), default=None)
        ),
        "last_affected_match": (
            max((entry.match_date for entry in frozen_entries), default=None)
        ),
        "complete": ready == len(frozen_entries),
    }

    return SemanticIdentityRepairManifest(
        schema_version=_MANIFEST_SCHEMA_VERSION,
        manifest_sha256=_canonical_manifest_hash(frozen_entries),
        summary=summary,
        entries=frozen_entries,
    )


__all__ = [
    "SemanticIdentityRepairEntry",
    "SemanticIdentityRepairManifest",
    "build_semantic_identity_repair_manifest",
]
