# ponytail: BLOCKED — restricted site, no authorised API contract. _fetch_remote returns None (fail-closed).
"""
Soccerway Competition and Fixture Scraper — BLOCKED.
No authorised API contract exists. All fetch methods return None (fail-closed).
Do not activate without a licensed data feed agreement.
"""

import logging
from typing import Dict, List, Optional
from urllib.parse import urljoin


from .base_scraper import BaseScraper, CACHE_DIR, PROCESSED_DIR

logger = logging.getLogger(__name__)


class SoccerwayScraper(BaseScraper):
    """
    Scraper for Soccerway fixture and standings data.

    Provides:
    - League tables with points, goal difference
    - Fixture lists with dates
    - Match results
    - Home/Away splits
    """

    BASE_URL = "https://int.soccerway.com"

    # League URL mappings
    LEAGUE_PATHS = {
        "EPL": "/national/england/premier-league/",
        "La Liga": "/national/spain/primera-division/",
        "Serie A": "/national/italy/serie-a/",
        "Bundesliga": "/national/germany/bundesliga/",
        "Ligue 1": "/national/france/ligue-1/",
        "Eredivisie": "/national/netherlands/eredivisie/",
        "Primeira Liga": "/national/portugal/portuguese-liga-/",
        "Championship": "/national/england/championship/",
    }

    def __init__(self):
        super().__init__(
            base_url=self.BASE_URL, rate_limit_delay=3.0, max_retries=3, timeout=20
        )

        self.cache_dir = CACHE_DIR / "soccerway"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.local_standings_path = PROCESSED_DIR / "standings.json"
        self.local_fixtures_path = PROCESSED_DIR / "fixtures.json"

    def _fetch_remote(
        self, league: str = "EPL", data_type: str = "standings"
    ) -> Optional[Dict]:
        """
        Fetch league data from Soccerway.

        Args:
            league: League identifier
            data_type: "standings", "fixtures", or "results"
        """
        league_path = self.LEAGUE_PATHS.get(league)
        if not league_path:
            logger.warning(f"Unknown league: {league}, using EPL")
            league_path = self.LEAGUE_PATHS["EPL"]

        url = urljoin(self.BASE_URL, league_path)
        logger.info(f"Fetching {data_type} from Soccerway for {league}")

        html = self.get_page(url)
        if html:
            return self._parse_data(html, data_type, league)

        # No real parser yet and simulation is forbidden; fail closed.
        return None

    def _parse_data(
        self, html: str, data_type: str = "standings", league: str = "EPL"
    ) -> Dict:
        """Parse HTML content from Soccerway.  TODO: implement BeautifulSoup parsing."""
        # Real parsing not yet implemented; return None so callers handle absence cleanly.
        return None

    def _get_league_teams(self, league: str) -> List[str]:
        """Get list of teams for a league."""
        teams_by_league = {
            "EPL": [
                "Arsenal",
                "Aston Villa",
                "Bournemouth",
                "Brentford",
                "Brighton",
                "Chelsea",
                "Crystal Palace",
                "Everton",
                "Fulham",
                "Ipswich",
                "Leicester",
                "Liverpool",
                "Man City",
                "Man United",
                "Newcastle",
                "Nottingham Forest",
                "Southampton",
                "Tottenham",
                "West Ham",
                "Wolves",
            ],
            "La Liga": [
                "Real Madrid",
                "Barcelona",
                "Atletico Madrid",
                "Athletic Bilbao",
                "Real Sociedad",
                "Villarreal",
                "Real Betis",
                "Sevilla",
                "Valencia",
                "Celta Vigo",
                "Girona",
                "Rayo Vallecano",
                "Osasuna",
                "Getafe",
                "Mallorca",
                "Las Palmas",
                "Alaves",
                "Leganes",
                "Espanyol",
                "Valladolid",
            ],
            "Serie A": [
                "Inter",
                "Juventus",
                "AC Milan",
                "Napoli",
                "Roma",
                "Lazio",
                "Atalanta",
                "Fiorentina",
                "Bologna",
                "Torino",
                "Udinese",
                "Sassuolo",
                "Empoli",
                "Monza",
                "Lecce",
                "Verona",
                "Cagliari",
                "Genoa",
                "Salernitana",
                "Frosinone",
            ],
            "Bundesliga": [
                "Bayern Munich",
                "Dortmund",
                "RB Leipzig",
                "Leverkusen",
                "Frankfurt",
                "Union Berlin",
                "Freiburg",
                "Wolfsburg",
                "Hoffenheim",
                "Mainz",
                "Monchengladbach",
                "Stuttgart",
                "Werder Bremen",
                "Augsburg",
                "Bochum",
                "Koln",
                "Heidenheim",
                "Darmstadt",
            ],
            "Ligue 1": [
                "PSG",
                "Monaco",
                "Lille",
                "Lyon",
                "Marseille",
                "Rennes",
                "Nice",
                "Lens",
                "Strasbourg",
                "Nantes",
                "Brest",
                "Montpellier",
                "Toulouse",
                "Lorient",
                "Reims",
                "Le Havre",
                "Metz",
                "Clermont",
            ],
        }
        return teams_by_league.get(league, teams_by_league["EPL"])

    def _get_result(self, home: int, away: int) -> str:
        """Get match result string."""
        if home > away:
            return "H"
        elif away > home:
            return "A"
        return "D"

    def get_standings(self, league: str = "EPL") -> Optional[Dict]:
        """Get current league standings."""
        return self._fetch_remote(league, "standings")

    def get_fixtures(self, league: str = "EPL") -> Optional[Dict]:
        """Get upcoming fixtures."""
        return self._fetch_remote(league, "fixtures")

    def get_results(self, league: str = "EPL") -> Optional[Dict]:
        """Get recent results."""
        return self._fetch_remote(league, "results")

    def get_team_position(self, team: str, league: str = "EPL") -> Optional[int]:
        """Get team's current league position."""
        standings = self.get_standings(league)
        if standings:
            for entry in standings.get("standings", []):
                if team.lower() in entry["team"].lower():
                    return entry["position"]
        return None

    def calculate_position_features(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Dict[str, float]:
        """
        Calculate position-based features for prediction.

        Returns features like:
        - Position difference
        - Points per game
        - Goal difference
        """
        standings = self.get_standings(league)
        if not standings:
            return {}

        home_data = None
        away_data = None

        for entry in standings.get("standings", []):
            team_name = entry["team"].lower()
            if home_team.lower() in team_name or team_name in home_team.lower():
                home_data = entry
            if away_team.lower() in team_name or team_name in away_team.lower():
                away_data = entry

        if not home_data or not away_data:
            return {}

        home_ppg = home_data["points"] / max(1, home_data["played"])
        away_ppg = away_data["points"] / max(1, away_data["played"])

        return {
            "home_position": home_data["position"],
            "away_position": away_data["position"],
            "position_diff": away_data["position"] - home_data["position"],
            "home_ppg": round(home_ppg, 2),
            "away_ppg": round(away_ppg, 2),
            "ppg_diff": round(home_ppg - away_ppg, 2),
            "home_gd": home_data["goal_difference"],
            "away_gd": away_data["goal_difference"],
            "gd_diff": home_data["goal_difference"] - away_data["goal_difference"],
        }


# Convenience functions
def get_standings(league: str = "EPL") -> Optional[Dict]:
    """Get current league standings from Soccerway."""
    return SoccerwayScraper().get_standings(league)


def get_fixtures(league: str = "EPL") -> Optional[Dict]:
    """Get upcoming fixtures from Soccerway."""
    return SoccerwayScraper().get_fixtures(league)
