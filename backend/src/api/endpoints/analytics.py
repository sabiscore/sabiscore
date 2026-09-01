"""First-party analytics event ingestion endpoint with recursive PII & credential scrubbing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional  # noqa: UP035

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...services.analytics_service import AnalyticsIngestionService
from ...services.auth_service import get_anon_id_from_request, get_optional_user_from_request

router = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsEventItem(BaseModel):
    event_id: Optional[str] = Field(None, description="Client-generated idempotency UUID")
    event_name: str = Field(..., min_length=1, max_length=100, description="Typed event name")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Event attributes/metadata")
    session_id: Optional[str] = Field(None, description="Ephemeral client session ID")
    client_platform: Optional[str] = Field("web", description="Client device platform ('web', 'mobile_web', etc.)")
    timestamp: Optional[str] = Field(None, description="ISO-8601 UTC timestamp")


class AnalyticsEventBatchRequest(BaseModel):
    events: List[AnalyticsEventItem] = Field(..., max_length=100, description="Batched telemetry events")


class AnalyticsEventBatchResponse(BaseModel):
    status: str = "OK"
    ingested_count: int
    scrubbed: bool = True


@router.post("/events", response_model=AnalyticsEventBatchResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_analytics_events(
    payload: AnalyticsEventBatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Ingest a batch of client-side product analytics and telemetry events.
    
    All properties are passed through a strict recursive filter that scrubs
    emails, passwords, tokens, API keys, and authorization headers before persisting.
    """
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    events_data = [item.model_dump() for item in payload.events]

    count = await AnalyticsIngestionService.record_events(
        db,
        events=events_data,
        default_anonymous_session_id=anon_id,
        default_user_id=str(user.id) if user else None,
    )

    return AnalyticsEventBatchResponse(
        status="OK",
        ingested_count=count,
        scrubbed=True,
    )


__all__ = ["router"]
