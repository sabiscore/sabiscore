"""Notification and timezone reminder endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...services.auth_service import get_anon_id_from_request, get_optional_user_from_request
from ...services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class NotificationPreferenceUpdate(BaseModel):
    timezone: Optional[str] = Field(None, description="User IANA timezone (e.g., 'Africa/Lagos', 'Europe/London')")
    odds_format: Optional[str] = Field(None, description="'DECIMAL', 'FRACTIONAL', or 'AMERICAN'")
    default_league: Optional[str] = Field(None, description="Default league slug, e.g. 'EPL'")


class NotificationPreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timezone: str
    odds_format: str
    default_league: Optional[str] = None
    updated_at: datetime


class MatchSubscriptionCreate(BaseModel):
    match_id: str = Field(..., description="Match identifier to monitor")
    subscription_type: str = Field("KICKOFF_REMINDER", description="'KICKOFF_REMINDER' or 'PROBABILITY_SWING'")
    channel: str = Field("IN_APP", description="'IN_APP', 'WEB_PUSH', or 'EMAIL'")
    destination: Optional[str] = Field(None, description="Push endpoint, email, or device token")
    threshold_pct: Optional[float] = Field(0.05, description="Probability delta threshold for alerts (default 5%)")
    reminder_minutes_before: Optional[int] = Field(60, description="Minutes before kickoff for reminder")


class MatchSubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    match_id: Optional[str] = None
    subscription_type: str
    channel: str
    threshold_pct: Optional[float] = None
    reminder_minutes_before: Optional[int] = None
    is_active: bool
    created_at: datetime


class InAppNotificationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    message: str
    category: str
    match_id: Optional[str] = None
    read: bool
    read_at: Optional[datetime] = None
    payload: Optional[Dict[str, Any]] = None
    created_at: datetime


class InAppNotificationListResponse(BaseModel):
    items: List[InAppNotificationItem]
    unread_count: int
    total: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/preferences", response_model=NotificationPreferenceResponse)
async def get_notification_preferences(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Get personal notification preferences and timezone settings."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    pref = await NotificationService.get_or_create_preferences(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    return NotificationPreferenceResponse.model_validate(pref)


@router.put("/preferences", response_model=NotificationPreferenceResponse)
async def update_notification_preferences(
    payload: NotificationPreferenceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Update timezone and notification preferences."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if payload.timezone:
        pref = await NotificationService.update_timezone(
            db,
            user_id=str(user.id) if user else None,
            anonymous_session_id=anon_id if not user else None,
            timezone_iana=payload.timezone,
        )
    else:
        pref = await NotificationService.get_or_create_preferences(
            db,
            user_id=str(user.id) if user else None,
            anonymous_session_id=anon_id if not user else None,
        )
    return NotificationPreferenceResponse.model_validate(pref)


@router.post("/subscriptions/matches", response_model=MatchSubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def subscribe_match_notifications(
    payload: MatchSubscriptionCreate,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Subscribe to match kickoff reminders or probability swing alerts."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        anon_id = str(uuid.uuid4())

    sub = await NotificationService.subscribe_match(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
        match_id=payload.match_id,
        subscription_type=payload.subscription_type,
        channel=payload.channel,
        destination=payload.destination,
        threshold_pct=payload.threshold_pct,
        reminder_minutes_before=payload.reminder_minutes_before or 60,
    )
    return MatchSubscriptionResponse.model_validate(sub)


@router.delete("/subscriptions/matches/{match_id}")
async def unsubscribe_match_notifications(
    match_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Unsubscribe from match reminders."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User authentication or anonymous session required",
        )

    success = await NotificationService.unsubscribe_match(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
        match_id=match_id,
    )
    return {"status": "UNSUBSCRIBED" if success else "NOT_FOUND"}


@router.get("/subscriptions/matches", response_model=List[MatchSubscriptionResponse])
async def list_match_subscriptions(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """List active match kickoff/probability-swing subscriptions for the caller."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        return []

    subs = await NotificationService.get_subscriptions(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    return [MatchSubscriptionResponse.model_validate(sub) for sub in subs]


@router.get("/in-app", response_model=InAppNotificationListResponse)
async def get_in_app_notifications(
    request: Request,
    unread_only: bool = False,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_session),
):
    """Retrieve in-app notifications and unread badge count."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    if not user and not anon_id:
        return InAppNotificationListResponse(items=[], unread_count=0, total=0)

    logs = await NotificationService.get_in_app_notifications(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
        unread_only=unread_only,
        limit=limit,
    )
    unread = sum(1 for log in logs if not log.read)
    return InAppNotificationListResponse(
        items=[InAppNotificationItem.model_validate(log) for log in logs],
        unread_count=unread,
        total=len(logs),
    )


@router.post("/in-app/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Mark a single in-app notification as read."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    success = await NotificationService.mark_as_read(
        db,
        notification_id=notification_id,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return {"status": "READ", "id": notification_id}


@router.post("/in-app/read-all")
async def mark_all_notifications_read(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Mark all in-app notifications as read."""
    user = await get_optional_user_from_request(request, db)
    anon_id = get_anon_id_from_request(request)

    count = await NotificationService.mark_all_as_read(
        db,
        user_id=str(user.id) if user else None,
        anonymous_session_id=anon_id if not user else None,
    )
    return {"status": "READ_ALL", "updated_count": count}


__all__ = ["router"]
