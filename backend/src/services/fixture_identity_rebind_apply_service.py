"""Class C executor for the reviewed live-fixture identity rebind.

docs/DEBT.md item 35(b). ``fixture_identity_rebind_service`` proves, read-only,
that a scheduled fixture's persisted ``Match.home_team_id``/``away_team_id``
disagrees with the already-verified canonical identity
(``CanonicalFixture.home_team_id``/``away_team_id``, resolved every tick by
``ensure_canonical_fixture`` regardless of whether the legacy row was
flagged). ``fixture_sync_service`` deliberately leaves the row unchanged when
it detects this. This module is the only thing that acts on that proof.

Scope mirrors the item-39 ``orphan_team_rebind_service`` precedent: it writes
``Match.home_team_id`` / ``Match.away_team_id`` and nothing else -- no
``Team``/``CanonicalTeam`` created, renamed, or deleted, no
``EloRatingSnapshot`` touched.

**Deliberate deviation from that precedent.** Orphan rebind refuses the whole
apply if *any* manifest entry is blocked -- safe there because that manifest
happened to reach zero-blocked before it was applied. This item's live
manifest is routinely a mix of ready and blocked entries, and a
``HAS_EXISTING_PREDICTIONS`` blocker will not resolve on its own (predictions
are not deleted), so an all-or-nothing rule would make this permanently
inapplicable. This executor therefore re-derives and digest-checks the full
manifest (so nothing about the reviewed state -- ready OR blocked -- may have
drifted since review), then writes only the entries whose ``blockers`` tuple
is empty, leaving blocked entries untouched and still visible on the next
review.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Match
from .fixture_identity_rebind_service import (
    FixtureIdentityRebindManifest,
    build_fixture_identity_rebind_manifest,
)


@dataclass(frozen=True)
class FixtureIdentityRebindApplyResult:
    manifest_sha256: str
    rebound_count: int
    affected_match_ids: tuple[str, ...]
    skipped_blocked_match_ids: tuple[str, ...]
    leagues: tuple[str, ...]
    # (match_id, column, from_team_id, to_team_id) -- the exact inverse needed
    # to undo this by hand.
    reversals: tuple[tuple[str, str, str, str], ...]


async def acquire_fixture_identity_rebind_locks(
    session: AsyncSession,
    *,
    lock_timeout_seconds: int = 5,
) -> None:
    """Take transaction-scoped write locks before the mutation.

    ``canonical_fixtures``, ``provider_event_mappings`` and
    ``match_prediction_logs`` are locked despite never being written: the
    manifest's own re-derivation reads all three to decide what is verified,
    what is drifted, and what is blocked, so a concurrent fixture-sync tick or
    a new prediction could otherwise move that evidence between the digest
    check and the write. The lock timeout makes contention fail closed rather
    than wedge a release.
    """
    if session.bind is None or session.bind.dialect.name != "postgresql":
        raise RuntimeError("fixture identity rebind requires PostgreSQL")
    timeout_ms = max(1, int(lock_timeout_seconds * 1000))
    await session.execute(text(f"SET LOCAL lock_timeout = '{timeout_ms}ms'"))
    await session.execute(
        text(
            "LOCK TABLE matches, canonical_fixtures, provider_event_mappings, "
            "match_prediction_logs IN SHARE ROW EXCLUSIVE MODE"
        )
    )


def _ready_entries(manifest: FixtureIdentityRebindManifest):
    return [entry for entry in manifest.entries if entry.rebind_ready]


def _assert_ready_entries_are_applicable(manifest: FixtureIdentityRebindManifest) -> None:
    ready = _ready_entries(manifest)
    if not ready:
        raise RuntimeError(
            "fixture identity rebind has no rebind-ready entries to apply "
            f"({len(manifest.entries)} entries total, all blocked)"
        )

    for entry in ready:
        if not entry.verified_home_team_id or not entry.verified_away_team_id:
            raise RuntimeError(
                f"manifest entry {entry.match_id} has no distinct verified identity"
            )
        if entry.verified_home_team_id == entry.verified_away_team_id:
            raise RuntimeError(
                f"manifest entry {entry.match_id} verified identity is self-play"
            )

    seen: set[str] = set()
    for entry in ready:
        if entry.match_id in seen:
            raise RuntimeError(f"manifest proposes {entry.match_id} more than once")
        seen.add(entry.match_id)


async def apply_fixture_identity_rebind(
    session: AsyncSession,
    *,
    expected_manifest_sha256: str,
    lock_timeout_seconds: int = 5,
) -> FixtureIdentityRebindApplyResult:
    """Repoint reviewed drifted fixtures at their verified canonical identity.

    The caller must commit explicitly. The full manifest digest -- ready and
    blocked entries alike -- is re-derived while holding the production write
    locks, so any change to a match, its canonical fixture, or its prediction
    state since review aborts before a single row is written. Only entries
    with no blockers are written; blocked entries are left untouched.
    """
    await acquire_fixture_identity_rebind_locks(
        session, lock_timeout_seconds=lock_timeout_seconds
    )

    manifest = await build_fixture_identity_rebind_manifest(session)
    if manifest.manifest_sha256 != expected_manifest_sha256:
        raise RuntimeError(
            "fixture identity rebind manifest changed since review: "
            f"expected={expected_manifest_sha256} actual={manifest.manifest_sha256}"
        )
    _assert_ready_entries_are_applicable(manifest)

    ready = _ready_entries(manifest)
    reversals: list[tuple[str, str, str, str]] = []
    for entry in ready:
        match = await session.get(Match, entry.match_id)
        if match is None:
            raise RuntimeError(f"match {entry.match_id} disappeared under lock")

        if match.home_team_id != entry.stored_home_team_id:
            raise RuntimeError(
                f"{entry.match_id}.home_team_id precondition failed: "
                f"expected={entry.stored_home_team_id} actual={match.home_team_id}"
            )
        if match.away_team_id != entry.stored_away_team_id:
            raise RuntimeError(
                f"{entry.match_id}.away_team_id precondition failed: "
                f"expected={entry.stored_away_team_id} actual={match.away_team_id}"
            )

        assert entry.verified_home_team_id is not None
        assert entry.verified_away_team_id is not None
        if entry.stored_home_team_id != entry.verified_home_team_id:
            match.home_team_id = entry.verified_home_team_id
            reversals.append(
                (entry.match_id, "home_team_id", entry.stored_home_team_id, entry.verified_home_team_id)
            )
        if entry.stored_away_team_id != entry.verified_away_team_id:
            match.away_team_id = entry.verified_away_team_id
            reversals.append(
                (entry.match_id, "away_team_id", entry.stored_away_team_id, entry.verified_away_team_id)
            )

    await session.flush()

    affected = tuple(sorted(entry.match_id for entry in ready))
    blocked = tuple(
        sorted(entry.match_id for entry in manifest.entries if not entry.rebind_ready)
    )

    # Postcondition 1: no touched fixture may now record a team playing
    # itself -- the exact shape item 23's 26 production rows had.
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
            f"fixture identity rebind postcondition failed: self-play matches {sorted(self_play)}"
        )

    # Postcondition 2: re-deriving the manifest must no longer propose any of
    # the fixtures just written -- their stored and verified identity now
    # agree, so they must drop out of the mismatch list entirely.
    residual_manifest = await build_fixture_identity_rebind_manifest(session)
    residual = [
        entry.match_id for entry in residual_manifest.entries if entry.match_id in set(affected)
    ]
    if residual:
        raise RuntimeError(
            f"fixture identity rebind postcondition failed: {residual} still mismatched after rebind"
        )

    return FixtureIdentityRebindApplyResult(
        manifest_sha256=manifest.manifest_sha256,
        rebound_count=len(ready),
        affected_match_ids=affected,
        skipped_blocked_match_ids=blocked,
        leagues=tuple(sorted({entry.league_id for entry in ready})),
        reversals=tuple(reversals),
    )


__all__ = [
    "FixtureIdentityRebindApplyResult",
    "acquire_fixture_identity_rebind_locks",
    "apply_fixture_identity_rebind",
]
