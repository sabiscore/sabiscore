"""Review or execute the source-bound semantic identity + Elo repair.

Production safety
-----------------
* default review mode is read-only and always rolls back;
* --apply requires the reviewed semantic-manifest SHA-256 and replay-plan SHA-256;
* --apply also requires an explicit authorization/change identifier and a literal
  confirmation token;
* no implicit SQLite fallback is enabled;
* the service recomputes both hashes while holding PostgreSQL write-conflict locks;
* commit occurs exactly once, only after all semantic and Elo postconditions pass.

Examples (from repository root):

    # backend/
    python scripts/repair_semantic_identity_and_rebuild_elo.py --review

    # backend/
    python scripts/repair_semantic_identity_and_rebuild_elo.py \
      --apply \
      --manifest-sha256 <reviewed-sha256> \
      --plan-sha256 <reviewed-sha256> \
      --authorization-id <approved-change-id> \
      --confirm APPLY_SEMANTIC_IDENTITY_AND_REBUILD_ELO
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

_CONFIRMATION = "APPLY_SEMANTIC_IDENTITY_AND_REBUILD_ELO"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def _redact(url: str) -> str:
    return re.sub(r"(://[^:/@]+:)[^@]*(@)", r"\1***\2", url)


def _validate_sha256(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
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
    from src.services.historical_identity_repair_manifest_service import (
        build_semantic_identity_repair_manifest,
    )
    from src.services.historical_identity_repair_service import (
        apply_semantic_identity_and_rebuild_elo,
        build_semantic_elo_repair_plan,
    )

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
                    raise RuntimeError(
                        "production semantic repair review requires PostgreSQL"
                    )
                await session.execute(text("SET TRANSACTION READ ONLY"))
                manifest = await build_semantic_identity_repair_manifest(session)
                complete = bool(manifest.summary.get("complete"))
                if not complete:
                    payload = {
                        "mode": "review",
                        "manifest": manifest.as_dict(),
                        "replay_plan": None,
                        "blocked": True,
                    }
                    print(json.dumps(payload, indent=2, sort_keys=True))
                    await session.rollback()
                    return 2

                plan = await build_semantic_elo_repair_plan(session, manifest=manifest)
                payload = {
                    "mode": "review",
                    "manifest": manifest.as_dict(),
                    "replay_plan": plan.as_dict(include_matches=False),
                    "blocked": False,
                }
                print(json.dumps(payload, indent=2, sort_keys=True))
                await session.rollback()
                return 0

            manifest_sha = _validate_sha256(
                args.manifest_sha256, field="--manifest-sha256"
            )
            plan_sha = _validate_sha256(args.plan_sha256, field="--plan-sha256")
            if not args.authorization_id or not args.authorization_id.strip():
                raise RuntimeError("--authorization-id is required for --apply")
            if args.confirm != _CONFIRMATION:
                raise RuntimeError(
                    f"--apply requires the literal confirmation token {_CONFIRMATION}"
                )

            try:
                result = await apply_semantic_identity_and_rebuild_elo(
                    session,
                    expected_manifest_sha256=manifest_sha,
                    expected_plan_sha256=plan_sha,
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
                        "manifest_sha256": manifest_sha,
                        "plan_sha256": plan_sha,
                        "created_team_count": len(result.created_team_ids),
                        "created_team_ids": list(result.created_team_ids),
                        "repaired_matches": result.repaired_matches,
                        "rebuilt_matches": result.rebuilt_matches,
                        "rebuilt_snapshots": result.rebuilt_snapshots,
                        "leagues": list(result.leagues),
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
        description="Review/apply source-bound historical semantic identity and Elo repair"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--review",
        action="store_true",
        help="Read-only: print source-backed manifest and deterministic Elo replay plan",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Mutate only after reviewed hashes and explicit authorization are supplied",
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--manifest-sha256", default="")
    parser.add_argument("--plan-sha256", default="")
    parser.add_argument("--authorization-id", default="")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--lock-timeout-seconds", type=int, default=5)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.lock_timeout_seconds < 1 or args.lock_timeout_seconds > 60:
        raise SystemExit("--lock-timeout-seconds must be between 1 and 60")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
