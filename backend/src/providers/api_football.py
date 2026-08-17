"""API-Football authenticated enrichment provider.

Operational client: injuries, lineups, teams, and team_statistics via
x-apisports-key header auth. team_statistics() requires a numeric API-Football
team_id; the orchestrator resolves one from the fixture's home/away team names
via teams() + reconciliation.reconcile_team() before calling it (see
orchestrator._resolve_team_statistics). Provider prediction/odds endpoints are
intentionally never called — SabiScore excludes provider predictions from
its own model.
"""

from __future__ import annotations

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
)
from .espn import ESPN_LEAGUE_SLUGS

_LEAGUE_IDS: dict[str, int] = {
    "EPL": 39,
    "LA_LIGA": 140,
    "SERIE_A": 135,
    "BUNDESLIGA": 78,
    "LIGUE_1": 61,
    "EREDIVISIE": 88,   # Dutch Eredivisie (all comps available on free plan)
    "UCL": 2,           # UEFA Champions League
}


def _current_season() -> int:
    """API-Football seasons are keyed by the year the season starts (Aug-Jul)."""
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1


class InjuryRecord(BaseModel):
    provider: str = "api_football"
    player_id: int | None = None
    player_name: str
    team_id: int | None = None
    team_name: str
    fixture_id: int | None = None
    injury_type: str | None = None
    reason: str | None = None
    coherent: bool
    rejection_reason: str | None = None


class LineupRecord(BaseModel):
    provider: str = "api_football"
    fixture_id: int | None = None
    team_id: int | None = None
    team_name: str
    formation: str | None = None
    player_id: int | None = None
    player_name: str
    role: str
    coherent: bool
    rejection_reason: str | None = None


class TeamRecord(BaseModel):
    provider: str = "api_football"
    team_id: int | None = None
    name: str
    country: str | None = None
    coherent: bool
    rejection_reason: str | None = None


class TeamStatisticsRecord(BaseModel):
    provider: str = "api_football"
    team_id: int | None = None
    team_name: str
    played: int | None = None
    wins: int | None = None
    draws: int | None = None
    losses: int | None = None
    goals_for: int | None = None
    goals_against: int | None = None
    form: str | None = None
    clean_sheets: int | None = None
    coherent: bool
    rejection_reason: str | None = None


