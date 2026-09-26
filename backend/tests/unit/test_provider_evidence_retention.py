"""Directive v9 R2: pruning evidence tables must not change what the service reads.

All three tables gained ~250 rows/day (2026-09-26: 9,944 rows, 2,680 older than
30 days). Retention deletes the old rows, and the guard is that
``latest_provider_evidence`` returns the same answer before and after, apart
from ``observations``, which counts retained rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import src.services.provider_evidence_service as svc
from src.db.models import (
    Base,
    ProviderHealthLog,
    ProviderQuotaObservation,
    ProviderRequestSummary,
)
from src.providers.base import ProviderQuota, ProviderResult, ProviderStatus, TrustTier
from src.services.provider_evidence_service import (
    ProviderEvidenceRecorder,
    latest_provider_evidence,
    prune_provider_evidence,
)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=40)


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _result(provider: str, competition: str, at: datetime) -> ProviderResult:
    return ProviderResult(
        provider=provider,
        operation="fixtures",
        status=ProviderStatus.VERIFIED,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        acquired_at=at,
        records=[{"fixture_id": "fx-1", "coherent": True}],
        quota=ProviderQuota(limit=100, remaining=90, cost=1),
        request_context={"competition": competition, "query_intent": "UPCOMING"},
    )


async def _seed(factory) -> None:
    rows = [
        # A stale context behind a repeated one: deleting the rows between them
        # (keep "newest per context") would pull SERIE_A into the reader's window.
        _result("p", "SERIE_A", OLD),
        _result("p", "LIGUE_1", OLD + timedelta(minutes=1)),
        _result("p", "LIGUE_1", OLD + timedelta(minutes=2)),
        _result("p", "LIGUE_1", OLD + timedelta(minutes=3)),
        _result("p", "EPL", NOW - timedelta(days=1)),
        # A provider last heard from 40 days ago must still report STALE.
        _result("quiet", "EPL", OLD),
        _result("quiet", "EPL", OLD + timedelta(minutes=1)),
    ]
    recorder = ProviderEvidenceRecorder()
    with patch("src.db.session.AsyncSessionLocal", new=factory):
        for row in rows:
            assert await recorder.record_result(row, duration_ms=5.0, circuit_open=False)


async def _evidence(factory) -> dict:
    async with factory() as session:
        return await latest_provider_evidence(session, ["p", "quiet"], now=NOW)


def _without_count(evidence: dict) -> dict:
    return {
        provider: {k: v for k, v in row.items() if k != "observations"}
        for provider, row in evidence.items()
    }


async def _count(factory, model) -> dict[str, int]:
    async with factory() as session:
        rows = await session.execute(
            select(model.provider, func.count()).group_by(model.provider)
        )
        return dict(rows.all())


@pytest.mark.asyncio
async def test_pruning_does_not_change_the_evidence_answer(factory, monkeypatch):
    monkeypatch.setattr(svc, "_PROVIDER_CONTEXT_LOOKBACK_PER_PROVIDER", 3)
    await _seed(factory)
    before = await _evidence(factory)

    async with factory() as session:
        deleted = await prune_provider_evidence(session, now=NOW)
        await session.commit()
    after = await _evidence(factory)

    assert _without_count(after) == _without_count(before)
    assert deleted["provider_health_log"] == 2  # SERIE_A and the oldest LIGUE_1
    assert after["quiet"]["state"] == "STALE"
    assert after["quiet"]["last_observed_at"] is not None
    assert (before["p"]["observations"], after["p"]["observations"]) == (5, 3)


@pytest.mark.asyncio
async def test_unread_tables_keep_only_the_newest_old_row_per_provider(factory):
    await _seed(factory)

    async with factory() as session:
        deleted = await prune_provider_evidence(session, now=NOW)
        await session.commit()

    for model in (ProviderRequestSummary, ProviderQuotaObservation):
        # p: its newest row is recent, so every old row goes; quiet: one survives.
        assert await _count(factory, model) == {"p": 1, "quiet": 1}
        assert deleted[model.__tablename__] == 5
    # Nothing inside the window is ever touched.
    assert (await _count(factory, ProviderHealthLog))["p"] == 5


@pytest.mark.asyncio
async def test_rows_inside_the_window_are_never_deleted(factory, monkeypatch):
    monkeypatch.setattr(svc, "_PROVIDER_CONTEXT_LOOKBACK_PER_PROVIDER", 1)
    recorder = ProviderEvidenceRecorder()
    with patch("src.db.session.AsyncSessionLocal", new=factory):
        for minutes in range(4):
            await recorder.record_result(
                _result("p", "EPL", NOW - timedelta(days=29, minutes=minutes)),
                duration_ms=5.0,
                circuit_open=False,
            )

    async with factory() as session:
        deleted = await prune_provider_evidence(session, now=NOW)
        await session.commit()

    assert deleted == {
        "provider_health_log": 0,
        "provider_request_summaries": 0,
        "provider_quota_observations": 0,
    }
