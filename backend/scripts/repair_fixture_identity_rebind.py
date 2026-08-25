"""Review or execute the reviewed live-fixture identity rebind (docs/DEBT.md item 35).

What this does
--------------
Repoints ``Match.home_team_id`` / ``Match.away_team_id`` for scheduled
fixtures whose stored identity disagrees with the already-verified canonical
identity (``CanonicalFixture.home_team_id``/``away_team_id``, resolved every
tick by ``ensure_canonical_fixture`` regardless of whether the legacy row was
flagged). ``fixture_sync_service`` deliberately leaves these unchanged when it
detects the drift.

It writes nothing else -- no ``Team``/``CanonicalTeam`` created, renamed, or
deleted, no ``EloRatingSnapshot`` touched.

Unlike the sibling ``repair_orphan_team_identities.py``, the manifest here is
routinely a mix of ready and blocked entries (a ``HAS_EXISTING_PREDICTIONS``
blocker will not resolve on its own). ``--apply`` therefore writes only the
currently rebind-ready subset; blocked entries are left untouched and still
visible on the next ``--review``.

Production safety
-----------------
* default review mode is read-only and always rolls back;
* --apply requires the reviewed repair-manifest SHA-256 for the FULL manifest
  (ready and blocked entries alike -- any drift in either aborts the apply);
* --apply also requires an explicit authorization/change identifier and a
  literal confirmation token;
* no implicit SQLite fallback is enabled;
* the service recomputes the manifest digest while holding PostgreSQL
  write-conflict locks, and re-checks each row's exact pre-state;
* commit occurs exactly once, only after the self-play and residual-mismatch
  postconditions pass.

The apply output prints a ``reversals`` list -- the exact (match, column,
from, to) tuples needed to undo the change by hand. Keep it with the
authorization record.

Examples (from repository root):

    # backend/
    python scripts/repair_fixture_identity_rebind.py --review

    # backend/
    python scripts/repair_fixture_identity_rebind.py \
      --apply \
      --manifest-sha256 <reviewed-sha256> \
      --authorization-id <approved-change-id> \
      --confirm APPLY_FIXTURE_IDENTITY_REBIND
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

_CONFIRMATION = "APPLY_FIXTURE_IDENTITY_REBIND"
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
    from src.services.fixture_identity_rebind_apply_service import (
        apply_fixture_identity_rebind,
    )
    from src.services.fixture_identity_rebind_service import (
        build_fixture_identity_rebind_manifest,
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
                    raise RuntimeError("fixture identity rebind review requires PostgreSQL")
                await session.execute(text("SET TRANSACTION READ ONLY"))
                manifest = await build_fixture_identity_rebind_manifest(session)
                ready = [e for e in manifest.entries if e.rebind_ready]
                payload = {
                    "mode": "review",
                    "manifest_sha256": manifest.manifest_sha256,
                    "summary": manifest.summary,
                    "entries": [e.as_dict() for e in manifest.entries],
                    "nothing_to_apply": not ready,
                }
                print(json.dumps(payload, indent=2, sort_keys=True))
                await session.rollback()
                return 2 if payload["nothing_to_apply"] else 0

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
                result = await apply_fixture_identity_rebind(
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
                        "rebound_count": result.rebound_count,
                        "affected_match_ids": list(result.affected_match_ids),
                        "skipped_blocked_match_ids": list(result.skipped_blocked_match_ids),
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
        description="Review/apply the reviewed live-fixture identity rebind"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--review",
        action="store_true",
        help="Read-only: print the rebind manifest and its SHA-256",
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
