"""Quota-aware evidence orchestration facade.

All six evidence profiles from Section 9 of the production contract are now
wired to real provider operations — with graceful degradation when providers
are stubs (no operational methods) or misconfigured.

Profile → primary providers → fallback providers:

    DISCOVERY          ESPN (keyless discovery) + football_data_org (fixture list)
    PREMATCH_STANDARD  football_data_org (fixtures/standings) + ESPN (corroboration)
    PREMATCH_ENRICHED  api_football (injuries/lineups/stats) + sportmonks (optional)
    LINEUP_REFRESH     api_football (confirmed lineups) + sportmonks (optional)
    MARKET_REFRESH     the_odds_api (1X2 snapshots, per-bookmaker)
    FORECAST_ONLY      football_data_org + ESPN (no market required)

Design constraints (Section 6 / verified ground truth 2026-06-28):
  - ESPN is SUPPLEMENTARY_ONLY, UNOFFICIAL_PUBLIC, KEYLESS.
    It may be used in DISCOVERY and PREMATCH_STANDARD as a low-cost corroborating
    source but must never be the sole provider for execution-eligible evidence.
  - football_data_org, api_football, sportmonks, and the_odds_api all have
    operational HTTP methods now. `_safe_call()` still wraps every call so an
    `AttributeError` (a genuinely unimplemented method) or network failure
    degrades to a structured PARTIAL rather than propagating.
  - api_football.team_statistics() needs a numeric team_id: PREMATCH_ENRICHED
    resolves one per fixture side via api_football.teams() +
    reconciliation.reconcile_team() (Section 8) before calling it. A team that
    doesn't reconcile to VERIFIED yields a structured PARTIAL, never a guess.
  - Provider predictions must never enter the evidence pipeline.
  - concurrent=True on independent operations to bound wall-clock time.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

from .base import ProviderResult, ProviderStatus, TrustTier, redact_text
from .reconciliation import TeamCandidate, reconcile_team
from .registry import ProviderRegistry

logger = logging.getLogger("sabiscore.providers.orchestrator")

_UTC = timezone.utc


class EvidenceProfile(str, Enum):
    DISCOVERY = "DISCOVERY"
    PREMATCH_STANDARD = "PREMATCH_STANDARD"
    PREMATCH_ENRICHED = "PREMATCH_ENRICHED"
    LINEUP_REFRESH = "LINEUP_REFRESH"
    MARKET_REFRESH = "MARKET_REFRESH"
    FORECAST_ONLY = "FORECAST_ONLY"


def _stub_result(provider: str, operation: str, reason: str) -> ProviderResult:
    """Return a structured PARTIAL when a provider has no operational method yet."""
    return ProviderResult(
        provider=provider,
        operation=operation,
        status=ProviderStatus.PARTIAL,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        acquired_at=datetime.now(_UTC),
        warnings=[reason],
        error_code="adapter_stub_no_operational_method",
    )


async def _safe_call(
    coro_factory: Callable[[], Coroutine[Any, Any, ProviderResult]],
    provider: str,
    operation: str,
) -> ProviderResult:
    """Wrap a provider call so a stub/missing-method/network error never propagates.

    Returns a PARTIAL result on any exception, keeping the orchestrator
    consistent for callers. The caller classifies the resulting status as
    critical or advisory based on the profile and field precedence rules.
    """
    try:
        return await coro_factory()
    except AttributeError:
        # Provider exists but has no operational method yet (stub).
        return _stub_result(
            provider, operation, f"{provider}.{operation}() not yet implemented"
        )
    except Exception as exc:
        logger.warning(
            "orchestrator_provider_error provider=%s op=%s error=%s",
            provider,
            operation,
            redact_text(str(exc)),
        )
        return ProviderResult(
            provider=provider,
            operation=operation,
            status=ProviderStatus.UNAVAILABLE,
            trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
            acquired_at=datetime.now(_UTC),
            error_code=type(exc).__name__,
        )


class EvidenceOrchestrator:
    """Routes fixture evidence requests to the appropriate provider combination.

    The registry is the single source of provider availability and capability.
    All provider selection, concurrent fan-out, and result aggregation happens
    here so endpoints never call providers directly.
    """

    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    async def collect(
        self,
        fixture: dict[str, Any],
        profile: EvidenceProfile,
        *,
        canonical_fixture_id: str | None = None,
    ) -> list[ProviderResult]:
        """Collect evidence for a fixture under the given profile.

        Args:
            fixture: Must contain at minimum 'competition' (canonical code) and
                optionally 'provider_event_id', 'home_team', 'away_team',
                'kickoff_utc', 'season'.
            profile: Evidence collection profile.
            canonical_fixture_id: When known, passed through for bookmaker
                record linking in MARKET_REFRESH.

        Returns:
            Ordered list of ProviderResult objects. The orchestrator does not
            classify critical vs advisory gaps — that is the evidence criticality
            layer's responsibility (Section 10). A PARTIAL result from a required
            source is classified as critical; from an optional source, advisory.
        """
        competition = str(
            fixture.get("competition") or fixture.get("league") or "EPL"
        ).upper()

        if profile == EvidenceProfile.DISCOVERY:
            return await self._collect_discovery(fixture, competition)
        if profile == EvidenceProfile.PREMATCH_STANDARD:
            return await self._collect_prematch_standard(fixture, competition)
        if profile == EvidenceProfile.PREMATCH_ENRICHED:
            return await self._collect_prematch_enriched(fixture, competition)
        if profile == EvidenceProfile.LINEUP_REFRESH:
            return await self._collect_lineup_refresh(fixture, competition)
        if profile == EvidenceProfile.MARKET_REFRESH:
            return await self._collect_market_refresh(
                fixture, competition, canonical_fixture_id
            )
        if profile == EvidenceProfile.FORECAST_ONLY:
            return await self._collect_forecast_only(fixture, competition)
        return [
            _stub_result("orchestrator", profile.value, f"unknown_profile_{profile}")
        ]

    # ------------------------------------------------------------------ #
    # Profile implementations                                              #
    # ------------------------------------------------------------------ #

    async def _collect_discovery(
        self, fixture: dict[str, Any], competition: str
    ) -> list[ProviderResult]:
        """Low-cost fixture discovery.

        ESPN provides keyless scoreboard discovery. football_data_org provides
        the official fixture list (when configured). Results run concurrently.
        """
        espn = self.registry.get("espn")
        fdo = self.registry.get("football_data_org")

        tasks = [
            _safe_call(
                lambda e=espn, c=competition: e.scoreboard(c), "espn", "scoreboard"
            ),
            _safe_call(
                lambda f=fdo, c=competition: f.fixtures(competition=c),
                "football_data_org",
                "fixtures",
            ),
        ]
        results = list(await asyncio.gather(*tasks))
        return results

    async def _collect_prematch_standard(
        self, fixture: dict[str, Any], competition: str
    ) -> list[ProviderResult]:
        """Standard pre-match evidence: standings + baseline fixture data.

        Primary: football_data_org (official, authenticated).
        Supplementary: ESPN (keyless corroboration, standings check).
        """
        fdo = self.registry.get("football_data_org")
        espn = self.registry.get("espn")

        tasks = [
            _safe_call(
                lambda f=fdo, c=competition: f.fixtures(competition=c),
                "football_data_org",
                "fixtures",
            ),
            _safe_call(
                lambda f=fdo, c=competition: f.standings(competition=c),
                "football_data_org",
                "standings",
            ),
            _safe_call(
                lambda e=espn, c=competition: e.scoreboard(c), "espn", "scoreboard"
            ),
        ]
        results = list(await asyncio.gather(*tasks))
        return results

    async def _collect_prematch_enriched(
        self, fixture: dict[str, Any], competition: str
    ) -> list[ProviderResult]:
        """Enriched pre-match evidence: injuries, availability, statistics.

        Primary: api_football (injuries, lineups, team stats, player stats).
        Optional: sportmonks (additional enrichment when configured).

        Provider predictions from either source are explicitly excluded.
        """
        apif = self.registry.get("api_football")
        sm = self.registry.get("sportmonks")

        apif_tasks = [
            _safe_call(
                lambda a=apif, c=competition: a.injuries(competition=c),
                "api_football",
                "injuries",
            ),
            _safe_call(
                lambda a=apif, c=competition: a.lineups(
                    fixture_id=fixture.get("provider_event_id"), competition=c
                ),
                "api_football",
                "lineups",
            ),
            _safe_call(
                lambda a=apif, c=competition: a.teams(competition=c),
                "api_football",
                "teams",
            ),
        ]
        sm_tasks = [
            _safe_call(
                lambda s=sm, c=competition: s.injuries(competition=c),
                "sportmonks",
                "injuries",
            ),
        ]

        results = list(await asyncio.gather(*(apif_tasks + sm_tasks)))
        results.extend(
            await self._resolve_team_statistics(apif, results[2], fixture, competition)
        )
        return results

    async def _resolve_team_statistics(
        self,
        apif: Any,
        teams_result: ProviderResult,
        fixture: dict[str, Any],
        competition: str,
    ) -> list[ProviderResult]:
        """Resolve the fixture's home/away team names to API-Football team_ids
        via reconcile_team(), then fetch team_statistics() for each resolved
        team. A team that doesn't reconcile to VERIFIED yields a structured
        PARTIAL instead of a guessed team_id (Section 8: ambiguity fails closed).
        """
        candidates = [
            TeamCandidate(team_id=str(record["team_id"]), name=record["name"])
            for record in teams_result.records
            if record.get("coherent") and record.get("team_id") is not None
        ]

        outcomes: list[ProviderResult] = []
        for label, team_name in (
            ("home", fixture.get("home_team")),
            ("away", fixture.get("away_team")),
        ):
            operation = f"team_statistics:{label}"
            if not team_name:
                outcomes.append(
                    _stub_result("api_football", operation, "fixture_missing_team_name")
                )
                continue
            if not candidates:
                outcomes.append(
                    _stub_result("api_football", operation, "team_list_unavailable")
                )
                continue

            decision = reconcile_team(str(team_name), candidates)
            if decision.status != "VERIFIED" or not decision.team_id:
                outcomes.append(
                    _stub_result(
                        "api_football",
                        operation,
                        f"team_identity_{decision.status.lower()}",
                    )
                )
                continue

            result = await _safe_call(
                lambda a=apif, tid=int(decision.team_id), c=competition: (
                    a.team_statistics(team_id=tid, competition=c)
                ),
                "api_football",
                operation,
            )
            outcomes.append(result)

        return outcomes

    async def _collect_lineup_refresh(
        self, fixture: dict[str, Any], competition: str
    ) -> list[ProviderResult]:
        """Lineup confirmation refresh — time-sensitive, runs close to kickoff.

        Primary: api_football (confirmed lineups, availability changes).
        Optional: sportmonks (expected vs confirmed cross-check).
        """
        apif = self.registry.get("api_football")
        sm = self.registry.get("sportmonks")
        fixture_id = fixture.get("provider_event_id") or fixture.get("fixture_id")

        tasks = [
            _safe_call(
                lambda a=apif, fid=fixture_id: a.lineups(fixture_id=fid),
                "api_football",
                "lineups",
            ),
            _safe_call(
                lambda s=sm, fid=fixture_id: s.lineups(fixture_id=fid),
                "sportmonks",
                "lineups",
            ),
        ]
        results = list(await asyncio.gather(*tasks))
        return results

    async def _collect_market_refresh(
        self,
        fixture: dict[str, Any],
        competition: str,
        canonical_fixture_id: str | None,
    ) -> list[ProviderResult]:
        """Market snapshot refresh — one coherent bookmaker record per fixture.

        Primary: the_odds_api (1X2 snapshots, per-bookmaker normalization).
        Per Section 6: one bookmaker's coherent snapshot per analysis.
        Mixed-bookmaker records are rejected by the_odds_api.odds() internally.
        """
        odds_api = self.registry.get("the_odds_api")
        canonical_lookup = (
            {fixture.get("provider_event_id", ""): canonical_fixture_id}
            if canonical_fixture_id
            else None
        )
        result = await _safe_call(
            lambda o=odds_api, c=competition: o.odds(
                competition=c,
                canonical_fixture_lookup=canonical_lookup,
            ),
            "the_odds_api",
            "odds",
        )
        return [result]

    async def _collect_forecast_only(
        self, fixture: dict[str, Any], competition: str
    ) -> list[ProviderResult]:
        """Forecast-only: probabilities without executable market.

        No market source is requested. Missing market is an advisory gap only,
        not critical, for FORECAST_ONLY (execution_eligible remains False).
        """
        fdo = self.registry.get("football_data_org")
        espn = self.registry.get("espn")

        tasks = [
            _safe_call(
                lambda f=fdo, c=competition: f.fixtures(competition=c),
                "football_data_org",
                "fixtures",
            ),
            _safe_call(
                lambda e=espn, c=competition: e.scoreboard(c), "espn", "scoreboard"
            ),
        ]
        results = list(await asyncio.gather(*tasks))
        return results
