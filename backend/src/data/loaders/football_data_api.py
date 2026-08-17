"""Compatibility adapter over the canonical football-data.org provider.

This module intentionally owns no HTTP client. Production background sync must
reuse the lifespan-owned ``football_data_org`` provider so request pooling,
transport classification, Retry-After handling, circuit breaking, and durable
provider evidence all flow through one observable boundary.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ...core.config import settings
from ...providers.base import ProviderStatus
from ...providers.football_data_org import FootballDataOrgProvider

logger = logging.getLogger(__name__)


class FootballDataAPIError(RuntimeError):
    """Raised when canonical football-data.org acquisition yields no usable data."""


class FootballDataAPIClient:
    """Normalize canonical provider records for legacy fixture/settlement consumers.

    The class name is retained to keep the storage-domain adapter small and to
    avoid mixing provider record shapes into SQLAlchemy persistence code. It is
    no longer a network client: ``provider`` is the sole request authority.
    """

    TOP_COMPETITIONS = {
        "PL": "EPL",
        "PD": "La Liga",
        "BL1": "Bundesliga",
        "SA": "Serie A",
        "FL1": "Ligue 1",
        "DED": "Eredivisie",
        "CL": "UCL",
    }
    CANONICAL_BY_CODE = {
        "PL": "EPL",
        "PD": "LA_LIGA",
        "BL1": "BUNDESLIGA",
        "SA": "SERIE_A",
        "FL1": "LIGUE_1",
        "DED": "EREDIVISIE",
        "CL": "UCL",
    }

    def __init__(
        self,
        provider: FootballDataOrgProvider | None = None,
        api_key: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        # api_key/timeout_seconds remain accepted for source compatibility only.
        # Creating another credential-bearing HTTP client here would recreate
        # the production split SAB-14 is explicitly removing.
        if provider is None and not getattr(settings, "mock_mode", False):
            try:
                from ...providers.registry import get_runtime_provider

                runtime_provider = get_runtime_provider("football_data_org")
            except (KeyError, RuntimeError):
                runtime_provider = None
            if isinstance(runtime_provider, FootballDataOrgProvider):
                provider = runtime_provider
        self.provider = provider
        self.api_key = api_key
        self.timeout = timeout_seconds

    async def get_upcoming_matches(
        self,
        days_ahead: int = 7,
        limit: int = 20,
        league: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if getattr(settings, "mock_mode", False):
            return self._mock_matches(days_ahead=days_ahead, limit=limit, league=league)

        now = datetime.now(timezone.utc)
        return await self._fetch_competitions(
            competitions=self._resolve_competitions(league),
            date_from=now.date().isoformat(),
            date_to=(now + timedelta(days=max(days_ahead, 1))).date().isoformat(),
            status="SCHEDULED",
            limit=limit,
            settled=False,
        )

    async def get_recent_results(
        self,
        days_back: int = 3,
        limit: int = 20,
        league: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if getattr(settings, "mock_mode", False):
            return self._mock_results(days_back=days_back, limit=limit)

        now = datetime.now(timezone.utc)
        return await self._fetch_competitions(
            competitions=self._resolve_competitions(league),
            date_from=(now - timedelta(days=max(days_back, 1))).date().isoformat(),
            date_to=now.date().isoformat(),
            status="FINISHED",
            limit=limit,
            settled=True,
        )

    async def _fetch_competitions(
        self,
        *,
        competitions: List[str],
        date_from: str,
        date_to: str,
        status: str,
        limit: int,
        settled: bool,
    ) -> List[Dict[str, Any]]:
        """Fetch one request per competition through the injected provider.

        Partial progress is retained. A genuine RATE_LIMITED/CIRCUIT_OPEN state
        stops the loop because further requests in the same quota window cannot
        improve evidence; ordinary per-competition failures remain isolated.
        """
        provider = self.provider
        if provider is None:
            raise FootballDataAPIError(
                "canonical football-data.org provider is required outside mock mode"
            )

        normalized: List[Dict[str, Any]] = []
        failures: List[str] = []

        for index, competition_code in enumerate(competitions):
            canonical = self.CANONICAL_BY_CODE[competition_code]
            result = await provider.fixtures(
                competition=canonical,
                date_from=date_from,
                date_to=date_to,
                status=status,
                limit=limit,
            )

            if result.status in {ProviderStatus.RATE_LIMITED, ProviderStatus.CIRCUIT_OPEN}:
                failures.append(f"{competition_code}: {result.status.value.lower()}")
                logger.warning(
                    "football_data: %s at %s — keeping %d match(es) from %d competition(s)",
                    result.status.value.lower(),
                    competition_code,
                    len(normalized),
                    index,
                )
                break

            if result.status in {
                ProviderStatus.UNAVAILABLE,
                ProviderStatus.UNCONFIGURED,
                ProviderStatus.INVALID,
                ProviderStatus.CONFLICTING,
            }:
                failures.append(
                    f"{competition_code}: {result.error_code or result.status.value.lower()}"
                )
                logger.warning(
                    "football_data: %s unavailable: %s",
                    competition_code,
                    result.error_code or result.status.value,
                )
                continue

            for record in result.records:
                item = (
                    self._normalize_result(record)
                    if settled
                    else self._normalize_match(record, competition_code=competition_code)
                )
                if item is not None:
                    normalized.append(item)

        if failures and not normalized:
            raise FootballDataAPIError(
                f"Football-Data API returned no data ({'; '.join(failures)})"
            )

        normalized.sort(key=lambda item: item.get("match_date") or "")
        return normalized[:limit]

    def _resolve_competitions(self, league: Optional[str]) -> List[str]:
        if not league:
            return list(self.TOP_COMPETITIONS.keys())

        normalized = league.strip().lower().replace("-", "_").replace(" ", "_")
        reverse_map = {
            "epl": "PL",
            "premier_league": "PL",
            "la_liga": "PD",
            "laliga": "PD",
            "bundesliga": "BL1",
            "serie_a": "SA",
            "seriea": "SA",
            "ligue_1": "FL1",
            "ligue1": "FL1",
            "eredivisie": "DED",
            "ucl": "CL",
            "champions_league": "CL",
            "uefa_champions_league": "CL",
        }
        code = reverse_map.get(normalized)
        return [code] if code else list(self.TOP_COMPETITIONS.keys())

    def _normalize_match(
        self,
        record: Dict[str, Any],
        *,
        competition_code: str,
    ) -> Optional[Dict[str, Any]]:
        if not record.get("coherent"):
            return None
        event_id = record.get("provider_event_id")
        home = record.get("home_team")
        away = record.get("away_team")
        kickoff = record.get("kickoff_utc")
        if not event_id or not home or not away or not kickoff:
            return None
        return {
            "id": f"fd-{event_id}",
            "home_team": str(home),
            "away_team": str(away),
            "league": self.TOP_COMPETITIONS[competition_code],
            "match_date": str(kickoff),
            "match_round": record.get("match_round"),
            "venue": None,
            "status": "scheduled",
            "has_odds": False,
            "source": "football-data.org",
        }

    def _normalize_result(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not record.get("coherent"):
            return None
        event_id = record.get("provider_event_id")
        kickoff = record.get("kickoff_utc")
        home_score = record.get("home_score")
        away_score = record.get("away_score")
        if event_id is None or not kickoff or home_score is None or away_score is None:
            return None
        return {
            "id": f"fd-{event_id}",
            "match_date": str(kickoff),
            "home_score": home_score,
            "away_score": away_score,
            "status": "finished",
        }

    def _mock_results(self, days_back: int, limit: int) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        samples = [(2, 1), (0, 0), (1, 3)]
        result: List[Dict[str, Any]] = []
        for idx, (home_score, away_score) in enumerate(samples):
            kickoff = now - timedelta(days=idx + 1)
            if kickoff < now - timedelta(days=max(days_back, 1)):
                continue
            result.append(
                {
                    "id": f"mock-fd-{idx+1}",
                    "match_date": kickoff.isoformat(),
                    "home_score": home_score,
                    "away_score": away_score,
                    "status": "finished",
                }
            )
        return result[:limit]

    def _mock_matches(
        self,
        days_ahead: int,
        limit: int,
        league: Optional[str],
    ) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        samples = [
            ("Arsenal", "Chelsea", "EPL"),
            ("Real Madrid", "Valencia", "La Liga"),
            ("Bayern Munich", "Leverkusen", "Bundesliga"),
            ("Inter", "Roma", "Serie A"),
            ("PSG", "Lyon", "Ligue 1"),
            ("Ajax", "PSV", "Eredivisie"),
            ("Manchester City", "Bayern Munich", "UCL"),
        ]

        result: List[Dict[str, Any]] = []
        for idx, (home, away, lg) in enumerate(samples):
            if league and league.lower() not in lg.lower().replace(" ", ""):
                continue
            kickoff = now + timedelta(hours=idx * 8 + 2)
            if kickoff > now + timedelta(days=max(days_ahead, 1)):
                continue
            result.append(
                {
                    "id": f"mock-fd-{idx+1}",
                    "home_team": home,
                    "away_team": away,
                    "league": lg,
                    "match_date": kickoff.isoformat(),
                    "venue": None,
                    "status": "scheduled",
                    "has_odds": False,
                    "source": "mock",
                }
            )

        return result[:limit]
