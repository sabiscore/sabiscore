"""Class C executor for the reviewed Understat ``match_stats`` xG backfill.

``understat_match_stats_reconciliation_service`` proves, read-only, which
tracked-corpus Understat matches reconcile to a canonical ``Match`` through the
one production team resolver. This module is the only thing that acts on that
proof, and it writes exactly one column: ``MatchStats.expected_goals``.

Scope, stated as narrowly as it is implemented:

* it INSERTs ``match_stats`` rows and nothing else — no UPDATE, no DELETE;
* it never creates, renames, or repoints a ``Match`` or a ``Team``;
* it populates ``expected_goals`` only. The Understat match frame carries
  ``home_goals``/``away_goals``/``home_xg``/``away_xg`` and no shot counts at
  all, so ``shots``, ``shots_on_target``, ``possession``, ``corners``, ``fouls``
  and the card columns stay NULL. NULL is the honest record of "not observed";
  a zero there would be read downstream as an observed zero-shot match.

Two rows per reconciled fixture, one per side, because that is the shape
``upcoming_match_feature_service._get_team_xg_series`` reads: it keys on
``(match_id, team_id)`` and decides for/against by comparing ``team_id``.

Production safety mirrors ``orphan_team_rebind_service`` exactly — PostgreSQL
only, transaction-scoped write locks, the reviewed manifest digest re-derived
*under* those locks, and postconditions that must pass before the caller
commits.

⚠️ ``match_stats`` has no unique constraint on ``(match_id, team_id)`` — only
the non-unique ``ix_match_stats_match_team`` index (alembic 0001). There is
therefore no ``ON CONFLICT`` target available, and a blind INSERT would silently
duplicate rows on a second run, which ``_get_team_xg_series`` would then read as
one match contributing twice to a rolling mean. Idempotency is enforced here
instead, by reading the existing rows for the proposed pairs under the same lock
and refusing to write over any of them (see ``_partition_against_existing``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import MatchStats
from .understat_match_stats_reconciliation_service import (
    UnderstatMatchStatsManifest,
    build_understat_match_stats_manifest,
)


def _now_naive_utc() -> datetime:
    """asyncpg raises DataError binding a tz-aware datetime against a naive
    ``TIMESTAMP WITHOUT TIME ZONE`` column, which ``MatchStats.created_at`` is.
    Same trap, same fix as ``_kickoff_window`` in the reconciliation service.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


#: Two rows differ meaningfully below this only through float round-tripping.
_XG_ATOL = 1e-9

#: Bound on any single ``IN (...)`` list built from the corpus, which is ~12k
#: fixtures wide.
_ID_CHUNK = 1000


@dataclass(frozen=True)
class UnderstatMatchStatsBackfillResult:
    manifest_sha256: str
    inserted_rows: int
    matches_written: int
    already_present_rows: int
    skipped_unresolved_entries: int
    leagues: tuple[str, ...]
    #: The exact ``(match_id, team_id)`` pairs inserted — the DELETE key needed
    #: to undo this by hand. Keep it with the authorization record.
    reversals: tuple[tuple[str, str], ...]


async def acquire_match_stats_backfill_locks(
    session: AsyncSession,
    *,
    lock_timeout_seconds: int = 5,
) -> None:
    """Take transaction-scoped write locks before the one-time insert.

    ``matches`` and ``teams`` are locked despite never being written: the
    manifest's own re-derivation resolves every corpus row against both, so a
    concurrent identity repair could otherwise move that evidence between the
    digest check and the insert. ACCESS SHARE readers (normal prediction and
    feature-projection queries) still proceed. The lock timeout makes contention
    fail closed rather than wedge a release.
    """
    if session.bind is None or session.bind.dialect.name != "postgresql":
        raise RuntimeError("understat match_stats backfill requires PostgreSQL")
    timeout_ms = max(1, int(lock_timeout_seconds * 1000))
    await session.execute(text(f"SET LOCAL lock_timeout = '{timeout_ms}ms'"))
    await session.execute(
        text("LOCK TABLE match_stats, matches, teams IN SHARE ROW EXCLUSIVE MODE")
    )


def _proposed_rows(manifest: UnderstatMatchStatsManifest) -> list[dict[str, Any]]:
    """Two ``match_stats`` payloads per READY entry, home side first.

    Blocked entries are dropped here rather than raising, which is the one
    deliberate divergence from ``orphan_team_rebind_service``'s
    ``_assert_manifest_is_applicable``. That manifest is a short, hand-reviewed
    list where a single blocked row means the review is stale. This one is a
    12k-row corpus in which some rows are *permanently* unreconcilable (a club
    with no fixture in our ``matches`` table can never resolve), so refusing the
    whole run over them would mean the backfill can never be applied at all.
    The blocked count is reported, never silently absorbed.
    """
    created_at = _now_naive_utc()
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for entry in manifest.entries:
        if not entry.repair_ready:
            continue
        if (
            entry.match_id is None
            or entry.home_team_id is None
            or entry.away_team_id is None
        ):
            # repair_ready is defined as status == READY, which is only reached
            # once all three are set. Defensive: a future status change that
            # broke that invariant must fail here, not write a NULL-keyed row.
            raise RuntimeError(f"READY entry is missing identity: {entry.as_dict()}")
        if entry.home_team_id == entry.away_team_id:
            raise RuntimeError(
                f"match {entry.match_id} resolves both sides to {entry.home_team_id}"
            )
        for team_id, xg in (
            (entry.home_team_id, entry.home_xg),
            (entry.away_team_id, entry.away_xg),
        ):
            key = (entry.match_id, team_id)
            if key in seen:
                # Two corpus rows reconciled to the same fixture would make the
                # later one silently win. The manifest's kickoff window is meant
                # to prevent this; re-check rather than trust it.
                raise RuntimeError(f"manifest proposes {key} more than once")
            seen.add(key)
            rows.append(
                {
                    "match_id": entry.match_id,
                    "team_id": team_id,
                    "expected_goals": float(xg),
                    "created_at": created_at,
                }
            )
    return rows


