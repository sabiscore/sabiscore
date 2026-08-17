"""The Odds API current-market provider.

Upgrades from the prior capability-only stub:
  * Per-bookmaker normalization into the canonical OddsMarketRecord shape.
  * Rejection of incomplete records (missing any of home/draw/away).
  * Rejection of mixed-bookmaker records (all three prices must come from one
    bookmaker in a single coherent snapshot).
  * Preservation of bookmaker last_update timestamp.
  * Quota header extraction (x-requests-remaining, x-requests-used).
  * Standard ProviderResult envelope with snapshot hash and acquisition time.

Design constraints:
  * This method is network-only. Credential validation is at health/probe time.
  * The caller (evidence orchestrator) selects ONE bookmaker record from the
    returned list for execution analysis. Never combine prices across records.
  * provider_predictions are excluded by design — only raw 1X2 prices used.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from .base import (
    BaseProvider,
    ProviderCapability,
    ProviderQuota,
    ProviderResult,
    ProviderStatus,
    TrustTier,
    stable_hash,
    utc_now,
)
from .espn import ESPN_LEAGUE_SLUGS

logger = logging.getLogger("sabiscore.providers.the_odds_api")

# ---------------------------------------------------------------------------
# Sport slugs — The Odds API uses different names to ESPN slugs.
# ---------------------------------------------------------------------------

_SABISCORE_COMP_TO_ODDS_SPORT: dict[str, str] = {
    "EPL": "soccer_epl",
    "LA_LIGA": "soccer_spain_la_liga",
    "SERIE_A": "soccer_italy_serie_a",
    "BUNDESLIGA": "soccer_germany_bundesliga",
    "LIGUE_1": "soccer_france_ligue_one",
    "EREDIVISIE": "soccer_netherlands_eredivisie",
    "UCL": "soccer_uefa_champs_league",
}

# Overround integrity limits — markets outside these bounds are rejected.
# Lower bound set to 1.005 to accommodate sharp exchanges (Betfair, Pinnacle)
# which can have overrounds as low as 1.005. A sub-1.00 overround would
# represent a sure-bet arbitrage, which is either a data error or a feed lag.
_MIN_OVERROUND = 1.005
_MAX_OVERROUND = 1.25


def devig_probabilities(home_odds: float, draw_odds: float, away_odds: float) -> tuple[float, float, float]:
    """(1/odds_i) / overround per outcome — the de-vig arithmetic implied by
    the overround check above but never previously factored into a callable
    (docs/adr/0004-clv-capture.md). Assumes coherent, already-validated odds;
    callers should only pass records where coherent=True."""
    overround = (1 / home_odds) + (1 / draw_odds) + (1 / away_odds)
    return (1 / home_odds) / overround, (1 / draw_odds) / overround, (1 / away_odds) / overround


# ---------------------------------------------------------------------------
# Canonical market record
# ---------------------------------------------------------------------------


class OddsMarketRecord(BaseModel):
    """A single bookmaker's coherent 1X2 market snapshot for one fixture.

    Executable only when coherent=True. The orchestrator may present multiple
    records (one per bookmaker) to the user; the user or backend policy selects
    one. Never combine prices across records.
    """

    canonical_fixture_id: str | None
    provider: str = "the_odds_api"
    provider_event_id: str
    home_team: str
    away_team: str
    bookmaker: str
    market_type: str = "1X2"
    home_odds: float
    draw_odds: float
    away_odds: float
    overround: float
    provider_event_timestamp: datetime | None
    bookmaker_last_update: datetime | None
    captured_at: datetime
    coherent: bool
    executable: bool
    rejection_reason: str | None = None


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class TheOddsAPIProvider(BaseProvider):
    provider_id = "the_odds_api"
    display_name = "The Odds API"
    trust_tier = TrustTier.OFFICIAL_AUTHENTICATED
    requires_key = True
    base_url = "https://api.the-odds-api.com/v4"

    async def capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability(
                provider=self.provider_id,
                competition=competition,
                fixtures=True,
                odds=True,
                notes=["single_bookmaker_snapshots_required", "quota_headers_recorded_when_live"],
            )
            for competition in ESPN_LEAGUE_SLUGS
        ]

    async def odds(
        self,
        *,
        competition: str,
        regions: str = "uk,eu",
        markets: str = "h2h",
        canonical_fixture_lookup: dict[str, str] | None = None,
    ) -> ProviderResult:
        """Fetch and normalize the current h2h market for a competition.

        Args:
            competition: Canonical SabiScore competition code (e.g. "EPL").
            regions: Comma-separated bookmaker regions (default "uk,eu").
            markets: Market type — only "h2h" produces valid 1X2 data.
            canonical_fixture_lookup: Optional {provider_event_id: fixture_id}
                map for linking records to canonical identities. If absent,
                canonical_fixture_id is None (reconciliation required upstream).

        Returns:
            ProviderResult with records as list[dict] (each is an
            OddsMarketRecord serialised via model_dump). Rejected records are
            included with coherent=False and rejection_reason populated.
        """
        if not self.enabled or not self.configured:
            return ProviderResult(
                provider=self.provider_id,
                operation="odds",
                status=ProviderStatus.UNAVAILABLE,
                trust_tier=self.trust_tier,
                error_code="provider_disabled_or_unconfigured",
                warnings=["provider must be enabled and configured with a backend credential"],
            )

        sport = _SABISCORE_COMP_TO_ODDS_SPORT.get(competition.upper())
        if sport is None:
            return ProviderResult(
                provider=self.provider_id,
                operation="odds",
                status=ProviderStatus.UNAVAILABLE,
                trust_tier=self.trust_tier,
                error_code="unsupported_competition",
                warnings=[f"competition {competition!r} has no Odds API sport mapping"],
            )

        captured_at = utc_now()
        try:
            payload, headers = await self._get_json(
                f"{self.base_url}/sports/{sport}/odds",
                # API key goes in params; base._get_json calls redact_url before logging.
                params={
                    "apiKey": self.api_key,
                    "regions": regions,
                    "markets": markets,
                    "oddsFormat": "decimal",
                },
            )
        except Exception as exc:
            return self._transport_failure_result("odds", exc)

        raw_events: list[dict[str, Any]] = payload if isinstance(payload, list) else []
        quota = self._quota_from_headers(headers)
        canonical_lookup = canonical_fixture_lookup or {}

        records: list[dict[str, Any]] = []
        warnings: list[str] = []

        for event in raw_events:
            event_id = str(event.get("id", ""))
            home_team = str(event.get("home_team", "")).strip()
            away_team = str(event.get("away_team", "")).strip()
            event_commence = self._parse_ts(event.get("commence_time"))
            canonical_id = canonical_lookup.get(event_id)

            bookmakers: list[dict[str, Any]] = event.get("bookmakers", [])
            if not bookmakers:
                warnings.append(f"event {event_id}: no bookmakers")
                continue

            for bm in bookmakers:
                record = self._normalize_bookmaker(
                    event_id=event_id,
                    canonical_fixture_id=canonical_id,
                    home_team=home_team,
                    away_team=away_team,
                    bookmaker=str(bm.get("key", "")),
                    bookmaker_last_update=self._parse_ts(bm.get("last_update")),
                    markets=bm.get("markets", []),
                    provider_event_timestamp=event_commence,
                    captured_at=captured_at,
                )
                if not record.coherent:
                    warnings.append(
                        f"event {event_id} bookmaker {record.bookmaker}: "
                        f"rejected — {record.rejection_reason}"
                    )
                records.append(record.model_dump(mode="json"))

        return ProviderResult(
            provider=self.provider_id,
            operation="odds",
            status=ProviderStatus.VERIFIED if records else ProviderStatus.PARTIAL,
            trust_tier=self.trust_tier,
            acquired_at=captured_at,
            records=records,
            quota=quota,
            warnings=warnings,
            raw_snapshot_id=stable_hash(raw_events),
        )

    async def probe(self) -> ProviderStatus:
        """Cheap liveness probe: fetch sports list (no quota cost)."""
        try:
            await self._get_json(
                f"{self.base_url}/sports",
                params={"apiKey": self.api_key, "all": "false"},
            )
            return ProviderStatus.VERIFIED
        except Exception as exc:  # pragma: no cover - network path
            return self._transport_status(exc)

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _normalize_bookmaker(
        self,
        *,
        event_id: str,
        canonical_fixture_id: str | None,
        home_team: str,
        away_team: str,
        bookmaker: str,
        bookmaker_last_update: datetime | None,
        markets: list[dict[str, Any]],
        provider_event_timestamp: datetime | None,
        captured_at: datetime,
    ) -> OddsMarketRecord:
        """Normalize one bookmaker's market into an OddsMarketRecord.

        A record is incoherent (and therefore not executable) if:
        - The h2h market is absent.
        - Any of the three 1X2 outcomes is missing.
        - The overround is outside integrity limits.
        - The market mixes data from multiple bookmakers (not possible at this
          layer since we iterate per-bookmaker, but noted for documentation).
        """
        h2h_market = next((m for m in markets if m.get("key") == "h2h"), None)
        if h2h_market is None:
            return OddsMarketRecord(
                canonical_fixture_id=canonical_fixture_id,
                provider_event_id=event_id,
                home_team=home_team,
                away_team=away_team,
                bookmaker=bookmaker,
                home_odds=0.0,
                draw_odds=0.0,
                away_odds=0.0,
                overround=0.0,
                provider_event_timestamp=provider_event_timestamp,
                bookmaker_last_update=bookmaker_last_update,
                captured_at=captured_at,
                coherent=False,
                executable=False,
                rejection_reason="missing_h2h_market",
            )

        outcomes: dict[str, float] = {}
        for outcome in h2h_market.get("outcomes", []):
            name = str(outcome.get("name", "")).strip().casefold()
            price = outcome.get("price")
            try:
                parsed_price = float(price)
            except (TypeError, ValueError):
                continue
            if parsed_price > 1.0:
                outcomes[name] = parsed_price

        draw_odds = outcomes.get("draw") or outcomes.get("tie")
        home_odds = outcomes.get(home_team.casefold())
        away_odds = outcomes.get(away_team.casefold())

        if not home_team or not away_team or draw_odds is None or home_odds is None or away_odds is None:
            return OddsMarketRecord(
                canonical_fixture_id=canonical_fixture_id,
                provider_event_id=event_id,
                home_team=home_team,
                away_team=away_team,
                bookmaker=bookmaker,
                home_odds=0.0,
                draw_odds=0.0,
                away_odds=0.0,
                overround=0.0,
                provider_event_timestamp=provider_event_timestamp,
                bookmaker_last_update=bookmaker_last_update,
                captured_at=captured_at,
                coherent=False,
                executable=False,
                rejection_reason="incomplete_1x2_outcomes",
            )

        # Validate overround integrity.
        try:
            overround = (1 / home_odds) + (1 / draw_odds) + (1 / away_odds)
        except ZeroDivisionError:
            return OddsMarketRecord(
                canonical_fixture_id=canonical_fixture_id,
                provider_event_id=event_id,
                home_team=home_team,
                away_team=away_team,
                bookmaker=bookmaker,
                home_odds=home_odds,
                draw_odds=draw_odds,
                away_odds=away_odds,
                overround=0.0,
                provider_event_timestamp=provider_event_timestamp,
                bookmaker_last_update=bookmaker_last_update,
                captured_at=captured_at,
                coherent=False,
                executable=False,
                rejection_reason="zero_division_in_overround",
            )

        if not (_MIN_OVERROUND <= overround <= _MAX_OVERROUND):
            return OddsMarketRecord(
                canonical_fixture_id=canonical_fixture_id,
                provider_event_id=event_id,
                home_team=home_team,
                away_team=away_team,
                bookmaker=bookmaker,
                home_odds=home_odds,
                draw_odds=draw_odds,
                away_odds=away_odds,
                overround=round(overround, 6),
                provider_event_timestamp=provider_event_timestamp,
                bookmaker_last_update=bookmaker_last_update,
                captured_at=captured_at,
                coherent=False,
                executable=False,
                rejection_reason=f"overround_outside_integrity_limits_{overround:.4f}",
            )

        return OddsMarketRecord(
            canonical_fixture_id=canonical_fixture_id,
            provider_event_id=event_id,
            home_team=home_team,
            away_team=away_team,
            bookmaker=bookmaker,
            home_odds=round(home_odds, 4),
            draw_odds=round(draw_odds, 4),
            away_odds=round(away_odds, 4),
            overround=round(overround, 6),
            provider_event_timestamp=provider_event_timestamp,
            bookmaker_last_update=bookmaker_last_update,
            captured_at=captured_at,
            coherent=True,
            executable=True,
        )

    def _quota_from_headers(self, headers: Any) -> ProviderQuota:
        remaining = headers.get("x-requests-remaining") if headers else None
        used = headers.get("x-requests-used") if headers else None
        return ProviderQuota(
            remaining=int(remaining) if remaining and str(remaining).isdigit() else None,
            cost=int(used) if used and str(used).isdigit() else None,
        )

    @staticmethod
    def _parse_ts(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
