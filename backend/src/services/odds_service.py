"""Odds compatibility service backed by the provider gateway."""

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.cache import cache_manager
from ..core.config import settings
from ..core.league_policy import LeaguePolicyUnavailableError, canonical_league_id
from ..core.redaction import redact_text
from ..db.models import Odds
from ..monitoring.metrics import metrics_collector
from ..providers.base import ProviderStatus
from ..providers.the_odds_api import TheOddsAPIProvider

logger = logging.getLogger(__name__)


class OddsService:
    """Fetch live odds through the canonical provider gateway."""
    DEFAULT_ODDS = {"source": "unavailable", "reason": "odds_not_verified"}

    def __init__(
        self,
        cache_backend: Any = None,
        provider: TheOddsAPIProvider | None = None,
    ) -> None:
        self.cache = cache_backend or cache_manager
        self.provider = provider or TheOddsAPIProvider(
            api_key=settings.the_odds_api_key,
            enabled=settings.enable_the_odds_api_provider,
            live_tests=settings.provider_live_tests,
        )

    async def close(self) -> None:
        return None

    async def fetch_live_odds(
        self,
        competition: str = "EPL",
        regions: str = "uk,eu",
        markets: str = "h2h",
    ) -> List[Dict[str, Any]]:
        """
        Fetch live odds from The Odds API.

        Args:
            competition: Canonical SabiScore competition code (e.g. "EPL",
                "LA_LIGA"). The provider owns the competition -> Odds API sport
                key mapping; this service must not duplicate it.
            regions: Comma-separated regions (uk, eu, us, au)
            markets: Comma-separated markets (h2h, spreads, totals)

        Returns:
            List of match odds dictionaries
        """
        cache_key = f"live_odds:{competition}:{regions}:{markets}"
        started_at = time.perf_counter()
        cached = self.cache.get(cache_key)
        if cached:
            logger.info("Cache hit for live odds: %s", competition)
            metrics_collector.record_provider_outcome(
                provider="the_odds_api",
                outcome="cache_hit",
                duration_ms=(time.perf_counter() - started_at) * 1000,
                cache_tier="shared",
                circuit_state=(
                    "open"
                    if getattr(getattr(self.provider, "breaker", None), "open", False)
                    else "closed"
                ),
            )
            return cached

        result = await self.provider.odds(
            competition=competition, regions=regions, markets=markets
        )
        schema_rejected = "schema" in str(result.error_code or "").casefold()
        metrics_collector.record_provider_outcome(
            provider=result.provider,
            outcome=result.status.value,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            cache_tier="none",
            circuit_state=(
                "open"
                if getattr(getattr(self.provider, "breaker", None), "open", False)
                else "closed"
            ),
            schema_rejected=schema_rejected,
        )
        if result.status is not ProviderStatus.VERIFIED:
            logger.warning(
                "Odds provider unavailable provider=%s status=%s error=%s",
                result.provider,
                result.status.value,
                result.error_code,
            )
            return []

        self.cache.set(cache_key, result.records, ttl=120)
        return result.records

    async def get_match_odds(
        self,
        home_team: str,
        away_team: str,
        league: str,
    ) -> Dict[str, Any]:
        """
        Get odds for a specific match by team names.
        
        Args:
            home_team: Home team name
            away_team: Away team name
            league: League identifier
            
        Returns:
            Dictionary with home_win, draw, away_win odds
        """
        cache_key = f"match_odds:{league}:{home_team}:{away_team}".lower().replace(" ", "_")
        cached = self.cache.get(cache_key)
        if cached:
            if isinstance(cached, dict):
                cached.setdefault("source", "cache")
                cached.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            return cached

        try:
            competition = canonical_league_id(league)
        except LeaguePolicyUnavailableError:
            logger.warning("Unsupported league for odds lookup: %r", league)
            return {
                "source": "unavailable",
                "reason": "unsupported_competition",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "bookmaker": None,
            }

        live_odds = await self.fetch_live_odds(competition=competition)

        home_normalized = self._team_key(home_team)
        away_normalized = self._team_key(away_team)

        for record in live_odds:
            if not record.get("coherent") or not record.get("executable"):
                continue
            if self._team_key(record.get("home_team", "")) != home_normalized:
                continue
            if self._team_key(record.get("away_team", "")) != away_normalized:
                continue
            odds = self._coherent_snapshot(record)
            if odds is not None:
                self.cache.set(cache_key, odds, ttl=300)
                return odds

        logger.warning("No verified live odds found for %s vs %s", home_team, away_team)
        unavailable = {
            "source": "unavailable",
            "reason": "coherent_1x2_market_snapshot_not_found",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bookmaker": None,
        }
        self.cache.set(cache_key, unavailable, ttl=60)
        return unavailable

    async def store_odds_snapshot(
        self,
        db: AsyncSession,
        match_id: str,
        odds: Dict[str, float],
        bookmaker: str = "aggregated",
    ) -> None:
        """Store odds snapshot in database for historical tracking."""
        try:
            odds_record = Odds(
                match_id=match_id,
                bookmaker=bookmaker,
                home_win=odds.get("home_win"),
                draw=odds.get("draw"),
                away_win=odds.get("away_win"),
                timestamp=datetime.now(timezone.utc),
            )
            db.add(odds_record)
            await db.commit()
            logger.info("Stored odds snapshot for match %s", match_id)
        except Exception as exc:
            logger.error("Failed to store odds snapshot: %s", redact_text(exc))
            await db.rollback()

    @staticmethod
    def _team_key(value: object) -> str:
        key = re.sub(r"[^a-z0-9]", "", str(value).casefold())
        for suffix in ("footballclub", "soccerclub", "afc", "fc"):
            if key.endswith(suffix) and len(key) > len(suffix) + 2:
                return key[: -len(suffix)]
        return key

    @staticmethod
    def _coherent_snapshot(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            home = float(record["home_odds"])
            draw = float(record["draw_odds"])
            away = float(record["away_odds"])
        except (KeyError, TypeError, ValueError):
            return None
        if any(value <= 1.0 for value in (home, draw, away)):
            return None
        return {
            "home_win": home,
            "draw": draw,
            "away_win": away,
            "source": str(record.get("provider") or "the_odds_api"),
            "timestamp": record.get("captured_at"),
            "bookmaker": record.get("bookmaker"),
            "provider_event_id": record.get("provider_event_id"),
            "bookmaker_last_update": record.get("bookmaker_last_update"),
        }

    async def get_odds_movement(
        self,
        db: AsyncSession,
        match_id: str,
        hours: int = 24,
    ) -> List[Dict[str, Any]]:
        """
        Get historical odds movement for a match.
        
        Args:
            db: Database session
            match_id: Match identifier
            hours: Hours of history to retrieve
            
        Returns:
            List of odds snapshots with timestamps
        """
        try:
            from sqlalchemy import select

            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            query = (
                select(Odds)
                .where(Odds.match_id == match_id)
                .where(Odds.timestamp >= cutoff)
                .order_by(Odds.timestamp.desc())
            )

            result = await db.execute(query)
            odds_records = result.scalars().all()

            movement = []
            for record in odds_records:
                movement.append({
                    "timestamp": record.timestamp.isoformat(),
                    "bookmaker": record.bookmaker,
                    "home_win": record.home_win,
                    "draw": record.draw,
                    "away_win": record.away_win,
                })

            return movement

        except Exception as exc:
            logger.error("Failed to retrieve odds movement: %s", redact_text(exc))
            return []


# Global instance (lazily initialized on first access)
odds_service = None


def get_odds_service(request: Request) -> OddsService:
    """Return the lifespan-scoped odds service for production requests."""

    return request.app.state.odds_service