async def _existing_xg_by_key(
    session: AsyncSession, match_ids: list[str]
) -> dict[tuple[str, str], float | None]:
    existing: dict[tuple[str, str], float | None] = {}
    for start in range(0, len(match_ids), _ID_CHUNK):
        chunk = match_ids[start : start + _ID_CHUNK]
        found = (
            await session.execute(
                select(
                    MatchStats.match_id, MatchStats.team_id, MatchStats.expected_goals
                ).where(MatchStats.match_id.in_(chunk))
            )
        ).all()
        for match_id, team_id, expected_goals in found:
            existing[(str(match_id), str(team_id))] = expected_goals
    return existing


async def _partition_against_existing(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Split ``rows`` into (to-insert, already-present-count).

    A pair that already exists with the same xG is an idempotent no-op and is
    dropped. A pair that already exists with a DIFFERENT xG is someone else's
    observation, and this backfill has no authority to overwrite it — that
    fails the run closed rather than choosing a winner.
    """
    if not rows:
        return [], 0

    existing = await _existing_xg_by_key(
        session, sorted({row["match_id"] for row in rows})
    )

    to_insert: list[dict[str, Any]] = []
    already = 0
    conflicts: list[str] = []
    for row in rows:
        key = (row["match_id"], row["team_id"])
        if key not in existing:
            to_insert.append(row)
            continue
        current = existing[key]
        if current is None or abs(float(current) - row["expected_goals"]) > _XG_ATOL:
            conflicts.append(f"{key}: stored={current} manifest={row['expected_goals']}")
        else:
            already += 1

    if conflicts:
        detail = "; ".join(conflicts[:10])
        if len(conflicts) > 10:
            detail += f" (+{len(conflicts) - 10} more)"
        raise RuntimeError(
            f"understat match_stats backfill refuses to overwrite existing rows: {detail}"
        )
    return to_insert, already


async def _assert_written_exactly_once(
    session: AsyncSession, to_insert: list[dict[str, Any]]
) -> None:
    """Read the written pairs back; require one row each, carrying our value.

    Absent a unique constraint this is the only thing that proves no duplicate
    was created, and it is checked against the written state rather than
    trusted.
    """
    written_by_key = {
        (row["match_id"], row["team_id"]): row["expected_goals"] for row in to_insert
    }
    existing = await _existing_xg_by_key(
        session, sorted({row["match_id"] for row in to_insert})
    )

    seen: set[tuple[str, str]] = set()
    for key, expected_goals in existing.items():
        if key not in written_by_key:
            continue
        seen.add(key)
        if (
            expected_goals is None
            or abs(float(expected_goals) - written_by_key[key]) > _XG_ATOL
        ):
            raise RuntimeError(
                f"understat match_stats backfill postcondition failed: {key} "
                f"read back {expected_goals}, wrote {written_by_key[key]}"
            )

    missing = sorted(set(written_by_key) - seen)
    if missing:
        raise RuntimeError(
            f"understat match_stats backfill postcondition failed: missing={missing[:5]}"
        )


async def apply_understat_match_stats_backfill(
    session: AsyncSession,
    *,
    expected_manifest_sha256: str,
    sources_dir: Path,
    batch_size: int = 1000,
    lock_timeout_seconds: int = 5,
) -> UnderstatMatchStatsBackfillResult:
    """Insert reviewed Understat xG into ``match_stats``.

    The caller must commit explicitly. The manifest digest is re-derived while
    holding the production write locks, so any change to a match, a team, or the
    resolver's answer since review aborts before a single row is written.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    await acquire_match_stats_backfill_locks(
        session, lock_timeout_seconds=lock_timeout_seconds
    )

    manifest = await build_understat_match_stats_manifest(session, sources_dir)
    if manifest.manifest_sha256 != expected_manifest_sha256:
        raise RuntimeError(
            "understat match_stats manifest changed since review: "
            f"expected={expected_manifest_sha256} actual={manifest.manifest_sha256}"
        )

    proposed = _proposed_rows(manifest)
    if not proposed:
        raise RuntimeError("understat match_stats manifest has no READY entries to apply")

    to_insert, already_present = await _partition_against_existing(session, proposed)

    before = int(
        (await session.execute(select(func.count()).select_from(MatchStats))).scalar_one()
    )
    for start in range(0, len(to_insert), batch_size):
        await session.execute(insert(MatchStats), to_insert[start : start + batch_size])
    await session.flush()

    after = int(
        (await session.execute(select(func.count()).select_from(MatchStats))).scalar_one()
    )
    if after - before != len(to_insert):
        raise RuntimeError(
            "understat match_stats backfill postcondition failed: row delta "
            f"{after - before} != inserted {len(to_insert)}"
        )

    await _assert_written_exactly_once(session, to_insert)

    ready_entries = [entry for entry in manifest.entries if entry.repair_ready]
    return UnderstatMatchStatsBackfillResult(
        manifest_sha256=manifest.manifest_sha256,
        inserted_rows=len(to_insert),
        matches_written=len({row["match_id"] for row in to_insert}),
        already_present_rows=already_present,
        skipped_unresolved_entries=len(manifest.entries) - len(ready_entries),
        leagues=tuple(sorted({entry.league_id for entry in ready_entries})),
        reversals=tuple((row["match_id"], row["team_id"]) for row in to_insert),
    )


__all__ = [
    "UnderstatMatchStatsBackfillResult",
    "acquire_match_stats_backfill_locks",
    "apply_understat_match_stats_backfill",
]
