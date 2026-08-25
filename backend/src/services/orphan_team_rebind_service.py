"""Class C executor for the reviewed orphan-team identity rebind.

docs/DEBT.md item 39. ``orphan_team_reconciliation_service`` proves, read-only,
that a fixture side currently points at an Elo-less orphan while a real,
history-bearing team in the same league is what the production resolver
(``team_identity.resolve_team_id``) now returns for that side's freshest
observed provider name. This module is the only thing that acts on that proof.

Scope is deliberately narrower than its sibling
``historical_identity_repair_service``:

* it writes ``Match.home_team_id`` / ``Match.away_team_id`` and nothing else;
* it never creates, renames, or deletes a ``Team``;
* it never writes, rebuilds, or deletes an ``EloRatingSnapshot``.

That narrowness is what makes it safe without a chronological Elo replay. The
manifest refuses any side whose kickoff has passed, so every repaired fixture
is still unplayed: there is no post-match Elo derived from the wrong
participant to unwind. Repointing an unplayed fixture at the team that already
owns the history is a forward-looking identity correction, not a rewrite of
the past.

Production safety mirrors the semantic-repair precedent: PostgreSQL only,
transaction-scoped write locks, the reviewed manifest digest re-derived *under*
those locks, and postconditions that must pass before the caller commits.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Match
from .orphan_team_reconciliation_service import (
    OrphanTeamRepairManifest,
    build_orphan_team_repair_manifest,
)

_APPLICABLE_SIDES = ("home", "away")


@dataclass(frozen=True)
class OrphanTeamRebindResult:
    manifest_sha256: str
    rebound_sides: int
    affected_match_ids: tuple[str, ...]
    leagues: tuple[str, ...]
    # (match_id, side, from_team_id, to_team_id) -- the exact inverse needed to
    # roll this back by hand if a postcondition is discovered later.
    reversals: tuple[tuple[str, str, str, str], ...]


async def acquire_orphan_team_rebind_locks(
    session: AsyncSession,
    *,
    lock_timeout_seconds: int = 5,
) -> None:
    """Take transaction-scoped write locks before the one-time mutation.

    ``teams`` and ``elo_rating_snapshots`` are locked despite never being
    written: the manifest's own re-derivation reads both to decide orphan-ness
    and to evidence the target's history, so a concurrent writer could
    otherwise move that evidence between the digest check and the update.
    ACCESS SHARE readers (normal prediction/Elo lookups) still proceed. The
    lock timeout makes contention fail closed rather than wedge a release.
    """
    if session.bind is None or session.bind.dialect.name != "postgresql":
        raise RuntimeError("orphan team rebind requires PostgreSQL")
    timeout_ms = max(1, int(lock_timeout_seconds * 1000))
    await session.execute(text(f"SET LOCAL lock_timeout = '{timeout_ms}ms'"))
    await session.execute(
        text(
            "LOCK TABLE teams, matches, elo_rating_snapshots "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    )


def _assert_manifest_is_applicable(manifest: OrphanTeamRepairManifest) -> None:
    if not manifest.entries:
        raise RuntimeError("orphan team rebind manifest has no entries to apply")

    blocked = [entry for entry in manifest.entries if not entry.repair_ready]
    if blocked:
        detail = ", ".join(
            f"{entry.match_id}/{entry.side}({'|'.join(entry.blockers)})"
            for entry in blocked
        )
        raise RuntimeError(f"orphan team rebind refuses blocked entries: {detail}")

    for entry in manifest.entries:
        if entry.side not in _APPLICABLE_SIDES:
            raise RuntimeError(f"unexpected manifest side {entry.side!r}")
        if not entry.target_team_id or entry.target_team_id == entry.orphan_team_id:
            raise RuntimeError(
                f"manifest entry {entry.match_id}/{entry.side} has no distinct target"
            )
        if entry.target_elo_snapshot_count <= 0:
            raise RuntimeError(
                f"manifest entry {entry.match_id}/{entry.side} target carries no Elo history"
            )

    # One side may appear at most once. A duplicate would mean two different
    # targets are proposed for the same column and the later would silently win.
    seen: set[tuple[str, str]] = set()
    for entry in manifest.entries:
        key = (entry.match_id, entry.side)
        if key in seen:
            raise RuntimeError(f"manifest proposes {key} more than once")
        seen.add(key)


async def apply_orphan_team_rebind(
    session: AsyncSession,
    *,
    expected_manifest_sha256: str,
    lock_timeout_seconds: int = 5,
) -> OrphanTeamRebindResult:
    """Repoint reviewed orphan fixture sides at their history-bearing teams.

    The caller must commit explicitly. The manifest digest is re-derived while
    holding the production write locks, so any change to a match, a team, the
    freshest observed provider name, or the target's Elo evidence since review
    aborts before a single row is written.
    """
    await acquire_orphan_team_rebind_locks(
        session, lock_timeout_seconds=lock_timeout_seconds
    )

    manifest = await build_orphan_team_repair_manifest(session)
    if manifest.manifest_sha256 != expected_manifest_sha256:
        raise RuntimeError(
            "orphan team rebind manifest changed since review: "
            f"expected={expected_manifest_sha256} actual={manifest.manifest_sha256}"
        )
    _assert_manifest_is_applicable(manifest)

    reversals: list[tuple[str, str, str, str]] = []
    for entry in manifest.entries:
        match = await session.get(Match, entry.match_id)
        if match is None:
            raise RuntimeError(f"match {entry.match_id} disappeared under lock")

        column = "home_team_id" if entry.side == "home" else "away_team_id"
        current = getattr(match, column)
        if current != entry.orphan_team_id:
            # Optimistic precondition: the row must still hold exactly what the
            # reviewed manifest recorded, or someone else has already moved it.
            raise RuntimeError(
                f"{entry.match_id}.{column} precondition failed: "
                f"expected={entry.orphan_team_id} actual={current}"
            )
        setattr(match, column, entry.target_team_id)
        reversals.append(
            (entry.match_id, entry.side, entry.orphan_team_id, entry.target_team_id)
        )

    await session.flush()

    affected = tuple(sorted({entry.match_id for entry in manifest.entries}))

    # Postcondition 1: no fixture may now record a team playing itself. This is
    # the failure mode the manifest's own collision guard exists to prevent, and
    # production has already produced 26 such rows once (docs/DEBT.md item 23),
    # so it is re-checked against the written state rather than trusted.
    self_play = (
        (
            await session.execute(
                select(Match.id).where(
                    Match.id.in_(affected),
                    Match.home_team_id == Match.away_team_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if self_play:
        raise RuntimeError(
            f"orphan team rebind postcondition failed: self-play matches {sorted(self_play)}"
        )

    # Postcondition 2: re-deriving the manifest must no longer propose any of
    # the sides just written. Each target carries real Elo in the same league,
    # so those sides are no longer orphans and must drop out entirely.
    residual_manifest = await build_orphan_team_repair_manifest(session)
    residual = [
        f"{entry.match_id}/{entry.side}"
        for entry in residual_manifest.entries
        if (entry.match_id, entry.side) in {(e.match_id, e.side) for e in manifest.entries}
    ]
    if residual:
        raise RuntimeError(
            f"orphan team rebind postcondition failed: {residual} still proposed after rebind"
        )

    return OrphanTeamRebindResult(
        manifest_sha256=manifest.manifest_sha256,
        rebound_sides=len(manifest.entries),
        affected_match_ids=affected,
        leagues=tuple(sorted({entry.league_id for entry in manifest.entries})),
        reversals=tuple(reversals),
    )


__all__ = [
    "OrphanTeamRebindResult",
    "acquire_orphan_team_rebind_locks",
    "apply_orphan_team_rebind",
]