def _dig(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


class APIFootballProvider(BaseProvider):
    provider_id = "api_football"
    display_name = "API-Football"
    trust_tier = TrustTier.OFFICIAL_AUTHENTICATED
    requires_key = True
    base_url = "https://v3.football.api-sports.io"

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
                notes=["provider_predictions_excluded_from_sabiscore_model"],
            )
            for competition in ESPN_LEAGUE_SLUGS
        ]

    async def injuries(self, *, competition: str) -> ProviderResult:
        guard = self._guard("injuries")
        if guard is not None:
            return guard
        league_id = _LEAGUE_IDS.get(competition.upper())
        if league_id is None:
            return self._unsupported_competition("injuries", competition)

        try:
            payload, headers = await self._get_json(
                f"{self.base_url}/injuries",
                headers={"x-apisports-key": self.api_key or ""},
                params={"league": league_id, "season": _current_season()},
            )
        except Exception as exc:
            return self._network_failure("injuries", exc)

        logical_error = self._logical_error("injuries", payload)
        if logical_error is not None:
            return logical_error

        raw_items = payload.get("response") if isinstance(payload, dict) else None
        raw_items = raw_items if isinstance(raw_items, list) else []
        records = [self._normalize_injury(raw) for raw in raw_items]

        return ProviderResult(
            provider=self.provider_id,
            operation="injuries",
            status=ProviderStatus.VERIFIED if records else ProviderStatus.PARTIAL,
            trust_tier=self.trust_tier,
            records=[r.model_dump(mode="json") for r in records],
            quota=self._quota_from_headers(headers),
            warnings=[f"rejected: {r.rejection_reason}" for r in records if not r.coherent],
            raw_snapshot_id=stable_hash(payload),
        )

    async def lineups(self, *, fixture_id: Any, competition: str | None = None) -> ProviderResult:
        # `competition` is accepted-but-unused: the orchestrator's
        # PREMATCH_ENRICHED call site passes it, but /fixtures/lineups only
        # needs the fixture id.
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
            payload, headers = await self._get_json(
                f"{self.base_url}/fixtures/lineups",
                headers={"x-apisports-key": self.api_key or ""},
                params={"fixture": fixture_id},
            )
        except Exception as exc:
            return self._network_failure("lineups", exc)

        logical_error = self._logical_error("lineups", payload)
        if logical_error is not None:
            return logical_error

        raw_teams = payload.get("response") if isinstance(payload, dict) else None
        raw_teams = raw_teams if isinstance(raw_teams, list) else []
        records: list[LineupRecord] = []
        for team_entry in raw_teams:
            records.extend(self._normalize_lineup_team(team_entry, fixture_id=fixture_id))

        return ProviderResult(
            provider=self.provider_id,
            operation="lineups",
            status=ProviderStatus.VERIFIED if records else ProviderStatus.PARTIAL,
            trust_tier=self.trust_tier,
            records=[r.model_dump(mode="json") for r in records],
            quota=self._quota_from_headers(headers),
            warnings=[f"rejected: {r.rejection_reason}" for r in records if not r.coherent],
            raw_snapshot_id=stable_hash(payload),
        )

    async def teams(self, *, competition: str) -> ProviderResult:
        """List teams for a competition's current season — used by the
        orchestrator to resolve a fixture's home/away team name to a numeric
        API-Football team_id via reconciliation.reconcile_team() before
        calling team_statistics()."""
        guard = self._guard("teams")
        if guard is not None:
            return guard
        league_id = _LEAGUE_IDS.get(competition.upper())
        if league_id is None:
            return self._unsupported_competition("teams", competition)

        try:
            payload, headers = await self._get_json(
                f"{self.base_url}/teams",
                headers={"x-apisports-key": self.api_key or ""},
                params={"league": league_id, "season": _current_season()},
            )
        except Exception as exc:
            return self._network_failure("teams", exc)

        logical_error = self._logical_error("teams", payload)
        if logical_error is not None:
            return logical_error

        raw_items = payload.get("response") if isinstance(payload, dict) else None
        raw_items = raw_items if isinstance(raw_items, list) else []
        records = [self._normalize_team(raw) for raw in raw_items]

        return ProviderResult(
            provider=self.provider_id,
            operation="teams",
            status=ProviderStatus.VERIFIED if records else ProviderStatus.PARTIAL,
            trust_tier=self.trust_tier,
            records=[r.model_dump(mode="json") for r in records],
            quota=self._quota_from_headers(headers),
            warnings=[f"rejected: {r.rejection_reason}" for r in records if not r.coherent],
            raw_snapshot_id=stable_hash(payload),
        )

    async def team_statistics(self, *, team_id: int | None, competition: str) -> ProviderResult:
        guard = self._guard("team_statistics")
        if guard is not None:
            return guard
        if not team_id:
            return ProviderResult(
                provider=self.provider_id,
                operation="team_statistics",
                status=ProviderStatus.PARTIAL,
                trust_tier=self.trust_tier,
                warnings=["team_id_unresolved"],
                error_code="team_id_required",
            )
        league_id = _LEAGUE_IDS.get(competition.upper())
        if league_id is None:
            return self._unsupported_competition("team_statistics", competition)

        try:
            payload, headers = await self._get_json(
                f"{self.base_url}/teams/statistics",
                headers={"x-apisports-key": self.api_key or ""},
                params={"league": league_id, "season": _current_season(), "team": team_id},
            )
        except Exception as exc:
            return self._network_failure("team_statistics", exc)

        logical_error = self._logical_error("team_statistics", payload)
        if logical_error is not None:
            return logical_error

        record = self._normalize_team_statistics(payload.get("response"), team_id=team_id)

        return ProviderResult(
            provider=self.provider_id,
            operation="team_statistics",
            status=ProviderStatus.VERIFIED if record.coherent else ProviderStatus.PARTIAL,
            trust_tier=self.trust_tier,
            records=[record.model_dump(mode="json")],
            quota=self._quota_from_headers(headers),
            warnings=[] if record.coherent else [f"rejected: {record.rejection_reason}"],
            raw_snapshot_id=stable_hash(payload),
        )

    async def probe(self) -> ProviderStatus:
        """Cheap liveness probe: account/quota status endpoint."""
        try:
            await self._get_json(
                f"{self.base_url}/status",
                headers={"x-apisports-key": self.api_key or ""},
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

    def _unsupported_competition(self, operation: str, competition: str) -> ProviderResult:
        return ProviderResult(
            provider=self.provider_id,
            operation=operation,
            status=ProviderStatus.UNAVAILABLE,
            trust_tier=self.trust_tier,
            error_code="unsupported_competition",
            warnings=[f"competition {competition!r} has no API-Football league mapping"],
        )

    def _network_failure(self, operation: str, exc: Exception) -> ProviderResult:
        return self._transport_failure_result(operation, exc)

    def _logical_error(self, operation: str, payload: Any) -> ProviderResult | None:
        """API-Football returns HTTP 200 with a populated `errors` field on logical failures."""
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            return ProviderResult(
                provider=self.provider_id,
                operation=operation,
                status=ProviderStatus.UNAVAILABLE,
                trust_tier=self.trust_tier,
                error_code="api_logical_error",
                warnings=[str(errors)],
            )
        return None

    def _normalize_injury(self, raw: dict[str, Any]) -> InjuryRecord:
        try:
            player = raw["player"]
            team = raw["team"]
            player_name = str(player.get("name") or "")
            team_name = str(team.get("name") or "")
            if not player_name or not team_name:
                raise ValueError("missing_name")
        except (KeyError, TypeError, ValueError):
            return InjuryRecord(
                player_name="",
                team_name="",
                coherent=False,
                rejection_reason="missing_field_player_or_team",
            )
        raw_fixture = raw.get("fixture")
        fixture: dict[str, Any] = raw_fixture if isinstance(raw_fixture, dict) else {}
        return InjuryRecord(
            player_id=player.get("id"),
            player_name=player_name,
            team_id=team.get("id"),
            team_name=team_name,
            fixture_id=fixture.get("id"),
            injury_type=raw.get("type"),
            reason=raw.get("reason") or (player.get("reason") if isinstance(player, dict) else None),
            coherent=True,
        )

    def _normalize_lineup_team(self, raw: dict[str, Any], *, fixture_id: Any) -> list[LineupRecord]:
        team = raw.get("team") if isinstance(raw, dict) else None
        if not isinstance(team, dict) or not team.get("name"):
            return [
                LineupRecord(
                    fixture_id=fixture_id,
                    team_name="",
                    player_name="",
                    role="starting",
                    coherent=False,
                    rejection_reason="missing_field_team",
                )
            ]
        team_name = str(team.get("name") or "")
        team_id = team.get("id")
        formation = raw.get("formation")
        records: list[LineupRecord] = []
        for entry in raw.get("startXI") or []:
            records.append(
                self._normalize_lineup_player(
                    entry, fixture_id=fixture_id, team_id=team_id, team_name=team_name,
                    formation=formation, role="starting",
                )
            )
        for entry in raw.get("substitutes") or []:
            records.append(
                self._normalize_lineup_player(
                    entry, fixture_id=fixture_id, team_id=team_id, team_name=team_name,
                    formation=formation, role="substitute",
                )
            )
        return records

    def _normalize_lineup_player(
        self, entry: dict[str, Any], *, fixture_id: Any, team_id: Any, team_name: str, formation: Any, role: str
    ) -> LineupRecord:
        player = entry.get("player") if isinstance(entry, dict) else None
        player_name = str(player.get("name") or "") if isinstance(player, dict) else ""
        if not player_name:
            return LineupRecord(
                fixture_id=fixture_id,
                team_id=team_id,
                team_name=team_name,
                formation=formation,
                player_name="",
                role=role,
                coherent=False,
                rejection_reason="missing_field_player",
            )
        assert isinstance(player, dict)  # guaranteed by the player_name check above
        return LineupRecord(
            fixture_id=fixture_id,
            team_id=team_id,
            team_name=team_name,
            formation=formation,
            player_id=player.get("id"),
            player_name=player_name,
            role=role,
            coherent=True,
        )

    def _normalize_team(self, raw: dict[str, Any]) -> TeamRecord:
        team = raw.get("team") if isinstance(raw, dict) else None
        if not isinstance(team, dict) or not team.get("name"):
            return TeamRecord(name="", coherent=False, rejection_reason="missing_field_team")
        return TeamRecord(
            team_id=team.get("id"),
            name=str(team["name"]),
            country=team.get("country"),
            coherent=True,
        )

    def _normalize_team_statistics(self, raw: Any, *, team_id: int) -> TeamStatisticsRecord:
        if not isinstance(raw, dict):
            return TeamStatisticsRecord(
                team_id=team_id, team_name="", coherent=False, rejection_reason="empty_response",
            )
        team = raw.get("team")
        team_name = str(team.get("name") or "") if isinstance(team, dict) else ""
        if not team_name:
            return TeamStatisticsRecord(
                team_id=team_id, team_name="", coherent=False, rejection_reason="missing_field_team",
            )
        fixtures = raw.get("fixtures")
        goals = raw.get("goals")
        clean_sheet = raw.get("clean_sheet")
        return TeamStatisticsRecord(
            team_id=team_id,
            team_name=team_name,
            played=_dig(fixtures, "played", "total"),
            wins=_dig(fixtures, "wins", "total"),
            draws=_dig(fixtures, "draws", "total"),
            # API-Football's own schema spells this field "loses" (not "losses").
            losses=_dig(fixtures, "loses", "total"),
            goals_for=_dig(goals, "for", "total", "total"),
            goals_against=_dig(goals, "against", "total", "total"),
            form=raw.get("form"),
            clean_sheets=_dig(clean_sheet, "total"),
            coherent=True,
        )

    def _quota_from_headers(self, headers: Any) -> ProviderQuota:
        # Daily remaining from API response headers; daily limit from config as override.
        from ..core.config import settings

        remaining = headers.get("x-ratelimit-requests-remaining") if headers else None
        limit_header = headers.get("x-ratelimit-requests-limit") if headers else None
        limit = settings.api_football_daily_request_limit or (
            int(limit_header) if limit_header and str(limit_header).isdigit() else None
        )
        return ProviderQuota(
            remaining=int(remaining) if remaining and str(remaining).isdigit() else None,
            limit=limit,
        )
