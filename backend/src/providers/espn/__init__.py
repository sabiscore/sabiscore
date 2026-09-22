"""ESPN provider — keyless, supplementary, discovery/readiness-only.

Trust tier: UNOFFICIAL_PUBLIC. ESPN supplies fixture discovery and event status
to the evidence orchestrator at the lowest precedence. It never establishes
critical odds, lineup, injury, probability, or execution evidence, and it never
computes model features, verdicts, EV, or stakes.

Public surface:
    EspnProvider            — the operational client (DI: httpx + breaker + clock)
    Competition             — canonical competition enum (7 supported)
    ProviderEnvelope        — redacted standard envelope
    NormalizedFixture       — normalized, audit-stamped fixture
    ProviderStatus          — health/status taxonomy
    TrustTier               — trust tier enum
    EspnSchemaError         — raised on contract drift (fail closed)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..base import (
    BaseProvider,
    ProviderCapability as BaseProviderCapability,
    ProviderResult as BaseProviderResult,
    ProviderStatus as BaseProviderStatus,
    TrustTier as BaseTrustTier,
    stable_hash,
)
from .client import CircuitBreaker, CircuitOpenError, EspnProvider
from .mappings import (
    Competition,
    UnsupportedCompetitionError,
    _ESPN_SLUG_BY_COMPETITION,
    competition_from_slug,
    espn_slug,
    supported_competitions,
)
from .schemas import (
    EspnSchemaError,
    NormalizedFixture,
    ProviderEnvelope,
    ProviderStatus,
    TrustTier,
)

ESPN_LEAGUE_SLUGS = {
    competition.value: slug for competition, slug in _ESPN_SLUG_BY_COMPETITION.items()
}


class ESPNProvider(BaseProvider):
    """Registry-compatible ESPN provider using shared provider contracts.

    The lowercase ``EspnProvider`` remains the operational package client used
    by the ESPN-specific tests. The registry imports this uppercase class and
    expects the shared ``src.providers.base`` result/status types.
    """

    provider_id = "espn"
    display_name = "ESPN Public Soccer API"
    trust_tier = BaseTrustTier.UNOFFICIAL_PUBLIC
    requires_key = False
    base_url = "https://site.api.espn.com/apis/site/v2/sports/soccer"

    async def capabilities(self) -> list[BaseProviderCapability]:
        return [
            BaseProviderCapability(
                provider=self.provider_id,
                competition=competition,
                fixtures=True,
                standings=True,
                notes=[
                    "supplementary_unofficial_public",
                    "no_odds_or_predictions",
                    "not_authoritative_for_actionable_fields",
                ],
            )
            for competition in ESPN_LEAGUE_SLUGS
        ]

    def normalize_event(
        self, event: dict[str, Any], competition: str
    ) -> dict[str, Any]:
        competitions = event.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            raise ValueError("missing competitions")

        fixture = competitions[0]
        competitors = fixture.get("competitors")
        if not isinstance(competitors, list) or len(competitors) != 2:
            raise ValueError(
                f"expected two competitors for ESPN event {event.get('id') or 'unknown'}"
            )

        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            raise ValueError(
                f"home/away competitors missing for ESPN event {event.get('id') or 'unknown'}"
            )

        status = event.get("status") or fixture.get("status") or {}
        kickoff_utc = event.get("date")
        provider_timestamp = event.get("lastModified") or fixture.get("lastModified")
        acquired_at = datetime.now(timezone.utc).isoformat()

        return {
            "provider_event_id": str(event.get("id") or ""),
            "competition": competition,
            "home_team": ((home.get("team") or {}).get("displayName") or "").strip(),
            "away_team": ((away.get("team") or {}).get("displayName") or "").strip(),
            "provider_home_team_id": str((home.get("team") or {}).get("id") or ""),
            "provider_away_team_id": str((away.get("team") or {}).get("id") or ""),
            "kickoff_utc": kickoff_utc,
            "status": ((status.get("type") or {}).get("name") or "UNKNOWN").upper(),
            "provider_timestamp": provider_timestamp,
            "acquired_at": acquired_at,
            "source_trust": self.trust_tier.value,
        }

    async def scoreboard(
        self, competition: str, date: str | None = None
    ) -> BaseProviderResult:
        competition = competition.upper()
        if competition not in ESPN_LEAGUE_SLUGS:
            return BaseProviderResult(
                provider=self.provider_id,
                operation="scoreboard",
                status=BaseProviderStatus.INVALID,
                trust_tier=self.trust_tier,
                warnings=[f"unsupported_competition:{competition}"],
                error_code="UNSUPPORTED_COMPETITION",
            )
        if not self.enabled:
            return BaseProviderResult(
                provider=self.provider_id,
                operation="scoreboard",
                status=BaseProviderStatus.UNAVAILABLE,
                trust_tier=self.trust_tier,
                warnings=["provider_disabled"],
            )
        if not self.live_tests:
            return BaseProviderResult(
                provider=self.provider_id,
                operation="scoreboard",
                status=BaseProviderStatus.PARTIAL,
                trust_tier=self.trust_tier,
                warnings=["live_provider_calls_disabled"],
            )

        params = {"dates": date} if date else None
        payload, _headers = await self._get_json(
            f"{self.base_url}/{ESPN_LEAGUE_SLUGS[competition]}/scoreboard",
            params=params,
        )
        events = payload.get("events")
        if not isinstance(events, list):
            self.breaker.record_failure()
            return BaseProviderResult(
                provider=self.provider_id,
                operation="scoreboard",
                status=BaseProviderStatus.INVALID,
                trust_tier=self.trust_tier,
                warnings=["schema_drift:events_not_list"],
                error_code="SCHEMA_DRIFT",
                raw_snapshot_id=stable_hash(payload),
            )

        records = [self.normalize_event(event, competition) for event in events]
        provider_ts = None
        if records and records[0].get("provider_timestamp"):
            provider_ts = datetime.fromisoformat(
                str(records[0]["provider_timestamp"]).replace("Z", "+00:00")
            )

        return BaseProviderResult(
            provider=self.provider_id,
            operation="scoreboard",
            status=BaseProviderStatus.VERIFIED
            if records
            else BaseProviderStatus.PARTIAL,
            trust_tier=self.trust_tier,
            provider_timestamp=provider_ts,
            records=records,
            raw_snapshot_id=stable_hash(payload),
            warnings=["supplementary_only"],
        )


__all__ = [
    "EspnProvider",
    "ESPNProvider",
    "CircuitBreaker",
    "CircuitOpenError",
    "Competition",
    "UnsupportedCompetitionError",
    "ESPN_LEAGUE_SLUGS",
    "competition_from_slug",
    "espn_slug",
    "supported_competitions",
    "EspnSchemaError",
    "NormalizedFixture",
    "ProviderEnvelope",
    "ProviderStatus",
    "TrustTier",
]
