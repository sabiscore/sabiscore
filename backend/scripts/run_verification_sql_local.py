"""Run a read-only .sql verification script without requiring the psql CLI.

psql is a separate PostgreSQL client binary and isn't installed on every dev
machine (Windows in particular). The repo already depends on SQLAlchemy +
asyncpg to talk to the same DATABASE_URL every service uses, so this reuses
that instead of asking anyone to install a second tool.

Usage (from backend/):
    DATABASE_URL=postgresql+asyncpg://... python scripts/run_verification_sql.py scripts/verify_elo.sql
    python scripts/run_verification_sql.py scripts/verify_clv_settlement.sql scripts/verify_clv_by_generation.sql

Strips the psql-only `BEGIN TRANSACTION READ ONLY;` / `ROLLBACK;` wrapper
lines each script uses (harmless psql convention, not needed here since the
query runs directly against the DB without mutating anything) and executes
the remaining single statement.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from sqlalchemy import text

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./sabiscore.db")
os.environ.setdefault("SABISCORE_ALLOW_INSECURE_FALLBACK", "true")
os.environ.setdefault("APP_ENV", "development")

from src.db.session import close_db, init_db  # noqa: E402

_WRAPPER_LINE = re.compile(r"^\s*(BEGIN\s+TRANSACTION\s+READ\s+ONLY|ROLLBACK)\s*;\s*$", re.IGNORECASE)


def _strip_psql_wrapper(sql: str) -> str:
    lines = [line for line in sql.splitlines() if not _WRAPPER_LINE.match(line)]
    return "\n".join(lines)


async def _run_one(path: Path) -> int:
    query = _strip_psql_wrapper(path.read_text(encoding="utf-8"))
    await init_db()
    from src.db import session as db_session

    session_factory = db_session.AsyncSessionLocal
    if session_factory is None:
        raise RuntimeError("Async database session is unavailable")
    try:
        async with session_factory() as session:
            result = await session.execute(text(query))
            rows = result.mappings().all()
            print(f"--- {path.name} ({len(rows)} row(s)) ---")
            for row in rows:
                print(dict(row))
            return 0
    finally:
        await close_db()


async def _run(paths: list[Path]) -> int:
    exit_code = 0
    for path in paths:
        exit_code = await _run_one(path) or exit_code
    return exit_code


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_verification_sql.py <file.sql> [more.sql ...]")
        return 2
    paths = [Path(arg) for arg in sys.argv[1:]]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        print(f"file(s) not found: {', '.join(str(p) for p in missing)}")
        return 2
    return asyncio.run(_run(paths))


if __name__ == "__main__":
    raise SystemExit(main())
