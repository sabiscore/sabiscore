"""Read-only semantic identity audit for historical football-data.co.uk matches.

Structural Elo checks can be green while a Match participant points at a Team
owned by another competition. This service joins persisted historical matches to
both Team rows and the committed football-data.co.uk source cache so the exact
source identity remains visible during incident review and repair planning.

Nothing in this module mutates database state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..core.database import Match, Team
from .historical_backfill_service import HistoricalMatch, default_cache_dir, parse_fd_csv


@dataclass(frozen=True)
class HistoricalSourceIdentity:
    match_id: str
    league_id: str
    match_date: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    source_file: str


@dataclass(frozen=True)
class SemanticIdentityFinding:
    match_id: str
    match_date: str
    match_league: str
    stored_home_team_id: str
    stored_home_team_name: str | None
    stored_home_team_league: str | None
    stored_away_team_id: str
    stored_away_team_name: str | None
    stored_away_team_league: str | None
    home_league_mismatch: bool
    away_league_mismatch: bool
    source_record_found: bool
    source_file: str | None
    source_home_team: str | None
    source_away_team: str | None
    source_home_score: int | None
    source_away_score: int | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _source_identity(item: HistoricalMatch, source_file: str) -> HistoricalSourceIdentity:
    return HistoricalSourceIdentity(
        match_id=item.match_id,
        league_id=item.league_id,
        match_date=item.match_date.date().isoformat(),
        home_team=item.home_team,
        away_team=item.away_team,
        home_score=item.home_score,
        away_score=item.away_score,
        source_file=source_file,
    )


def build_historical_source_index(
    cache_dir: Path | None = None,
) -> dict[str, HistoricalSourceIdentity]:
    """Index committed source rows by the same deterministic id used by backfill.

    Duplicate source rows with an identical deterministic id must also be
    identical. A conflicting duplicate is an evidence-integrity failure and is
    raised rather than silently choosing one row.
    """
    directory = cache_dir or default_cache_dir()
    if not directory.is_dir():
        raise FileNotFoundError(f"historical cache directory not found: {directory}")

    index: dict[str, HistoricalSourceIdentity] = {}
    for path in sorted(directory.glob("fd_*.csv")):
        for item in parse_fd_csv(path):
            identity = _source_identity(item, path.name)
            existing = index.get(identity.match_id)
            if existing is not None and existing != identity:
                raise ValueError(
                    "conflicting historical source rows share deterministic match id "
                    f"{identity.match_id}: {existing.source_file} vs {path.name}"
                )
            index[identity.match_id] = identity
    return index


async def audit_historical_semantic_identity(
    session: AsyncSession,
    *,
    cache_dir: Path | None = None,
) -> list[SemanticIdentityFinding]:
    """Return cross-league participant findings with original source evidence.

    Only deterministic ``fdco-*`` historical matches are in scope. A Team whose
    declared league differs from the Match league is never reinterpreted here;
    the original CSV identity is attached for an operator-visible repair
    manifest. Missing Team rows and missing source evidence remain explicit
    findings rather than disappearing through an inner join or guessed fallback.
    """
    source_index = build_historical_source_index(cache_dir)
    home_team = aliased(Team, name="semantic_home_team")
    away_team = aliased(Team, name="semantic_away_team")

    rows = (
        await session.execute(
            select(
                Match.id,
                Match.match_date,
                Match.league_id,
                Match.home_team_id,
                home_team.name,
                home_team.league_id,
                Match.away_team_id,
                away_team.name,
                away_team.league_id,
            )
            .outerjoin(home_team, home_team.id == Match.home_team_id)
            .outerjoin(away_team, away_team.id == Match.away_team_id)
            .where(
                Match.id.like("fdco-%"),
                or_(
                    home_team.id.is_(None),
                    away_team.id.is_(None),
                    home_team.league_id != Match.league_id,
                    away_team.league_id != Match.league_id,
                    home_team.league_id.is_(None),
                    away_team.league_id.is_(None),
                ),
            )
            .order_by(Match.match_date, Match.id)
        )
    ).all()

    findings: list[SemanticIdentityFinding] = []
    for (
        match_id,
        match_date,
        match_league,
        stored_home_id,
        stored_home_name,
        stored_home_league,
        stored_away_id,
        stored_away_name,
        stored_away_league,
    ) in rows:
        source = source_index.get(str(match_id))
        findings.append(
            SemanticIdentityFinding(
                match_id=str(match_id),
                match_date=match_date.isoformat(),
                match_league=str(match_league),
                stored_home_team_id=str(stored_home_id),
                stored_home_team_name=(
                    str(stored_home_name) if stored_home_name is not None else None
                ),
                stored_home_team_league=(
                    str(stored_home_league) if stored_home_league is not None else None
                ),
                stored_away_team_id=str(stored_away_id),
                stored_away_team_name=(
                    str(stored_away_name) if stored_away_name is not None else None
                ),
                stored_away_team_league=(
                    str(stored_away_league) if stored_away_league is not None else None
                ),
                home_league_mismatch=stored_home_league != match_league,
                away_league_mismatch=stored_away_league != match_league,
                source_record_found=source is not None,
                source_file=source.source_file if source else None,
                source_home_team=source.home_team if source else None,
                source_away_team=source.away_team if source else None,
                source_home_score=source.home_score if source else None,
                source_away_score=source.away_score if source else None,
            )
        )
    return findings


def summarize_semantic_identity_findings(
    findings: Iterable[SemanticIdentityFinding],
) -> dict[str, object]:
    rows = list(findings)
    return {
        "affected_matches": len(rows),
        "home_league_mismatches": sum(row.home_league_mismatch for row in rows),
        "away_league_mismatches": sum(row.away_league_mismatch for row in rows),
        "source_records_found": sum(row.source_record_found for row in rows),
        "source_records_missing": sum(not row.source_record_found for row in rows),
        "first_affected_match": min((row.match_date for row in rows), default=None),
        "last_affected_match": max((row.match_date for row in rows), default=None),
    }
