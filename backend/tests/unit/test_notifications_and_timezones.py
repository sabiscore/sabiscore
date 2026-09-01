"""Unit tests for notification preferences, match subscriptions, and in-app logs."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from src.db.models import UserPreference
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

    # Mark as read
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: log)
    marked = await NotificationService.mark_as_read(
        db, notification_id=log.id, user_id="user-101"
    )
    assert marked is True
    assert log.read is True
