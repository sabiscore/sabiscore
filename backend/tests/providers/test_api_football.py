"""Tests for api_football.py (injuries, lineups, teams, team_statistics; x-apisports-key header auth).

Run:
    cd backend
    python -m pytest tests/providers/test_api_football.py -q --no-cov
"""

from __future__ import annotations

import httpx
import pytest

from src.providers.api_football import APIFootballProvider
from src.providers.base import ProviderStatus

VALID_INJURY = {
    # Real shape, confirmed against a live api_football payload while
    # scoping Portfolio B Phase 3 (docs/DEBT.md item 65) — `type`/`reason`
    # live under `player`, not at the record's top level; `fixture.date` is
    # present and needed for point-in-time reconstruction.
    "player": {
        "id": 1,
        "name": "Bukayo Saka",
        "type": "Muscle Injury",
        "reason": "Hamstring",
    },
    "team": {"id": 57, "name": "Arsenal FC"},
    "fixture": {"id": 12345, "date": "2024-08-16T19:00:00+00:00"},
}

VALID_LINEUP_TEAM = {
    "team": {"id": 57, "name": "Arsenal FC"},
    "formation": "4-3-3",
    "startXI": [{"player": {"id": 1, "name": "Bukayo Saka"}}],
    "substitutes": [{"player": {"id": 2, "name": "Reiss Nelson"}}],
}


@pytest.mark.asyncio
async def test_injuries_happy_path(mock_client_factory):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, json={"response": [VALID_INJURY], "errors": {}, "results": 1}
        )

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.injuries(competition="EPL")

    assert result.status == ProviderStatus.VERIFIED
    assert result.records[0]["player_name"] == "Bukayo Saka"
    assert result.records[0]["coherent"] is True
    assert calls[0].headers["x-apisports-key"] == "test-key"
    # Regression guard for the nested player.type/player.reason + fixture.date
    # fix: a record with the real payload shape must not silently normalize
    # injury_type/fixture_date to None.
    assert result.records[0]["injury_type"] == "Muscle Injury"
    assert result.records[0]["reason"] == "Hamstring"
    assert result.records[0]["fixture_date"] == "2024-08-16T19:00:00+00:00"


@pytest.mark.asyncio
async def test_injuries_scoped_to_fixture_uses_fixture_param_only(mock_client_factory):
    """docs/DEBT.md item 65: the API also accepts a `fixture` param for a
    match-scoped query; this repository's default call never used it. When
    provided, the request must use ONLY `fixture` -- not the league/season
    pair, which would be a different (and, per the endpoint's own semantics,
    unnecessary) query.
    """
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, json={"response": [VALID_INJURY], "errors": {}, "results": 1}
        )

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.injuries(competition="EPL", fixture_id=12345)

    assert result.status == ProviderStatus.VERIFIED
    params = calls[0].url.params
    assert params.get("fixture") == "12345"
    assert "league" not in params
    assert "season" not in params


@pytest.mark.asyncio
async def test_injuries_without_fixture_id_is_unchanged_from_before(
    mock_client_factory,
):
    """Regression guard: adding the optional `fixture_id` parameter must not
    alter the request for every existing caller that omits it
    (orchestrator.py's _collect_prematch_enriched calls injuries(competition=c)
    with no fixture_id) -- same league/season query, no `fixture` key at all.
    """
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, json={"response": [VALID_INJURY], "errors": {}, "results": 1}
        )

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.injuries(competition="EPL")

    assert result.status == ProviderStatus.VERIFIED
    params = calls[0].url.params
    assert "fixture" not in params
    assert "league" in params
    assert "season" in params


@pytest.mark.asyncio
async def test_injuries_explicit_season_overrides_current_season(mock_client_factory):
    """docs/DEBT.md item 65 follow-up: Portfolio B's Gate R1 study needs a
    plan-permitted historical season (this repo's free tier rejects the
    current season outright), so `season` must reach the query string
    verbatim instead of always resolving to `_current_season()`.
    """
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, json={"response": [VALID_INJURY], "errors": {}, "results": 1}
        )

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.injuries(competition="EPL", season=2024)

    assert result.status == ProviderStatus.VERIFIED
    assert calls[0].url.params["season"] == "2024"


@pytest.mark.asyncio
async def test_injuries_logical_error_in_200_response(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"response": [], "errors": {"league": "Invalid league"}, "results": 0},
        )

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.injuries(competition="EPL")

    assert result.status == ProviderStatus.UNAVAILABLE
    assert result.error_code == "api_logical_error"


@pytest.mark.asyncio
async def test_injuries_malformed_record_is_rejected_not_raised(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"response": [{"team": {"name": "Arsenal"}}], "errors": {}}
        )

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.injuries(competition="EPL")

    assert result.records[0]["coherent"] is False
    assert result.records[0]["rejection_reason"] == "missing_field_player_or_team"


