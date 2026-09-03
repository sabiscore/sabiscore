"""Review which tracked-corpus Understat matches can safely populate match_stats.

Read-only. Prints a summary and the manifest SHA-256; always rolls back.
There is deliberately no --apply mode yet — see docs/DEBT.md item 56 Finding 5:
applying writes to production match_stats needs real numbers from a review run
first, plus the same authorization/confirmation-token discipline
scripts/repair_orphan_team_identities.py already establishes for production
identity writes. This script produces the numbers; it does not act on them.

Usage (from backend/):

    python scripts/review_understat_match_stats_backfill.py

    # Full entry dump instead of the default bounded sample:
    python scripts/review_understat_match_stats_backfill.py --full
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_SAMPLE_SIZE = 10


def _redact(url: str) -> str:
    return re.sub(r"(://[^:/@]+:)[^@]*(@)", r"\1***\2", url)


async def _run(args: argparse.Namespace) -> int:
    if args.database_url:
        os.environ["DATABASE_URL"] = str(args.database_url)

    from sqlalchemy import text

    from src.core.config import settings
    from src.db.session import close_db, init_db
    from src.services.understat_match_stats_reconciliation_service import (
        build_understat_match_stats_manifest,
    )

    print(f"target={_redact(settings.database_url)}", file=sys.stderr)
    await init_db()
    from src.db import session as db_session

    factory = db_session.AsyncSessionLocal
    if factory is None:
        raise RuntimeError("Async database session is unavailable")

    try:
        async with factory() as session:
            if session.bind is None or session.bind.dialect.name != "postgresql":
                raise RuntimeError("this review requires PostgreSQL — refusing to run against SQLite fallback")
            await session.execute(text("SET TRANSACTION READ ONLY"))

            manifest = await build_understat_match_stats_manifest(
                session, args.sources_dir
            )

            ready = [e.as_dict() for e in manifest.entries if e.repair_ready]
            blocked_by_status: dict[str, list[dict]] = {}
            for entry in manifest.entries:
                if not entry.repair_ready:
                    blocked_by_status.setdefault(entry.status, []).append(entry.as_dict())

            payload = {
                "mode": "review",
                "manifest_sha256": manifest.manifest_sha256,
                "summary": manifest.summary,
                "ready_entries": ready if args.full else ready[:_SAMPLE_SIZE],
                "ready_entries_truncated": (not args.full) and len(ready) > _SAMPLE_SIZE,
                "blocked_samples": {
                    status: (rows if args.full else rows[:_SAMPLE_SIZE])
                    for status, rows in blocked_by_status.items()
                },
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            await session.rollback()
            return 0
    finally:
        await close_db()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources-dir",
        type=Path,
        default=_BACKEND_DIR / "data" / "processed" / "v4_sources",
    )
    parser.add_argument("--database-url", default="")
    parser.add_argument(
        "--full", action="store_true", help="Print every entry instead of a bounded sample"
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
