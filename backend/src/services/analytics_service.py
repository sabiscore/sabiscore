"""First-party analytics service with recursive PII & secret scrubbing filter."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AnalyticsEvent

_SENSITIVE_KEYS = {
    "password",
    "email",
    "token",
    "secret",
    "key",
    "authorization",
    "cookie",
    "credit_card",
    "ssn",
    "auth",
    "apikey",
    "api_key",
    "session_token",
    "jwt",
    "access_token",
    "refresh_token",
    "hashed_password",
}

_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)
_BEARER_PATTERN = re.compile(
    r"(?i)bearer\s+[A-Za-z0-9\-_\.=]+"
)


def scrub_pii_and_secrets(data: Any) -> Any:
    """Recursively redact PII (emails), passwords, auth headers, and tokens from any dictionary, list, or scalar."""
    if isinstance(data, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            k_tokens = set(re.split(r"[_ \-\.]+", k_lower))
            if any(sensitive in k_tokens or sensitive == k_lower for sensitive in _SENSITIVE_KEYS):
                cleaned[k] = "[REDACTED_SECRET]"
            else:
                cleaned[k] = scrub_pii_and_secrets(v)
        return cleaned
    elif isinstance(data, list):
        return [scrub_pii_and_secrets(item) for item in data]
    elif isinstance(data, str):
        # Scrub inline emails
        scrubbed = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", data)
        # Scrub inline bearer tokens
        scrubbed = _BEARER_PATTERN.sub("[REDACTED_BEARER]", scrubbed)
        return scrubbed
    return data


class AnalyticsIngestionService:
    """Ingests, sanitizes, and persists first-party user engagement and telemetry events."""

    @staticmethod
    def sanitize_event_properties(properties: Dict[str, Any]) -> Dict[str, Any]:
        return scrub_pii_and_secrets(properties) if properties else {}

    @classmethod
    async def record_events(
        cls,
        db: AsyncSession,
        *,
        events: List[Dict[str, Any]],
        default_anonymous_session_id: Optional[str] = None,
        default_user_id: Optional[str] = None,
    ) -> int:
        """Batch sanitize and persist events to the database."""
        now = datetime.now(timezone.utc)
        records: List[AnalyticsEvent] = []

        for raw in events:
            event_name = str(raw.get("event_name") or raw.get("name") or "unknown_event").strip()
            properties = raw.get("properties") or {}
            sanitized_props = cls.sanitize_event_properties(properties)

            raw_timestamp = raw.get("timestamp")
            if isinstance(raw_timestamp, str):
                try:
                    event_time = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
                except Exception:
                    event_time = now
            elif isinstance(raw_timestamp, (int, float)):
                event_time = datetime.fromtimestamp(raw_timestamp, tz=timezone.utc)
            else:
                event_time = now

            record = AnalyticsEvent(
                event_id=str(raw.get("event_id") or uuid.uuid4()),
                anonymous_session_id=raw.get("anonymous_session_id") or default_anonymous_session_id,
                user_id=raw.get("user_id") or default_user_id,
                event_name=event_name,
                properties=sanitized_props,
                session_id=raw.get("session_id"),
                client_platform=raw.get("client_platform") or "web",
                timestamp=event_time,
                created_at=now,
            )
            records.append(record)

        if records:
            db.add_all(records)
            await db.commit()

        return len(records)
