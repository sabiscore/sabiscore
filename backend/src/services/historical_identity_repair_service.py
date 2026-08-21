"""Deterministic semantic-identity repair and Elo replay planning.

This module makes the *future* production mutation reviewable without performing it
implicitly.  The repair is bound to two immutable digests:

1. the source-backed semantic identity manifest; and
2. a replay plan containing every corrected finished match from the earliest
   affected day forward, plus the Elo configuration used for reconstruction.

Why the replay is full-from-boundary
------------------------------------
Elo is path dependent.  Updating only the directly corrupted Match rows or deleting
only their 532 snapshots leaves every later opponent rating contaminated.  For each
affected league this service therefore plans replacement of all Elo snapshots from
the beginning of the earliest affected UTC day, then replays every score-verified
finished match in deterministic ``(match_date, id)`` order.

No function in this module commits.  ``apply_semantic_identity_and_rebuild_elo``
performs writes only when called explicitly by an operator-controlled CLI; any
exception leaves the caller free to roll the transaction back.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from typing import Iterable

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.database import Match, Team
from ..core.league_policy import canonical_league_id
from ..db.models import EloRatingSnapshot
from .elo_state_service import apply_finished_match_to_elo
from .historical_identity_audit_service import audit_historical_semantic_identity
from .historical_identity_repair_manifest_service import (
    SemanticIdentityRepairManifest,
    build_semantic_identity_repair_manifest,
)


_REPLAY_PLAN_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ReplayMatchEvidence:
    match_id: str
    league: str
    match_date: str
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LeagueEloReplayPlan:
    league: str
    boundary_utc: str
    finished_matches: int
    existing_snapshots_to_replace: int
    expected_rebuilt_snapshots: int
    match_sequence_sha256: str
    matches: tuple[ReplayMatchEvidence, ...]

    def as_dict(self, *, include_matches: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "league": self.league,
            "boundary_utc": self.boundary_utc,
            "finished_matches": self.finished_matches,
            "existing_snapshots_to_replace": self.existing_snapshots_to_replace,
            "expected_rebuilt_snapshots": self.expected_rebuilt_snapshots,
            "match_sequence_sha256": self.match_sequence_sha256,
        }
        if include_matches:
            payload["matches"] = [item.as_dict() for item in self.matches]
        return payload


@dataclass(frozen=True)
class SemanticEloRepairPlan:
    schema_version: int
    semantic_manifest_sha256: str
    elo_k_base: float
    elo_home_advantage: float
    plan_sha256: str
    leagues: tuple[LeagueEloReplayPlan, ...]

    def as_dict(self, *, include_matches: bool = True) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "semantic_manifest_sha256": self.semantic_manifest_sha256,
            "elo_config": {
                "k_base": self.elo_k_base,
                "home_advantage": self.elo_home_advantage,
            },
            "plan_sha256": self.plan_sha256,
            "leagues": [
                league.as_dict(include_matches=include_matches)
                for league in self.leagues
            ],
        }


@dataclass(frozen=True)
class SemanticEloRepairResult:
    created_team_ids: tuple[str, ...]
    repaired_matches: int
    rebuilt_matches: int
    rebuilt_snapshots: int
    leagues: tuple[str, ...]


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _day_boundary(value: datetime) -> datetime:
    """Return naive-UTC midnight matching the DB's TIMESTAMP WITHOUT TZ convention."""
    return value.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def _corrected_ids_by_match(
    manifest: SemanticIdentityRepairManifest,
) -> dict[str, tuple[str, str]]:
    corrected: dict[str, tuple[str, str]] = {}
    for entry in manifest.entries:
        if not entry.repair_ready:
            raise RuntimeError(
                f"semantic repair manifest is incomplete for match_id={entry.match_id}: "
                f"{', '.join(entry.blockers)}"
            )
        if not entry.target_home_team_id or not entry.target_away_team_id:
            raise RuntimeError(
                f"semantic repair target missing for match_id={entry.match_id}"
            )
        corrected[entry.match_id] = (
            entry.target_home_team_id,
            entry.target_away_team_id,
        )
    return corrected


def _sequence_hash(matches: Iterable[ReplayMatchEvidence]) -> str:
    return _canonical_sha256([item.as_dict() for item in matches])