@pytest.mark.asyncio
async def test_injuries_rate_limited(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={})

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    provider.max_retries = 0
    result = await provider.injuries(competition="EPL")

    assert result.status == ProviderStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_injuries_disabled_makes_no_network_call(mock_client_factory):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"response": []})

    provider = APIFootballProvider(
        api_key="test-key", enabled=False, http_client=mock_client_factory(handler)
    )
    result = await provider.injuries(competition="EPL")

    assert result.status == ProviderStatus.UNAVAILABLE
    assert calls == []


@pytest.mark.asyncio
async def test_lineups_happy_path_splits_starting_and_substitute(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": [VALID_LINEUP_TEAM], "errors": {}})

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.lineups(fixture_id=12345, competition="EPL")

    assert result.status == ProviderStatus.VERIFIED
    assert len(result.records) == 2
    roles = {r["role"] for r in result.records}
    assert roles == {"starting", "substitute"}


@pytest.mark.asyncio
async def test_lineups_requires_fixture_id(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": []})

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.lineups(fixture_id=None)

    assert result.status == ProviderStatus.UNAVAILABLE
    assert result.error_code == "fixture_id_required"


@pytest.mark.asyncio
async def test_team_statistics_requires_team_id_makes_no_network_call(
    mock_client_factory,
):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            "team_statistics must not call out without a resolved team_id"
        )

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.team_statistics(team_id=None, competition="EPL")

    assert result.status == ProviderStatus.PARTIAL
    assert result.error_code == "team_id_required"


@pytest.mark.asyncio
async def test_team_statistics_happy_path(mock_client_factory):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "response": {
                    "team": {"id": 57, "name": "Arsenal FC"},
                    "fixtures": {
                        "played": {"total": 30},
                        "wins": {"total": 20},
                        "draws": {"total": 6},
                        "loses": {"total": 4},
                    },
                    "goals": {
                        "for": {"total": {"total": 65}},
                        "against": {"total": {"total": 25}},
                    },
                    "form": "WWDWL",
                    "clean_sheet": {"total": 14},
                },
                "errors": {},
            },
        )

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.team_statistics(team_id=57, competition="EPL")

    assert result.status == ProviderStatus.VERIFIED
    record = result.records[0]
    assert record["team_name"] == "Arsenal FC"
    assert record["played"] == 30
    assert record["wins"] == 20
    assert record["losses"] == 4
    assert record["goals_for"] == 65
    assert record["goals_against"] == 25
    assert record["form"] == "WWDWL"
    assert record["clean_sheets"] == 14
    assert calls[0].url.params["team"] == "57"


@pytest.mark.asyncio
async def test_team_statistics_logical_error_in_200_response(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"response": {}, "errors": {"team": "Invalid team"}}
        )

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.team_statistics(team_id=57, competition="EPL")

    assert result.status == ProviderStatus.UNAVAILABLE
    assert result.error_code == "api_logical_error"


@pytest.mark.asyncio
async def test_team_statistics_malformed_record_is_rejected_not_raised(
    mock_client_factory,
):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": {"fixtures": {}}, "errors": {}})

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.team_statistics(team_id=57, competition="EPL")

    assert result.status == ProviderStatus.PARTIAL
    assert result.records[0]["coherent"] is False
    assert result.records[0]["rejection_reason"] == "missing_field_team"


@pytest.mark.asyncio
async def test_teams_happy_path(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": [
                    {"team": {"id": 57, "name": "Arsenal FC", "country": "England"}},
                    {"team": {"id": 49, "name": "Chelsea FC", "country": "England"}},
                ],
                "errors": {},
            },
        )

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    result = await provider.teams(competition="EPL")

    assert result.status == ProviderStatus.VERIFIED
    assert len(result.records) == 2
    assert {r["name"] for r in result.records} == {"Arsenal FC", "Chelsea FC"}


@pytest.mark.asyncio
async def test_teams_disabled_makes_no_network_call(mock_client_factory):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"response": []})

    provider = APIFootballProvider(
        api_key="test-key", enabled=False, http_client=mock_client_factory(handler)
    )
    result = await provider.teams(competition="EPL")

    assert result.status == ProviderStatus.UNAVAILABLE
    assert calls == []


@pytest.mark.asyncio
async def test_probe_verified_on_success(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"response": {"requests": {"current": 1, "limit_day": 100}}}
        )

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    assert await provider.probe() == ProviderStatus.VERIFIED


@pytest.mark.asyncio
async def test_probe_unavailable_on_failure(mock_client_factory):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    provider = APIFootballProvider(
        api_key="test-key", enabled=True, http_client=mock_client_factory(handler)
    )
    provider.max_retries = 0
    assert await provider.probe() == ProviderStatus.UNAVAILABLE
