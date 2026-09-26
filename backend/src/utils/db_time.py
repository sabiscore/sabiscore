"""Shared helper for writing to naive ``DateTime`` (TIMESTAMP WITHOUT TIME ZONE) columns.

Every timestamp column in ``db/models.py`` and ``core/database.py`` is a plain
``DateTime`` — none use ``DateTime(timezone=True)``. asyncpg's codec for that
Postgres type raises ``can't subtract offset-naive and offset-aware
datetimes`` at bind time if handed a tz-aware Python `datetime` (it diffs
against a naive epoch internally), so every value written to one of these
columns must have `tzinfo` stripped first — but the *application's* own
"now" should stay tz-aware (``datetime.now(timezone.utc)``) everywhere else.

This exact two-line fix had already been reinvented independently at least
seven times across this codebase (``auth_service.py``, ``elo_state_service.py``,
``market_observation_service.py``, ``clv_capture_service.py``,
``prediction_log_service.py``, ``provider_evidence_service.py``,
``notification_dispatch_service.py``) before this module existed — new
service code should import from here instead of adding an eighth.
"""

from __future__ import annotations

from datetime import datetime, timezone


def naive_utc_now() -> datetime:
    """Current UTC time with `tzinfo` stripped, for direct assignment to a
    naive `DateTime` column."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime) -> datetime:
    """Strip `tzinfo` from an existing datetime before binding it to a naive
    `DateTime` column. A naive input is returned unchanged (already safe)."""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def to_utc_iso(value: datetime) -> str:
    """ISO 8601 with an explicit UTC offset, for a value read back from a naive
    column. Browsers parse an offset-less timestamp as *local* time, so a Lagos
    visitor read an 18:00 UTC kickoff as "18:00 WAT" (live 2026-09-26; it is
    19:00 WAT), and a server render in UTC disagreed with the browser."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


__all__ = ["naive_utc_now", "to_naive_utc", "to_utc_iso"]
