"""
Enhanced Football-Data.co.uk Scraper
=====================================

Downloads historical match data with Pinnacle odds from football-data.co.uk.

Features:
- Multiple league support (EPL, La Liga, Bundesliga, etc.)
- Season-by-season downloads
- Automatic caching with TTL
- Pinnacle odds extraction for CLV analysis
- Standardized column naming
- Local fallback for offline operation

This is the primary source for historical match results and closing line values.
"""

import io
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .base_scraper import BaseScraper, PROCESSED_DIR, CACHE_DIR

logger = logging.getLogger(__name__)


class FootballDataEnhancedScraper(BaseScraper):
    """
    Enhanced scraper for football-data.co.uk historical data.

    Implements ethical scraping with:
    - Rate limiting (3s between requests)
    - Retry with exponential backoff
    - 24-hour caching to minimize requests
    - Local fallback for offline operation

    Data includes:
    - Match results (FTHG, FTAG, FTR)
    - Pinnacle odds (PSH, PSD, PSA) - our primary CLV benchmark
    - Bet365 odds for backup
    - Shot/corner/foul statistics
    - Referee data
    """

    BASE_URL = "https://www.football-data.co.uk"

    # League code mapping
    LEAGUE_CODES = {
        "EPL": "E0",
        "Premier League": "E0",
        "Championship": "E1",
        "League 1": "E2",
        "League 2": "E3",
        "La Liga": "SP1",
        "La_Liga": "SP1",
        "Bundesliga": "D1",
        "Serie A": "I1",
        "Serie_A": "I1",
        "Ligue 1": "F1",
        "Ligue_1": "F1",
        "Eredivisie": "N1",
        "Portuguese": "P1",
        "Turkish": "T1",
        "Greek": "G1",
        "Scottish Premiership": "SC0",
        "Belgian": "B1",
        "Russian": "R1",
    }

    # Column standardization mapping
    COLUMN_MAPPING = {
        # Core match info
        "Date": "date",
        "HomeTeam": "home_team",
        "AwayTeam": "away_team",
        "FTHG": "home_goals",
        "FTAG": "away_goals",
        "FTR": "result",  # H/D/A
        "HTHG": "ht_home_goals",
        "HTAG": "ht_away_goals",
        "HTR": "ht_result",
        # Match statistics
        "HS": "home_shots",
        "AS": "away_shots",
        "HST": "home_shots_target",
        "AST": "away_shots_target",
        "HF": "home_fouls",
        "AF": "away_fouls",
        "HC": "home_corners",
        "AC": "away_corners",
        "HY": "home_yellows",
        "AY": "away_yellows",
        "HR": "home_reds",
        "AR": "away_reds",
        # Pinnacle odds (our primary benchmark - sharpest odds in market)
        "PSH": "pinnacle_home",
        "PSD": "pinnacle_draw",
        "PSA": "pinnacle_away",
        "PSCH": "pinnacle_closing_home",
        "PSCD": "pinnacle_closing_draw",
        "PSCA": "pinnacle_closing_away",
        # Bet365 odds (backup)
        "B365H": "bet365_home",
        "B365D": "bet365_draw",
        "B365A": "bet365_away",
        # Market averages
        "AvgH": "avg_home",
        "AvgD": "avg_draw",
        "AvgA": "avg_away",
        "MaxH": "max_home",
        "MaxD": "max_draw",
        "MaxA": "max_away",
    }

    def __init__(self, cache_ttl_hours: int = 24):
        super().__init__(
            base_url=self.BASE_URL,
            rate_limit_delay=3.0,  # Hardened to 3s to align with global policy
            max_retries=3,
            timeout=30,
        )

        self.cache_ttl_hours = cache_ttl_hours
        self.cache_dir = CACHE_DIR / "football_data"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Local data paths for fallback
        self.local_raw_path = PROCESSED_DIR / "historical_raw.csv"
        self.local_processed_path = PROCESSED_DIR / "historical_processed.csv"

        logger.info(
            f"FootballDataEnhancedScraper initialized with cache at {self.cache_dir}"
        )

    def _get_league_code(self, league: str) -> str:
        """Convert league name to football-data.co.uk code."""
        # If already a valid code, return it
        valid_codes = [
            "E0",
            "E1",
            "E2",
            "E3",
            "SP1",
            "D1",
            "I1",
            "F1",
            "N1",
            "P1",
            "T1",
            "G1",
            "SC0",
            "B1",
            "R1",
        ]
        if league in valid_codes:
            return league

        return self.LEAGUE_CODES.get(league, league)

    def _get_season_url(self, league_code: str, season: str) -> str:
        """
        Build URL for season CSV download.

        Args:
            league_code: League code (e.g., 'E0')
            season: Season string (e.g., '2526' for 2025/26)
        """
        # Season format: '2526' or '25-26' -> folder '2526'
        folder = season.replace("-", "")
        return f"{self.BASE_URL}/mmz4281/{folder}/{league_code}.csv"

    def _get_cache_path(self, league_code: str, season: str) -> Path:
        """Get cache file path for a league/season."""
        return self.cache_dir / f"{league_code}_{season}.csv"

    def _is_cache_valid(self, cache_path: Path) -> bool:
        """Check if cache file exists and is fresh."""
        if not cache_path.exists():
            return False

        cache_age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        return cache_age_hours < self.cache_ttl_hours

    def _fetch_remote(self, league: str = "E0", season: str = "2526") -> Optional[str]:
        """Fetch CSV data from football-data.co.uk."""
        league_code = self._get_league_code(league)
        url = self._get_season_url(league_code, season)

        logger.info(f"Fetching data from {url}")

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def _parse_data(self, page_content: str) -> pd.DataFrame:
        """Parse CSV content into standardized DataFrame."""
        try:
            df = pd.read_csv(io.StringIO(page_content), encoding="latin1")
        except Exception:
            # Try alternative encoding
            df = pd.read_csv(io.StringIO(page_content), encoding="utf-8")

        return self._standardize_dataframe(df)

    def _standardize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize column names and add computed features.
        """
        # Rename columns that exist
        rename_map = {k: v for k, v in self.COLUMN_MAPPING.items() if k in df.columns}
        df = df.rename(columns=rename_map)

        # Parse date column
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
        elif "Date" in df.columns:
            df["date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
            df = df.drop(columns=["Date"], errors="ignore")

        # Add computed columns
        if "home_goals" in df.columns and "away_goals" in df.columns:
            df["total_goals"] = df["home_goals"] + df["away_goals"]
            df["goal_diff"] = df["home_goals"] - df["away_goals"]

        # Over/under markets
        if "total_goals" in df.columns:
            df["over_2.5"] = (df["total_goals"] > 2.5).astype(int)
            df["over_3.5"] = (df["total_goals"] > 3.5).astype(int)
            df["btts"] = ((df["home_goals"] > 0) & (df["away_goals"] > 0)).astype(int)

        # Implied probabilities from Pinnacle odds (for CLV analysis)
        pinnacle_cols = ["pinnacle_home", "pinnacle_draw", "pinnacle_away"]
        if all(col in df.columns for col in pinnacle_cols):
            df["implied_home_prob"] = 1 / df["pinnacle_home"]
            df["implied_draw_prob"] = 1 / df["pinnacle_draw"]
            df["implied_away_prob"] = 1 / df["pinnacle_away"]
            df["margin"] = (
                df["implied_home_prob"]
                + df["implied_draw_prob"]
                + df["implied_away_prob"]
                - 1
            )

            # Calculate fair (no-vig) probabilities
            total_implied = (
                df["implied_home_prob"]
                + df["implied_draw_prob"]
                + df["implied_away_prob"]
            )
            df["fair_home_prob"] = df["implied_home_prob"] / total_implied
            df["fair_draw_prob"] = df["implied_draw_prob"] / total_implied
            df["fair_away_prob"] = df["implied_away_prob"] / total_implied

        # Add metadata
        df["source"] = "football-data.co.uk"
        df["scraped_at"] = datetime.now().isoformat()

        return df

    def download_season_data(
        self, league: str, season: str, use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Download historical match data for a season.

        Args:
            league: League name or code (e.g., 'EPL' or 'E0')
            season: Season code (e.g., '2526' for 2025/26)
            use_cache: Whether to use cached data if available

        Returns:
            DataFrame with standardized column names
        """
        league_code = self._get_league_code(league)
        cache_path = self._get_cache_path(league_code, season)

        # Check cache first
        if use_cache and self._is_cache_valid(cache_path):
            logger.info(f"Using cached data for {league_code} {season}")
            df = pd.read_csv(cache_path)
            self.metrics["cache_hits"] += 1
            return self._standardize_dataframe(df)

        # Fetch from remote
        content = self._fetch_remote(league_code, season)
        if content is None:
            # Try stale cache as fallback
            if cache_path.exists():
                logger.warning("Using stale cache as fallback")
                df = pd.read_csv(cache_path)
                return self._standardize_dataframe(df)
            return pd.DataFrame()

        df = self._parse_data(content)

        # Cache the result
        if use_cache and not df.empty:
            df.to_csv(cache_path, index=False)
            logger.info(f"Cached {len(df)} matches to {cache_path}")

        return df

    def download_multiple_seasons(
        self, league: str, seasons: List[str], use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Download and combine data from multiple seasons.
        """
        all_data = []

        for season in seasons:
            df = self.download_season_data(league, season, use_cache)
            if not df.empty:
                df["season"] = season
                all_data.append(df)

        if not all_data:
            return pd.DataFrame()

        combined = pd.concat(all_data, ignore_index=True)
        combined = combined.sort_values("date", ascending=True)

        logger.info(f"Combined {len(combined)} matches across {len(seasons)} seasons")
        return combined

    def download_all_leagues(
        self, season: str, leagues: Optional[List[str]] = None, use_cache: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Download data for multiple leagues in a season.
        """
        if leagues is None:
            leagues = ["EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1"]

        results = {}
        for league in leagues:
            df = self.download_season_data(league, season, use_cache)
            if not df.empty:
                results[league] = df

        logger.info(f"Downloaded data for {len(results)} leagues")
        return results

    def get_team_history(
        self, team_name: str, league: str, seasons: List[str], use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Get all matches for a specific team.
        """
        all_data = self.download_multiple_seasons(league, seasons, use_cache)

        if all_data.empty:
            return pd.DataFrame()

        # Find matches where team played
        team_lower = team_name.lower()
        mask = all_data["home_team"].str.lower().str.contains(
            team_lower, na=False
        ) | all_data["away_team"].str.lower().str.contains(team_lower, na=False)

        team_matches = all_data[mask].copy()
        logger.info(f"Found {len(team_matches)} matches for {team_name}")
        return team_matches

    def get_available_leagues(self) -> List[str]:
        """Return list of available league codes."""
        return list(self.LEAGUE_CODES.keys())

    def clear_cache(self) -> None:
        """Clear all cached data files."""
        for cache_file in self.cache_dir.glob("*.csv"):
            cache_file.unlink()
            logger.info(f"Deleted cache file: {cache_file}")


# Convenience function
def scrape_football_data(league: str, season: str) -> pd.DataFrame:
    """Convenience function to scrape football-data.co.uk."""
    return FootballDataEnhancedScraper().download_season_data(league, season)