async def build_semantic_elo_repair_plan(
    session: AsyncSession,
    *,
    manifest: SemanticIdentityRepairManifest | None = None,
) -> SemanticEloRepairPlan:
    """Build the exact post-repair Elo reconstruction plan without mutating state."""

    semantic_manifest = manifest or await build_semantic_identity_repair_manifest(
        session
    )
    if not bool(semantic_manifest.summary.get("complete")):
        raise RuntimeError(
            "semantic identity repair manifest is incomplete; production mutation remains blocked"
        )
    corrected_ids = _corrected_ids_by_match(semantic_manifest)

    boundaries: dict[str, datetime] = {}
    for entry in semantic_manifest.entries:
        # The manifest date is derived from the persisted Match datetime.
        parsed = datetime.fromisoformat(entry.match_date)
        league = canonical_league_id(entry.match_league)
        boundary = _day_boundary(parsed)
        current = boundaries.get(league)
        if current is None or boundary < current:
            boundaries[league] = boundary

    league_plans: list[LeagueEloReplayPlan] = []
    for league in sorted(boundaries):
        boundary = boundaries[league]
        matches = (
            (
                await session.execute(
                    select(Match)
                    .where(
                        func.lower(Match.status) == "finished",
                        Match.home_score.is_not(None),
                        Match.away_score.is_not(None),
                        func.lower(Match.league_id) == league.lower(),
                        Match.match_date >= boundary,
                    )
                    .order_by(Match.match_date.asc(), Match.id.asc())
                )
            )
            .scalars()
            .all()
        )

        evidence: list[ReplayMatchEvidence] = []
        for match in matches:
            match_id = str(match.id)
            home_id, away_id = corrected_ids.get(
                match_id,
                (str(match.home_team_id), str(match.away_team_id)),
            )
            if not home_id or not away_id:
                raise RuntimeError(
                    f"missing participant id in replay scope: {match_id}"
                )
            if home_id == away_id:
                raise RuntimeError(
                    f"self-play fixture remains in replay scope: match_id={match_id} team_id={home_id}"
                )
            if match.home_score is None or match.away_score is None:
                raise RuntimeError(f"unsettled match entered replay scope: {match_id}")
            match_date = match.match_date
            if not isinstance(match_date, datetime):
                raise RuntimeError(
                    f"non-datetime match_date in replay scope: {match_id}"
                )
            evidence.append(
                ReplayMatchEvidence(
                    match_id=match_id,
                    league=league,
                    match_date=match_date.isoformat(),
                    home_team_id=home_id,
                    away_team_id=away_id,
                    home_score=int(match.home_score),
                    away_score=int(match.away_score),
                )
            )

        existing_snapshots = int(
            (
                await session.execute(
                    select(func.count(EloRatingSnapshot.id)).where(
                        func.lower(EloRatingSnapshot.league) == league.lower(),
                        EloRatingSnapshot.match_date >= boundary,
                    )
                )
            ).scalar_one()
        )
        ordered = tuple(evidence)
        league_plans.append(
            LeagueEloReplayPlan(
                league=league,
                boundary_utc=boundary.isoformat(),
                finished_matches=len(ordered),
                existing_snapshots_to_replace=existing_snapshots,
                expected_rebuilt_snapshots=len(ordered) * 2,
                match_sequence_sha256=_sequence_hash(ordered),
                matches=ordered,
            )
        )

    hash_payload = {
        "schema_version": _REPLAY_PLAN_SCHEMA_VERSION,
        "semantic_manifest_sha256": semantic_manifest.manifest_sha256,
        "elo_config": {
            "k_base": float(settings.elo_k_base),
            "home_advantage": float(settings.elo_home_advantage),
        },
        "leagues": [plan.as_dict(include_matches=True) for plan in league_plans],
    }
    return SemanticEloRepairPlan(
        schema_version=_REPLAY_PLAN_SCHEMA_VERSION,
        semantic_manifest_sha256=semantic_manifest.manifest_sha256,
        elo_k_base=float(settings.elo_k_base),
        elo_home_advantage=float(settings.elo_home_advantage),
        plan_sha256=_canonical_sha256(hash_payload),
        leagues=tuple(league_plans),
    )


