"""Understat Telemetry API Endpoints.

Provides FastAPI routes to trigger asynchronous ingestion of Understat match telemetry
as background tasks and inspect ingested telemetry and ML features.
"""

from __future__ import annotations

import logging
from typing import Any, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import MatchTelemetry
from ...db.session import get_async_session
from ...services.understat.formatter import UnderstatTensorFormatter
from ...services.understat.orchestrator import ingest_understat_telemetry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry/understat", tags=["telemetry", "understat"])


class UnderstatIngestRequest(BaseModel):
    """Payload to trigger background Understat match telemetry ingestion."""

    match_ids: List[int] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of integer Understat match IDs to scrape and ingest.",
        examples=[[11662, 11663, 11664]],
    )


class UnderstatIngestResponse(BaseModel):
    """Response returned upon successfully enqueuing the background ingestion task."""

    status: str = "queued"
    enqueued_count: int
    match_ids: List[int]
    message: str


class TelemetrySummary(BaseModel):
    match_id: int
    provider_id: str
    home_team_slug: str
    away_team_slug: str
    home_xg: float | None
    away_xg: float | None
    home_xa: float | None
    away_xa: float | None
    created_at: str


@router.post(
    "/ingest",
    response_model=UnderstatIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue asynchronous Understat telemetry ingestion",
)
async def trigger_understat_ingestion(
    payload: UnderstatIngestRequest,
    background_tasks: BackgroundTasks,
) -> UnderstatIngestResponse:
    """Schedule Understat telemetry scraping and ingestion as a FastAPI BackgroundTask.

    Idempotently upserts telemetry to PostgreSQL and invalidates Redis caches.
    """
    logger.info("Scheduling telemetry ingestion for %d match IDs", len(payload.match_ids))
    background_tasks.add_task(ingest_understat_telemetry, payload.match_ids)

    return UnderstatIngestResponse(
        status="queued",
        enqueued_count=len(payload.match_ids),
        match_ids=payload.match_ids,
        message="Understat match telemetry ingestion scheduled as a background task.",
    )


@router.get(
    "/{match_id}",
    response_model=TelemetrySummary,
    summary="Get ingested match telemetry by Understat match ID",
)
async def get_match_telemetry(
    match_id: int,
    db: AsyncSession = Depends(get_async_session),
) -> TelemetrySummary:
    """Retrieve raw xG, xA, and metadata for an ingested match."""
    stmt = select(MatchTelemetry).where(MatchTelemetry.match_id == match_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Telemetry for match_id {match_id} not found",
        )

    return TelemetrySummary(
        match_id=record.match_id,
        provider_id=record.provider_id,
        home_team_slug=record.home_team_slug,
        away_team_slug=record.away_team_slug,
        home_xg=record.home_xg,
        away_xg=record.away_xg,
        home_xa=record.home_xa,
        away_xa=record.away_xa,
        created_at=record.created_at.isoformat(),
    )


@router.get(
    "/features/schema",
    summary="Get ML feature vector metadata for Understat models",
)
async def get_features_schema() -> dict[str, Any]:
    """Return feature names and tensor metadata produced by UnderstatTensorFormatter."""
    return {
        "feature_names": UnderstatTensorFormatter.get_feature_names(),
        "feature_count": len(UnderstatTensorFormatter.get_feature_names()),
        "dtype": "float32",
        "memory_order": "C_CONTIGUOUS",
        "target_models": ["XGBoost", "LightGBM"],
    }
