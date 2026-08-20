"""Backfill durable Elo snapshots from real Match/Team identities.

Usage (from backend/):
    python scripts/replay_elo_from_db.py --dry-run
    python scripts/replay_elo_from_db.py --apply
    python scripts/replay_elo_from_db.py --dry-run --database-url postgresql://...

The authoritative production state is ``elo_rating_snapshots`` in PostgreSQL.
The legacy Parquet Elo engine remains offline/backward-compatible tooling only.

This recovery CLI deliberately has no implicit SQLite fallback.  A missing or stale
production DATABASE_URL must fail visibly rather than producing a misleading
``eligible=0`` result against an empty local database.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _redact(url: str) -> str:
    """Strip a URL password before echoing the selected database target."""
    return re.sub(r"(://[^:/@]+:)[^@]*(@)", r"\1***\2", url)


async def _run(*, apply: bool) -> int:
    # Imports happen after --database-url has been copied into the environment so
    # pydantic-settings resolves exactly the operator-selected target.
    from sqlalchemy import func, select

    from src.core.config import settings
    from src.core.database import Match
    from src.db.models import EloRatingSnapshot
    from src.db.session import close_db, init_db
    from src.services.elo_state_service import apply_finished_match_to_elo

    print(f"target={_redact(settings.database_url)}")
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
                f"processed={processed} rows={row_count} unique_teams={team_count} "
                "authority=postgres"
            )
            return 0
    finally:
        await close_db()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay durable Elo state from finished DB matches"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report eligible matches without mutation",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Persist missing Elo snapshots",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "Explicit SQLAlchemy database URL. When omitted, use the normal settings "
            "chain; there is intentionally no automatic SQLite fallback."
        ),
    )
    args = parser.parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = str(args.database_url)
    return asyncio.run(_run(apply=bool(args.apply)))


if __name__ == "__main__":
    raise SystemExit(main())
