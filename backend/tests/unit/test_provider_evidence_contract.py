"""SAB-15 request-level provider evidence contract regressions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, ProviderHealthLog
from src.providers.base import (
    BaseProvider,
    ProviderResult,
    ProviderStatus,
    ProviderTransportError,
    ProviderTransportKind,
    TrustTier,
)
from src.providers.football_data_org import FootballDataOrgProvider
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


class _HTTPDummyProvider(BaseProvider):
    provider_id = "http_dummy"
    trust_tier = TrustTier.OFFICIAL_OPEN

    async def fixtures(self) -> ProviderResult:
        payload, _headers = await self._get_json("https://provider.test/fixtures")
        return ProviderResult(
            provider=self.provider_id,
            operation="fixtures",
            status=ProviderStatus.VERIFIED,
            trust_tier=self.trust_tier,
            records=[{"provider_event_id": payload["id"], "coherent": True}],
        )


async def test_registry_attaches_sanitized_success_http_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "fx-1"}, request=request)

    sink = SimpleNamespace(
        record_result=AsyncMock(return_value=True),
        record_exception=AsyncMock(return_value=True),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = _HTTPDummyProvider(enabled=True, http_client=client, observation_sink=sink)
    registry = ProviderRegistry([provider])
    try:
        result = await registry.get("http_dummy").fixtures()
    finally:
        await client.aclose()

    assert result.http_status_code == 200
    assert result.http_status_category == "SUCCESS"
    observed = sink.record_result.await_args.args[0]
    assert observed.http_status_code == 200
    assert observed.http_status_category == "SUCCESS"
    sink.record_exception.assert_not_awaited()


async def test_http_200_with_zero_usable_odds_is_not_coverage_success(factory) -> None:
    observed_at = datetime(2026, 8, 17, 18, 0, tzinfo=timezone.utc)
    result = ProviderResult(
        provider="the_odds_api",
        operation="odds",
        status=ProviderStatus.VERIFIED,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        acquired_at=observed_at,
        http_status_code=200,
        http_status_category="SUCCESS",
        records=[
            {
                "provider_event_id": "evt-1",
                "bookmaker": "book-a",
                "coherent": False,
                "executable": False,
                "rejection_reason": "incomplete_1x2_outcomes",
            }
        ],
    )
    recorder = ProviderEvidenceRecorder()

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        assert await recorder.record_result(result, duration_ms=14.0, circuit_open=False) is True

    async with factory() as session:
        health = (await session.execute(select(ProviderHealthLog))).scalar_one()
        evidence = await latest_provider_evidence(
            session,
            ["the_odds_api"],
            now=observed_at + timedelta(minutes=5),
        )

    assert health.details["transport"] == {
        "outcome": "SUCCESS",
        "http_status_code": 200,
        "http_status_category": "SUCCESS",
    }
    assert health.details["coverage"]["state"] == "UNUSABLE"
    assert health.details["coverage"]["total_records"] == 1
    assert health.details["coverage"]["usable_records"] == 0
    assert health.details["coverage"]["usable_events"] == 0
    row = evidence["the_odds_api"]
    assert row["state"] == "LIVE_VERIFIED"
    assert row["transport"]["outcome"] == "SUCCESS"
    assert row["coverage"]["state"] == "UNUSABLE"
    assert row["coverage"]["usable_records"] == 0


async def test_odds_coverage_counts_executable_events_without_double_counting_bookmakers(factory) -> None:
    observed_at = datetime(2026, 8, 17, 18, 10, tzinfo=timezone.utc)
    source_at = observed_at - timedelta(seconds=45)
    result = ProviderResult(
        provider="the_odds_api",
        operation="odds",
        status=ProviderStatus.VERIFIED,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        acquired_at=observed_at,
        http_status_code=200,
        http_status_category="SUCCESS",
        records=[
            {
                "provider_event_id": "evt-1",
                "bookmaker": "book-a",
                "coherent": True,
                "executable": True,
                "bookmaker_last_update": source_at.isoformat(),
            },
            {
                "provider_event_id": "evt-1",
                "bookmaker": "book-b",
                "coherent": True,
                "executable": True,
                "bookmaker_last_update": source_at.isoformat(),
            },
            {
                "provider_event_id": "evt-2",
                "bookmaker": "book-c",
                "coherent": False,
                "executable": False,
                "bookmaker_last_update": (source_at - timedelta(seconds=10)).isoformat(),
            },
        ],
    )
    recorder = ProviderEvidenceRecorder()

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        await recorder.record_result(result, duration_ms=11.0, circuit_open=False)

    async with factory() as session:
        evidence = await latest_provider_evidence(
            session,
            ["the_odds_api"],
            now=observed_at + timedelta(minutes=1),
        )

    coverage = evidence["the_odds_api"]["coverage"]
    assert coverage["total_records"] == 3
    assert coverage["coherent_records"] == 2
    assert coverage["executable_records"] == 2
    assert coverage["usable_records"] == 2
    assert coverage["total_events"] == 2
    assert coverage["usable_events"] == 1
    freshness = evidence["the_odds_api"]["freshness"]
    assert freshness["source_latest_at"] == source_at.replace(tzinfo=None).isoformat()
    assert freshness["source_age_seconds"] == pytest.approx(105.0)


async def test_fixture_coverage_counts_only_coherent_and_settled_records(factory) -> None:
    result = ProviderResult(
        provider="football_data_org",
        operation="fixtures",
        status=ProviderStatus.VERIFIED,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        acquired_at=datetime(2026, 8, 17, 18, 20, tzinfo=timezone.utc),
        http_status_code=200,
        http_status_category="SUCCESS",
        records=[
            {
                "provider_event_id": "fx-1",
                "coherent": True,
                "home_score": 2,
                "away_score": 1,
            },
            {
                "provider_event_id": "fx-2",
                "coherent": True,
                "home_score": None,
                "away_score": None,
            },
            {
                "provider_event_id": "fx-3",
                "coherent": False,
                "home_score": None,
                "away_score": None,
            },
        ],
    )
    recorder = ProviderEvidenceRecorder()

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        await recorder.record_result(result, duration_ms=8.0, circuit_open=False)

    async with factory() as session:
        health = (await session.execute(select(ProviderHealthLog))).scalar_one()

    coverage = health.details["coverage"]
    assert coverage["basis"] == "coherent"
    assert coverage["coherent_records"] == 2
    assert coverage["usable_records"] == 2
    assert coverage["settled_records"] == 1


def test_football_data_reset_header_is_delta_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_now = datetime(2026, 8, 17, 18, 30, tzinfo=timezone.utc)
    monkeypatch.setattr("src.providers.football_data_org.utc_now", lambda: fixed_now)
    provider = FootballDataOrgProvider(api_key="test", enabled=True)

    quota = provider._quota_from_headers(
        httpx.Headers(
            {
                "X-Requests-Available-Minute": "4",
                "X-RequestCounter-Reset": "59",
            }
        )
    )

    assert quota.remaining == 4
    assert quota.reset_at == fixed_now + timedelta(seconds=59)
    assert quota.reset_at.year == 2026


def test_transport_failure_result_preserves_sanitized_http_outcome() -> None:
    provider = BaseProvider(enabled=True)
    result = provider._transport_failure_result(
        "fixtures",
        ProviderTransportError(
            ProviderTransportKind.RATE_LIMITED,
            status_code=429,
            retry_after_seconds=7.0,
        ),
    )

    assert result.status is ProviderStatus.RATE_LIMITED
    assert result.http_status_code == 429
    assert result.http_status_category == "CLIENT_ERROR"
    assert result.error_code == "TRANSPORT_RATE_LIMITED"
