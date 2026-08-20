#!/usr/bin/env python3
"""Emit a read-only historical team-identity repair manifest.

The script never commits. On PostgreSQL it explicitly marks the transaction
READ ONLY before running the audit query. Source identities are reconstructed
from the committed football-data.co.uk cache using the production parser and
deterministic match-id contract.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import text

from src.db.session import close_db, init_db
from src.services.historical_identity_audit_service import (
    audit_historical_semantic_identity,
    summarize_semantic_identity_findings,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only semantic identity audit for fdco historical matches"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Override backend/data/cache for deterministic source reconstruction",
    )
    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="Exit 2 when semantic identity mismatches are found",
    )
    return parser


async def _run(cache_dir: Path | None) -> tuple[dict[str, object], list[dict[str, object]]]:
    await init_db()
    try:
        from src.db.session import AsyncSessionLocal

        if AsyncSessionLocal is None:
            raise RuntimeError("database session factory was not initialized")
        async with AsyncSessionLocal() as session:
            bind = session.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                await session.execute(text("SET TRANSACTION READ ONLY"))
            findings = await audit_historical_semantic_identity(
                session,
                cache_dir=cache_dir,
            )
            summary = summarize_semantic_identity_findings(findings)
            await session.rollback()
            return summary, [finding.as_dict() for finding in findings]
    finally:
        await close_db()


async def _main() -> int:
    args = _parser().parse_args()
    summary, findings = await _run(args.cache_dir)
    print(
        json.dumps(
            {"summary": summary, "findings": findings},
            indent=2,
            sort_keys=True,
        )
    )
    return 2 if args.fail_on_findings and findings else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
