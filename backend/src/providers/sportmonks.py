"""Sportmonks optional enrichment provider.

Operational client: sidelined players + lineups via Authorization header
auth (unlike football_data_org/api_football, which use header auth). Quota
is reported in the response body's `rate_limit` object, not HTTP headers —
an intentional deviation from the other two adapters, not an oversight.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


class SidelinedRecord(BaseModel):
    provider: str = "sportmonks"
    player_id: int | None = None
    category: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    coherent: bool
    rejection_reason: str | None = None


class LineupRecord(BaseModel):
    provider: str = "sportmonks"
    fixture_id: int | None = None
    player_id: int | None = None
    team_id: int | None = None
    jersey_number: int | None = None
    role: str
    coherent: bool
    rejection_reason: str | None = None


class SportmonksProvider(BaseProvider):
    provider_id = "sportmonks"
    display_name = "Sportmonks"
    trust_tier = TrustTier.OFFICIAL_AUTHENTICATED
    requires_key = True
    base_url = "https://api.sportmonks.com/v3/football"

    async def capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability(
                provider=self.provider_id,
                competition=competition,
                fixtures=True,
                standings=True,
                lineups=True,
                injuries=True,
                team_statistics=True,
                player_statistics=True,
                odds=True,
                notes=["subscription_gated_fields_reported_by_doctor", "provider_value_bets_excluded"],
            )
            for competition in ESPN_LEAGUE_SLUGS
        ]

    async def injuries(self, *, competition: str) -> ProviderResult:
        # `competition` is accepted for orchestrator-call-site compatibility;
        # the sidelined endpoint has no competition/league filter in the
        # subscribed API shape, so results are unfiltered by design.
        guard = self._guard("injuries")
        if guard is not None:
            return guard

        try:
            payload, _headers = await self._get_json(
                f"{self.base_url}/sidelined",
                headers={"Authorization": self.api_key},
            )
        except Exception as exc:
            return self._network_failure("injuries", exc)

        raw_items = payload.get("data") if isinstance(payload, dict) else None
        raw_items = raw_items if isinstance(raw_items, list) else []
        records = [self._normalize_sidelined(raw) for raw in raw_items]
        warnings = [f"rejected: {r.rejection_reason}" for r in records if not r.coherent]
        if records:
            warnings.append("unfiltered_by_competition")

        return ProviderResult(
            provider=self.provider_id,
            operation="injuries",
            status=ProviderStatus.VERIFIED if records else ProviderStatus.PARTIAL,
            trust_tier=self.trust_tier,
            records=[r.model_dump(mode="json") for r in records],
            quota=self._quota_from_payload(payload),
            warnings=warnings,
            raw_snapshot_id=stable_hash(payload),
        )

    async def lineups(self, *, fixture_id: Any) -> ProviderResult:
        guard = self._guard("lineups")
        if guard is not None:
            return guard
        if not fixture_id:
            return ProviderResult(
                provider=self.provider_id,
                operation="lineups",
                status=ProviderStatus.UNAVAILABLE,
                trust_tier=self.trust_tier,
                error_code="fixture_id_required",
            )

        try:
            payload, _headers = await self._get_json(
                f"{self.base_url}/fixtures/{fixture_id}",
                params={"include": "lineups"},
                headers={"Authorization": self.api_key},
            )
        except Exception as exc:
            return self._network_failure("lineups", exc)

        data = payload.get("data") if isinstance(payload, dict) else None
        lineups_block = data.get("lineups") if isinstance(data, dict) else None
        raw_entries = lineups_block.get("data") if isinstance(lineups_block, dict) else None
        if not isinstance(raw_entries, list):
            return ProviderResult(
                provider=self.provider_id,
                operation="lineups",
                status=ProviderStatus.PARTIAL,
                trust_tier=self.trust_tier,
                warnings=["no_lineup_data_in_response"],
                raw_snapshot_id=stable_hash(payload),
            )

        records = [self._normalize_lineup_entry(raw, fixture_id=fixture_id) for raw in raw_entries]

        return ProviderResult(
            provider=self.provider_id,
            operation="lineups",
            status=ProviderStatus.VERIFIED if records else ProviderStatus.PARTIAL,
            trust_tier=self.trust_tier,
            records=[r.model_dump(mode="json") for r in records],
            quota=self._quota_from_payload(payload),
            warnings=[f"rejected: {r.rejection_reason}" for r in records if not r.coherent],
            raw_snapshot_id=stable_hash(payload),
        )

    async def probe(self) -> ProviderStatus:
        """Cheap liveness probe: /leagues is the cheapest call valid on every plan.

        Live-verified 2026-07-04: bare /sidelined 404s in the subscribed API
        shape, so probing it could never verify a valid token.
        """
        try:
            await self._get_json(
                f"{self.base_url}/leagues",
                headers={"Authorization": self.api_key},
            )
            return ProviderStatus.VERIFIED
        except Exception as exc:  # pragma: no cover - network path
            return self._transport_status(exc)

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _guard(self, operation: str) -> ProviderResult | None:
        if not self.enabled or not self.configured:
            return ProviderResult(
                provider=self.provider_id,
                operation=operation,
                status=ProviderStatus.UNAVAILABLE,
                trust_tier=self.trust_tier,
                error_code="provider_disabled_or_unconfigured",
                warnings=["provider must be enabled and configured with a backend credential"],
            )
        return None

    def _network_failure(self, operation: str, exc: Exception) -> ProviderResult:
        return self._transport_failure_result(operation, exc)

    def _normalize_sidelined(self, raw: dict[str, Any]) -> SidelinedRecord:
        sideline = raw.get("sideline") if isinstance(raw, dict) else None
        if not isinstance(sideline, dict) or not raw.get("player_id"):
            return SidelinedRecord(coherent=False, rejection_reason="missing_field_player_id_or_sideline")
        return SidelinedRecord(
            player_id=raw.get("player_id"),
            category=sideline.get("category"),
            start_date=_parse_ts(sideline.get("start_date")),
            end_date=_parse_ts(sideline.get("end_date")),
            coherent=True,
        )

    def _normalize_lineup_entry(self, raw: dict[str, Any], *, fixture_id: Any) -> LineupRecord:
        if not isinstance(raw, dict) or not raw.get("player_id"):
            return LineupRecord(
                fixture_id=fixture_id, role="lineup", coherent=False, rejection_reason="missing_field_player_id"
            )
        raw_type = str(raw.get("type") or "lineup").lower()
        role = "bench" if raw_type in ("bench", "substitute") else "lineup"
        return LineupRecord(
            fixture_id=fixture_id,
            player_id=raw.get("player_id"),
            team_id=raw.get("team_id"),
            jersey_number=raw.get("jersey_number"),
            role=role,
            coherent=True,
        )

    def _quota_from_payload(self, payload: Any) -> ProviderQuota:
        rate_limit = payload.get("rate_limit") if isinstance(payload, dict) else None
        if not isinstance(rate_limit, dict):
            return ProviderQuota()
        resets_in = rate_limit.get("resets_in_seconds")
        reset_at = utc_now() + timedelta(seconds=resets_in) if isinstance(resets_in, (int, float)) else None
        return ProviderQuota(remaining=rate_limit.get("remaining"), reset_at=reset_at)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
