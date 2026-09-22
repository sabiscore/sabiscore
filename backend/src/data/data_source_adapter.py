"""
Data Source Adapter Layer for SabiScore
========================================

This module implements the Adapter Pattern for seamless data source integration.
It allows scraping implementations to look like API calls, preserving existing
code interfaces while enabling ethical web scraping for data acquisition.

Design Principles:
- Drop-in replacement for API connectors
- Consistent interface via DataSourceAdapter ABC
- Factory pattern for runtime source switching
- Redis caching for performance optimization
- Ethical scraping with rate limits and delays
"""

import json
import os
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from ..core.config import settings

logger = logging.getLogger(__name__)


class DataSourceAdapter(ABC):
    """
    Abstract base class defining the interface for data sources.

    All data sources (APIs, scrapers) must implement this interface
    to ensure seamless integration with existing pipelines.
    """

    @abstractmethod
    async def fetch_match_odds(self, match_id: str) -> Dict[str, Any]:
        """
        Fetch current odds for a specific match.

        Args:
            match_id: Unique identifier for the match

        Returns:
            Dict containing:
            - match_id: str
            - timestamp: ISO format datetime
            - bookmaker: str (e.g., 'Pinnacle')
            - odds: Dict[str, float] with 'home', 'draw', 'away' keys
            - closing_line: bool
            - source: str ('api' or 'scraped')
        """
        pass

    @abstractmethod
    async def fetch_team_stats(self, team_name: str) -> Dict[str, Any]:
        """
        Fetch team statistics including form, player data, etc.

        Args:
            team_name: Name of the team

        Returns:
            Dict containing:
            - team_name: str
            - timestamp: ISO format datetime
            - stats: Dict with possession_avg, player_ratings, injuries
            - source: str ('api' or 'scraped')
        """
        pass

    @abstractmethod
    def fetch_historical_matches(self, league: str, season: str) -> pd.DataFrame:
        """
        Fetch historical match data for a league/season.

        Args:
            league: League code (e.g., 'E0' for EPL)
            season: Season code (e.g., '2526' for 2025/26)

        Returns:
            DataFrame with columns matching existing schema:
            - Date, HomeTeam, AwayTeam
            - FTHG, FTAG (full-time goals)
            - PSH, PSD, PSA (Pinnacle odds)
        """
        pass

    @abstractmethod
    async def fetch_live_scores(self, league: str) -> List[Dict[str, Any]]:
        """
        Fetch live match scores for a league.

        Args:
            league: League code

        Returns:
            List of dicts with match details and live scores
        """
        pass

    def get_source_name(self) -> str:
        """Return the name of this data source for logging/monitoring."""
        return self.__class__.__name__


