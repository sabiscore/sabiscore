"""Contract tests for OddsService -> TheOddsAPIProvider.

`OddsService.fetch_live_odds` called `provider.odds(sport=...)` long after the
provider's keyword-only parameter had been renamed to `competition`. Because
both are keyword-only, the mismatch raised TypeError on *every* call. It was
swallowed by the enrichment loop's broad `except Exception`, discarding a
valid prediction and reporting only `data_gaps: ["prediction_failed"]`.

These tests pin the call contract so a future rename cannot fail silently.
They stub the provider — no live quota is consumed (PROVIDER_LIVE_TESTS
stays false in CI, and these must hold regardless of local .env state).
"""

from __future__ import annotations

import inspect
import os
import sys
from typing import Any, Dict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.providers.base import ProviderStatus
from src.providers.the_odds_api import TheOddsAPIProvider
from src.services.odds_service import OddsService


class _StubResult:
    def __init__(self, status: ProviderStatus, records: list | None = None):
        self.status = status
        self.records = records or []
        self.provider = "the_odds_api"
        self.error_code = None


class _StubProvider:
    """Records the kwargs the service actually sends."""

    def __init__(
        self,
        status: ProviderStatus = ProviderStatus.UNAVAILABLE,
        records: list | None = None,
    ):
        self.status = status
        self.records = records or []
        self.calls: list[Dict[str, Any]] = []

    async def odds(self, **kwargs):
        self.calls.append(kwargs)
        return _StubResult(self.status, self.records)


class _StubCache:
    def __init__(self):
        self.store: Dict[str, Any] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value


def _service(status: ProviderStatus = ProviderStatus.UNAVAILABLE):
    service = OddsService(cache_backend=_StubCache())
    service.provider = _StubProvider(status)
    return service


def test_provider_odds_accepts_the_keyword_odds_service_sends():
    params = inspect.signature(TheOddsAPIProvider.odds).parameters
    assert "competition" in params, (
        "OddsService.fetch_live_odds calls provider.odds(competition=...); "
        "renaming this parameter breaks that call at runtime only."
    )
    assert "sport" not in params


@pytest.mark.asyncio
async def test_fetch_live_odds_sends_competition_not_sport():
    service = _service()

    await service.fetch_live_odds(competition="EPL")

    assert service.provider.calls, "provider.odds was never called"
    sent = service.provider.calls[0]
    assert sent.get("competition") == "EPL"
    assert "sport" not in sent


@pytest.mark.asyncio
async def test_fetch_live_odds_degrades_instead_of_raising():
    """An unavailable provider must yield an empty market, not an exception —
    no market means no edge, never a crash that discards the surrounding
    prediction."""
    service = _service(ProviderStatus.UNAVAILABLE)

    assert await service.fetch_live_odds(competition="EPL") == []


@pytest.mark.asyncio
async def test_unmappable_league_yields_no_market_and_is_never_coerced_to_epl():
    """The deleted `_league_to_sport_key` defaulted every unknown league to
    "soccer_epl", which would attach English odds to a foreign fixture. The
    league must now reach the provider verbatim — the provider owns the
    competition mapping and rejects an unknown code before any HTTP call —
    and the service must surface no market rather than the wrong one."""
    service = _service()

    odds = await service.get_match_odds("Some Team", "Other Team", "NOT_A_LEAGUE")

    assert odds.get("source") == "unavailable"
    assert not {"home_win", "draw", "away_win"}.issubset(odds)
    assert service.provider.calls[0]["competition"] == "NOT_A_LEAGUE", (
        "the league must not be silently rewritten to a supported one"
    )


@pytest.mark.asyncio
async def test_match_lookup_consumes_one_normalized_bookmaker_snapshot():
    record = {
        "provider": "the_odds_api",
        "provider_event_id": "evt-1",
        "home_team": "Arsenal",
        "away_team": "Brighton",
        "bookmaker": "pinnacle",
        "home_odds": 1.9,
        "draw_odds": 3.5,
        "away_odds": 4.4,
        "captured_at": "2026-08-09T08:00:00Z",
        "bookmaker_last_update": "2026-08-09T07:59:00Z",
        "coherent": True,
        "executable": True,
    }
    service = OddsService(cache_backend=_StubCache())
    service.provider = _StubProvider(ProviderStatus.VERIFIED, [record])

    odds = await service.get_match_odds("Arsenal FC", "Brighton FC", "EPL")

    assert odds["home_win"] == 1.9
    assert odds["draw"] == 3.5
    assert odds["away_win"] == 4.4
    assert odds["bookmaker"] == "pinnacle"
    assert odds["provider_event_id"] == "evt-1"


@pytest.mark.asyncio
async def test_match_lookup_rejects_cross_fixture_or_incoherent_records():
    records = [
        {
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "home_odds": 1.9,
            "draw_odds": 3.5,
            "away_odds": 4.4,
            "coherent": True,
            "executable": True,
        },
        {
            "home_team": "Arsenal",
            "away_team": "Brighton",
            "home_odds": 1.9,
            "draw_odds": 3.5,
            "away_odds": 4.4,
            "coherent": False,
            "executable": False,
        },
    ]
    service = OddsService(cache_backend=_StubCache())
    service.provider = _StubProvider(ProviderStatus.VERIFIED, records)

    odds = await service.get_match_odds("Arsenal", "Brighton", "EPL")

    assert odds["source"] == "unavailable"
    assert "home_win" not in odds
