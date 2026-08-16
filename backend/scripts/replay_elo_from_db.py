"""Backfill durable Elo snapshots from real Match/Team identities.

Usage (from backend/):
    python scripts/replay_elo_from_db.py --dry-run
    python scripts/replay_elo_from_db.py --apply

The authoritative production state is ``elo_rating_snapshots`` in PostgreSQL.
The legacy Parquet Elo engine remains offline/backward-compatible tooling only.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import func, select

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./sabiscore.db")
os.environ.setdefault("SABISCORE_ALLOW_INSECURE_FALLBACK", "true")
os.environ.setdefault("APP_ENV", "development")

from src.core.database import Match  # noqa: E402
from src.db.models import EloRatingSnapshot  # noqa: E402
from src.db.session import close_db, init_db  # noqa: E402
from src.services.elo_state_service import apply_finished_match_to_elo  # noqa: E402


async def _run(*, apply: bool) -> int:
    await init_db()
    from src.db import session as db_session

    session_factory = db_session.AsyncSessionLocal
    if session_factory is None:
        raise RuntimeError("Async database session is unavailable")

    try:
        async with session_factory() as session:
            matches = (
                await session.execute(
                    select(Match)
                    .where(
                        func.lower(Match.status) == "finished",
                        Match.home_score.is_not(None),
                        Match.away_score.is_not(None),
                        Match.league_id.is_not(None),
                    )
                    .order_by(Match.match_date.asc(), Match.id.asc())
                )
            ).scalars().all()

            existing_matches = set(
                (
                    await session.execute(
                        select(EloRatingSnapshot.match_id).distinct()
                    )
                ).scalars().all()
            )

            eligible = [match for match in matches if str(match.id) not in existing_matches]
            print(
                f"finished={len(matches)} existing_elo_matches={len(existing_matches)} "
                f"eligible={len(eligible)} mode={'apply' if apply else 'dry-run'}"
            )
            if not apply:
                if eligible:
                    first, last = eligible[0], eligible[-1]
                    print(
                        "eligible_range="
                        f"{first.match_date.isoformat()}..{last.match_date.isoformat()}"
                    )
                return 0

            processed = 0
            for match in eligible:
                if await apply_finished_match_to_elo(session, match):
                    processed += 1
            await session.commit()

            row_count = int(
                (
                    await session.execute(select(func.count(EloRatingSnapshot.id)))
                ).scalar_one()
            )
            team_count = int(
                (
                    await session.execute(
                        select(func.count(func.distinct(EloRatingSnapshot.team_id)))
                    )
                ).scalar_one()
            )
            print(
                f"processed={processed} rows={row_count} unique_teams={team_count} authority=postgres"
            )
            return 0
    finally:
        await close_db()


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay durable Elo state from finished DB matches")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Report eligible matches without mutation")
    mode.add_argument("--apply", action="store_true", help="Persist missing Elo snapshots")
    args = parser.parse_args()
    return asyncio.run(_run(apply=bool(args.apply)))


if __name__ == "__main__":
    raise SystemExit(main())