class ScraperAdapter(DataSourceAdapter):
    """
    Scraping implementation of DataSourceAdapter.

    Makes scrapers look like API calls to preserve existing code interface.
    Implements ethical scraping practices:
    - Rate limiting (configurable delays)
    - User-agent rotation
    - Circuit breaker pattern
    - Respectful caching
    """

    def __init__(self):
        """Initialize scraper adapter with all required scrapers."""
        # Import scrapers lazily to avoid circular imports
        from ..data.scrapers import (
            FlashscoreScraper,
            OddsPortalScraper,
            TransfermarktScraper,
        )

        self.flashscore = FlashscoreScraper()
        self.oddsportal = OddsPortalScraper()
        self.transfermarkt = TransfermarktScraper()

        # Optional scrapers - initialize if available
        self._football_data = None
        # Note: WhoScored removed due to 403 blocks; form features rebuilt from Soccerway + Understat

        # Initialize cache connection
        self._cache = None
        self._init_cache()

        logger.info("ScraperAdapter initialized with ethical scraping config")

    def _init_cache(self) -> None:
        """Initialize Redis cache connection."""
        try:
            import redis

            self._cache = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
            )
            # Test connection
            self._cache.ping()
            logger.info("ScraperAdapter cache connected")
        except Exception as e:
            logger.warning(f"Cache connection failed, operating without cache: {e}")
            self._cache = None

    def _get_cached(self, key: str) -> Optional[str]:
        """Get value from cache with fallback."""
        if self._cache is None:
            return None
        try:
            return self._cache.get(key)
        except Exception as e:
            logger.debug(f"Cache get failed for {key}: {e}")
            return None

    def _set_cached(self, key: str, value: str, ttl: int = 60) -> None:
        """Set value in cache with TTL."""
        if self._cache is None:
            return
        try:
            self._cache.setex(key, ttl, value)
        except Exception as e:
            logger.debug(f"Cache set failed for {key}: {e}")

    async def fetch_match_odds(self, match_id: str) -> Dict[str, Any]:
        """
        Fetch match odds from scrapers.

        Returns SAME structure as old API for backward compatibility.
        """
        cache_key = f"sabiscore:odds:{match_id}"
        cached = self._get_cached(cache_key)

        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                pass

        # Try Flashscore first, then OddsPortal as fallback
        odds = None
        source = "flashscore"

        try:
            odds = await self._fetch_flashscore_odds(match_id)
        except Exception as e:
            logger.warning(f"Flashscore odds fetch failed: {e}")
            source = "oddsportal"
            try:
                odds = await self._fetch_oddsportal_odds(match_id)
            except Exception as e2:
                logger.warning(f"OddsPortal odds fetch failed: {e2}")
                # Return default odds structure
                odds = {"home_odds": 2.0, "draw_odds": 3.2, "away_odds": 3.5}

        # Standardize to expected format
        result = {
            "match_id": match_id,
            "timestamp": datetime.now().isoformat(),
            "bookmaker": "Pinnacle",
            "odds": {
                "home": odds.get("home_odds", 2.0),
                "draw": odds.get("draw_odds", 3.2),
                "away": odds.get("away_odds", 3.5),
            },
            "closing_line": odds.get("is_closing", False),
            "source": f"scraped:{source}",
        }

        # Cache for 30 seconds (odds change frequently)
        self._set_cached(cache_key, json.dumps(result), ttl=30)

        return result

    async def _fetch_flashscore_odds(self, match_id: str) -> Dict[str, float]:
        """Fetch odds from Flashscore scraper."""
        # Use existing Flashscore scraper
        data = self.flashscore.get_match_data(match_id)
        return {
            "home_odds": data.get("odds", {}).get("home", 2.0),
            "draw_odds": data.get("odds", {}).get("draw", 3.2),
            "away_odds": data.get("odds", {}).get("away", 3.5),
            "is_closing": data.get("status") == "about_to_start",
        }

    async def _fetch_oddsportal_odds(self, match_id: str) -> Dict[str, float]:
        """Fetch odds from OddsPortal scraper."""
        data = self.oddsportal.get_match_odds(match_id)
        return {
            "home_odds": data.get("pinnacle", {}).get("home", 2.0),
            "draw_odds": data.get("pinnacle", {}).get("draw", 3.2),
            "away_odds": data.get("pinnacle", {}).get("away", 3.5),
            "is_closing": True,  # OddsPortal data is usually closing line
        }

    async def fetch_team_stats(self, team_name: str) -> Dict[str, Any]:
        """
        Fetch team stats for feature engineering.

        Combines data from multiple sources for comprehensive stats.
        """
        cache_key = f"sabiscore:stats:{team_name.lower().replace(' ', '_')}"
        cached = self._get_cached(cache_key)

        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                pass

        # Fetch from Transfermarkt for squad/injury data
        stats = {}
        try:
            squad_data = self.transfermarkt.get_team_squad(team_name)
            stats["squad_value"] = squad_data.get("total_value", 0)
            stats["injuries"] = squad_data.get("injuries", [])
            stats["missing_value"] = squad_data.get("missing_value", 0)
        except Exception as e:
            logger.warning(f"Transfermarkt stats fetch failed for {team_name}: {e}")
            stats["squad_value"] = 100  # Default in millions
            stats["injuries"] = []
            stats["missing_value"] = 0

        result = {
            "team_name": team_name,
            "timestamp": datetime.now().isoformat(),
            "stats": {
                "possession_avg": 50.0,  # Default, can be enriched
                "player_ratings": {},
                "injuries": stats.get("injuries", []),
                "squad_value": stats.get("squad_value", 100),
                "missing_value": stats.get("missing_value", 0),
            },
            "source": "scraped:transfermarkt",
        }

        # Cache for 5 minutes (stats change less frequently)
        self._set_cached(cache_key, json.dumps(result), ttl=300)

        return result

    def fetch_historical_matches(self, league: str, season: str) -> pd.DataFrame:
        """
        Fetch historical match data from football-data.co.uk.

        Returns DataFrame matching existing schema for seamless integration.
        """
        cache_key = f"sabiscore:historical:{league}:{season}"
        cached = self._get_cached(cache_key)

        if cached:
            try:
                return pd.read_json(cached)
            except Exception:
                pass

        # Initialize FootballDataScraper lazily
        if self._football_data is None:
            try:
                from .scrapers.football_data_scraper import FootballDataScraper

                self._football_data = FootballDataScraper()
            except ImportError:
                logger.warning(
                    "FootballDataScraper not available, using empty DataFrame"
                )
                return pd.DataFrame()

        try:
            df = self._football_data.download_season_data(league, season)

            # Rename columns to match existing expectations
            column_mapping = {
                "PSH": "pinnacle_home_odds",
                "PSD": "pinnacle_draw_odds",
                "PSA": "pinnacle_away_odds",
                "FTHG": "full_time_home_goals",
                "FTAG": "full_time_away_goals",
            }

            df = df.rename(columns=column_mapping)

            # Add metadata
            df["data_source"] = "football-data.co.uk"
            df["scrape_timestamp"] = datetime.now().isoformat()

            # Cache for 24 hours (historical data doesn't change)
            self._set_cached(cache_key, df.to_json(), ttl=86400)

            return df

        except Exception as e:
            logger.error(f"Failed to fetch historical data: {e}")
            return pd.DataFrame()

    async def fetch_live_scores(self, league: str) -> List[Dict[str, Any]]:
        """Fetch live scores from Flashscore."""
        cache_key = f"sabiscore:live:{league}"
        cached = self._get_cached(cache_key)

        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                pass

        try:
            scores = self.flashscore.get_live_scores(league)

            # Cache for 10 seconds (live scores change rapidly)
            self._set_cached(cache_key, json.dumps(scores), ttl=10)

            return scores
        except Exception as e:
            logger.warning(f"Live scores fetch failed: {e}")
            return []


