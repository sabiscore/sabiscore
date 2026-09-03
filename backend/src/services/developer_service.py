"""Developer platform service: API key generation, revocation, rate-limiting and usage tracking."""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request, Security, status
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.cache import cache
from ..db.models import ApiKey
from ..db.session import get_async_session
from ..utils.db_time import naive_utc_now, to_naive_utc

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# In-memory sliding window fallback when Redis is offline (e.g. unit test suite)
_in_memory_rate_counts: Dict[str, List[float]] = {}
_in_memory_daily_counts: Dict[str, Dict[str, int]] = {}


class DeveloperPlatformService:
    """Manages API key lifecycle, entitlement quotas, and sliding-window rate limiting."""

    TIER_DEFAULTS = {
        "FREE": {"rate_limit_per_minute": 10, "daily_quota": 100},
        "PRO": {"rate_limit_per_minute": 60, "daily_quota": 5000},
    }

    @staticmethod
    def hash_key(raw_key: str) -> str:
        """Compute cryptographic SHA-256 hash of API key."""
        return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()

    @staticmethod
    def generate_raw_key() -> str:
        """Generate secure live API key token: sbk_live_<48_hex_chars>."""
        return f"sbk_live_{secrets.token_hex(24)}"

    @classmethod
    async def create_api_key(
        cls,
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        name: str,
        tier: str = "FREE",
    ) -> tuple[ApiKey, str]:
        clean_tier = tier.strip().upper()
        if clean_tier not in cls.TIER_DEFAULTS:
            clean_tier = "FREE"

        tier_config = cls.TIER_DEFAULTS[clean_tier]
        raw_key = cls.generate_raw_key()
        key_prefix = raw_key[:16]  # e.g. "sbk_live_a1b2c3d4"
        key_hash = cls.hash_key(raw_key)

        api_key = ApiKey(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=name.strip() or "Default API Key",
            key_prefix=key_prefix,
            key_hash=key_hash,
            tier=clean_tier,
            rate_limit_per_minute=tier_config["rate_limit_per_minute"],
            daily_quota=tier_config["daily_quota"],
            is_active=True,
            created_at=naive_utc_now(),
            last_used_at=None,
            expires_at=None,
        )
        db.add(api_key)
        await db.commit()
        await db.refresh(api_key)

        return api_key, raw_key

    @staticmethod
    async def list_keys(
        db: AsyncSession, *, user_id: Optional[str] = None
    ) -> List[ApiKey]:
        stmt = select(ApiKey)
        if user_id:
            stmt = stmt.where(ApiKey.user_id == user_id)
        stmt = stmt.order_by(ApiKey.created_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_key_by_id(
        db: AsyncSession, key_id: str, *, user_id: Optional[str] = None
    ) -> Optional[ApiKey]:
        stmt = select(ApiKey).where(ApiKey.id == key_id)
        if user_id:
            stmt = stmt.where(ApiKey.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def revoke_key(
        db: AsyncSession, key_id: str, *, user_id: Optional[str] = None
    ) -> bool:
        stmt = select(ApiKey).where(ApiKey.id == key_id)
        if user_id:
            stmt = stmt.where(ApiKey.user_id == user_id)
        result = await db.execute(stmt)
        key = result.scalar_one_or_none()
        if not key:
            return False

        key.is_active = False
        await db.commit()
        return True

    @classmethod
    async def check_and_record_usage(
        cls, db: AsyncSession, api_key: ApiKey
    ) -> Dict[str, Any]:
        """Check minute rate limit and daily quota, updating meters."""
        now_ts = time.time()
        today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key_id = api_key.id
        minute_limit = api_key.rate_limit_per_minute
        daily_limit = api_key.daily_quota

        # 1. Try Redis rate limiting
        redis_client = getattr(cache, "redis_client", None)
        if redis_client and getattr(cache, "is_available", False):
            try:
                min_key = f"ratelimit:dev:{key_id}:{int(now_ts // 60)}"
                day_key = f"quota:dev:{key_id}:{today_date}"

                # Increment minute counter
                min_count = await redis_client.incr(min_key)
                if min_count == 1:
                    await redis_client.expire(min_key, 65)

                if min_count > minute_limit:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail={
                            "error": "RATE_LIMIT_EXCEEDED",
                            "message": f"Rate limit of {minute_limit} requests per minute exceeded.",
                            "tier": api_key.tier,
                            "limit": minute_limit,
                            "remaining": 0,
                            "reset_seconds": 60 - int(now_ts % 60),
                        },
                        headers={
                            "X-RateLimit-Limit": str(minute_limit),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(60 - int(now_ts % 60)),
                            "Retry-After": str(60 - int(now_ts % 60)),
                        },
                    )

                # Increment daily counter
                day_count = await redis_client.incr(day_key)
                if day_count == 1:
                    await redis_client.expire(day_key, 86400 * 2)

                if day_count > daily_limit:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail={
                            "error": "DAILY_QUOTA_EXCEEDED",
                            "message": f"Daily quota of {daily_limit} requests exceeded for today.",
                            "tier": api_key.tier,
                            "daily_limit": daily_limit,
                            "daily_remaining": 0,
                        },
                        headers={
                            "X-Quota-Daily-Limit": str(daily_limit),
                            "X-Quota-Daily-Remaining": "0",
                            "Retry-After": "3600",
                        },
                    )

                return {
                    "minute_count": min_count,
                    "minute_remaining": max(0, minute_limit - min_count),
                    "day_count": day_count,
                    "day_remaining": max(0, daily_limit - day_count),
                }
            except HTTPException:
                raise
            except Exception:
                pass  # Fall through to in-memory

        # 2. In-memory fallback
        # Minute window
        timestamps = _in_memory_rate_counts.setdefault(key_id, [])
        cutoff = now_ts - 60.0
        timestamps[:] = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= minute_limit:
            reset_sec = max(1, int(60 - (now_ts - timestamps[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "RATE_LIMIT_EXCEEDED",
                    "message": f"Rate limit of {minute_limit} requests per minute exceeded.",
                    "tier": api_key.tier,
                    "limit": minute_limit,
                    "remaining": 0,
                    "reset_seconds": reset_sec,
                },
                headers={
                    "X-RateLimit-Limit": str(minute_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_sec),
                    "Retry-After": str(reset_sec),
                },
            )
        timestamps.append(now_ts)

        # Day window
        day_dict = _in_memory_daily_counts.setdefault(key_id, {})
        current_day_count = day_dict.get(today_date, 0)
        if current_day_count >= daily_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "DAILY_QUOTA_EXCEEDED",
                    "message": f"Daily quota of {daily_limit} requests exceeded for today.",
                    "tier": api_key.tier,
                    "daily_limit": daily_limit,
                    "daily_remaining": 0,
                },
                headers={
                    "X-Quota-Daily-Limit": str(daily_limit),
                    "X-Quota-Daily-Remaining": "0",
                    "Retry-After": "3600",
                },
            )
        day_dict[today_date] = current_day_count + 1

        return {
            "minute_count": len(timestamps),
            "minute_remaining": max(0, minute_limit - len(timestamps)),
            "day_count": day_dict[today_date],
            "day_remaining": max(0, daily_limit - day_dict[today_date]),
        }

    @classmethod
    async def get_usage_summary(
        cls, db: AsyncSession, *, api_key: ApiKey
    ) -> Dict[str, Any]:
        """Fetch usage stats for a developer API key."""
        now_ts = time.time()
        today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key_id = api_key.id
        minute_limit = api_key.rate_limit_per_minute
        daily_limit = api_key.daily_quota

        day_count = 0
        min_count = 0

        redis_client = getattr(cache, "redis_client", None)
        if redis_client and getattr(cache, "is_available", False):
            try:
                min_key = f"ratelimit:dev:{key_id}:{int(now_ts // 60)}"
                day_key = f"quota:dev:{key_id}:{today_date}"
                val_min = await redis_client.get(min_key)
                val_day = await redis_client.get(day_key)
                min_count = int(val_min) if val_min else 0
                day_count = int(val_day) if val_day else 0
            except Exception:
                pass
        else:
            timestamps = _in_memory_rate_counts.get(key_id, [])
            cutoff = now_ts - 60.0
            min_count = sum(1 for t in timestamps if t > cutoff)
            day_count = _in_memory_daily_counts.get(key_id, {}).get(today_date, 0)

        return {
            "key_id": api_key.id,
            "key_name": api_key.name,
            "key_prefix": api_key.key_prefix,
            "tier": api_key.tier,
            "rate_limit_per_minute": minute_limit,
            "minute_requests_used": min_count,
            "minute_requests_remaining": max(0, minute_limit - min_count),
            "daily_quota": daily_limit,
            "daily_requests_used": day_count,
            "daily_requests_remaining": max(0, daily_limit - day_count),
            "is_active": api_key.is_active,
            "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
            "created_at": api_key.created_at.isoformat(),
        }


