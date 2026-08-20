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


async def test_football_data_fixture_result_retains_request_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["status"] == "SCHEDULED"
        return httpx.Response(200, json={"matches": []}, request=request)

    sink = SimpleNamespace(
        record_result=AsyncMock(return_value=True),
        record_exception=AsyncMock(return_value=True),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = FootballDataOrgProvider(
        api_key="test",
        enabled=True,
        http_client=client,
        observation_sink=sink,
    )
    registry = ProviderRegistry([provider])
    try:
        result = await registry.get("football_data_org").fixtures(
            competition="UCL",
            date_from="2026-08-20",
            date_to="2026-08-27",
            status="SCHEDULED",
            limit=50,
        )
    finally:
        await client.aclose()

    assert result.status is ProviderStatus.PARTIAL
    assert result.http_status_code == 200
    assert result.request_context == {
        "competition": "UCL",
        "query_intent": "UPCOMING",
        "match_status": "SCHEDULED",
        "date_from": "2026-08-20",
        "date_to": "2026-08-27",
    }
    observed = sink.record_result.await_args.args[0]
    assert observed.request_context == result.request_context


async def test_http_200_empty_fixture_window_is_live_with_empty_coverage(factory) -> None:
    observed_at = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    result = ProviderResult(
        provider="football_data_org",
        operation="fixtures",
        status=ProviderStatus.PARTIAL,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        acquired_at=observed_at,
        http_status_code=200,
        http_status_category="SUCCESS",
        records=[],
        request_context={
            "competition": "UCL",
            "query_intent": "UPCOMING",
            "match_status": "SCHEDULED",
        },
    )
    recorder = ProviderEvidenceRecorder()

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        await recorder.record_result(result, duration_ms=9.0, circuit_open=False)

    async with factory() as session:
        evidence = await latest_provider_evidence(
            session,
            ["football_data_org"],
            now=observed_at + timedelta(minutes=1),
        )

    row = evidence["football_data_org"]
    assert row["state"] == "LIVE_VERIFIED"
    assert row["status"] == "PARTIAL"
    assert row["transport"]["outcome"] == "SUCCESS"
    assert row["coverage"]["state"] == "EMPTY"
    assert row["coverage_summary"] == {
        "state": "EMPTY",
        "contexts": 1,
        "usable_contexts": 0,
        "empty_contexts": 1,
        "unusable_contexts": 0,
        "unknown_contexts": 0,
    }
    assert row["contexts"][0]["request_context"]["competition"] == "UCL"


async def test_context_aggregation_prevents_last_empty_query_from_dominating(factory) -> None:
    recorder = ProviderEvidenceRecorder()
    base = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)

    observations = [
        ProviderResult(
            provider="football_data_org",
            operation="fixtures",
            status=ProviderStatus.VERIFIED,
            trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
            acquired_at=base,
            http_status_code=200,
            http_status_category="SUCCESS",
            records=[{"provider_event_id": "epl-1", "coherent": True}],
            request_context={
                "competition": "EPL",
                "query_intent": "UPCOMING",
                "match_status": "SCHEDULED",
            },
        ),
        ProviderResult(
            provider="football_data_org",
            operation="fixtures",
            status=ProviderStatus.PARTIAL,
            trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
            acquired_at=base + timedelta(seconds=1),
            http_status_code=200,
            http_status_category="SUCCESS",
            records=[],
            request_context={
                "competition": "UCL",
                "query_intent": "UPCOMING",
                "match_status": "SCHEDULED",
            },
        ),
        ProviderResult(
            provider="football_data_org",
            operation="fixtures",
            status=ProviderStatus.PARTIAL,
            trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
            acquired_at=base + timedelta(seconds=2),
            http_status_code=200,
            http_status_category="SUCCESS",
            records=[],
            request_context={
                "competition": "EREDIVISIE",
                "query_intent": "RESULTS",
                "match_status": "FINISHED",
            },
        ),
    ]

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        for result in observations:
            await recorder.record_result(result, duration_ms=7.0, circuit_open=False)

    async with factory() as session:
        evidence = await latest_provider_evidence(
            session,
            ["football_data_org"],
            now=base + timedelta(minutes=2),
        )

    row = evidence["football_data_org"]
    assert row["status"] == "PARTIAL"  # raw latest observation remains auditable.
    assert row["coverage"]["state"] == "EMPTY"
    assert row["state"] == "LIVE_VERIFIED"
    assert row["context_count"] == 3
    assert row["coverage_summary"] == {
        "state": "PARTIAL",
        "contexts": 3,
        "usable_contexts": 1,
        "empty_contexts": 2,
        "unusable_contexts": 0,
        "unknown_contexts": 0,
    }
    context_keys = {
        (
            context["request_context"].get("competition"),
            context["request_context"].get("query_intent"),
        )
        for context in row["contexts"]
    }
    assert context_keys == {
        ("EPL", "UPCOMING"),
        ("UCL", "UPCOMING"),
        ("EREDIVISIE", "RESULTS"),
    }


async def test_rate_limited_context_remains_provider_wide_operational_signal(factory) -> None:
    recorder = ProviderEvidenceRecorder()
    base = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
    live = ProviderResult(
        provider="football_data_org",
        operation="fixtures",
        status=ProviderStatus.VERIFIED,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        acquired_at=base,
        http_status_code=200,
        http_status_category="SUCCESS",
        records=[{"provider_event_id": "fx-1", "coherent": True}],
        request_context={
            "competition": "EPL",
            "query_intent": "UPCOMING",
            "match_status": "SCHEDULED",
        },
    )
    limited = ProviderResult(
        provider="football_data_org",
        operation="fixtures",
        status=ProviderStatus.RATE_LIMITED,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        acquired_at=base + timedelta(seconds=1),
        http_status_code=429,
        http_status_category="CLIENT_ERROR",
        error_code="TRANSPORT_RATE_LIMITED",
        records=[],
        request_context={
            "competition": "LA_LIGA",
            "query_intent": "UPCOMING",
            "match_status": "SCHEDULED",
        },
    )

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        await recorder.record_result(live, duration_ms=7.0, circuit_open=False)
        await recorder.record_result(limited, duration_ms=7.0, circuit_open=False)

    async with factory() as session:
        evidence = await latest_provider_evidence(
            session,
            ["football_data_org"],
            now=base + timedelta(minutes=1),
        )

    assert evidence["football_data_org"]["state"] == "RATE_LIMITED"


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