class APIAdapter(DataSourceAdapter):
    """
    API implementation of DataSourceAdapter.

    Uses official APIs when available (currently limited/unavailable).
    Preserved for future API integration.
    """

    def __init__(self):
        """Initialize API adapter with available connectors."""
        self._initialized = False
        logger.info("APIAdapter initialized (limited functionality)")

    async def fetch_match_odds(self, match_id: str) -> Dict[str, Any]:
        """Fetch odds via API (not currently available)."""
        raise NotImplementedError(
            "API odds endpoint not available - use ScraperAdapter"
        )

    async def fetch_team_stats(self, team_name: str) -> Dict[str, Any]:
        """Fetch team stats via API (not currently available)."""
        raise NotImplementedError(
            "API stats endpoint not available - use ScraperAdapter"
        )

    def fetch_historical_matches(self, league: str, season: str) -> pd.DataFrame:
        """Fetch historical data via API (not currently available)."""
        raise NotImplementedError(
            "API historical endpoint not available - use ScraperAdapter"
        )

    async def fetch_live_scores(self, league: str) -> List[Dict[str, Any]]:
        """Fetch live scores via API (not currently available)."""
        raise NotImplementedError(
            "API live scores endpoint not available - use ScraperAdapter"
        )


class DataSourceFactory:
    """
    Factory for creating data source adapters.

    Enables runtime switching between API and scraper implementations
    without code changes in consuming modules.

    Usage:
        source = DataSourceFactory.create('scraper')
        odds = await source.fetch_match_odds('12345')
    """

    _instances: Dict[str, DataSourceAdapter] = {}

    @classmethod
    def create(cls, source_type: Optional[str] = None) -> DataSourceAdapter:
        """
        Create or return cached data source adapter.

        Args:
            source_type: 'api', 'scraper', or None (uses env default)

        Returns:
            DataSourceAdapter instance
        """
        if source_type is None:
            source_type = os.getenv("DATA_SOURCE", "scraper")

        source_type = source_type.lower()

        # Return cached instance if available
        if source_type in cls._instances:
            return cls._instances[source_type]

        # Create new instance
        if source_type == "api":
            instance = APIAdapter()
        elif source_type == "scraper":
            instance = ScraperAdapter()
        else:
            logger.warning(
                f"Unknown source type '{source_type}', defaulting to scraper"
            )
            instance = ScraperAdapter()

        cls._instances[source_type] = instance
        logger.info(f"Created DataSourceAdapter: {instance.get_source_name()}")

        return instance

    @classmethod
    def get_default(cls) -> DataSourceAdapter:
        """Get the default data source (scraper for SabiScore)."""
        return cls.create("scraper")

    @classmethod
    def reset(cls) -> None:
        """Reset all cached instances (for testing)."""
        cls._instances.clear()


# Convenience function for quick access
def get_data_source() -> DataSourceAdapter:
    """Get the default data source adapter."""
    return DataSourceFactory.get_default()
