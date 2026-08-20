#!/usr/bin/env python3
"""Emit the immutable, read-only historical semantic identity repair manifest.

Usage (from ``backend/``):

    python scripts/build_semantic_identity_repair_manifest.py --require-complete
    python scripts/build_semantic_identity_repair_manifest.py \
        --require-complete \
        --output artifacts/semantic_identity_repair_manifest.json

This script never mutates production data. PostgreSQL transactions are explicitly
READ ONLY and rolled back.  ``--require-complete`` exits 2 unless every affected
match has source-consistent, deterministic, distinct same-league repair targets.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from sqlalchemy import text

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the source-backed historical semantic identity repair manifest"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Override backend/data/cache for deterministic source reconstruction",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optionally write the canonical manifest JSON to this local path",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit 2 unless every affected row is repair-ready",
    )
    return parser


async def _run(cache_dir: Path | None) -> dict[str, object]:
    from src.db.session import close_db, init_db
    from src.services.historical_identity_repair_manifest_service import (
        build_semantic_identity_repair_manifest,
    )

    await init_db()
    try:
        from src.db.session import AsyncSessionLocal

        if AsyncSessionLocal is None:
            raise RuntimeError("database session factory was not initialized")

        async with AsyncSessionLocal() as session:
            bind = session.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                await session.execute(text("SET TRANSACTION READ ONLY"))
            manifest = await build_semantic_identity_repair_manifest(
                session,
                cache_dir=cache_dir,
            )
            await session.rollback()
            return manifest.as_dict()
    finally:
        await close_db()


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


async def _main() -> int:
    args = _parser().parse_args()
    manifest = await _run(args.cache_dir)
    payload = json.dumps(manifest, indent=2, sort_keys=True)
    print(payload)

    if args.output is not None:
        _write_atomic(args.output, payload + "\n")

    summary = manifest["summary"]
    if args.require_complete and not bool(summary["complete"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
