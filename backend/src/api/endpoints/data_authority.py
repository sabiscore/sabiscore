"""Read-only production data-authority evidence for release verification."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...services.elo_recovery_health_service import elo_recovery_health
from ...services.historical_identity_repair_manifest_service import (
    build_semantic_identity_repair_manifest,
)
from ...services.historical_identity_repair_service import build_semantic_elo_repair_plan

router = APIRouter(prefix="/release", tags=["release-verification"])


def _proposed_replacement_summary(entries: Iterable[object]) -> list[dict[str, object]]:
    """Aggregate manifest entries without exposing hundreds of raw repair rows."""
    counts: Counter[tuple[str, str, str, str]] = Counter()
    for entry in entries:
        participants = (
            (
                str(getattr(entry, "stored_home_team_id")),
                getattr(entry, "stored_home_team_name"),
                getattr(entry, "target_home_team_id"),
                getattr(entry, "source_home_team"),
            ),
            (
                str(getattr(entry, "stored_away_team_id")),
                getattr(entry, "stored_away_team_name"),
                getattr(entry, "target_away_team_id"),
                getattr(entry, "source_away_team"),
            ),
        )
        for stored_id, stored_name, target_id, source_name in participants:
            if target_id is None or stored_id == str(target_id):
                continue
            counts[
                (
                    stored_id,
                    str(stored_name or ""),
                    str(target_id),
                    str(source_name or ""),
                )
            ] += 1

    return [
        {
            "stored_team_id": stored_id,
            "stored_team_name": stored_name or None,
            "target_team_id": target_id,
            "source_team_name": source_name or None,
            "participant_references": count,
        }
        for (stored_id, stored_name, target_id, source_name), count in sorted(counts.items())
    ]


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


@router.get("/semantic-repair-review")
async def semantic_repair_review(
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Build the exact SAB-22 Class-C review evidence without mutating production.

    The PostgreSQL transaction is server-enforced read-only and rolled back before
    returning. The response exposes the immutable semantic-manifest hash, summary,
    aggregated participant replacements, and (only when the manifest is complete)
    the deterministic Elo replay-plan hash/boundaries. It never authorizes apply.
    """
    bind = db.get_bind()
    dialect = bind.dialect.name if bind is not None else "unknown"
    if dialect != "postgresql":
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "read_only": True,
            "blocked": True,
            "reason": "POSTGRES_REQUIRED",
            "manifest": None,
            "replay_plan": None,
            "proposed_replacements": [],
            "authorization": {
                "review_ready": False,
                "production_mutation_authorized": False,
            },
        }

    try:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        manifest = await build_semantic_identity_repair_manifest(db)
        summary = dict(manifest.summary)
        review_ready = bool(
            summary.get("complete")
            and int(summary.get("source_records_missing", 0)) == 0
            and int(summary.get("repair_blocked_matches", 0)) == 0
        )
        replacements = _proposed_replacement_summary(manifest.entries)

        replay_plan: dict[str, object] | None = None
        if review_ready:
            plan = await build_semantic_elo_repair_plan(db, manifest=manifest)
            replay_plan = plan.as_dict(include_matches=False)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "read_only": True,
            "blocked": not review_ready,
            "reason": None if review_ready else "SEMANTIC_REPAIR_MANIFEST_INCOMPLETE",
            "manifest": {
                "schema_version": manifest.schema_version,
                "repair_manifest_sha256": manifest.manifest_sha256,
                "summary": summary,
            },
            "replay_plan": replay_plan,
            "proposed_replacements": replacements,
            "authorization": {
                "review_ready": review_ready,
                "production_mutation_authorized": False,
                "required": (
                    "explicit_class_c_authorization_referencing_"
                    "repair_manifest_sha256_and_replay_plan_sha256"
                ),
            },
        }
    finally:
        await db.rollback()


__all__ = ["router"]
