"""Per-competition failure isolation in FootballDataAPIClient.

Regression guard for the 2026-08-08 production incident: a 429 on the first
of seven competitions raised and discarded all seven, so fixture_sync logged
"0 new upcoming fixtures seeded" while six leagues were never even attempted.

SAB-14 moved transport ownership into FootballDataOrgProvider. These tests now
exercise the adapter at that canonical provider-result boundary rather than
patching the removed legacy AsyncJSONClient transport.

Contracts verified:
  1. A mid-loop rate limit keeps the competitions already fetched.
  2. An ordinary provider failure skips only that competition; the rest still load.
  3. Total failure (nothing collected anywhere) still raises, so the caller's
     warning + metrics path fires rather than silently returning empty.
  4. get_recent_results() shares the same isolation (same helper, one fix).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.data.loaders.football_data_api import (
    FootballDataAPIClient,
    FootballDataAPIError,
)
from src.providers.base import ProviderResult, ProviderStatus, TrustTier
from src.providers.football_data_org import FootballDataOrgProvider


def _record(
    match_id: int,
    *,
    utc_date: str = "2026-08-20T15:00:00Z",
    home_score: int | None = None,
    away_score: int | None = None,
) -> dict:
    return {
        "provider": "football_data_org",
        "provider_event_id": str(match_id),
        "competition": "EPL",
        "home_team": f"Home {match_id}",
        "away_team": f"Away {match_id}",
        "home_team_id": match_id * 10,
        "away_team_id": match_id * 10 + 1,
        "kickoff_utc": utc_date,
        "status": "FINISHED" if home_score is not None else "SCHEDULED",
        "season_id": 2026,
        "match_round": "REGULAR_SEASON",
        "home_score": home_score,
        "away_score": away_score,
        "coherent": True,
        "rejection_reason": None,
    }


def _result(
    status: ProviderStatus,
    *records: dict,
    error_code: str | None = None,
) -> ProviderResult:
    return ProviderResult(
        provider="football_data_org",
        operation="fixtures",
        status=status,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        records=list(records),
        error_code=error_code,
    )


def _provider_with(*results: ProviderResult) -> AsyncMock:
    provider = AsyncMock(spec=FootballDataOrgProvider)
    provider.fixtures.side_effect = list(results)
    return provider


async def test_rate_limit_midloop_keeps_already_fetched_competitions() -> None:
    """PL and PD succeed, BL1 is rate-limited: the two successes survive."""
    provider = _provider_with(
        _result(ProviderStatus.VERIFIED, _record(1)),
        _result(ProviderStatus.VERIFIED, _record(2)),
        _result(
            ProviderStatus.RATE_LIMITED,
            error_code="TRANSPORT_RATE_LIMITED",
        ),
    )
    client = FootballDataAPIClient(provider=provider)

    matches = await client.get_upcoming_matches(days_ahead=14, limit=50)

    # Pre-fix this returned nothing at all — the raise discarded PL and PD.
    assert len(matches) == 2
    assert {match["id"] for match in matches} == {"fd-1", "fd-2"}
    assert provider.fixtures.await_count == 3


async def test_provider_error_skips_only_that_competition() -> None:
    """A canonical 403/auth failure on one league must not stop later leagues."""
    provider = _provider_with(
        _result(
            ProviderStatus.UNAVAILABLE,
            error_code="TRANSPORT_AUTHENTICATION",
        ),
        _result(ProviderStatus.VERIFIED, _record(3)),
        _result(ProviderStatus.VERIFIED, _record(4)),
        _result(ProviderStatus.PARTIAL),
        _result(ProviderStatus.PARTIAL),
        _result(ProviderStatus.PARTIAL),
        _result(ProviderStatus.PARTIAL),
    )
    client = FootballDataAPIClient(provider=provider)

    matches = await client.get_upcoming_matches(days_ahead=14, limit=50)

    assert {match["id"] for match in matches} == {"fd-3", "fd-4"}
    assert provider.fixtures.await_count == 7


async def test_total_failure_still_raises() -> None:
    """Nothing collected anywhere -> raise, so the caller logs + records metrics."""
    provider = _provider_with(
        _result(
            ProviderStatus.RATE_LIMITED,
            error_code="TRANSPORT_RATE_LIMITED",
        )
    )
    client = FootballDataAPIClient(provider=provider)

    with pytest.raises(FootballDataAPIError):
        await client.get_upcoming_matches(days_ahead=14, limit=50)

    assert provider.fixtures.await_count == 1


async def test_recent_results_shares_the_same_isolation() -> None:
    """get_recent_results() keeps completed results collected before rate limiting."""
    provider = _provider_with(
        _result(
            ProviderStatus.VERIFIED,
            _record(
                10,
                utc_date="2026-08-16T15:00:00Z",
                home_score=2,
                away_score=1,
            ),
        ),
        _result(
            ProviderStatus.RATE_LIMITED,
            error_code="TRANSPORT_RATE_LIMITED",
        ),
    )
    client = FootballDataAPIClient(provider=provider)

    results = await client.get_recent_results(days_back=3, limit=100)

    assert len(results) == 1
    assert results[0]["id"] == "fd-10"
    assert results[0]["home_score"] == 2
    assert provider.fixtures.await_count == 2


async def test_an_all_incoherent_batch_is_distinguishable_from_an_empty_one(caplog) -> None:
    """Two very different failures must not produce the same observable.

    On 2026-09-22 production reported `fixture_sync.successes: 1,
    fixture_sync.inserted: 0` with no warning and no failure counter, and the
    platform served zero upcoming fixtures across all six leagues. Nothing
    recorded whether football-data.org had returned nothing, or had returned a
    full slate that was then dropped as incoherent -- so the incident was not
    diagnosable at all (docs/DEBT.md item 130).

    Both paths still legitimately yield zero fixtures. The contract is that they
    no longer look the same from outside.
    """
    incoherent = _record(11)
    incoherent["coherent"] = False
    incoherent["rejection_reason"] = "kickoff_utc missing"

    provider = _provider_with(
        ProviderResult(
            provider="football_data_org",
            operation="fixtures",
            status=ProviderStatus.VERIFIED,
            trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
            records=[incoherent],
            warnings=["rejected: kickoff_utc missing"],
        ),
        *[_result(ProviderStatus.PARTIAL) for _ in range(6)],
    )
    client = FootballDataAPIClient(provider=provider)

    with caplog.at_level("INFO"):
        matches = await client.get_upcoming_matches(days_ahead=14, limit=50)

    assert matches == []
    text = caplog.text
    assert "received=1" in text, "candidate count must be recorded"
    assert "dropped_incoherent=1" in text, "the drop must be attributable"
    assert "kickoff_utc missing" in text, "the provider's own reason must survive"


async def test_a_genuinely_empty_provider_response_records_zero_candidates(caplog) -> None:
    """The other side of the same contract: nothing received, nothing dropped."""
    provider = _provider_with(*[_result(ProviderStatus.PARTIAL) for _ in range(7)])
    client = FootballDataAPIClient(provider=provider)

    with caplog.at_level("INFO"):
        matches = await client.get_upcoming_matches(days_ahead=14, limit=50)

    assert matches == []
    assert "received=0" in caplog.text
    assert "dropped_incoherent=0" in caplog.text
