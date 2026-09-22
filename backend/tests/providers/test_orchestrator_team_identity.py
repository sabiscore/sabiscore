"""Tests for the PREMATCH_ENRICHED team-identity resolution wired into
EvidenceOrchestrator (orchestrator.py: _resolve_team_statistics).

Run:
    cd backend
    python -m pytest tests/providers/test_orchestrator_team_identity.py -q --no-cov
"""

from __future__ import annotations

from typing import Any

import pytest

from src.providers.base import ProviderResult, ProviderStatus, TrustTier
from src.providers.orchestrator import EvidenceOrchestrator, EvidenceProfile


class _FakeRegistry:
    def __init__(self, providers: dict[str, Any]) -> None:
        self._providers = providers

    def get(self, name: str) -> Any:
        return self._providers.get(name)


class _FakeAPIFootball:
    def __init__(
        self, teams_result: ProviderResult, stats_by_team_id: dict[int, ProviderResult]
    ) -> None:
        self._teams_result = teams_result
        self._stats_by_team_id = stats_by_team_id
        self.team_statistics_calls: list[int] = []

    async def injuries(self, *, competition: str) -> ProviderResult:
        return ProviderResult(
            provider="api_football",
            operation="injuries",
            status=ProviderStatus.PARTIAL,
            trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        )

    async def lineups(
        self, *, fixture_id: Any, competition: str | None = None
    ) -> ProviderResult:
        return ProviderResult(
            provider="api_football",
            operation="lineups",
            status=ProviderStatus.PARTIAL,
            trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        )

    async def teams(self, *, competition: str) -> ProviderResult:
        return self._teams_result

    async def team_statistics(
        self, *, team_id: int, competition: str
    ) -> ProviderResult:
        self.team_statistics_calls.append(team_id)
        return self._stats_by_team_id.get(
            team_id,
            ProviderResult(
                provider="api_football",
                operation="team_statistics",
                status=ProviderStatus.PARTIAL,
                trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
            ),
        )


class _FakeSportmonks:
    async def injuries(self, *, competition: str) -> ProviderResult:
        return ProviderResult(
            provider="sportmonks",
            operation="injuries",
            status=ProviderStatus.PARTIAL,
            trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        )


def _teams_result(records: list[dict[str, Any]]) -> ProviderResult:
    return ProviderResult(
        provider="api_football",
        operation="teams",
        status=ProviderStatus.VERIFIED,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        records=records,
    )


def _verified_stats(team_id: int, name: str) -> ProviderResult:
    return ProviderResult(
        provider="api_football",
        operation="team_statistics",
        status=ProviderStatus.VERIFIED,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        records=[{"team_id": team_id, "team_name": name, "coherent": True}],
    )


@pytest.mark.asyncio
async def test_prematch_enriched_resolves_team_ids_and_fetches_statistics():
    teams = _teams_result(
        [
            {"team_id": 57, "name": "Arsenal FC", "coherent": True},
            {"team_id": 49, "name": "Chelsea FC", "coherent": True},
        ]
    )
    apif = _FakeAPIFootball(
        teams,
        stats_by_team_id={
            57: _verified_stats(57, "Arsenal FC"),
            49: _verified_stats(49, "Chelsea FC"),
        },
    )
    orchestrator = EvidenceOrchestrator(
        _FakeRegistry({"api_football": apif, "sportmonks": _FakeSportmonks()})
    )

    results = await orchestrator.collect(
        {
            "competition": "EPL",
            "home_team": "Arsenal FC",
            "away_team": "Chelsea FC",
            "provider_event_id": "12345",
        },
        EvidenceProfile.PREMATCH_ENRICHED,
    )

    stat_results = [r for r in results if r.operation.startswith("team_statistics")]
    assert len(stat_results) == 2
    assert all(r.status == ProviderStatus.VERIFIED for r in stat_results)
    assert sorted(apif.team_statistics_calls) == [49, 57]


@pytest.mark.asyncio
async def test_prematch_enriched_yields_partial_when_team_name_unresolved():
    """A team name with no plausible candidate must not guess a team_id."""
    teams = _teams_result([{"team_id": 57, "name": "Arsenal FC", "coherent": True}])
    apif = _FakeAPIFootball(teams, stats_by_team_id={})
    orchestrator = EvidenceOrchestrator(
        _FakeRegistry({"api_football": apif, "sportmonks": _FakeSportmonks()})
    )

    results = await orchestrator.collect(
        {
            "competition": "EPL",
            "home_team": "Arsenal FC",
            "away_team": "Watford",
            "provider_event_id": "12345",
        },
        EvidenceProfile.PREMATCH_ENRICHED,
    )

    away_result = next(r for r in results if r.operation == "team_statistics:away")
    assert away_result.status == ProviderStatus.PARTIAL
    assert away_result.error_code == "adapter_stub_no_operational_method"
    assert apif.team_statistics_calls == [57]


@pytest.mark.asyncio
async def test_prematch_enriched_yields_partial_when_team_list_unavailable():
    teams = ProviderResult(
        provider="api_football",
        operation="teams",
        status=ProviderStatus.UNAVAILABLE,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        records=[],
    )
    apif = _FakeAPIFootball(teams, stats_by_team_id={})
    orchestrator = EvidenceOrchestrator(
        _FakeRegistry({"api_football": apif, "sportmonks": _FakeSportmonks()})
    )

    results = await orchestrator.collect(
        {"competition": "EPL", "home_team": "Arsenal", "away_team": "Chelsea"},
        EvidenceProfile.PREMATCH_ENRICHED,
    )

    stat_results = [r for r in results if r.operation.startswith("team_statistics")]
    assert len(stat_results) == 2
    assert all(r.status == ProviderStatus.PARTIAL for r in stat_results)
    assert apif.team_statistics_calls == []


@pytest.mark.asyncio
async def test_prematch_enriched_yields_partial_when_fixture_missing_team_names():
    teams = _teams_result([{"team_id": 57, "name": "Arsenal FC", "coherent": True}])
    apif = _FakeAPIFootball(teams, stats_by_team_id={})
    orchestrator = EvidenceOrchestrator(
        _FakeRegistry({"api_football": apif, "sportmonks": _FakeSportmonks()})
    )

    results = await orchestrator.collect(
        {"competition": "EPL"}, EvidenceProfile.PREMATCH_ENRICHED
    )

    stat_results = [r for r in results if r.operation.startswith("team_statistics")]
    assert len(stat_results) == 2
    assert all(r.warnings == ["fixture_missing_team_name"] for r in stat_results)
