"""Read-only production data-authority evidence for release verification."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...services.elo_recovery_health_service import elo_recovery_health

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


__all__ = ["router"]
