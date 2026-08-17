"""Provider evidence persistence and registry-observation regressions."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base
from src.db.models import ProviderHealthLog, ProviderQuotaObservation, ProviderRequestSummary
from src.providers.base import BaseProvider, ProviderQuota, ProviderResult, ProviderStatus, TrustTier
from src.providers.registry import ProviderRegistry
from src.services.provider_evidence_service import ProviderEvidenceRecorder, latest_provider_evidence


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


def _result(status: ProviderStatus = ProviderStatus.VERIFIED) -> ProviderResult:
    return ProviderResult(
        provider="test_provider",
        operation="fixtures",
        status=status,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        acquired_at=datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc),
        provider_timestamp=datetime(2026, 8, 16, 23, 59, tzinfo=timezone.utc),
        records=[{"fixture_id": "fx-1", "coherent": True}],
        quota=ProviderQuota(limit=100, remaining=91, cost=1),
        warnings=["Bearer secret-token", "apiKey=secret-value"],
        raw_snapshot_id="abc123",
    )


async def test_recorder_persists_sanitized_request_health_and_quota(factory) -> None:
    recorder = ProviderEvidenceRecorder()

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        persisted = await recorder.record_result(
            _result(),
            duration_ms=12.5,
            circuit_open=False,
        )

    assert persisted is True
    async with factory() as session:
        summaries = (await session.execute(select(ProviderRequestSummary))).scalars().all()
        health_rows = (await session.execute(select(ProviderHealthLog))).scalars().all()
        quota_rows = (await session.execute(select(ProviderQuotaObservation))).scalars().all()

    assert len(summaries) == len(health_rows) == len(quota_rows) == 1
    summary = summaries[0]
    assert summary.provider == "test_provider"
    assert summary.operation == "fixtures"
    assert summary.status == "VERIFIED"
    assert summary.quota_remaining == 91
    assert summary.response_hash
    persisted_warning_text = " ".join(summary.warnings or [])
    assert "secret-token" not in persisted_warning_text
    assert "secret-value" not in persisted_warning_text
    assert "[REDACTED]" in persisted_warning_text

    health = health_rows[0]
    assert health.latency_ms == pytest.approx(12.5)
    assert health.details["record_count"] == 1
    assert health.details["operation"] == "fixtures"
    assert health.details["circuit_open"] is False


async def test_recorder_db_not_ready_is_non_disruptive() -> None:
    recorder = ProviderEvidenceRecorder()

    with patch("src.db.session.AsyncSessionLocal", new=None):
        persisted = await recorder.record_result(
            _result(),
            duration_ms=1.0,
            circuit_open=False,
        )

    assert persisted is False


async def test_latest_evidence_zero_observations_is_unknown(factory) -> None:
    async with factory() as session:
        evidence = await latest_provider_evidence(session, ["test_provider"])

    assert evidence["test_provider"]["state"] == "UNKNOWN"
    assert evidence["test_provider"]["observations"] == 0
    assert evidence["test_provider"]["last_observed_at"] is None


async def test_latest_evidence_uses_latest_persisted_status(factory) -> None:
    recorder = ProviderEvidenceRecorder()

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        first = _result(ProviderStatus.RATE_LIMITED)
        first.acquired_at = datetime(2026, 8, 16, 23, 0, tzinfo=timezone.utc)
        second = _result(ProviderStatus.VERIFIED)
        second.acquired_at = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
        await recorder.record_result(first, duration_ms=20.0, circuit_open=False)
        await recorder.record_result(second, duration_ms=10.0, circuit_open=False)

    async with factory() as session:
        evidence = await latest_provider_evidence(session, ["test_provider"])

    assert evidence["test_provider"]["state"] == "LIVE_VERIFIED"
    assert evidence["test_provider"]["status"] == "VERIFIED"
    assert evidence["test_provider"]["observations"] == 2
    assert evidence["test_provider"]["operation"] == "fixtures"


class _DummyProvider(BaseProvider):
    provider_id = "dummy"
    trust_tier = TrustTier.OPEN_DATA

    async def fixtures(self) -> ProviderResult:
        return ProviderResult(
            provider=self.provider_id,
            operation="fixtures",
            status=ProviderStatus.VERIFIED,
            trust_tier=self.trust_tier,
            records=[{"ok": True}],
        )

    async def exploding(self) -> ProviderResult:
        raise RuntimeError("Bearer should-not-leak")


async def test_registry_proxy_observes_provider_results_without_changing_return() -> None:
    sink = SimpleNamespace(
        record_result=AsyncMock(return_value=True),
        record_exception=AsyncMock(return_value=True),
    )
    provider = _DummyProvider(enabled=True, observation_sink=sink)
    registry = ProviderRegistry([provider])

    result = await registry.get("dummy").fixtures()

    assert result.status is ProviderStatus.VERIFIED
    sink.record_result.assert_awaited_once()
    sink.record_exception.assert_not_awaited()


async def test_registry_proxy_observes_then_reraises_unexpected_exception() -> None:
    sink = SimpleNamespace(
        record_result=AsyncMock(return_value=True),
        record_exception=AsyncMock(return_value=True),
    )
    provider = _DummyProvider(enabled=True, observation_sink=sink)
    registry = ProviderRegistry([provider])

    with pytest.raises(RuntimeError, match="should-not-leak"):
        await registry.get("dummy").exploding()

    sink.record_exception.assert_awaited_once()
    sink.record_result.assert_not_awaited()


async def test_observation_sink_failure_never_changes_provider_result() -> None:
    sink = SimpleNamespace(
        record_result=AsyncMock(side_effect=RuntimeError("telemetry unavailable")),
        record_exception=AsyncMock(return_value=True),
    )
    provider = _DummyProvider(enabled=True, observation_sink=sink)
    registry = ProviderRegistry([provider])

    result = await registry.get("dummy").fixtures()

    assert result.status is ProviderStatus.VERIFIED
