"""ESPN provider tests.

Covers the certificate's ESPN test requirements:
  * ESPN kickoff is not treated as provider update time
  * provider team IDs are preserved (not displayed as names)
  * schema drift fails closed (SCHEMA_INVALID, not a fabricated fixture)
  * circuit-open short-circuits without a network call
  * all 7 competitions map; unsupported competitions fail closed
  * configured is not equivalent to healthy (probe-gated status)
  * egress allowlist blocks non-ESPN hosts

Run:
    cd backend
    python -m pytest tests/providers/test_espn_provider.py -q --no-cov
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
import pytest

from src.providers.espn import (
    Competition,
    EspnProvider,
    ProviderStatus,
    TrustTier,
    espn_slug,
    supported_competitions,
)
from src.providers.espn.client import CircuitOpenError
from src.providers.espn.mappings import UnsupportedCompetitionError

FIXED_NOW = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return FIXED_NOW


def _valid_scoreboard() -> dict[str, Any]:
    return {
        "events": [
            {
                "id": "401234567",
                "date": "2026-06-26T18:00Z",
                "status": {"type": {"name": "STATUS_SCHEDULED", "completed": False}},
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "home", "team": {"id": "359", "displayName": "Arsenal"}},
                            {"homeAway": "away", "team": {"id": "363", "displayName": "Chelsea"}},
                        ]
                    }
                ],
            }
        ]
    }


class _FakeBreaker:
    """In-memory breaker honoring the documented contract for tests."""

    def __init__(self, *, open_: bool = False) -> None:
        self._open = open_
        self.schema_failures = 0

    def is_open(self) -> bool:
        return self._open

    async def call(self, fn: Callable[[], Awaitable[httpx.Response]]) -> httpx.Response:
        if self._open:
            raise CircuitOpenError("circuit open")
        return await fn()

    def record_schema_failure(self) -> None:
        self.schema_failures += 1


def _provider(handler: Callable[[httpx.Request], httpx.Response], *, breaker=None,
              enabled: bool = True) -> EspnProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return EspnProvider(
        http=client,
        breaker=breaker or _FakeBreaker(),
        enabled=enabled,
        clock=_clock,
    )


# --------------------------------------------------------------------------- #
# Mapping tests
# --------------------------------------------------------------------------- #


def test_all_seven_competitions_map():
    expected = {
        Competition.EPL: "eng.1",
        Competition.LA_LIGA: "esp.1",
        Competition.SERIE_A: "ita.1",
        Competition.BUNDESLIGA: "ger.1",
        Competition.LIGUE_1: "fra.1",
        Competition.EREDIVISIE: "ned.1",
        Competition.UCL: "uefa.champions",
    }
    assert len(supported_competitions()) == 7
    for comp, slug in expected.items():
        assert espn_slug(comp) == slug


def test_unsupported_competition_fails_closed():
    with pytest.raises(UnsupportedCompetitionError):
        espn_slug("MLS")


# --------------------------------------------------------------------------- #
# Happy path + normalization invariants
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_discover_returns_healthy_with_normalized_fixture():
    provider = _provider(lambda req: httpx.Response(200, json=_valid_scoreboard()))
    env = await provider.discover_fixtures(Competition.EPL, correlation_id="abc-123")

    assert env.status is ProviderStatus.HEALTHY
    assert env.trust_tier is TrustTier.UNOFFICIAL_PUBLIC
    assert env.quota is None  # keyless
    assert env.snapshot_hash is not None
    assert env.correlation_id == "abc-123"
    assert len(env.fixtures) == 1

    fx = env.fixtures[0]
    assert fx.provider == "espn"
    assert fx.provider_event_id == "401234567"


@pytest.mark.asyncio
async def test_kickoff_is_not_provider_timestamp():
    """Certificate: ESPN kickoff must not be treated as provider update time."""
    provider = _provider(lambda req: httpx.Response(200, json=_valid_scoreboard()))
    env = await provider.discover_fixtures(Competition.EPL)
    fx = env.fixtures[0]

    assert fx.kickoff_utc == datetime(2026, 6, 26, 18, 0, tzinfo=timezone.utc)
    assert fx.provider_timestamp is None          # not silently set to kickoff
    assert fx.acquired_at == FIXED_NOW            # acquisition time used instead


@pytest.mark.asyncio
async def test_provider_team_ids_preserved():
    """Certificate: preserve provider team IDs; never display raw IDs as names."""
    provider = _provider(lambda req: httpx.Response(200, json=_valid_scoreboard()))
    env = await provider.discover_fixtures(Competition.EPL)
    fx = env.fixtures[0]

    assert fx.provider_home_team_id == "359"
    assert fx.provider_away_team_id == "363"
    assert fx.provider_home_team_name == "Arsenal"
    assert fx.provider_away_team_name == "Chelsea"


# --------------------------------------------------------------------------- #
# Fail-closed + resilience
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_schema_drift_fails_closed():
    """Missing required competitors → SCHEMA_INVALID, no fabricated fixture."""
    drifted = {"events": [{"id": "x", "date": "2026-06-26T18:00Z",
                           "status": {"type": {"name": "STATUS_SCHEDULED"}},
                           "competitions": [{"competitors": []}]}]}
    breaker = _FakeBreaker()
    provider = _provider(lambda req: httpx.Response(200, json=drifted), breaker=breaker)
    env = await provider.discover_fixtures(Competition.EPL)

    assert env.status is ProviderStatus.SCHEMA_INVALID
    assert env.fixtures == ()
    assert breaker.schema_failures == 1
    assert env.warnings


@pytest.mark.asyncio
async def test_circuit_open_short_circuits_without_network():
    called = False

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_valid_scoreboard())

    provider = _provider(handler, breaker=_FakeBreaker(open_=True))
    env = await provider.discover_fixtures(Competition.EPL)

    assert env.status is ProviderStatus.CIRCUIT_OPEN
    assert called is False  # no network call attempted


@pytest.mark.asyncio
async def test_rate_limit_maps_to_rate_limited_status():
    provider = _provider(lambda req: httpx.Response(429, json={"message": "slow down"}))
    env = await provider.discover_fixtures(Competition.EPL)
    assert env.status is ProviderStatus.RATE_LIMITED


@pytest.mark.asyncio
async def test_disabled_provider_returns_disabled():
    """Certificate: configured is not equivalent to healthy."""
    provider = _provider(lambda req: httpx.Response(200, json=_valid_scoreboard()),
                         enabled=False)
    env = await provider.discover_fixtures(Competition.EPL)
    assert env.status is ProviderStatus.DISABLED
    assert env.fixtures == ()


@pytest.mark.asyncio
async def test_probe_is_health_gated():
    """probe() returns HEALTHY only after a successful, schema-valid response."""
    ok = _provider(lambda req: httpx.Response(200, json=_valid_scoreboard()))
    assert await ok.probe() is ProviderStatus.HEALTHY

    bad = _provider(lambda req: httpx.Response(503, json={}))
    assert await bad.probe() is ProviderStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_egress_allowlist_blocks_foreign_host(monkeypatch):
    """An attacker-controlled base must not be reachable; allowlist fails closed."""
    from src.providers.espn import client as espn_client

    monkeypatch.setattr(espn_client, "_BASE", "https://evil.example.com/soccer")
    provider = _provider(lambda req: httpx.Response(200, json=_valid_scoreboard()))
    env = await provider.discover_fixtures(Competition.EPL)

    # The allowlist raises inside _get_scoreboard; surfaced as UNAVAILABLE/SCHEMA.
    assert env.status in {ProviderStatus.UNAVAILABLE, ProviderStatus.SCHEMA_INVALID}
    assert env.fixtures == ()
