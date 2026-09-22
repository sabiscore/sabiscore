# ponytail: BLOCKED — restricted site, no authorised API contract. _fetch_remote returns None (fail-closed).
"""
OddsPortal Historical Odds Scraper — BLOCKED.
No authorised API contract exists. All fetch methods return None (fail-closed).
Do not activate without a licensed data feed agreement.
"""

import logging
from typing import Dict, Optional

from .base_scraper import BaseScraper, CACHE_DIR, PROCESSED_DIR

logger = logging.getLogger(__name__)


class OddsPortalScraper(BaseScraper):
    """
    Scraper for OddsPortal historical odds data.

    Provides:
    - Opening and closing odds
    - Line movement analysis
    - Multi-bookmaker comparisons
    - Historical odds trends
    """

    BASE_URL = "https://www.oddsportal.com"

    # League paths on OddsPortal
    LEAGUE_PATHS = {
        "EPL": "/football/england/premier-league/",
        "La Liga": "/football/spain/laliga/",
        "Serie A": "/football/italy/serie-a/",
        "Bundesliga": "/football/germany/bundesliga/",
        "Ligue 1": "/football/france/ligue-1/",
    }

    # Common bookmakers
    BOOKMAKERS = [
        "bet365",
        "Pinnacle",
        "Betfair",
        "Unibet",
        "William Hill",
        "888sport",
        "Betway",
        "1xBet",
    ]

    def __init__(self):
        super().__init__(
            base_url=self.BASE_URL, rate_limit_delay=3.0, max_retries=3, timeout=20
        )

        self.cache_dir = CACHE_DIR / "oddsportal"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.local_odds_path = PROCESSED_DIR / "historical_odds.json"

    def _fetch_remote(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Optional[Dict]:
        """
        Fetch historical odds for a match.

        Note: OddsPortal uses JavaScript rendering.
        Full implementation requires Playwright/Selenium.
        """
        logger.info(f"Fetching OddsPortal odds for {home_team} vs {away_team}")
        # OddsPortal requires JavaScript rendering (Playwright/Selenium); not yet implemented.
        return None

    def _find_best_odds(
        self, bookmaker_odds: Dict[str, Dict[str, float]]
    ) -> Dict[str, Dict]:
        """Find best odds across bookmakers."""
        best = {
            "home": {"odds": 0, "bookmaker": ""},
            "draw": {"odds": 0, "bookmaker": ""},
            "away": {"odds": 0, "bookmaker": ""},
        }

        for bookie, odds in bookmaker_odds.items():
            for outcome in ["home", "draw", "away"]:
                if odds[outcome] > best[outcome]["odds"]:
                    best[outcome]["odds"] = odds[outcome]
                    best[outcome]["bookmaker"] = bookie

        return best

    def _calculate_average_odds(
        self, bookmaker_odds: Dict[str, Dict[str, float]]
    ) -> Dict[str, float]:
        """Calculate average odds across bookmakers."""
        totals = {"home": 0, "draw": 0, "away": 0}
        count = len(bookmaker_odds)

        for bookie_odds in bookmaker_odds.values():
            for outcome in totals:
                totals[outcome] += bookie_odds[outcome]

        return {k: round(v / count, 2) for k, v in totals.items()}

    def _parse_data(self, content: Dict) -> Dict:
        """Parse odds data."""
        return content

    def get_match_odds(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Optional[Dict]:
        """
        Get historical odds for a match.

        Args:
            home_team: Home team name
            away_team: Away team name
            league: League identifier

        Returns:
            Dict with opening/closing odds, movement, best odds
        """
        return self.fetch_data(home_team, away_team, league)

    def get_odds_movement(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Dict[str, float]:
        """
        Get odds movement (opening to closing).

        Positive = odds drifted (less likely)
        Negative = odds shortened (more likely)
        """
        data = self.get_match_odds(home_team, away_team, league)
        if data:
            return data.get("movement", {})
        return {}

    def calculate_odds_features(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Dict[str, float]:
        """
        Calculate odds-based features for prediction.

        Returns features like:
        - Implied probabilities
        - Odds movement signals
        - Market confidence
        """
        data = self.get_match_odds(home_team, away_team, league)
        if not data:
            return {}

        closing = data.get("closing_odds", {})
        probs = data.get("implied_probabilities", {})
        movement = data.get("movement", {})

        return {
            "odds_home": closing.get("home", 2.0),
            "odds_draw": closing.get("draw", 3.5),
            "odds_away": closing.get("away", 3.0),
            "prob_home": probs.get("home", 0.33),
            "prob_draw": probs.get("draw", 0.33),
            "prob_away": probs.get("away", 0.33),
            "movement_home": movement.get("home", 0),
            "movement_away": movement.get("away", 0),
            "overround": data.get("overround", 5.0),
            "market_confidence": round(1 / max(data.get("overround", 5), 0.1), 3),
        }


# Convenience function
def get_historical_odds(
    home_team: str, away_team: str, league: str = "EPL"
) -> Optional[Dict]:
    """Get historical odds from OddsPortal."""
    return OddsPortalScraper().get_match_odds(home_team, away_team, league)
