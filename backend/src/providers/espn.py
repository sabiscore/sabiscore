"""ESPN supplementary provider.

ESPN is keyless, unofficial/public for this product, and may corroborate
fixtures/status/standings only. It must never provide SabiScore probabilities,
odds, stakes, or authoritative availability on its own.

NOTE: The active implementation lives in providers/espn/ (package). This flat
module is superseded and retained only for backwards-compat imports. The package
takes Python precedence when both exist.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import (
    BaseProvider,
    ProviderCapability,
    ProviderResult,
    ProviderStatus,
    TrustTier,
    stable_hash,
)

ESPN_LEAGUE_SLUGS: dict[str, str] = {
    "EPL": "eng.1",
    "LA_LIGA": "esp.1",
    "SERIE_A": "ita.1",
    "BUNDESLIGA": "ger.1",
    "LIGUE_1": "fra.1",
    "EREDIVISIE": "ned.1",
    "UCL": "uefa.champions",
}


class ESPNProvider(BaseProvider):
    provider_id = "espn"
    display_name = "ESPN Public Soccer API"
    trust_tier = TrustTier.UNOFFICIAL_PUBLIC
    requires_key = False
    base_url = "https://site.api.espn.com/apis/site/v2/sports/soccer"

    async def capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability(
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
            raise ValueError("expected two competitors")
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            raise ValueError("home/away competitors missing")
        status = event.get("status") or fixture.get("status") or {}
        kickoff_utc = event.get("date")
        # ponytail: ESPN scoreboards carry no content-update timestamp — provider_timestamp
        # must be None, never aliased to kickoff_utc (CLAUDE.md timestamp discipline).
        provider_timestamp = event.get("lastModified") or None
        return {
            "provider_event_id": str(event.get("id") or ""),
            "competition": competition,
            "home_team": ((home.get("team") or {}).get("displayName") or "").strip(),
            "away_team": ((away.get("team") or {}).get("displayName") or "").strip(),
            "kickoff_utc": kickoff_utc,
            "status": ((status.get("type") or {}).get("name") or "UNKNOWN").upper(),
            "provider_timestamp": provider_timestamp,
            "source_trust": self.trust_tier.value,
        }

    async def scoreboard(
        self, competition: str, date: str | None = None
    ) -> ProviderResult:
        competition = competition.upper()
        if competition not in ESPN_LEAGUE_SLUGS:
            return ProviderResult(
                provider=self.provider_id,
                operation="scoreboard",
                status=ProviderStatus.INVALID,
                trust_tier=self.trust_tier,
                warnings=[f"unsupported_competition:{competition}"],
                error_code="UNSUPPORTED_COMPETITION",
            )
        if not self.enabled:
            return ProviderResult(
                provider=self.provider_id,
                operation="scoreboard",
                status=ProviderStatus.UNAVAILABLE,
                trust_tier=self.trust_tier,
                warnings=["provider_disabled"],
            )
        if not self.live_tests:
            return ProviderResult(
                provider=self.provider_id,
                operation="scoreboard",
                status=ProviderStatus.PARTIAL,
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
            return ProviderResult(
                provider=self.provider_id,
                operation="scoreboard",
                status=ProviderStatus.INVALID,
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
        return ProviderResult(
            provider=self.provider_id,
            operation="scoreboard",
            status=ProviderStatus.VERIFIED if records else ProviderStatus.PARTIAL,
            trust_tier=self.trust_tier,
            provider_timestamp=provider_ts,
            records=records,
            raw_snapshot_id=stable_hash(payload),
            warnings=["supplementary_only"],
        )
