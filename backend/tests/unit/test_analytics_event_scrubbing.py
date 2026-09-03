"""Unit tests for first-party analytics ingestion and recursive PII scrubbing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest

from src.services.analytics_service import (
    AnalyticsIngestionService,
    scrub_pii_and_secrets,
)


def test_scrub_pii_and_secrets_removes_sensitive_data() -> None:
    raw_payload = {
        "user_email": "analyst@sabiscore.com",
        "nested": {
            "password": "supersecretpassword",
            "api_key": "sbk_live_1234567890",  # gitleaks:allow — fake fixture proving the scrubber redacts this shape
            "safe_property": "Chelsea vs Arsenal",
            "feedback_text": "Contact support at user.name@domain.co.uk for details",
            "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz",
        },
        "event_list": [
            {"token": "secret_token_val", "safe_val": 42},
            "Send reports to manager@corp.com immediately",
        ],
    }

    cleaned = scrub_pii_and_secrets(raw_payload)

    # Key scrubbing
    assert cleaned["user_email"] == "[REDACTED_SECRET]"
    assert cleaned["nested"]["password"] == "[REDACTED_SECRET]"
    assert cleaned["nested"]["api_key"] == "[REDACTED_SECRET]"
    assert cleaned["nested"]["auth_header"] == "[REDACTED_SECRET]"
    assert cleaned["nested"]["safe_property"] == "Chelsea vs Arsenal"

    # String value regex email scrubbing
    assert "[REDACTED_EMAIL]" in cleaned["nested"]["feedback_text"]
    assert "user.name@domain.co.uk" not in cleaned["nested"]["feedback_text"]

    # List items scrubbing
    assert cleaned["event_list"][0]["token"] == "[REDACTED_SECRET]"
    assert cleaned["event_list"][0]["safe_val"] == 42
    assert "[REDACTED_EMAIL]" in cleaned["event_list"][1]
    assert "manager@corp.com" not in cleaned["event_list"][1]


@pytest.mark.asyncio
async def test_analytics_ingestion_service_batch() -> None:
    db = AsyncMock()
    db.add_all = MagicMock()

    events = [
        {
            "event_name": "match_viewed",
            "properties": {"match_id": "fd-100", "email": "test@example.com"},
            "client_platform": "web",
        },
        {
            "event_name": "odds_compared",
            "properties": {"match_id": "fd-100", "bookmakers": 4},
            "client_platform": "web_mobile",
        },
    ]

    count = await AnalyticsIngestionService.record_events(
        db, events=events, default_anonymous_session_id="anon-777"
    )

    assert count == 2
    db.add_all.assert_called_once()
    records = db.add_all.call_args[0][0]
    assert len(records) == 2
    assert records[0].event_name == "match_viewed"
    assert records[0].properties["email"] == "[REDACTED_SECRET]"
    assert records[0].anonymous_session_id == "anon-777"
    # Regression: AnalyticsEvent.timestamp/created_at are naive `DateTime`
    # columns — a tz-aware value crashes asyncpg at bind time on every event.
    assert records[0].created_at.tzinfo is None
    assert records[0].timestamp.tzinfo is None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_analytics_ingestion_normalizes_client_supplied_timestamps() -> None:
    """A client can send its own event timestamp as an ISO string (with a Z or
    numeric offset) or a Unix epoch float — both are tz-aware once parsed and
    must be stripped before reaching the naive `timestamp` column."""
    db = AsyncMock()
    db.add_all = MagicMock()

    events = [
        {"event_name": "iso_ts", "properties": {}, "timestamp": "2026-01-01T12:00:00Z"},
        {"event_name": "epoch_ts", "properties": {}, "timestamp": 1735732800.0},
    ]

    await AnalyticsIngestionService.record_events(db, events=events)

    records = db.add_all.call_args[0][0]
    assert records[0].timestamp.tzinfo is None
    assert records[1].timestamp.tzinfo is None
