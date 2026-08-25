"""Review or execute the reviewed orphan-team identity rebind (docs/DEBT.md item 39).

What this does
--------------
Repoints ``Match.home_team_id`` / ``Match.away_team_id`` for *unplayed* fixture
sides that currently reference an Elo-less orphan, onto the real,
history-bearing team the production resolver now returns for that side's
freshest observed provider name.

It writes nothing else. No Team is created, renamed, or deleted. No
EloRatingSnapshot is written, rebuilt, or deleted. Because the manifest refuses
any side whose kickoff has passed, there is no post-match Elo derived from the
wrong participant to unwind -- which is why this needs no chronological replay,
unlike its historical-repair sibling.

Production safety
-----------------
* default review mode is read-only and always rolls back;
* --apply requires the reviewed repair-manifest SHA-256;
* --apply also requires an explicit authorization/change identifier and a
  literal confirmation token;
* no implicit SQLite fallback is enabled;
* the service recomputes the manifest digest while holding PostgreSQL
  write-conflict locks, and re-checks each row's exact pre-state;
* commit occurs exactly once, only after the self-play and residual-orphan
  postconditions pass.

The apply output prints a ``reversals`` list -- the exact (match, side, from,
to) tuples needed to undo the change by hand. Keep it with the authorization
record.

Examples (from repository root):

    # backend/
    python scripts/repair_orphan_team_identities.py --review

    # backend/
    python scripts/repair_orphan_team_identities.py \
      --apply \
      --manifest-sha256 <reviewed-sha256> \
      --authorization-id <approved-change-id> \
      --confirm APPLY_ORPHAN_TEAM_REBIND
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

_CONFIRMATION = "APPLY_ORPHAN_TEAM_REBIND"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def _redact(url: str) -> str:
    return re.sub(r"(://[^:/@]+:)[^@]*(@)", r"\1***\2", url)


def _validate_sha256(value: str, *, field: str) -> str:
    normalized = (value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return normalized


async def _run(args: argparse.Namespace) -> int:
    # Apply the explicit URL before importing pydantic settings/database modules.
    if args.database_url:
        os.environ["DATABASE_URL"] = str(args.database_url)

    from sqlalchemy import text

    from src.core.config import settings
    from src.db.session import close_db, init_db
    from src.services.orphan_team_reconciliation_service import (
        build_orphan_team_repair_manifest,
    )
    from src.services.orphan_team_rebind_service import apply_orphan_team_rebind

    print(f"target={_redact(settings.database_url)}")
    await init_db()
    from src.db import session as db_session

    factory = db_session.AsyncSessionLocal
    if factory is None:
        raise RuntimeError("Async database session is unavailable")

    try:
        async with factory() as session:
            if args.review:
                # Force a server-enforced read-only transaction on PostgreSQL.
                if session.bind is None or session.bind.dialect.name != "postgresql":
                    raise RuntimeError("orphan team rebind review requires PostgreSQL")
                await session.execute(text("SET TRANSACTION READ ONLY"))
                manifest = await build_orphan_team_repair_manifest(session)
                blocked = [e for e in manifest.entries if not e.repair_ready]
                payload = {
                    "mode": "review",
                    "manifest_sha256": manifest.manifest_sha256,
                    "summary": manifest.summary,
                    "entries": [e.as_dict() for e in manifest.entries],
                    "blocked": bool(blocked) or not manifest.entries,
                }
                print(json.dumps(payload, indent=2, sort_keys=True))
                await session.rollback()
                return 2 if payload["blocked"] else 0

            manifest_sha = _validate_sha256(
                args.manifest_sha256, field="--manifest-sha256"
            )
            if not args.authorization_id or not args.authorization_id.strip():
                raise RuntimeError("--authorization-id is required for --apply")
            if args.confirm != _CONFIRMATION:
                raise RuntimeError(
                    f"--apply requires the literal confirmation token {_CONFIRMATION}"
                )

            try:
                result = await apply_orphan_team_rebind(
                    session,
                    expected_manifest_sha256=manifest_sha,
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
                        "rebound_sides": result.rebound_sides,
                        "affected_match_ids": list(result.affected_match_ids),
                        "leagues": list(result.leagues),
                        "reversals": [list(r) for r in result.reversals],
                        "committed": True,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
    finally:
        await close_db()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review/apply the reviewed orphan-team identity rebind"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--review",
        action="store_true",
        help="Read-only: print the repair manifest and its SHA-256",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Mutate only after the reviewed hash and explicit authorization are supplied",
    )
    parser.add_argument("--manifest-sha256", default="")
    parser.add_argument("--authorization-id", default="")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--lock-timeout-seconds", type=int, default=5)
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