async def verify_developer_api_key(
    request: Request,
    header_key: Optional[str] = Security(api_key_header),
    db: AsyncSession = Security(get_async_session),
) -> ApiKey:
    """FastAPI dependency verifying API key token, active status, rate limit and quota."""
    raw_key = header_key
    if not raw_key:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token_candidate = auth_header.split(" ", 1)[1].strip()
            if token_candidate.startswith("sbk_live_"):
                raw_key = token_candidate

    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide header 'X-API-Key: sbk_live_...' or 'Authorization: Bearer sbk_live_...'",
        )

    key_hash = DeveloperPlatformService.hash_key(raw_key)
    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    if not api_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key has been revoked",
        )

    # api_key.expires_at is a naive `DateTime` column, so a real Postgres
    # read-back is naive — but callers (tests included) may hand this
    # function an ApiKey built in-process with an aware value, so normalize
    # whichever we got rather than assume. None do today — create_api_key
    # always writes None — but this must not be a landmine for whenever a
    # real expiry ships.
    if api_key.expires_at and to_naive_utc(api_key.expires_at) < naive_utc_now():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key has expired",
        )

    # Check and record rate limit & daily quota
    await DeveloperPlatformService.check_and_record_usage(db, api_key)

    # Asynchronously touch last_used_at
    api_key.last_used_at = naive_utc_now()
    try:
        await db.commit()
    except Exception:
        # A failed commit leaves this request-scoped session's transaction in
        # a failed state; without rolling back, every subsequent db.execute()
        # in this same request (the endpoint handler downstream of this
        # dependency) would raise PendingRollbackError instead of the
        # request's own logic ever running.
        await db.rollback()

    return api_key
