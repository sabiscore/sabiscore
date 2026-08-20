"""CLI wrapper for ``src.services.self_play_repair_service`` (docs/DEBT.md item 23).

Usage (from backend/):
    python scripts/repair_self_play_matches.py --dry-run --database-url postgresql://...
    python scripts/repair_self_play_matches.py --apply   --database-url postgresql://...

``--database-url`` is optional; without it the normal settings chain
(``DATABASE_URL`` env var, then ``backend/.env``) resolves the target. The flag
exists because this is a data-repair tool that must never guess which database
it is pointed at, and because setting an env var inline is shell-specific
(``VAR=x cmd`` is POSIX-only; PowerShell needs ``$env:VAR="x"``).

Deliberately NOT bootstrapped with ``os.environ.setdefault("DATABASE_URL",
"sqlite...")`` the way ``replay_elo_from_db.py`` is: that pattern silently wins
over ``backend/.env`` and would point this script at an empty local SQLite file,
where it would report ``corrupted_rows_found=0`` — indistinguishable from a
clean production database. The resolved target is echoed (credentials redacted)
for the same reason.

See ``src/services/self_play_repair_service.py`` for the repair logic and root
cause.
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
    """Strip the password from a SQLAlchemy URL before logging it."""
    return re.sub(r"(://[^:/@]+:)[^@]*(@)", r"\1***\2", url)


async def _run(*, apply: bool) -> int:
    # Imported here, not at module scope, so --database-url is already in the
    # environment before pydantic-settings reads it.
    from src.core.config import settings
    from src.db.session import close_db, init_db
    from src.services.self_play_repair_service import find_and_repair_self_play_matches

    print(f"target={_redact(settings.database_url)}")

    await init_db()
    from src.db import session as db_session

    session_factory = db_session.AsyncSessionLocal
    if session_factory is None:
        raise RuntimeError("Async database session is unavailable")

    try:
        async with session_factory() as session:
            report = await find_and_repair_self_play_matches(session, apply=apply)
            print(f"corrupted_rows_found={report.corrupted_found} mode={'apply' if apply else 'dry-run'}")
            for line in report.lines:
                print(f"  {line}")
            print(f"repaired={report.repaired} skipped={report.skipped}")
            return 0
    finally:
        await close_db()


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair self-play matches.home_team_id/away_team_id collisions")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Report repairable rows without mutation")
    mode.add_argument("--apply", action="store_true", help="Persist the corrected team ids")
    parser.add_argument(
        "--database-url",
        help="Target database. Overrides DATABASE_URL/.env for this run. Avoids shell-specific env syntax.",
    )
    args = parser.parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    return asyncio.run(_run(apply=bool(args.apply)))


if __name__ == "__main__":
    raise SystemExit(main())
