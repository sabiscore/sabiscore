"""Read-only manifest: which tracked-corpus Understat matches can safely
populate ``match_stats``, and which cannot.

docs/DEBT.md item 56 Finding 5 named the actual blocker between "the xG corpus
exists" and "serving can compute the three CAUSAL_DRIVER xG features": nothing
carries the corpus's xG into ``match_stats``, which currently holds 0 rows in
production. This module is the review half of that write — it never writes
anything.

Entity resolution reuses the repository's one production team-identity
resolver, ``team_identity.resolve_team_id()`` (the exact function
``fixture_sync_service`` and the orphan-team-repair manifest both call).
CLAUDE.md is explicit that a second team-name normalizer beside it has caused
three separate production incidents; this module introduces none.

Match resolution has no equivalent shared helper (``reconcile_fixture()``
scores on name-similarity + kickoff, but by the time both team names are
already resolved to canonical ``team_id``, an exact-ID lookup with a kickoff
tolerance window is strictly more precise and needs no fuzzy scoring). The
window is 36 hours: wide enough to absorb any single-day timezone
misalignment between football-data.org's and Understat's recorded kickoff,
narrow enough that two fixtures of the *same* home/away pairing — always
months apart in any real season — can never both fall inside it.

Corpus filtering — COVID-cancelled rows and the cross-file ``game_id``
duplication — is owned by ``data.understat_corpus.load_corpus_matches`` and
documented there. Both matter here: a cancelled fixture is not a resolution
failure (there is no observation to report as blocked), and a duplicated one
would make this manifest propose the same ``match_stats`` row twice.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Match
from ..core.league_policy import canonical_league_id
# One corpus definition, shared with features.xg_replay: the write-ready set
# here and the rows that reach training must describe the same population.
from ..data.understat_corpus import load_corpus_matches
from .fixture_sync_service import is_unusable_team_name
from .team_identity import resolve_team_id

_MANIFEST_SCHEMA_VERSION = 1
_KICKOFF_TOLERANCE = timedelta(hours=36)

_STATUS_READY = "READY"
_STATUS_TEAM_UNRESOLVED = "TEAM_UNRESOLVED"
_STATUS_MATCH_UNRESOLVED = "MATCH_UNRESOLVED"
_STATUS_MATCH_AMBIGUOUS = "MATCH_AMBIGUOUS"


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class UnderstatMatchStatsEntry:
    league_id: str
    season: int
    kickoff_utc: str
    understat_home: str
    understat_away: str
    home_team_id: str | None
    away_team_id: str | None
    match_id: str | None
    home_xg: float
    away_xg: float
    status: str
    blockers: tuple[str, ...]

    @property
    def repair_ready(self) -> bool:
        return self.status == _STATUS_READY

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["repair_ready"] = self.repair_ready
        return payload


@dataclass(frozen=True)
class UnderstatMatchStatsManifest:
    schema_version: int
    manifest_sha256: str
    summary: dict[str, Any]
    entries: tuple[UnderstatMatchStatsEntry, ...]
    """Every row the corpus offered, ready or not. Kept in full (not just the
    ready subset) so the manifest hash a future --apply gate checks proves the
    reviewer saw the same complete picture, not a filtered one."""


async def _resolve_team_cached(
    name: str,
    league_id: str,
    session: AsyncSession,
    cache: dict[tuple[str, str], str | None],
) -> str | None:
    """``resolve_team_id`` result cached per (league, name) for one review run.

    A team name repeats roughly 15-19 times per season; without this cache a
    12k-row corpus issues ~25k resolver calls against an unchanging snapshot
    for no reason. The cache lives only for the duration of one manifest
    build — it is never persisted, unlike ``ProviderTeamMapping``, which is
    the durable equivalent for live fixture sync.
    """
    key = (league_id, name)
    if key not in cache:
        if is_unusable_team_name(name):
            cache[key] = None
        else:
            cache[key] = await resolve_team_id(
                name, session, league_id=league_id, require_elo_history=True
            )
    return cache[key]


async def _load_match_index(
    session: AsyncSession, league_ids: set[str]
) -> dict[tuple[str, str, str], list[tuple[str, datetime]]]:
    """Prefetch every ``Match`` in the corpus's leagues, indexed by
    ``(league_id, home_team_id, away_team_id)`` -> ``[(match_id, match_date), ...]``.

    A first review run against production issued one ``SELECT`` per corpus
    row (~13,000 sequential round trips over the WAN to Render's Postgres)
    and died mid-run with ``ConnectionDoesNotExistError`` -- the connection
    was reset partway through, not because anything was wrong, just because
    holding one session open for that many round trips is fragile. The full
    match table for these five leagues is a few thousand rows; loading it
    once and resolving every corpus row against the in-memory index cuts
    round trips from ~13,000 to one per league.
    """
    if not league_ids:
        return {}
    rows = (
        await session.execute(
            select(Match.id, Match.league_id, Match.home_team_id, Match.away_team_id, Match.match_date).where(
                Match.league_id.in_(league_ids)
            )
        )
    ).all()
    index: dict[tuple[str, str, str], list[tuple[str, datetime]]] = {}
    for match_id, league_id, home_team_id, away_team_id, match_date in rows:
        key = (str(league_id), str(home_team_id), str(away_team_id))
        index.setdefault(key, []).append((str(match_id), match_date))
    return index


def _kickoff_window(kickoff: datetime) -> tuple[datetime, datetime]:
    """The (start, end) tolerance bounds around ``kickoff``, tz-stripped.

    ``Match.match_date`` is a naive ``TIMESTAMP WITHOUT TIME ZONE`` column;
    asyncpg raises a ``DataError`` if a tz-aware Python datetime is bound
    against it. This is an established, repeatedly-documented trap in this
    codebase — see ``upcoming_match_feature_service.py:230`` and
    ``notification_dispatch_service._now_naive_utc()`` for the same fix
    elsewhere. Pulled into its own pure function so the tz-stripping is unit
    testable without a real Postgres connection: SQLite (this module's own
    test suite) silently accepts a tz-aware bind and would not catch a
    regression here on its own.
    """
    return (
        (kickoff - _KICKOFF_TOLERANCE).replace(tzinfo=None),
        (kickoff + _KICKOFF_TOLERANCE).replace(tzinfo=None),
    )


def _resolve_match_id(
    match_index: dict[tuple[str, str, str], list[tuple[str, datetime]]],
    *,
    league_id: str,
    home_team_id: str,
    away_team_id: str,
    kickoff: datetime,
) -> tuple[str | None, str]:
    """Exact-ID lookup within a kickoff tolerance window, against the
    prefetched in-memory index (see ``_load_match_index``) — no DB round trip.

    Returns (match_id, status) where status is one of MATCH_UNRESOLVED (zero
    candidates), MATCH_AMBIGUOUS (more than one — fails closed rather than
    guessing), or the found id with status="" (caller treats non-empty
    match_id as resolved).
    """
    window_start, window_end = _kickoff_window(kickoff)
    candidates = match_index.get((league_id, home_team_id, away_team_id), ())
    matches = [match_id for match_id, match_date in candidates if window_start <= match_date <= window_end]

    if not matches:
        return None, _STATUS_MATCH_UNRESOLVED
    if len(matches) > 1:
        return None, _STATUS_MATCH_AMBIGUOUS
    return matches[0], ""


async def build_understat_match_stats_manifest(
    session: AsyncSession,
    sources_dir: Path,
) -> UnderstatMatchStatsManifest:
    """Read-only reconciliation of the tracked corpus against canonical identity.

    Issues SELECT statements only — no INSERT, UPDATE, or bind. Safe to call
    inside a rolled-back transaction, exactly as
    ``build_orphan_team_repair_manifest`` documents for its own read-only
    contract.
    """
    corpus = load_corpus_matches(sources_dir)
    team_cache: dict[tuple[str, str], str | None] = {}
    entries: list[UnderstatMatchStatsEntry] = []

    league_ids = {canonical_league_id(str(league)) for league in corpus["sabi_league"].unique()}
    match_index = await _load_match_index(session, league_ids)

    for row in corpus.itertuples(index=False):
        league_id = canonical_league_id(str(row.sabi_league))
        kickoff = pd.Timestamp(row.date).to_pydatetime()
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)

        home_team_id = await _resolve_team_cached(str(row.home_team), league_id, session, team_cache)
        away_team_id = await _resolve_team_cached(str(row.away_team), league_id, session, team_cache)

        blockers: list[str] = []
        match_id: str | None = None
        status = _STATUS_READY

        if home_team_id is None:
            blockers.append(f"home_team_unresolved:{row.home_team!r}")
        if away_team_id is None:
            blockers.append(f"away_team_unresolved:{row.away_team!r}")

        if blockers:
            status = _STATUS_TEAM_UNRESOLVED
        else:
            match_id, match_status = _resolve_match_id(
                match_index,
                league_id=league_id,
                home_team_id=home_team_id,  # type: ignore[arg-type]
                away_team_id=away_team_id,  # type: ignore[arg-type]
                kickoff=kickoff,
            )
            if match_status:
                status = match_status
                blockers.append(match_status.lower())

        entries.append(
            UnderstatMatchStatsEntry(
                league_id=league_id,
                season=int(row.sabi_season),
                kickoff_utc=kickoff.isoformat(),
                understat_home=str(row.home_team),
                understat_away=str(row.away_team),
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                match_id=match_id,
                home_xg=float(row.home_xg),
                away_xg=float(row.away_xg),
                status=status,
                blockers=tuple(blockers),
            )
        )

    summary = dict(Counter(entry.status for entry in entries))
    summary["total_rows"] = len(entries)
    summary["ready_rows"] = sum(1 for e in entries if e.repair_ready)

    manifest_sha256 = _canonical_sha256([entry.as_dict() for entry in entries])
    return UnderstatMatchStatsManifest(
        schema_version=_MANIFEST_SCHEMA_VERSION,
        manifest_sha256=manifest_sha256,
        summary=summary,
        entries=tuple(entries),
    )
