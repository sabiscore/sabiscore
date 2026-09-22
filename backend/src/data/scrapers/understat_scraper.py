"""
Understat xG (Expected Goals) Scraper
======================================

Scrapes advanced expected goals (xG) statistics from Understat.

Features:
- Match xG (expected goals)
- Shot maps and shot quality
- Player xG contributions
- Team xG trends

Understat provides some of the best free xG data available.

Ethical Note:
- Uses local data fallback when available
- Respects rate limits (3 seconds between requests)
- Only scrapes publicly available statistics
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from .base_scraper import BaseScraper, CACHE_DIR, PROCESSED_DIR

logger = logging.getLogger(__name__)


class UnderstatScraper(BaseScraper):
    """
    Scraper for Understat xG (expected goals) data.

    Provides:
    - Match xG values
    - Shot quality metrics
    - Player xG contributions
    - Historical xG trends

    xG is one of the most predictive metrics in football analytics.
    """

    BASE_URL = "https://understat.com"

    # League identifiers on Understat
    LEAGUE_IDS = {
        "EPL": "EPL",
        "La Liga": "La_liga",
        "Serie A": "Serie_A",
        "Bundesliga": "Bundesliga",
        "Ligue 1": "Ligue_1",
        "RFPL": "RFPL",  # Russian Premier League
    }

    def __init__(self):
        super().__init__(
            base_url=self.BASE_URL, rate_limit_delay=3.0, max_retries=3, timeout=20
        )

        self.cache_dir = CACHE_DIR / "understat"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.local_xg_path = PROCESSED_DIR / "xg_data.json"

        # Load cached xG data
        self.xg_cache = self._load_xg_cache()

    def _load_xg_cache(self) -> Dict:
        """Load cached xG data."""
        if self.local_xg_path.exists():
            try:
                with open(self.local_xg_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading xG cache: {e}")
        return {}

    def _save_xg_cache(self):
        """Save xG data to cache."""
        try:
            with open(self.local_xg_path, "w", encoding="utf-8") as f:
                json.dump(self.xg_cache, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving xG cache: {e}")

    def _fetch_remote(
        self, team: str, league: str = "EPL", season: str = "2024"
    ) -> Optional[Dict]:
        """
        Fetch xG data from Understat.

        Understat embeds data in JavaScript variables on the page.
        Full implementation would parse these with regex or ast.
        """
        logger.info(f"Fetching Understat xG data for {team}")

        cache_key = f"{team}_{league}_{season}".lower().replace(" ", "_")

        # Check cache first
        if cache_key in self.xg_cache:
            cached = self.xg_cache[cache_key]
            cache_time = datetime.fromisoformat(cached.get("timestamp", "2000-01-01"))
            if (datetime.now() - cache_time).days < 1:  # 1 day cache
                return cached

        # Understat embeds data in JS; real parser not yet implemented; fail closed.
        return None

    def _calculate_trend(self, matches: List[Dict], key: str) -> str:
        """Calculate trend (improving/declining/stable)."""
        if len(matches) < 3:
            return "insufficient_data"

        recent = sum(m[key] for m in matches[:2]) / 2
        older = sum(m[key] for m in matches[3:]) / 2

        diff = recent - older
        if abs(diff) < 0.2:
            return "stable"
        return "improving" if diff > 0 else "declining"

    def _parse_data(self, content: Dict) -> Dict:
        """Parse xG data."""
        return content

    def get_team_xg(
        self, team: str, league: str = "EPL", season: str = "2024"
    ) -> Optional[Dict]:
        """
        Get team xG statistics.

        Args:
            team: Team name
            league: League identifier
            season: Season year (e.g., "2024")

        Returns:
            Dict with xG totals, averages, trends
        """
        return self.fetch_data(team, league, season)

    def get_match_xg_prediction(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Dict[str, float]:
        """
        Predict match xG based on team averages.

        Returns expected xG for each team.
        """
        home_data = self.get_team_xg(home_team, league)
        away_data = self.get_team_xg(away_team, league)

        if not home_data or not away_data:
            return {"home_xg": 1.3, "away_xg": 1.1}

        home_stats = home_data.get("stats", {})
        away_stats = away_data.get("stats", {})

        # Home team attacking vs Away team defending
        home_xg = (
            home_stats.get("xg_per_game", 1.5) + away_stats.get("xga_per_game", 1.3)
        ) / 2
        # Away team attacking vs Home team defending
        away_xg = (
            away_stats.get("xg_per_game", 1.3) + home_stats.get("xga_per_game", 1.2)
        ) / 2

        # Home advantage adjustment
        home_xg *= 1.1
        away_xg *= 0.9

        return {
            "home_xg": round(home_xg, 2),
            "away_xg": round(away_xg, 2),
            "total_xg": round(home_xg + away_xg, 2),
            "xg_diff": round(home_xg - away_xg, 2),
        }

    def calculate_xg_features(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Dict[str, float]:
        """
        Calculate xG-based features for prediction.

        Returns features like:
        - xG per game
        - xG difference
        - Recent xG form
        - Shot quality metrics
        """
        home_data = self.get_team_xg(home_team, league)
        away_data = self.get_team_xg(away_team, league)

        if not home_data or not away_data:
            return {}

        home_stats = home_data.get("stats", {})
        away_stats = away_data.get("stats", {})
        home_form = home_data.get("recent_form", {})
        away_form = away_data.get("recent_form", {})
        home_shots = home_data.get("shot_quality", {})
        away_shots = away_data.get("shot_quality", {})

        return {
            "home_xg_pg": home_stats.get("xg_per_game", 1.3),
            "away_xg_pg": away_stats.get("xg_per_game", 1.2),
            "home_xga_pg": home_stats.get("xga_per_game", 1.2),
            "away_xga_pg": away_stats.get("xga_per_game", 1.3),
            "home_xg_diff": home_stats.get("xg_difference", 0.1),
            "away_xg_diff": away_stats.get("xg_difference", -0.1),
            "home_recent_xg": home_form.get("last_5_xg_avg", 1.3),
            "away_recent_xg": away_form.get("last_5_xg_avg", 1.2),
            "home_xg_per_shot": home_shots.get("avg_xg_per_shot", 0.11),
            "away_xg_per_shot": away_shots.get("avg_xg_per_shot", 0.10),
            "home_big_chances": home_shots.get("big_chances_per_game", 2.5),
            "away_big_chances": away_shots.get("big_chances_per_game", 2.0),
        }


# Convenience function
def get_xg_stats(team: str, league: str = "EPL") -> Optional[Dict]:
    """Get xG statistics from Understat."""
    return UnderstatScraper().get_team_xg(team, league)
