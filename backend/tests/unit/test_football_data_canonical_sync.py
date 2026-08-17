"""SAB-14 regressions for canonical football-data.org background acquisition."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.config import settings
from src.data.loaders.football_data_api import FootballDataAPIClient
from src.db.models import Base, ProviderRequestSummary
from src.providers.football_data_org import FootballDataOrgProvider
from src.providers.registry import ProviderRegistry, build_provider_registry
from src.services.provider_evidence_service import ProviderEvidenceRecorder


@pytest.fixture
async def evidence_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _scheduled_match(event_id: int) -> dict:
    return {
        "id": event_id,
        "utcDate": "2026-08-20T15:00:00Z",
        "status": "SCHEDULED",
        "stage": "REGULAR_SEASON",
        "homeTeam": {"id": event_id * 10, "name": f"Home {event_id}"},
        "awayTeam": {"id": event_id * 10 + 1, "name": f"Away {event_id}"},
        "season": {"id": 2026},
        "score": {"fullTime": {"home": None, "away": None}},
    }


def _finished_match(event_id: int) -> dict:
    raw = _scheduled_match(event_id)
    raw["status"] = "FINISHED"
    raw["score"] = {"fullTime": {"home": 2, "away": 1}}
    return raw


async def test_runtime_adapter_reuses_exact_lifespan_provider_instance() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"matches": []}, request=request)
    )
    http_client = httpx.AsyncClient(transport=transport)
    sink = SimpleNamespace(
        record_result=AsyncMock(return_value=True),
        record_exception=AsyncMock(return_value=True),
    )
    try:
        with patch.object(settings, "football_data_api_key", "test-key"), patch.object(
            settings, "enable_football_data_provider", True
        ):
            registry = build_provider_registry(
                http_client=http_client,
                observation_sink=sink,
            )
        provider = registry.get("football_data_org")
        adapter = FootballDataAPIClient()

        assert adapter.provider is provider
        assert provider._http_client is http_client
    finally:
        await http_client.aclose()


async def test_upcoming_sync_keeps_seven_request_budget_and_persists_each_observation(
    evidence_factory,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        event_id = len(requests)
        return httpx.Response(
            200,
            headers={"X-Requests-Available-Minute": str(10 - event_id)},
            json={"matches": [_scheduled_match(event_id)]},
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = FootballDataOrgProvider(
        api_key="test-key",
        enabled=True,
        http_client=http_client,
        observation_sink=ProviderEvidenceRecorder(),
    )
    provider = ProviderRegistry([provider]).get("football_data_org")
    try:
        with patch("src.db.session.AsyncSessionLocal", new=evidence_factory):
            rows = await FootballDataAPIClient(provider=provider).get_upcoming_matches(
                days_ahead=14,
                limit=50,
            )
    finally:
        await http_client.aclose()

    assert len(requests) == 7
    assert len(rows) == 7
    assert all(request.url.params.get("status") == "SCHEDULED" for request in requests)
    assert all(request.url.params.get("limit") == "50" for request in requests)
    assert all(request.url.params.get("dateFrom") for request in requests)
    assert all(request.url.params.get("dateTo") for request in requests)
    assert all(request.headers.get("X-Auth-Token") == "test-key" for request in requests)

    async with evidence_factory() as session:
        evidence = (
            await session.execute(
                select(ProviderRequestSummary).where(
                    ProviderRequestSummary.provider == "football_data_org"
                )
            )
        ).scalars().all()

    assert len(evidence) == 7
    assert {row.operation for row in evidence} == {"fixtures"}
    assert {row.status for row in evidence} == {"VERIFIED"}
    assert all(row.response_hash for row in evidence)
    assert all("test-key" not in " ".join(row.warnings or []) for row in evidence)


async def test_recent_results_preserve_finished_filter_scores_and_telemetry(
    evidence_factory,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"matches": [_finished_match(9001)]},
            request=request,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = FootballDataOrgProvider(
        api_key="test-key",
        enabled=True,
        http_client=http_client,
        observation_sink=ProviderEvidenceRecorder(),
    )
    provider = ProviderRegistry([provider]).get("football_data_org")
    try:
        with patch("src.db.session.AsyncSessionLocal", new=evidence_factory):
            rows = await FootballDataAPIClient(provider=provider).get_recent_results(
                days_back=3,
                limit=100,
                league="EPL",
            )
    finally:
        await http_client.aclose()

    assert len(requests) == 1
    assert requests[0].url.params.get("status") == "FINISHED"
    assert rows == [
        {
            "id": "fd-9001",
            "match_date": "2026-08-20T15:00:00Z",
            "home_score": 2,
            "away_score": 1,
            "status": "finished",
        }
    ]

    async with evidence_factory() as session:
        evidence = (await session.execute(select(ProviderRequestSummary))).scalars().all()
    assert len(evidence) == 1
    assert evidence[0].provider == "football_data_org"
    assert evidence[0].operation == "fixtures"
    assert evidence[0].status == "VERIFIED"


async def test_rate_limit_stops_polling_but_keeps_prior_competition_progress() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"matches": [_scheduled_match(1)]},
                request=request,
            )
        return httpx.Response(429, json={"message": "quota"}, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sink = SimpleNamespace(
        record_result=AsyncMock(return_value=True),
        record_exception=AsyncMock(return_value=True),
    )
    provider = FootballDataOrgProvider(
        api_key="test-key",
        enabled=True,
        http_client=http_client,
        observation_sink=sink,
    )
    provider = ProviderRegistry([provider]).get("football_data_org")
    try:
        rows = await FootballDataAPIClient(provider=provider).get_upcoming_matches(
            days_ahead=14,
            limit=50,
        )
    finally:
        await http_client.aclose()

    assert len(requests) == 2
    assert [row["id"] for row in rows] == ["fd-1"]
    assert sink.record_result.await_count == 2
    observed_statuses = [
        call.args[0].status.value for call in sink.record_result.await_args_list
    ]
    assert observed_statuses == ["VERIFIED", "RATE_LIMITED"]
    assert provider.breaker.failures == 1
