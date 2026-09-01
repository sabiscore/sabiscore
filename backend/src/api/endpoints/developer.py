"""Developer platform endpoints: API key management, entitlement tiers, and usage metering."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import ApiKey
from ...db.session import get_async_session
from ...services.auth_service import get_optional_user_from_request
from ...services.developer_service import (
    DeveloperPlatformService,
    verify_developer_api_key,
)

router = APIRouter(prefix="/developer", tags=["developer"])


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Friendly label for this API key")
    tier: str = Field("FREE", description="'FREE' (10 req/min, 100/day) or 'PRO' (60 req/min, 5000/day)")


class ApiKeyCreatedResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key_prefix: str
    api_key: str
    tier: str
    rate_limit_per_minute: int
    daily_quota: int
    created_at: datetime
    warning: str = "Store this API key securely. It will never be shown again."


class ApiKeyListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    key_prefix: str
    tier: str
    rate_limit_per_minute: int
    daily_quota: int
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None


class DeveloperUsageResponse(BaseModel):
    key_id: str
    key_name: str
    key_prefix: str
    tier: str
    rate_limit_per_minute: int
    minute_requests_used: int
    minute_requests_remaining: int
    daily_quota: int
    daily_requests_used: int
    daily_requests_remaining: int
    is_active: bool
    last_used_at: Optional[str] = None
    created_at: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: ApiKeyCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Generate a new developer API key with tier entitlement limits."""
    user = await get_optional_user_from_request(request, db)

    tier = payload.tier.strip().upper()
    if tier not in DeveloperPlatformService.TIER_DEFAULTS:
        tier = "FREE"

    api_key, raw_key = await DeveloperPlatformService.create_api_key(
        db,
        user_id=str(user.id) if user else None,
        name=payload.name,
        tier=tier,
    )

    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        api_key=raw_key,
        tier=api_key.tier,
        rate_limit_per_minute=api_key.rate_limit_per_minute,
        daily_quota=api_key.daily_quota,
        created_at=api_key.created_at,
    )


@router.get("/keys", response_model=List[ApiKeyListItem])
async def list_keys(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """List API keys owned by current user or created in current session."""
    user = await get_optional_user_from_request(request, db)
    keys = await DeveloperPlatformService.list_keys(
        db, user_id=str(user.id) if user else None
    )
    return [ApiKeyListItem.model_validate(k) for k in keys]


@router.delete("/keys/{key_id}")
async def revoke_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Revoke an active API key."""
    user = await get_optional_user_from_request(request, db)
    success = await DeveloperPlatformService.revoke_key(
        db, key_id=key_id, user_id=str(user.id) if user else None
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or not owned by current user",
        )
    return {"status": "REVOKED", "key_id": key_id}


@router.get("/usage", response_model=DeveloperUsageResponse)
async def get_developer_usage(
    api_key: ApiKey = Security(verify_developer_api_key),
    db: AsyncSession = Depends(get_async_session),
):
    """Get live rate-limit and quota usage telemetry for the authenticated developer key."""
    summary = await DeveloperPlatformService.get_usage_summary(db, api_key=api_key)
    return DeveloperUsageResponse(**summary)


__all__ = ["router", "verify_developer_api_key"]
