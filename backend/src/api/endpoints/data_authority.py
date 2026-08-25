"""Read-only production data-authority evidence for release verification."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

import dataclasses

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...services.elo_recovery_health_service import elo_recovery_health
from ...services.fixture_identity_rebind_service import (
    build_fixture_identity_rebind_manifest,
)
from ...services.historical_identity_repair_manifest_service import (
    build_semantic_identity_repair_manifest,
)
from ...services.historical_identity_repair_service import (
    build_semantic_elo_repair_plan,
)
from ...services.orphan_team_reconciliation_service import (
    build_orphan_team_repair_manifest,
)
from ...services.orphan_team_rebind_service import apply_orphan_team_rebind

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
        for (stored_id, stored_name, target_id, source_name), count in sorted(
            counts.items()
        )
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
    response: Response,
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Build the exact SAB-22 Class-C review evidence without mutating production.

    The PostgreSQL transaction is server-enforced read-only and rolled back before
    returning. The response exposes the immutable semantic-manifest hash, summary,
    aggregated participant replacements, source-linked Team creations, and (only
    when the manifest is complete) the deterministic Elo replay-plan
    hash/boundaries. It never authorizes apply.
    """
    response.headers["Cache-Control"] = "no-store"
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
            "proposed_team_creations": [],
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
            summary.get("complete") is True
            and summary.get("source_records_missing") == 0
            and summary.get("repair_blocked_matches") == 0
        )
        replacements = _proposed_replacement_summary(manifest.entries)
        team_creations = [
            proposal.as_dict() for proposal in manifest.proposed_team_creations
        ]

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
            "proposed_team_creations": team_creations,
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


@router.get("/fixture-identity-review")
async def fixture_identity_review(
    response: Response,
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Review live fixtures whose stored identity disagrees with the already-
    verified canonical identity (docs/DEBT.md item 35).

    Purely read-only — never mutates ``matches``. No rebind/apply path exists
    yet; that would be a Class-C production-identity mutation under the APEX
    directive and needs its own, separately-authorized dry-run manifest flow,
    mirroring ``semantic_repair_review`` for the sibling historical case.
    """
    response.headers["Cache-Control"] = "no-store"
    manifest = await build_fixture_identity_rebind_manifest(db)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "manifest": {
            "schema_version": manifest.schema_version,
            "rebind_manifest_sha256": manifest.manifest_sha256,
            "summary": manifest.summary,
        },
        "entries": [entry.as_dict() for entry in manifest.entries],
        "authorization": {
            "apply_supported": False,
            "note": (
                "review only; no rebind/apply path exists yet — "
                "see docs/DEBT.md item 35"
            ),
        },
    }


@router.get("/orphan-team-repair-review")
async def orphan_team_repair_review(
    response: Response,
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Review Elo-less orphan team identities with a now-resolvable target.

    docs/DEBT.md item 39: unlike ``fixture_identity_review`` (which compares
    against the unrelated ``canonical_teams`` system), this replays the exact
    resolver ``fixture_sync`` uses for ``Match.home_team_id``/``away_team_id``
    against the freshest observed provider team name, and only proposes a
    target that already carries real Elo history in the same league. Purely
    read-only — never mutates ``matches`` or ``teams``. No rebind/apply path
    exists yet; that would be a Class-C production-identity mutation under
    the APEX directive and needs its own, separately-authorized dry-run
    manifest flow.
    """
    response.headers["Cache-Control"] = "no-store"
    manifest = await build_orphan_team_repair_manifest(db)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "manifest": {
            "schema_version": manifest.schema_version,
            "repair_manifest_sha256": manifest.manifest_sha256,
            "summary": manifest.summary,
        },
        "entries": [entry.as_dict() for entry in manifest.entries],
        "authorization": {
            "apply_supported": True,
            "apply_endpoint": "POST /api/v1/release/orphan-team-repair-apply",
        },
    }


class OrphanTeamRebindApplyRequest(BaseModel):
    expected_manifest_sha256: str
    authorization_id: str
    confirm: str  # must equal the literal "APPLY_ORPHAN_TEAM_REBIND"


@router.post("/orphan-team-repair-apply")
async def apply_orphan_team_rebind_endpoint(
    body: OrphanTeamRebindApplyRequest,
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Execute the Class-C orphan-team identity rebind (docs/DEBT.md item 39).

    Requires the exact confirmation token ``"APPLY_ORPHAN_TEAM_REBIND"``, the
    manifest SHA-256 from the immediately-preceding review call, and an
    operator-supplied authorization id that becomes part of the audit trail.

    Always run ``GET /orphan-team-repair-review`` immediately before this call
    to confirm the manifest digest is still current — the digest changes
    whenever fixture sync resolves a previously-unresolvable side.
    """
    if body.confirm != "APPLY_ORPHAN_TEAM_REBIND":
        raise HTTPException(status_code=422, detail="confirmation token mismatch")
    result = await apply_orphan_team_rebind(
        db, expected_manifest_sha256=body.expected_manifest_sha256
    )
    await db.commit()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authorization_id": body.authorization_id,
        **dataclasses.asdict(result),
    }


__all__ = ["router"]
