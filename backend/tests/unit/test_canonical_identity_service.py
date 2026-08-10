"""Regression tests for canonical identity writes."""
from __future__ import annotations

from datetime import datetime

import pytest

from src.services.canonical_identity_service import ensure_canonical_fixture


class _FakeResult:
    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return self

    def first(self):
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[str] = []
        self.flush_snapshots: list[list[str]] = []

    async def get(self, *_args, **_kwargs):
        return None

    async def execute(self, *_args, **_kwargs):
        return _FakeResult()

    def add(self, obj) -> None:
        self.added.append(type(obj).__name__)

    async def flush(self) -> None:
        self.flush_snapshots.append(list(self.added))

    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_ensure_canonical_fixture_flushes_teams_before_fixture_insert() -> None:
    session = _FakeSession()

    fixture_id = await ensure_canonical_fixture(
        session,
        provider="football-data.org",
        provider_event_id="fd-1",
        competition_id="EPL",
        competition_name="Premier League",
        home_provider_id="home-1",
        home_name="Arsenal",
        away_provider_id="away-1",
        away_name="Chelsea",
        kickoff_utc=datetime(2026, 8, 10, 15, 0),
        season="2026/27",
        status="scheduled",
        evidence={"source": "football-data.org"},
    )

    assert fixture_id.startswith("fixture-")
    assert session.flush_snapshots, "expected a flush before the canonical fixture insert"
    assert all("CanonicalFixture" not in snapshot for snapshot in session.flush_snapshots)
    assert "CanonicalFixture" in session.added
