"""Read-only manifest of Elo-less orphan team identities eligible for repair.

docs/DEBT.md item 39 (mojibake team names) and the live investigation behind
it established that PR #81's fixture-identity-review endpoint compares the
wrong pair of systems: ``Match.home_team_id``/``away_team_id`` (legacy
``teams`` table) against ``CanonicalFixture.home_team_id``/``away_team_id``
(``canonical_teams`` table, a *different* table Match never references, whose
mapping resolver — ``canonical_identity_service._provider_team_anchor`` — has
no name-quality guard and, once a ``ProviderTeamMapping`` row exists, reuses
its ``canonical_team_id`` forever regardless of the current display name).
That comparison cannot produce a safe repair target.

The genuinely correct "verified" identity for ``Match.home_team_id`` is
whatever ``team_identity.resolve_team_id()`` — the exact function
``fixture_sync_service._resolve_upcoming_team_id`` calls — resolves *today*,
because that is the one system that actually shares Match's table. Unlike the
canonical-team resolver, the Elo-bridge resolver
(``resolve_provider_elo_team_id``/``bind_provider_elo_team_id``) never binds a
provider ID to a team with no real Elo history (the deterministic
``_team_id()`` fallback path explicitly skips the bind), so a corrupted-name
orphan carries no sticky mapping and *can* still resolve correctly once the
provider name is clean again.

This module replays that same read-only resolution against the freshest
observed provider team name — sourced from ``ProviderTeamMapping.provider_team_name``,
which is refreshed on every sync tick (unlike ``CanonicalTeam.name``, which is
set once at creation and never touched again) — for every unsettled fixture's
Elo-less side. It never binds, writes, or mutates anything; it only proves
whether a safe rebind target now exists and, if so, evidences it with the
target's own Elo history.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Match, Team
from ..db.models import EloRatingSnapshot, MatchPredictionLog, ProviderEventMapping, ProviderTeamMapping
from ..repositories.fixtures import SETTLED_MATCH_STATUSES
from .fixture_sync_service import is_unusable_team_name
from .team_identity import resolve_team_id

_MANIFEST_SCHEMA_VERSION = 1
_PROVIDER = "football-data.org"


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class OrphanTeamRepairEntry:
    match_id: str
    league_id: str
    side: str
    kickoff_utc: str
    status: str
    orphan_team_id: str
    orphan_team_name: str | None
    freshest_observed_name: str | None
    target_team_id: str
    target_team_name: str | None
    target_elo_snapshot_count: int
    target_elo_first_match_date: str | None
    target_elo_last_match_date: str | None
    blockers: tuple[str, ...]

    @property
    def repair_ready(self) -> bool:
        return not self.blockers

    @property
    def repair_status(self) -> str:
        return "READY" if self.repair_ready else "BLOCKED"

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["repair_ready"] = self.repair_ready
        payload["repair_status"] = self.repair_status
        return payload


@dataclass(frozen=True)
class OrphanTeamRepairManifest:
    schema_version: int
    manifest_sha256: str
    summary: dict[str, object]
    entries: tuple[OrphanTeamRepairEntry, ...]


async def _elo_evidence(
    session: AsyncSession, team_id: str, league_id: str
) -> tuple[int, str | None, str | None]:
    rows = (
        (
            await session.execute(
                select(EloRatingSnapshot.match_date)
                .where(
                    EloRatingSnapshot.team_id == team_id,
                    EloRatingSnapshot.league == league_id,
                )
                .order_by(EloRatingSnapshot.match_date.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0, None, None
    return len(rows), rows[0].isoformat(), rows[-1].isoformat()


async def _has_elo_history(session: AsyncSession, team_id: str, league_id: str) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(
                    EloRatingSnapshot.team_id == team_id,
                    EloRatingSnapshot.league == league_id,
                )
            )
        )
    )


async def build_orphan_team_repair_manifest(
    session: AsyncSession,
) -> OrphanTeamRepairManifest:
    """Find Elo-less orphan team identities with a now-resolvable clean target.

    Read-only throughout: ``resolve_team_id`` issues SELECT statements only,
    and this function never calls ``bind_provider_elo_team_id`` or stages any
    write. A caller wanting transactional isolation from concurrent writers
    may wrap this in a rolled-back transaction as
    ``data_authority.semantic_repair_review`` does for its sibling case.
    """
    statement = (
        select(Match, ProviderEventMapping.evidence)
        .join(
            ProviderEventMapping,
            (ProviderEventMapping.provider_event_id == Match.id)
            & (ProviderEventMapping.provider == _PROVIDER),
        )
        .where(
            or_(
                Match.status.is_(None),
                func.lower(Match.status).notin_(SETTLED_MATCH_STATUSES),
            )
        )
    )
    rows = (await session.execute(statement)).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    entries: list[OrphanTeamRepairEntry] = []
    unrepaired: Counter[str] = Counter()
    for match, evidence in rows:
        evidence = evidence or {}
        for side, stored_team_id in (
            ("home", match.home_team_id),
            ("away", match.away_team_id),
        ):
            if not stored_team_id:
                continue
            if await _has_elo_history(session, stored_team_id, match.league_id):
                continue  # not an orphan — already carries real history

            provider_team_id = str(evidence.get(f"{side}_provider_team_id") or "").strip()
            if not provider_team_id:
                unrepaired["ORPHAN_NO_PROVIDER_TEAM_ID_EVIDENCE"] += 1
                continue

            mapping = (
                await session.execute(
                    select(ProviderTeamMapping.provider_team_name).where(
                        ProviderTeamMapping.provider == _PROVIDER,
                        ProviderTeamMapping.provider_team_id == provider_team_id,
                        ProviderTeamMapping.competition == match.league_id,
                    )
                )
            ).scalar_one_or_none()
            freshest_name = mapping.strip() if mapping else None
            if not freshest_name:
                unrepaired["ORPHAN_NO_PROVIDER_TEAM_MAPPING_YET"] += 1
                continue
            if is_unusable_team_name(freshest_name):
                unrepaired["ORPHAN_FRESHEST_NAME_STILL_CORRUPT"] += 1
                continue

            target_id = await resolve_team_id(
                freshest_name,
                session,
                league_id=match.league_id,
                require_elo_history=True,
            )
            if not target_id or target_id == stored_team_id:
                unrepaired["ORPHAN_NO_RESOLVER_MATCH"] += 1
                continue

            other_side_id = match.away_team_id if side == "home" else match.home_team_id
            if target_id == other_side_id:
                unrepaired["ORPHAN_TARGET_COLLIDES_WITH_OTHER_SIDE"] += 1
                continue  # would create a self-play collision — refuse, not guess

            blockers: list[str] = []
            if match.match_date is not None and match.match_date < now:
                blockers.append("KICKOFF_PASSED")
            has_predictions = bool(
                await session.scalar(
                    select(exists().where(MatchPredictionLog.match_id == match.id))
                )
            )
            if has_predictions:
                blockers.append("HAS_EXISTING_PREDICTIONS")

            snapshot_count, first_date, last_date = await _elo_evidence(
                session, target_id, match.league_id
            )
            target_name_row = await session.get(Team, target_id)
            orphan_name_row = await session.get(Team, stored_team_id)

            entries.append(
                OrphanTeamRepairEntry(
                    match_id=match.id,
                    league_id=match.league_id,
                    side=side,
                    kickoff_utc=match.match_date.isoformat() if match.match_date else "",
                    status=match.status or "",
                    orphan_team_id=stored_team_id,
                    orphan_team_name=str(orphan_name_row.name) if orphan_name_row else None,
                    freshest_observed_name=freshest_name,
                    target_team_id=target_id,
                    target_team_name=str(target_name_row.name) if target_name_row else None,
                    target_elo_snapshot_count=snapshot_count,
                    target_elo_first_match_date=first_date,
                    target_elo_last_match_date=last_date,
                    blockers=tuple(blockers),
                )
            )

    entries.sort(key=lambda entry: (entry.match_id, entry.side))
    distinct_orphans = {entry.orphan_team_id for entry in entries}
    distinct_targets = {entry.target_team_id for entry in entries}
    summary = {
        "total_candidates": len(entries),
        "repair_ready_count": sum(1 for entry in entries if entry.repair_ready),
        "blocked_count": sum(1 for entry in entries if not entry.repair_ready),
        "distinct_orphan_teams": len(distinct_orphans),
        "distinct_repair_targets": len(distinct_targets),
        "leagues_affected": sorted({entry.league_id for entry in entries}),
        # Orphan sides found but not proposed, broken down by why — otherwise
        # an orphan that fails to resolve is silently indistinguishable from
        # "there was never an orphan here" from outside this function.
        "unrepaired_orphan_sides": dict(sorted(unrepaired.items())),
    }
    manifest_sha256 = _canonical_sha256(
        {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "entries": [entry.as_dict() for entry in entries],
        }
    )
    return OrphanTeamRepairManifest(
        schema_version=_MANIFEST_SCHEMA_VERSION,
        manifest_sha256=manifest_sha256,
        summary=summary,
        entries=tuple(entries),
    )


__all__ = [
    "OrphanTeamRepairEntry",
    "OrphanTeamRepairManifest",
    "build_orphan_team_repair_manifest",
]
