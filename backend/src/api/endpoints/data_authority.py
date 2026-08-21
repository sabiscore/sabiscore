"""Read-only production data-authority evidence for release verification."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...services.elo_recovery_health_service import elo_recovery_health
from ...services.historical_identity_repair_manifest_service import (
    build_semantic_identity_repair_manifest,
)

router = APIRouter(prefix="/release", tags=["release-verification"])


@router.get("/data-authority")
async def data_authority(
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Expose non-secret DB identity and read-only Elo release evidence.

    The endpoint executes SELECT-only queries. Structural and semantic Elo states
    are direct persisted-data gates, while model performance, CLV sufficiency,
    and staking authorization remain deliberately outside this endpoint.
    """
    bind = db.get_bind()
    dialect = bind.dialect.name if bind is not None else "unknown"
    database_name: str | None = None
    if dialect == "postgresql":
        result = await db.execute(text("SELECT current_database()"))
        raw_name = result.scalar_one_or_none()
        database_name = str(raw_name) if raw_name is not None else None

    elo = await elo_recovery_health(db)
    structural = elo.get("structural_integrity") or {}
    semantic = elo.get("semantic_integrity") or {}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "database": {
            "dialect": dialect,
            "name": database_name,
        },
        "elo": elo,
        "certification": {
            "structural_elo": structural.get("status", "NOT_EVALUATED"),
            "semantic_identity": semantic.get("status", "NOT_EVALUATED"),
            "model": "NOT_EVALUATED",
            "clv": "NOT_EVALUATED",
            "staking": "NOT_AUTHORIZED",
        },
    }


@router.get("/semantic-repair-manifest")
async def semantic_repair_manifest(
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Expose the immutable SAB-22 repair authorization artifact, read-only.

    The existing manifest builder cross-checks persisted historical findings
    against the committed football-data.co.uk source corpus and current
    league-scoped Team identities. This route intentionally returns only the
    deterministic manifest identity and aggregate gate summary; per-match repair
    entries remain operator evidence rather than a large public API payload.

    This endpoint never mutates Match, Team, or Elo state and never authorizes a
    Class-C repair by itself. ``authorization_ready`` only means the dry-run
    evidence set has zero missing/blocked rows and is eligible for explicit human
    review plus backup/rollback authorization.
    """
    manifest = await build_semantic_identity_repair_manifest(db)
    summary = dict(manifest.summary)
    authorization_ready = (
        bool(summary.get("complete"))
        and int(summary.get("source_records_missing", 0)) == 0
        and int(summary.get("repair_blocked_matches", 0)) == 0
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "manifest_schema_version": manifest.schema_version,
        "repair_manifest_sha256": manifest.manifest_sha256,
        "summary": summary,
        "authorization_ready": authorization_ready,
        "production_mutation_authorized": False,
    }


__all__ = ["router"]
