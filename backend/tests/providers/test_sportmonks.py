"""Tests for sportmonks.py (sidelined + lineups, Authorization-header auth).

Run:
    cd backend
    python -m pytest tests/providers/test_sportmonks.py -q --no-cov
"""

from __future__ import annotations

import httpx
import pytest

from src.providers.base import ProviderStatus
from src.providers.sportmonks import SportmonksProvider

VALID_SIDELINED = {
    "player_id": 1,
    "sideline": {"category": "injury", "start_date": "2026-06-01", "end_date": None},
}

VALID_LINEUP_RESPONSE = {
    "data": {
        "id": 999,
        "lineups": {
            "data": [
                {"player_id": 1, "team_id": 57, "jersey_number": 7, "type": "lineup"},
                {"player_id": 2, "team_id": 57, "jersey_number": 19, "type": "bench"},
            ]
        },
    }
}


@pytest.mark.asyncio
async def test_injuries_happy_path_uses_header_auth_never_url_token(
    mock_client_factory,
):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, json={"data": [VALID_SIDELINED], "rate_limit": {"remaining": 100}}
        )

    provider = SportmonksProvider(
        api_key="test-token", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.injuries(competition="EPL")

    assert result.status == ProviderStatus.VERIFIED
    assert result.records[0]["category"] == "injury"
    # Token travels in the Authorization header only — never in the URL, where
    # it would leak through httpx exception messages and access logs.
    assert calls[0].headers.get("authorization") == "test-token"
    assert "test-token" not in str(calls[0].url)
    assert "unfiltered_by_competition" in result.warnings


@pytest.mark.asyncio
async def test_injuries_malformed_record_is_rejected_not_raised(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"sideline": {}}]})

    provider = SportmonksProvider(
        api_key="test-token", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.injuries(competition="EPL")

    assert result.records[0]["coherent"] is False
    assert (
        result.records[0]["rejection_reason"] == "missing_field_player_id_or_sideline"
    )


@pytest.mark.asyncio
async def test_injuries_rate_limited(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={})

    provider = SportmonksProvider(
        api_key="test-token", enabled=True, http_client=mock_client_factory(handler)
    )
    provider.max_retries = 0
    result = await provider.injuries(competition="EPL")

    assert result.status == ProviderStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_injuries_disabled_makes_no_network_call(mock_client_factory):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"data": []})

    provider = SportmonksProvider(
        api_key="test-token", enabled=False, http_client=mock_client_factory(handler)
    )
    result = await provider.injuries(competition="EPL")

    assert result.status == ProviderStatus.UNAVAILABLE
    assert calls == []


@pytest.mark.asyncio
async def test_lineups_happy_path_maps_bench_to_role(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=VALID_LINEUP_RESPONSE)

    provider = SportmonksProvider(
        api_key="test-token", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.lineups(fixture_id=999)

    assert result.status == ProviderStatus.VERIFIED
    roles = {r["role"] for r in result.records}
    assert roles == {"lineup", "bench"}


@pytest.mark.asyncio
async def test_lineups_requires_fixture_id(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}})

    provider = SportmonksProvider(
        api_key="test-token", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.lineups(fixture_id=None)

    assert result.status == ProviderStatus.UNAVAILABLE
    assert result.error_code == "fixture_id_required"


@pytest.mark.asyncio
async def test_lineups_missing_data_returns_partial_not_raise(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": None})

    provider = SportmonksProvider(
        api_key="test-token", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.lineups(fixture_id=999)

    assert result.status == ProviderStatus.PARTIAL
    assert "no_lineup_data_in_response" in result.warnings


@pytest.mark.asyncio
async def test_probe_verified_on_success(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    provider = SportmonksProvider(
        api_key="test-token", enabled=True, http_client=mock_client_factory(handler)
    )
    assert await provider.probe() == ProviderStatus.VERIFIED


@pytest.mark.asyncio
async def test_probe_unavailable_on_failure(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    provider = SportmonksProvider(
        api_key="test-token", enabled=True, http_client=mock_client_factory(handler)
    )
    provider.max_retries = 0
    assert await provider.probe() == ProviderStatus.UNAVAILABLE
