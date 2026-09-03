"""Review or execute the Understat -> ``match_stats`` xG backfill (docs/DEBT.md item 56).

What this does
--------------
Reconciles the tracked Understat corpus against canonical fixture identity and,
under ``--apply``, inserts the resolved rows' xG into ``match_stats`` as two
rows per fixture (one per side), populating ``expected_goals`` and nothing else.

That column is the input ``upcoming_match_feature_service.project_xg_rolling_features``
reads; with ``match_stats`` empty it returns None for every fixture, which is
why the three CAUSAL_DRIVER xG features have no serving answer today.

Production safety
-----------------
* default review mode is read-only and always rolls back;
* --apply requires the reviewed manifest SHA-256;
* --apply also requires an explicit authorization/change identifier and a
  literal confirmation token;
* no implicit SQLite fallback is enabled;
* the service recomputes the manifest digest while holding PostgreSQL
  write-conflict locks;
* it refuses to overwrite any ``match_stats`` row that already exists;
* commit occurs exactly once, only after the read-back postconditions pass.

The apply output prints a ``reversals`` list — the exact (match_id, team_id)
pairs to DELETE to undo the change by hand. Keep it with the authorization
record.

Examples (from backend/):

    python scripts/review_understat_match_stats_backfill.py

    # Full entry dump instead of the default bounded sample:
    python scripts/review_understat_match_stats_backfill.py --full

    python scripts/review_understat_match_stats_backfill.py \
      --apply \
      --manifest-sha256 <reviewed-sha256> \
      --authorization-id <approved-change-id> \
      --confirm APPLY_UNDERSTAT_MATCH_STATS
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
_CONFIRMATION = "APPLY_UNDERSTAT_MATCH_STATS"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def _redact(url: str) -> str:
    return re.sub(r"(://[^:/@]+:)[^@]*(@)", r"\1***\2", url)


def _validate_sha256(value: str, *, field: str) -> str:
    normalized = (value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return normalized


async def _review(session, args: argparse.Namespace) -> int:
    from sqlalchemy import text

    from src.services.understat_match_stats_reconciliation_service import (
        build_understat_match_stats_manifest,
    )

    if session.bind is None or session.bind.dialect.name != "postgresql":
        raise RuntimeError(
            "this review requires PostgreSQL — refusing to run against SQLite fallback"
        )
    await session.execute(text("SET TRANSACTION READ ONLY"))

    manifest = await build_understat_match_stats_manifest(session, args.sources_dir)

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


def _validated_apply_authorization(args: argparse.Namespace) -> str:
    """The reviewed manifest digest, once every authorization check has passed.

    Called BEFORE ``init_db()`` on purpose. All of these are pure argument
    checks, so failing them after opening a connection to production would hold
    a session open for an operator error that was knowable without one — the
    same reason a human confirmation step belongs outside a transaction.
    """
    manifest_sha = _validate_sha256(args.manifest_sha256, field="--manifest-sha256")
    if not args.authorization_id or not args.authorization_id.strip():
        raise RuntimeError("--authorization-id is required for --apply")
    if args.confirm != _CONFIRMATION:
        raise RuntimeError(
            f"--apply requires the literal confirmation token {_CONFIRMATION}"
        )
    if args.batch_size < 1:
        raise RuntimeError("--batch-size must be >= 1")
    return manifest_sha


async def _apply(session, args: argparse.Namespace, manifest_sha: str) -> int:
    from src.services.understat_match_stats_backfill_service import (
        apply_understat_match_stats_backfill,
    )

    try:
        result = await apply_understat_match_stats_backfill(
            session,
            expected_manifest_sha256=manifest_sha,
            sources_dir=args.sources_dir,
            batch_size=args.batch_size,
            lock_timeout_seconds=args.lock_timeout_seconds,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    print(
        json.dumps(
            {
                "mode": "apply",
                "authorization_id": args.authorization_id.strip(),
                "manifest_sha256": result.manifest_sha256,
                "inserted_rows": result.inserted_rows,
                "matches_written": result.matches_written,
                "already_present_rows": result.already_present_rows,
                "skipped_unresolved_entries": result.skipped_unresolved_entries,
                "leagues": list(result.leagues),
                # Bounded: 11k+ pairs would bury the counts that matter. The
                # full reversal key is (match_id, team_id) for every inserted
                # row, reproducible from the same manifest SHA.
                "reversals_sample": [list(r) for r in result.reversals[:_SAMPLE_SIZE]],
                "reversals_total": len(result.reversals),
                "committed": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


async def _run(args: argparse.Namespace) -> int:
    # Authorization is settled before anything opens a connection.
    manifest_sha = _validated_apply_authorization(args) if args.apply else ""

    if args.database_url:
        os.environ["DATABASE_URL"] = str(args.database_url)

    from src.core.config import settings
    from src.db.session import close_db, init_db

    print(f"target={_redact(settings.database_url)}", file=sys.stderr)
    await init_db()
    from src.db import session as db_session

    factory = db_session.AsyncSessionLocal
    if factory is None:
        raise RuntimeError("Async database session is unavailable")

    try:
        async with factory() as session:
            if args.apply:
                return await _apply(session, args, manifest_sha)
            return await _review(session, args)
    finally:
        await close_db()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Mutate only after the reviewed hash and explicit authorization are "
            "supplied. Without this flag the script is read-only and always "
            "rolls back."
        ),
    )
    parser.add_argument(
        "--sources-dir",
        type=Path,
        default=_BACKEND_DIR / "data" / "processed" / "v4_sources",
    )
    parser.add_argument("--database-url", default="")
    parser.add_argument("--manifest-sha256", default="")
    parser.add_argument("--authorization-id", default="")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--lock-timeout-seconds", type=int, default=5)
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