async def acquire_semantic_elo_repair_locks(
    session: AsyncSession,
    *,
    lock_timeout_seconds: int = 5,
) -> None:
    """Acquire PostgreSQL transaction-scoped locks before the one-time mutation.

    ACCESS SHARE readers (normal prediction/Elo lookups) remain allowed.  Competing
    Match/Elo writers wait instead of observing or creating a half-rebuilt league.
    The lock timeout makes contention fail closed rather than wedging a release.
    """

    if session.bind is None or session.bind.dialect.name != "postgresql":
        raise RuntimeError("semantic Elo production repair requires PostgreSQL")
    timeout_ms = max(1, int(lock_timeout_seconds * 1000))
    await session.execute(text(f"SET LOCAL lock_timeout = '{timeout_ms}ms'"))
    await session.execute(
        text(
            "LOCK TABLE teams, matches, elo_rating_snapshots "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    )


async def _apply_proposed_team_creations(
    session: AsyncSession,
    manifest: SemanticIdentityRepairManifest,
) -> tuple[str, ...]:
    created: list[str] = []
    for proposal in manifest.proposed_team_creations:
        existing = await session.get(Team, proposal.team_id)
        if existing is not None:
            raise RuntimeError(
                "semantic repair Team precondition failed: deterministic id "
                f"already exists: team_id={proposal.team_id}"
            )
        session.add(
            Team(
                id=proposal.team_id,
                name=proposal.team_name,
                league_id=proposal.league_id,
            )
        )
        created.append(proposal.team_id)
    await session.flush()

    for proposal in manifest.proposed_team_creations:
        persisted = await session.get(Team, proposal.team_id)
        if (
            persisted is None
            or str(persisted.name) != proposal.team_name
            or str(persisted.league_id) != proposal.league_id
        ):
            raise RuntimeError(
                f"semantic repair Team postcondition failed: team_id={proposal.team_id}"
            )
    return tuple(created)


async def _apply_identity_manifest(
    session: AsyncSession,
    manifest: SemanticIdentityRepairManifest,
) -> int:
    repaired = 0
    for entry in manifest.entries:
        if not entry.repair_ready:
            raise RuntimeError(f"blocked repair entry reached apply: {entry.match_id}")
        if (
            not entry.target_home_team_id
            or not entry.target_away_team_id
            or entry.target_home_team_id == entry.target_away_team_id
        ):
            raise RuntimeError(
                "repair-ready entry has invalid canonical participants: "
                f"match_id={entry.match_id}"
            )
        result = await session.execute(
            update(Match)
            .where(
                Match.id == entry.match_id,
                Match.home_team_id == entry.stored_home_team_id,
                Match.away_team_id == entry.stored_away_team_id,
                Match.league_id == entry.match_league,
            )
            .values(
                home_team_id=entry.target_home_team_id,
                away_team_id=entry.target_away_team_id,
            )
        )
        rowcount = getattr(result, "rowcount", None)
        if rowcount != 1:
            raise RuntimeError(
                "semantic repair optimistic precondition failed for "
                f"match_id={entry.match_id}; expected exactly one unchanged source row, "
                f"updated={rowcount}"
            )
        repaired += 1
    await session.flush()
    return repaired


async def _assert_post_repair_match_sequence(
    session: AsyncSession,
    plan: LeagueEloReplayPlan,
) -> tuple[Match, ...]:
    boundary = datetime.fromisoformat(plan.boundary_utc)
    rows = (
        (
            await session.execute(
                select(Match)
                .where(
                    func.lower(Match.status) == "finished",
                    Match.home_score.is_not(None),
                    Match.away_score.is_not(None),
                    func.lower(Match.league_id) == plan.league.lower(),
                    Match.match_date >= boundary,
                )
                .order_by(Match.match_date.asc(), Match.id.asc())
            )
        )
        .scalars()
        .all()
    )

    evidence = tuple(
        ReplayMatchEvidence(
            match_id=str(match.id),
            league=plan.league,
            match_date=match.match_date.isoformat(),
            home_team_id=str(match.home_team_id),
            away_team_id=str(match.away_team_id),
            home_score=int(match.home_score),
            away_score=int(match.away_score),
        )
        for match in rows
    )
    digest = _sequence_hash(evidence)
    if digest != plan.match_sequence_sha256:
        raise RuntimeError(
            f"post-repair match sequence drift for {plan.league}: "
            f"expected={plan.match_sequence_sha256} actual={digest}"
        )
    return tuple(rows)


async def _rebuild_league_elo(
    session: AsyncSession,
    plan: LeagueEloReplayPlan,
) -> tuple[int, int]:
    matches = await _assert_post_repair_match_sequence(session, plan)
    boundary = datetime.fromisoformat(plan.boundary_utc)

    await session.execute(
        delete(EloRatingSnapshot).where(
            func.lower(EloRatingSnapshot.league) == plan.league.lower(),
            EloRatingSnapshot.match_date >= boundary,
        )
    )
    await session.flush()

    rebuilt = 0
    for match in matches:
        if not await apply_finished_match_to_elo(session, match):
            raise RuntimeError(
                "Elo replay failed closed because a scoped match was not rebuilt: "
                f"match_id={match.id}"
            )
        rebuilt += 1

    snapshot_rows = (
        await session.execute(
            select(
                EloRatingSnapshot.match_id,
                EloRatingSnapshot.team_id,
                EloRatingSnapshot.league,
                EloRatingSnapshot.match_date,
            ).where(
                func.lower(EloRatingSnapshot.league) == plan.league.lower(),
                EloRatingSnapshot.match_date >= boundary,
            )
        )
    ).all()
    snapshot_count = len(snapshot_rows)

    expected_by_match = {
        str(match.id): {
            "team_ids": {str(match.home_team_id), str(match.away_team_id)},
            "match_date": match.match_date,
        }
        for match in matches
    }
    observed_by_match: dict[str, list[tuple[str, str, datetime]]] = {}
    for match_id, team_id, league, match_date in snapshot_rows:
        observed_by_match.setdefault(str(match_id), []).append(
            (str(team_id), str(league), match_date)
        )

    if set(observed_by_match) != set(expected_by_match):
        missing = sorted(set(expected_by_match) - set(observed_by_match))
        unexpected = sorted(set(observed_by_match) - set(expected_by_match))
        raise RuntimeError(
            f"Elo replay match population mismatch for {plan.league}: "
            f"missing={missing[:10]} unexpected={unexpected[:10]}"
        )

    for match_id, expected in expected_by_match.items():
        rows = observed_by_match[match_id]
        observed_team_ids = {row[0] for row in rows}
        if len(rows) != 2 or observed_team_ids != expected["team_ids"]:
            raise RuntimeError(
                f"Elo replay structural integrity failed for match_id={match_id}: "
                f"rows={len(rows)} teams={sorted(observed_team_ids)}"
            )
        if any(row[1] != plan.league for row in rows):
            raise RuntimeError(
                f"Elo replay league integrity failed for match_id={match_id}"
            )
        if any(row[2] != expected["match_date"] for row in rows):
            raise RuntimeError(
                f"Elo replay timestamp integrity failed for match_id={match_id}"
            )

    if rebuilt != plan.finished_matches:
        raise RuntimeError(
            f"Elo replay count drift for {plan.league}: "
            f"expected={plan.finished_matches} actual={rebuilt}"
        )
    if snapshot_count != plan.expected_rebuilt_snapshots:
        raise RuntimeError(
            f"Elo snapshot count drift for {plan.league}: "
            f"expected={plan.expected_rebuilt_snapshots} actual={snapshot_count}"
        )
    return rebuilt, snapshot_count


async def apply_semantic_identity_and_rebuild_elo(
    session: AsyncSession,
    *,
    expected_manifest_sha256: str,
    expected_plan_sha256: str,
    lock_timeout_seconds: int = 5,
) -> SemanticEloRepairResult:
    """Apply one reviewed semantic repair + full path-dependent Elo rebuild.

    The caller must commit explicitly.  The function recomputes both digests under
    the production write locks and fails if any source row, Team resolution, match,
    score, Elo config, or replay population changed since review.
    """

    await acquire_semantic_elo_repair_locks(
        session, lock_timeout_seconds=lock_timeout_seconds
    )
    manifest = await build_semantic_identity_repair_manifest(session)
    if manifest.manifest_sha256 != expected_manifest_sha256:
        raise RuntimeError(
            "semantic repair manifest changed since review: "
            f"expected={expected_manifest_sha256} actual={manifest.manifest_sha256}"
        )
    if not bool(manifest.summary.get("complete")):
        raise RuntimeError("semantic repair manifest is not complete")

    plan = await build_semantic_elo_repair_plan(session, manifest=manifest)
    if plan.plan_sha256 != expected_plan_sha256:
        raise RuntimeError(
            "semantic Elo replay plan changed since review: "
            f"expected={expected_plan_sha256} actual={plan.plan_sha256}"
        )

    created_team_ids = await _apply_proposed_team_creations(session, manifest)
    repaired = await _apply_identity_manifest(session, manifest)
    if repaired != len(manifest.entries):
        raise RuntimeError(
            "semantic repair match count postcondition failed: "
            f"expected={len(manifest.entries)} actual={repaired}"
        )

    residual = await audit_historical_semantic_identity(session)
    if residual:
        raise RuntimeError(
            f"semantic identity postcondition failed: {len(residual)} residual findings"
        )

    total_matches = 0
    total_snapshots = 0
    for league_plan in plan.leagues:
        rebuilt, snapshots = await _rebuild_league_elo(session, league_plan)
        total_matches += rebuilt
        total_snapshots += snapshots

    return SemanticEloRepairResult(
        created_team_ids=created_team_ids,
        repaired_matches=repaired,
        rebuilt_matches=total_matches,
        rebuilt_snapshots=total_snapshots,
        leagues=tuple(item.league for item in plan.leagues),
    )


__all__ = [
    "LeagueEloReplayPlan",
    "ReplayMatchEvidence",
    "SemanticEloRepairPlan",
    "SemanticEloRepairResult",
    "acquire_semantic_elo_repair_locks",
    "apply_semantic_identity_and_rebuild_elo",
    "build_semantic_elo_repair_plan",
]
