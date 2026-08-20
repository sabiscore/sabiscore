"""football-data.org canonical fixture/standing provider.

Operational client: fixtures + standings via X-Auth-Token header auth.
All request-time football-data.org acquisition is routed through this provider
so the lifespan-owned HTTP pool, transport semantics, and durable evidence
instrumentation remain authoritative.
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

COMPETITIONS = {
    "EPL": "PL",
    "LA_LIGA": "PD",
    "SERIE_A": "SA",
    "BUNDESLIGA": "BL1",
    "LIGUE_1": "FL1",
    "EREDIVISIE": "DED",
    "UCL": "CL",
}


class FixtureRecord(BaseModel):
    provider: str = "football_data_org"
    provider_event_id: str
    competition: str
    home_team: str
    away_team: str
    home_team_id: int | None = None
    away_team_id: int | None = None
    kickoff_utc: datetime | None = None
    status: str
    season_id: int | None = None
    match_round: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    coherent: bool
    rejection_reason: str | None = None


class StandingsRecord(BaseModel):
    provider: str = "football_data_org"
    competition: str
    standings_type: str
    position: int | None = None
    team: str | None = None
    team_id: int | None = None
    played: int | None = None
    won: int | None = None
    draw: int | None = None
    lost: int | None = None
    points: int | None = None
    goals_for: int | None = None
    goals_against: int | None = None
    coherent: bool
    rejection_reason: str | None = None


def _fixture_request_context(
    *,
    competition: str,
    date_from: str | None,
    date_to: str | None,
    status: str | None,
) -> dict[str, str]:
    """Return only non-secret dimensions needed to interpret one match query."""
    context = {"competition": competition.upper()}
    if status:
        normalized_status = status.upper()
        context["match_status"] = normalized_status
        if normalized_status in {"SCHEDULED", "TIMED"}:
            context["query_intent"] = "UPCOMING"
        elif normalized_status == "FINISHED":
            context["query_intent"] = "RESULTS"
        else:
            context["query_intent"] = "MATCHES"
    if date_from:
        context["date_from"] = date_from
    if date_to:
        context["date_to"] = date_to
    return context


class FootballDataOrgProvider(BaseProvider):
    provider_id = "football_data_org"
    display_name = "football-data.org"
    trust_tier = TrustTier.OFFICIAL_AUTHENTICATED
    requires_key = True
    base_url = "https://api.football-data.org/v4"

    async def capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability(
                provider=self.provider_id,
                competition=competition,
                fixtures=True,
                standings=True,
                notes=["official_authenticated", "not_football_data_csv"],
            )
            for competition in COMPETITIONS
        ]

    async def fixtures(
        self,
        *,
        competition: str,
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> ProviderResult:
        """Fetch one competition's match window through the canonical gateway.

        Optional filters mirror the v4 endpoint parameters used by the fixture
        and settlement background jobs. Keeping the operation per competition
        preserves the historical seven-request tick and gives the registry one
        durable observation for each real upstream request. Request dimensions
        are retained as sanitized evidence so an empty UCL or FINISHED query is
        not confused with provider-wide availability.
        """
        canonical_competition = competition.upper()
        request_context = _fixture_request_context(
            competition=canonical_competition,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
        guard = self._guard("fixtures")
        if guard is not None:
            return guard.model_copy(update={"request_context": request_context})
        code = COMPETITIONS.get(canonical_competition)
        if code is None:
            result = self._unsupported_competition("fixtures", competition)
            return result.model_copy(update={"request_context": request_context})

        params: dict[str, Any] = {}
        if date_from is not None:
            params["dateFrom"] = date_from
        if date_to is not None:
            params["dateTo"] = date_to
        if status is not None:
            params["status"] = status
        if limit is not None:
            params["limit"] = int(limit)

        try:
            payload, headers = await self._get_json(
                f"{self.base_url}/competitions/{code}/matches",
                headers={"X-Auth-Token": self.api_key or ""},
                params=params or None,
            )
        except Exception as exc:
            result = self._network_failure("fixtures", exc)
            return result.model_copy(update={"request_context": request_context})

        raw_matches_any = payload.get("matches") if isinstance(payload, dict) else None
        raw_matches: list[dict[str, Any]] = raw_matches_any if isinstance(raw_matches_any, list) else []
        records = [
            self._normalize_match(raw=match, competition=canonical_competition)
            for match in raw_matches
        ]

        return ProviderResult(
            provider=self.provider_id,
            operation="fixtures",
            status=ProviderStatus.VERIFIED if records else ProviderStatus.PARTIAL,
            trust_tier=self.trust_tier,
            records=[record.model_dump(mode="json") for record in records],
            quota=self._quota_from_headers(headers),
            warnings=[
                f"rejected: {record.rejection_reason}"
                for record in records
                if not record.coherent
            ],
            raw_snapshot_id=stable_hash(payload),
            request_context=request_context,
        )

    async def standings(self, *, competition: str) -> ProviderResult:
        canonical_competition = competition.upper()
        request_context = {
            "competition": canonical_competition,
            "query_intent": "STANDINGS",
        }
        guard = self._guard("standings")
        if guard is not None:
            return guard.model_copy(update={"request_context": request_context})
        code = COMPETITIONS.get(canonical_competition)
        if code is None:
            result = self._unsupported_competition("standings", competition)
            return result.model_copy(update={"request_context": request_context})

        try:
            payload, headers = await self._get_json(
                f"{self.base_url}/competitions/{code}/standings",
                headers={"X-Auth-Token": self.api_key or ""},
            )
        except Exception as exc:
            result = self._network_failure("standings", exc)
            return result.model_copy(update={"request_context": request_context})

        raw_groups_any = payload.get("standings") if isinstance(payload, dict) else None
        raw_groups: list[dict[str, Any]] = raw_groups_any if isinstance(raw_groups_any, list) else []
        records: list[StandingsRecord] = []
        for group in raw_groups:
            if not isinstance(group, dict) or group.get("type") != "TOTAL":
                continue
            table = group.get("table")
            table = table if isinstance(table, list) else []
            for row in table:
                records.append(
                    self._normalize_standings_row(
                        raw=row,
                        competition=canonical_competition,
                        standings_type="TOTAL",
                    )
                )

        return ProviderResult(
            provider=self.provider_id,
            operation="standings",
            status=ProviderStatus.VERIFIED if records else ProviderStatus.PARTIAL,
            trust_tier=self.trust_tier,
            records=[r.model_dump(mode="json") for r in records],
            quota=self._quota_from_headers(headers),
            warnings=[f"rejected: {r.rejection_reason}" for r in records if not r.coherent],
            raw_snapshot_id=stable_hash(payload),
            request_context=request_context,
        )

    async def probe(self) -> ProviderStatus:
        """Cheap liveness probe: competition metadata only, no match list."""
        first_code = next(iter(COMPETITIONS.values()))
        try:
            await self._get_json(
                f"{self.base_url}/competitions/{first_code}",
                headers={"X-Auth-Token": self.api_key or ""},
            )
            return ProviderStatus.VERIFIED
        except Exception as exc:  # pragma: no cover - network path
            return self._transport_status(exc)

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
            warnings=[f"competition {competition!r} has no football-data.org mapping"],
        )

    def _network_failure(self, operation: str, exc: Exception) -> ProviderResult:
        return self._transport_failure_result(operation, exc)

    def _normalize_match(self, *, raw: dict[str, Any], competition: str) -> FixtureRecord:
        try:
            event_id = str(raw["id"])
            home = raw["homeTeam"]
            away = raw["awayTeam"]
            home_name = str(home.get("name") or home.get("shortName") or "")
            away_name = str(away.get("name") or away.get("shortName") or "")
            if not home_name or not away_name:
                raise ValueError("missing_team_name")
        except (KeyError, TypeError, ValueError):
            return FixtureRecord(
                provider_event_id=str(raw.get("id", "")),
                competition=competition,
                home_team="",
                away_team="",
                status="UNKNOWN",
                coherent=False,
                rejection_reason="missing_field_team_or_id",
            )

        raw_season = raw.get("season")
        season: dict[str, Any] = raw_season if isinstance(raw_season, dict) else {}
        score = raw.get("score") if isinstance(raw.get("score"), dict) else {}
        full_time = score.get("fullTime") if isinstance(score, dict) else {}
        full_time = full_time if isinstance(full_time, dict) else {}
        stage = raw.get("stage")
        matchday = raw.get("matchday")
        match_round = str(stage or matchday or "") or None

        return FixtureRecord(
            provider_event_id=event_id,
            competition=competition,
            home_team=home_name,
            away_team=away_name,
            home_team_id=home.get("id"),
            away_team_id=away.get("id"),
            kickoff_utc=_parse_ts(raw.get("utcDate")),
            status=str(raw.get("status") or "UNKNOWN").upper(),
            season_id=season.get("id"),
            match_round=match_round,
            home_score=_as_int(full_time.get("home")),
            away_score=_as_int(full_time.get("away")),
            coherent=True,
        )

    def _normalize_standings_row(
        self, *, raw: dict[str, Any], competition: str, standings_type: str
    ) -> StandingsRecord:
        try:
            position = raw["position"]
            team = raw["team"]
            points = raw["points"]
            team_name = str(team.get("name") or "")
            if not team_name:
                raise ValueError("missing_team_name")
        except (KeyError, TypeError, ValueError):
            return StandingsRecord(
                competition=competition,
                standings_type=standings_type,
                coherent=False,
                rejection_reason="missing_field_position_team_or_points",
            )
        return StandingsRecord(
            competition=competition,
            standings_type=standings_type,
            position=position,
            team=team_name,
            team_id=team.get("id"),
            played=raw.get("playedGames"),
            won=raw.get("won"),
            draw=raw.get("draw"),
            lost=raw.get("lost"),
            points=points,
            goals_for=raw.get("goalsFor"),
            goals_against=raw.get("goalsAgainst"),
            coherent=True,
        )

    def _quota_from_headers(self, headers: Any) -> ProviderQuota:
        from ..core.config import settings

        remaining_minute = headers.get("X-Requests-Available-Minute") if headers else None
        reset_header = headers.get("X-RequestCounter-Reset") if headers else None
        reset_at = None
        if reset_header:
            try:
                # football-data.org defines X-RequestCounter-Reset as delta
                # seconds until the request counter resets, not a Unix epoch.
                reset_seconds = int(reset_header)
                if reset_seconds >= 0:
                    reset_at = utc_now() + timedelta(seconds=reset_seconds)
            except (TypeError, ValueError, OverflowError):
                pass
        return ProviderQuota(
            limit=settings.football_data_daily_request_limit,
            remaining=(
                int(remaining_minute)
                if remaining_minute and str(remaining_minute).isdigit()
                else None
            ),
            reset_at=reset_at,
        )


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
