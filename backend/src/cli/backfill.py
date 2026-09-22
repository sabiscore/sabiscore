"""CLI for the historical match backfill.

The same backfill runs automatically on the boot tick of the fixture-sync task
(``api/main.py``). This command exists for operator use: forcing a re-check after
adding a season CSV, and inspecting coverage without waiting for a redeploy.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import click


@click.group("backfill")
def backfill_cli() -> None:
    """Historical match-history operations."""


@backfill_cli.command("history")
@click.option(
    "--cache-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Directory of fd_*.csv season files (defaults to backend/data/cache).",
)
@click.option(
    "--dry-run", is_flag=True, help="Parse and report without writing to the database."
)
def history(cache_dir: Optional[Path], dry_run: bool) -> None:
    """Load completed matches from committed football-data.co.uk CSVs."""
    from ..services.historical_backfill_service import (
        default_cache_dir,
        parse_fd_csv,
        run_historical_backfill,
    )

    directory = cache_dir or default_cache_dir()

    if dry_run:
        files = sorted(directory.glob("fd_*.csv"))
        parsed = [row for path in files for row in parse_fd_csv(path)]
        by_league: dict[str, int] = {}
        for row in parsed:
            by_league[row.league_id] = by_league.get(row.league_id, 0) + 1
        click.echo(
            json.dumps(
                {
                    "dry_run": True,
                    "cache_dir": str(directory),
                    "files_read": len(files),
                    "rows_parsed": len(parsed),
                    "unique_match_ids": len({r.match_id for r in parsed}),
                    "leagues": by_league,
                    "date_range": (
                        [
                            min(r.match_date for r in parsed).date().isoformat(),
                            max(r.match_date for r in parsed).date().isoformat(),
                        ]
                        if parsed
                        else None
                    ),
                },
                indent=2,
            )
        )
        return

    report = asyncio.run(run_historical_backfill())
    if report is None:
        raise SystemExit("historical backfill failed — see logs")
    click.echo(json.dumps(report.as_dict(), indent=2))


@backfill_cli.command("coverage")
def coverage() -> None:
    """Report how many upcoming fixtures have real history on BOTH sides.

    This is the metric that decides whether a prediction is publishable at all:
    ``_get_team_stats()`` returning None for either side sets ``is_synthetic``,
    which suppresses the prediction.
    """
    from sqlalchemy import select

    from ..core.database import Match, Team

    async def _run() -> dict:
        from ..db.session import AsyncSessionLocal, init_db

        await init_db()
        if AsyncSessionLocal is None:
            raise SystemExit("database unavailable")

        async with AsyncSessionLocal() as session:
            finished = (
                await session.execute(
                    select(Match.home_team_id, Match.away_team_id).where(
                        Match.status == "finished"
                    )
                )
            ).all()
            with_history = {tid for row in finished for tid in row if tid}

            upcoming = (
                await session.execute(
                    select(
                        Match.league_id, Match.home_team_id, Match.away_team_id
                    ).where(Match.status == "scheduled")
                )
            ).all()
            names = dict((await session.execute(select(Team.id, Team.name))).all())

        per_league: dict[str, dict] = {}
        missing: set[str] = set()
        for league_id, home_id, away_id in upcoming:
            bucket = per_league.setdefault(
                league_id or "UNKNOWN", {"total": 0, "covered": 0}
            )
            bucket["total"] += 1
            if home_id in with_history and away_id in with_history:
                bucket["covered"] += 1
            else:
                missing.update(
                    names.get(t, t) for t in (home_id, away_id) if t not in with_history
                )

        return {
            "finished_matches": len(finished),
            "teams_with_history": len(with_history),
            "per_league": per_league,
            "upcoming_teams_without_history": sorted(missing),
        }

    click.echo(json.dumps(asyncio.run(_run()), indent=2))
