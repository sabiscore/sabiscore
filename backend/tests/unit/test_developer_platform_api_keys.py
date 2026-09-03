"""Unit tests for developer platform, API keys, rate limiting and usage quotas."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException

from src.db.models import ApiKey
from src.services.developer_service import (
    DeveloperPlatformService,
    verify_developer_api_key,
)


@pytest.mark.asyncio
async def test_developer_key_creation_and_hashing() -> None:
    db = AsyncMock()
    db.add = MagicMock()

    api_key, raw_key = await DeveloperPlatformService.create_api_key(
        db, user_id="user-123", name="Analytics Script", tier="PRO"
    )

    assert raw_key.startswith("sbk_live_")
    assert api_key.key_prefix == raw_key[:16]
    assert api_key.key_hash == DeveloperPlatformService.hash_key(raw_key)
    assert api_key.tier == "PRO"
    assert api_key.rate_limit_per_minute == 60
    assert api_key.daily_quota == 5000
    assert api_key.is_active is True
    # Regression: ApiKey.created_at is a naive `DateTime` column — a tz-aware
    # value crashes asyncpg at bind time on every key creation.
    assert api_key.created_at.tzinfo is None
    db.add.assert_called_once()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_developer_rate_limiting_in_memory() -> None:
    db = AsyncMock()

    api_key = ApiKey(
        id="test-key-1",
        name="Rate Limit Test",
        key_prefix="sbk_live_test",
        key_hash="hash",
        tier="FREE",
        rate_limit_per_minute=2,  # set small limit for testing
        daily_quota=5,
        is_active=True,
    )

    # First request: OK
    res1 = await DeveloperPlatformService.check_and_record_usage(db, api_key)
    assert res1["minute_count"] == 1
    assert res1["minute_remaining"] == 1

    # Second request: OK
    res2 = await DeveloperPlatformService.check_and_record_usage(db, api_key)
    assert res2["minute_count"] == 2
    assert res2["minute_remaining"] == 0

    # Third request: Rate Limit Exceeded
    with pytest.raises(HTTPException) as exc_info:
        await DeveloperPlatformService.check_and_record_usage(db, api_key)
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error"] == "RATE_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_verify_developer_api_key_dependency() -> None:
    db = AsyncMock()
    raw_key = "sbk_live_secretkey12345678901234567890"  # gitleaks:allow — fake fixture, not a real key
    key_hash = DeveloperPlatformService.hash_key(raw_key)

    api_key = ApiKey(
        id="dev-123",
        name="Test Bot",
        key_prefix=raw_key[:16],
        key_hash=key_hash,
        tier="FREE",
        rate_limit_per_minute=10,
        daily_quota=100,
        is_active=True,
    )

    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: api_key)

    request_mock = MagicMock()
    request_mock.headers = {"X-API-Key": raw_key}

    verified_key = await verify_developer_api_key(
        request=request_mock,
        header_key=raw_key,
        db=db,
    )
    assert verified_key.id == "dev-123"
    assert verified_key.tier == "FREE"
    # Regression: last_used_at is a naive `DateTime` column, touched on every
    # authenticated request through this dependency.
    assert verified_key.last_used_at.tzinfo is None
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_verify_developer_api_key_rolls_back_a_failed_commit() -> None:
    """A failed commit here must not leave the request-scoped session's
    transaction in a failed state — the endpoint handler downstream of this
    dependency reuses the same session and would otherwise raise
    PendingRollbackError on its own first query, regardless of what actually
    failed the commit."""
    db = AsyncMock()
    db.commit.side_effect = RuntimeError("boom")
    raw_key = "sbk_live_secretkey12345678901234567890"  # gitleaks:allow — fake fixture, not a real key

    api_key = ApiKey(
        id="dev-124",
        name="Test Bot",
        key_prefix=raw_key[:16],
        key_hash=DeveloperPlatformService.hash_key(raw_key),
        tier="FREE",
        rate_limit_per_minute=10,
        daily_quota=100,
        is_active=True,
    )
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: api_key)
    request_mock = MagicMock()
    request_mock.headers = {"X-API-Key": raw_key}

    await verify_developer_api_key(request=request_mock, header_key=raw_key, db=db)

    db.rollback.assert_awaited_once()
