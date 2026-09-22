"""Tests for football_data_org.py (fixtures + standings, X-Auth-Token header auth).

Run:
    cd backend
    python -m pytest tests/providers/test_football_data_org.py -q --no-cov
"""

from __future__ import annotations

import httpx
import pytest

from src.providers.base import ProviderStatus
from src.providers.football_data_org import FootballDataOrgProvider


def _matches_response(matches: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"matches": matches})


def _standings_response(table: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"standings": [{"type": "TOTAL", "table": table}]})


VALID_MATCH = {
    "id": 12345,
    "utcDate": "2026-08-15T15:00:00Z",
    "status": "SCHEDULED",
    "homeTeam": {"id": 57, "name": "Arsenal FC"},
    "awayTeam": {"id": 61, "name": "Chelsea FC"},
    "season": {"id": 2025},
}

VALID_STANDINGS_ROW = {
    "position": 1,
    "team": {"id": 57, "name": "Arsenal FC"},
    "playedGames": 10,
    "won": 8,
    "draw": 1,
    "lost": 1,
    "points": 25,
    "goalsFor": 20,
    "goalsAgainst": 5,
}


@pytest.mark.asyncio
async def test_fixtures_happy_path(mock_client_factory):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _matches_response([VALID_MATCH])

    provider = FootballDataOrgProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.fixtures(competition="EPL")

    assert result.status == ProviderStatus.VERIFIED
    assert len(result.records) == 1
    record = result.records[0]
    assert record["home_team"] == "Arsenal FC"
    assert record["away_team"] == "Chelsea FC"
    assert record["coherent"] is True
    assert calls[0].headers["x-auth-token"] == "test-key"


@pytest.mark.asyncio
async def test_fixtures_malformed_match_is_rejected_not_raised(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return _matches_response([{"id": 1}])  # missing homeTeam/awayTeam

    provider = FootballDataOrgProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.fixtures(competition="EPL")

    assert len(result.records) == 1
    assert result.records[0]["coherent"] is False
    assert result.records[0]["rejection_reason"] == "missing_field_team_or_id"


@pytest.mark.asyncio
async def test_fixtures_rate_limited(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={})

    provider = FootballDataOrgProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    provider.max_retries = 0
    result = await provider.fixtures(competition="EPL")

    assert result.status == ProviderStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_fixtures_disabled_makes_no_network_call(mock_client_factory):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _matches_response([])

    provider = FootballDataOrgProvider(
        api_key="test-key", enabled=False, http_client=mock_client_factory(handler)
    )
    result = await provider.fixtures(competition="EPL")

    assert result.status == ProviderStatus.UNAVAILABLE
    assert result.error_code == "provider_disabled_or_unconfigured"
    assert calls == []


@pytest.mark.asyncio
async def test_fixtures_unconfigured_makes_no_network_call(mock_client_factory):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _matches_response([])

    provider = FootballDataOrgProvider(
        api_key=None, enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.fixtures(competition="EPL")

    assert result.status == ProviderStatus.UNAVAILABLE
    assert calls == []


@pytest.mark.asyncio
async def test_fixtures_unsupported_competition(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return _matches_response([])

    provider = FootballDataOrgProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.fixtures(competition="FIFA_WC")  # not in COMPETITIONS

    assert result.status == ProviderStatus.UNAVAILABLE
    assert result.error_code == "unsupported_competition"


@pytest.mark.asyncio
async def test_standings_happy_path_filters_total_only(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "standings": [
                    {"type": "HOME", "table": [VALID_STANDINGS_ROW]},
                    {"type": "TOTAL", "table": [VALID_STANDINGS_ROW]},
                ]
            },
        )

    provider = FootballDataOrgProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.standings(competition="EPL")

    assert result.status == ProviderStatus.VERIFIED
    assert len(result.records) == 1  # HOME table excluded
    assert result.records[0]["team"] == "Arsenal FC"
    assert result.records[0]["points"] == 25


@pytest.mark.asyncio
async def test_standings_malformed_row_is_rejected_not_raised(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return _standings_response([{"position": 1}])  # missing team/points

    provider = FootballDataOrgProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.standings(competition="EPL")

    assert result.records[0]["coherent"] is False
    assert (
        result.records[0]["rejection_reason"] == "missing_field_position_team_or_points"
    )


@pytest.mark.asyncio
async def test_probe_verified_on_success(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 2021, "name": "Premier League"})

    provider = FootballDataOrgProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    assert await provider.probe() == ProviderStatus.VERIFIED


@pytest.mark.asyncio
async def test_probe_unavailable_on_failure(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    provider = FootballDataOrgProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    provider.max_retries = 0
    assert await provider.probe() == ProviderStatus.UNAVAILABLE
