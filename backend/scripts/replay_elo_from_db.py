"""Replay Elo ratings from real Match table rows.

Replaces the synthetically-keyed parquet (keyed by placeholder IDs like
"bundesliga_home_0") with ratings keyed by real Team.id values, enabling
EloEngine.get_context() to return non-neutral (non-1500/1500) ratings for
all teams that appear in the DB.

Usage (from backend/ directory):
    python scripts/replay_elo_from_db.py [--dry-run]

Requirements:
    - DATABASE_URL env var pointing to a Postgres or SQLite DB with Match rows
    - The Elo parquet output path from settings (elo_parquet_path)

The replay is idempotent: update_after_match() skips a match_id that already
exists in the parquet. Run again after new matches settle to extend the table.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running from backend/ or backend/scripts/
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR / "src") not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
    sys.path.insert(0, str(_BACKEND_DIR / "src"))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./sabiscore.db")
os.environ.setdefault("ALLOW_SQLITE_FALLBACK", "true")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.core.config import settings  # noqa: E402
from src.core.database import Match  # noqa: E402
from src.data.elo_engine import EloEngine  # noqa: E402
from src.utils.season import canonical_season  # noqa: E402


def _sync_engine():
    """Return a synchronous SQLAlchemy engine derived from the async DATABASE_URL."""
    url = str(settings.database_url).replace("+asyncpg", "").replace("+aiosqlite", "")
    return create_engine(url)


def replay(dry_run: bool = False) -> None:
    engine = _sync_engine()
    elo = EloEngine()

    with Session(engine) as session:
        matches = (
            session.query(Match)
            .filter(Match.status == "finished")
            .order_by(Match.match_date.asc())
            .all()
        )

    if not matches:
        print("No finished matches found in the database.")
        return

    print(f"Replaying Elo over {len(matches)} finished matches...")
    processed = skipped = 0

    for m in matches:
        if m.home_score is None or m.away_score is None:
            skipped += 1
            continue
        match_date = m.match_date
        season = canonical_season(match_date)
        # league_id is canonical (EPL, LA_LIGA, ...) after migration 0006
        league = (m.league_id or "").lower().replace("_", " ").replace(" ", "_")
        if not league:
            skipped += 1
            continue
        if not dry_run:
            elo.update_after_match(
                match_id=str(m.id),
                home_team_id=str(m.home_team_id),
                away_team_id=str(m.away_team_id),
                home_goals=int(m.home_score),
                away_goals=int(m.away_score),
                league=league,
                season=season,
                match_date=match_date,
            )
        processed += 1

    parquet_path = Path(settings.elo_parquet_path)
    print(f"Processed: {processed}  Skipped (no score / no league): {skipped}")
    if dry_run:
        print("[dry-run] No parquet written.")
    else:
        print(f"Elo parquet written to: {parquet_path}")
        table = elo._load_table()
        unique_teams = table["team_id"].nunique()
        print(f"  Rows: {len(table)}  Unique teams: {unique_teams}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay Elo ratings from DB matches")
    parser.add_argument("--dry-run", action="store_true", help="Parse matches but do not write parquet")
    args = parser.parse_args()
    replay(dry_run=args.dry_run)
