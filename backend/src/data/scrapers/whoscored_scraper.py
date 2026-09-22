# ponytail: BLOCKED — restricted site, no authorised API contract. _fetch_remote returns None (fail-closed).
"""
WhoScored Advanced Stats Scraper — BLOCKED.
No authorised API contract exists. All fetch methods return None (fail-closed).
Do not activate without a licensed data feed agreement.
"""

import logging
from typing import Dict, List, Optional


from .base_scraper import BaseScraper, CACHE_DIR, PROCESSED_DIR

logger = logging.getLogger(__name__)


class WhoScoredScraper(BaseScraper):
    """
    Scraper for WhoScored player and match statistics.

    Provides:
    - Player ratings (0-10 scale)
    - Match statistics
    - Tactical formation data
    - Historical head-to-head records

    Note: Full implementation requires headless browser
    (Playwright/Selenium) due to JavaScript rendering.
    """

    BASE_URL = "https://www.whoscored.com"

    def __init__(self):
        super().__init__(
            base_url=self.BASE_URL,
            rate_limit_delay=3.0,  # Hardened global minimum; still conservative
            max_retries=3,
            timeout=30,
        )

        self.cache_dir = CACHE_DIR / "whoscored"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.local_processed_path = PROCESSED_DIR / "whoscored_stats.json"

    def _fetch_remote(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Optional[Dict]:
        """
        Fetch match statistics.

        In development, returns simulated statistics.
        Production implementation would use Playwright.
        """
        logger.info(f"Fetching WhoScored stats for {home_team} vs {away_team}")
        # WhoScored requires a headless browser (Playwright/Selenium); not yet implemented.
        return None

    def _parse_data(self, page_content: Dict) -> Dict:
        """Parse match statistics."""
        return page_content

    def get_match_stats(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Optional[Dict]:
        """
        Get comprehensive match statistics.

        Args:
            home_team: Home team name
            away_team: Away team name
            league: League identifier

        Returns:
            Dict with possession, shots, player ratings, etc.
        """
        return self.fetch_data(home_team, away_team, league)

    def get_team_form(self, team: str, matches: int = 5) -> List[Dict]:
        """
        Get recent form for a team.  Requires real data; returns empty list without it.
        """
        return []

    def calculate_form_features(
        self, home_team: str, away_team: str, matches: int = 5
    ) -> Dict[str, float]:
        """
        Calculate form-based features for prediction.

        Returns features like:
        - Average rating
        - Win rate
        - Possession tendency
        - Shots per game
        """
        home_form = self.get_team_form(home_team, matches)
        away_form = self.get_team_form(away_team, matches)

        def calc_win_rate(form):
            wins = sum(1 for m in form if m["result"] == "W")
            return wins / len(form) if form else 0.33

        def calc_avg(form, key):
            return sum(m[key] for m in form) / len(form) if form else 0

        return {
            "home_avg_rating": round(calc_avg(home_form, "rating"), 2),
            "away_avg_rating": round(calc_avg(away_form, "rating"), 2),
            "home_win_rate_5": round(calc_win_rate(home_form), 2),
            "away_win_rate_5": round(calc_win_rate(away_form), 2),
            "home_avg_possession": round(calc_avg(home_form, "possession"), 1),
            "away_avg_possession": round(calc_avg(away_form, "possession"), 1),
            "home_shots_per_game": round(calc_avg(home_form, "shots"), 1),
            "away_shots_per_game": round(calc_avg(away_form, "shots"), 1),
        }


# Convenience function
def get_whoscored_stats(
    home_team: str, away_team: str, league: str = "EPL"
) -> Optional[Dict]:
    """Get WhoScored statistics for a match."""
    return WhoScoredScraper().get_match_stats(home_team, away_team, league)
