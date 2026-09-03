"""Unit tests for notification preferences, match subscriptions, and in-app logs."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.db.models import UserNotificationSubscription, UserPreference
from src.services.notification_service import NotificationService


@pytest.mark.asyncio
async def test_notification_preferences_and_timezone_update() -> None:
    db = AsyncMock()
    pref = UserPreference(
        id="pref-1",
        user_id="user-101",
        anonymous_session_id=None,
        odds_format="DECIMAL",
        timezone="Africa/Lagos",
    )
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: pref)

    updated = await NotificationService.update_timezone(
        db, user_id="user-101", timezone_iana="Europe/London"
    )
    assert updated.timezone == "Europe/London"
    # Regression: UserPreference.updated_at is a naive `DateTime` column.
    assert updated.updated_at.tzinfo is None
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_notification_subscription_and_in_app_logs() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)

    # Subscribe
    sub = await NotificationService.subscribe_match(
        db,
        user_id="user-101",
        match_id="fd-500",
        subscription_type="KICKOFF_REMINDER",
        channel="IN_APP",
        reminder_minutes_before=30,
    )
    assert sub.user_id == "user-101"
    assert sub.match_id == "fd-500"
    assert sub.reminder_minutes_before == 30
    # Regression: UserNotificationSubscription.created_at/updated_at are
    # naive `DateTime` columns.
    assert sub.created_at.tzinfo is None
    assert sub.updated_at.tzinfo is None
    db.add.assert_called_once()
    db.commit.assert_awaited()

    # Create log
    log = await NotificationService.create_in_app_notification(
        db,
        user_id="user-101",
        title="Match reminder",
        message="Arsenal vs Chelsea starts soon",
        category="KICKOFF_REMINDER",
        match_id="fd-500",
    )
    assert log.title == "Match reminder"
    assert log.read is False
    # Regression: UserNotificationLog.created_at is a naive `DateTime` column.
    assert log.created_at.tzinfo is None

    # Mark as read
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: log)
    marked = await NotificationService.mark_as_read(
        db, notification_id=log.id, user_id="user-101"
    )
    assert marked is True
    assert log.read is True
    # Regression: UserNotificationLog.read_at is a naive `DateTime` column.
    assert log.read_at.tzinfo is None


@pytest.mark.asyncio
async def test_get_subscriptions_returns_active_matches_only() -> None:
    db = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []
    db.execute.return_value = MagicMock(scalars=lambda: scalars_mock)

    subs = await NotificationService.get_subscriptions(db, user_id="user-101")
    assert subs == []
    db.execute.assert_awaited()


@pytest.mark.asyncio
async def test_list_match_subscriptions_endpoint_returns_active_subscriptions() -> None:
    from src.db.session import get_async_session

    now = datetime.now(timezone.utc)
    sub = UserNotificationSubscription(
        id="sub-1",
        user_id=None,
        anonymous_session_id="anon-77",
        match_id="fd-500",
        subscription_type="KICKOFF_REMINDER",
        channel="IN_APP",
        threshold_pct=None,
        reminder_minutes_before=60,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    mock_db = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [sub]
    mock_db.execute.return_value = MagicMock(scalars=lambda: scalars_mock)

    app.dependency_overrides[get_async_session] = lambda: mock_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/notifications/subscriptions/matches",
                headers={"X-Anonymous-Session": "anon-77"},
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["match_id"] == "fd-500"
        assert data[0]["subscription_type"] == "KICKOFF_REMINDER"
    finally:
        app.dependency_overrides.pop(get_async_session, None)


@pytest.mark.asyncio
async def test_list_match_subscriptions_endpoint_empty_without_identity() -> None:
    from src.db.session import get_async_session

    mock_db = AsyncMock()
    app.dependency_overrides[get_async_session] = lambda: mock_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/notifications/subscriptions/matches")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        app.dependency_overrides.pop(get_async_session, None)
