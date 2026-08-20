"""Repair legacy ``matches`` rows where a team was recorded as playing itself.

Root cause (see docs/DEBT.md item 23): an earlier, since-fixed version of
``historical_backfill_service.TeamIndex`` mis-resolved a handful of opponent
short-names (``Milan``, ``Barcelona``, ``Paris SG``) onto the *other* side's
team id (``Inter``, ``Espanyol``, ``Paris FC`` respectively). The resolver
itself is already correct today — verified by re-resolving every known
corrupted row's original raw team names through a fresh ``TeamIndex`` seeded
from the live ``teams`` table. This is therefore a data repair, not an
algorithm change: it recovers each corrupted row's original raw CSV names via
the deterministic ``historical_match_id`` hash (which is keyed on the raw
names, not on any resolved team id) and re-resolves them with today's logic.

A row is only ever repaired when re-resolution yields two *distinct* team
ids. A row that still collides, or whose original CSV row can't be found, is
skipped and reported — never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Match, Team
from .historical_backfill_service import (
    TeamIndex,
    default_cache_dir,
    historical_match_id,
    parse_fd_csv,
)


@dataclass
class RepairReport:
    corrupted_found: int = 0
    repaired: int = 0
    skipped: int = 0
    lines: list[str] = field(default_factory=list)


async def find_and_repair_self_play_matches(
    session: AsyncSession, *, cache_dir: Optional[Path] = None, apply: bool
) -> RepairReport:
    """Find ``matches`` rows with ``home_team_id == away_team_id`` and, where the
    original raw CSV team names are recoverable and re-resolve unambiguously under
    today's ``TeamIndex``, correct them. See module docstring for root cause.
    """
    report = RepairReport()
    corrupted = (
        await session.execute(select(Match).where(Match.home_team_id == Match.away_team_id))
    ).scalars().all()
    corrupted_ids = {str(m.id): m for m in corrupted}
    report.corrupted_found = len(corrupted_ids)
    if not corrupted_ids:
        return report

    # Recover each corrupted row's original raw (home, away) names by recomputing
    # the deterministic id — keyed on raw names, not resolved team ids — from
    # every locally-cached CSV row.
    directory = cache_dir or default_cache_dir()
    recovered: dict[str, tuple[str, str, str]] = {}
    for path in sorted(directory.glob("fd_*.csv")):
        for row in parse_fd_csv(path):
            mid = historical_match_id(row.league_id, row.match_date, row.home_team, row.away_team)
            if mid in corrupted_ids:
                recovered[mid] = (row.league_id, row.home_team, row.away_team)

    index = TeamIndex((await session.execute(select(Team.id, Team.name))).tuples().all())

    for match_id, match in corrupted_ids.items():
        found = recovered.get(match_id)
        if found is None:
            report.lines.append(f"SKIP {match_id}: original CSV row not found in local cache")
            report.skipped += 1
            continue
        league_id, home_name, away_name = found
        home_id = index.resolve(home_name)
        away_id = index.resolve(away_name)
        if not home_id or not away_id or home_id == away_id:
            report.lines.append(
                f"SKIP {match_id}: re-resolution still ambiguous "
                f"({home_name!r}->{home_id}, {away_name!r}->{away_id})"
            )
            report.skipped += 1
            continue
        report.lines.append(
            f"REPAIR {match_id} ({league_id}, {match.match_date.date()}): "
            f"{home_name!r}->{home_id}  {away_name!r}->{away_id}"
        )
        report.repaired += 1
        if apply:
            await session.execute(
                update(Match)
                .where(Match.id == match_id)
                .values(home_team_id=home_id, away_team_id=away_id)
            )

    if apply:
        await session.commit()
    return report
