"""
Mock data generator — TEST/DEVELOPMENT USE ONLY.

Never import mock_generator from production routes.
In production, settings.mock_mode must remain False (the safe default).
"""

from datetime import datetime, timezone, timedelta
import random
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class MockDataGenerator:
    """
    Generates realistic football match data for development/demo
    """

    LEAGUES = {
        "EPL": {
            "name": "Premier League",
            "teams": [
                "Arsenal",
                "Manchester City",
                "Liverpool",
                "Manchester United",
                "Chelsea",
                "Tottenham",
                "Newcastle",
                "Brighton",
                "Aston Villa",
                "West Ham",
                "Crystal Palace",
                "Fulham",
                "Brentford",
                "Wolves",
                "Nottingham Forest",
                "Everton",
                "Bournemouth",
                "Luton Town",
                "Burnley",
                "Sheffield United",
            ],
        },
        "BUNDESLIGA": {
            "name": "Bundesliga",
            "teams": [
                "Bayern Munich",
                "Borussia Dortmund",
                "RB Leipzig",
                "Union Berlin",
                "Freiburg",
                "Bayer Leverkusen",
                "Eintracht Frankfurt",
                "Wolfsburg",
                "Mainz",
                "Borussia Mönchengladbach",
                "Köln",
                "Hoffenheim",
                "Werder Bremen",
                "Augsburg",
                "Stuttgart",
                "Bochum",
                "Darmstadt",
                "Heidenheim",
            ],
        },
        "LALIGA": {
            "name": "La Liga",
            "teams": [
                "Real Madrid",
                "Barcelona",
                "Atlético Madrid",
                "Real Sociedad",
                "Athletic Bilbao",
                "Real Betis",
                "Villarreal",
                "Valencia",
                "Osasuna",
                "Girona",
                "Getafe",
                "Sevilla",
                "Rayo Vallecano",
                "Las Palmas",
                "Celta Vigo",
                "Mallorca",
                "Cádiz",
                "Almería",
                "Granada",
                "Alavés",
            ],
        },
        "SERIEA": {
            "name": "Serie A",
            "teams": [
                "Inter Milan",
                "AC Milan",
                "Juventus",
                "Napoli",
                "Roma",
                "Lazio",
                "Atalanta",
                "Fiorentina",
                "Bologna",
                "Torino",
                "Monza",
                "Udinese",
                "Sassuolo",
                "Empoli",
                "Hellas Verona",
                "Cagliari",
                "Lecce",
                "Frosinone",
                "Genoa",
                "Salernitana",
            ],
        },
        "LIGUE1": {
            "name": "Ligue 1",
            "teams": [
                "Paris Saint-Germain",
                "Monaco",
                "Marseille",
                "Lille",
                "Nice",
                "Lyon",
                "Lens",
                "Rennes",
                "Montpellier",
                "Toulouse",
                "Nantes",
                "Strasbourg",
                "Reims",
                "Le Havre",
                "Brest",
                "Lorient",
                "Metz",
                "Clermont Foot",
            ],
        },
    }

    def generate_upcoming_matches(
        self, days: int = 7, count: int = 30
    ) -> List[Dict[str, Any]]:
        """Generate upcoming matches for the next N days"""
        matches = []
        now = datetime.now(timezone.utc)

        for _ in range(count):
            league_code = random.choice(list(self.LEAGUES.keys()))
            league = self.LEAGUES[league_code]

            # Random date within the next N days
            days_ahead = random.uniform(0, days)
            match_date = now + timedelta(days=days_ahead)

            # Pick two different teams
            teams = random.sample(league["teams"], 2)

            match = {
                "id": f"match_{random.randint(10000, 99999)}",
                "home_team": teams[0],
                "away_team": teams[1],
                "league": league_code,
                "league_name": league["name"],
                "match_date": match_date.isoformat(),
                "venue": f"{teams[0]} Stadium",
                "status": "scheduled",
                "home_odds": round(random.uniform(1.5, 4.5), 2),
                "draw_odds": round(random.uniform(2.8, 4.2), 2),
                "away_odds": round(random.uniform(1.5, 5.5), 2),
            }

            matches.append(match)

        # Sort by date
        matches.sort(key=lambda x: x["match_date"])
        return matches

    def generate_prediction(self, match: Dict[str, Any]) -> Dict[str, Any]:
        """Generate realistic prediction data for a match"""

        # Generate probabilities that sum to 1.0
        home_prob = random.uniform(0.25, 0.60)
        draw_prob = random.uniform(0.15, 0.35)
        away_prob = 1.0 - home_prob - draw_prob

        # Normalize to ensure sum = 1.0
        total = home_prob + draw_prob + away_prob
        home_prob /= total
        draw_prob /= total
        away_prob /= total

        # Calculate fair odds (inverse of probability)
        fair_home_odds = 1.0 / home_prob
        fair_draw_odds = 1.0 / draw_prob
        fair_away_odds = 1.0 / away_prob

        # Get market odds
        market_home = match.get("home_odds", fair_home_odds * 1.1)
        market_draw = match.get("draw_odds", fair_draw_odds * 1.1)
        market_away = match.get("away_odds", fair_away_odds * 1.1)

        # Calculate edges (in Naira, assuming ₦10,000 base bet)
        base_bet = 10000
        home_edge_ngn = max(0, (fair_home_odds * base_bet) - (market_home * base_bet))
        max(0, (fair_draw_odds * base_bet) - (market_draw * base_bet))
        away_edge_ngn = max(0, (fair_away_odds * base_bet) - (market_away * base_bet))

        # Find best value bet
        value_bets = []
        min_edge_ngn = 66  # ₦66 minimum (4.2% of ₦10k)

        if home_edge_ngn > min_edge_ngn:
            kelly_stake = int(home_prob * 0.125 * 10000)  # ⅛ Kelly
            value_bets.append(
                {
                    "bet_type": "home_win",
                    "recommended_odds": round(fair_home_odds, 2),
                    "market_odds": market_home,
                    "edge_ngn": int(home_edge_ngn),
                    "edge_percent": round((home_edge_ngn / base_bet) * 100, 2),
                    "kelly_stake_ngn": kelly_stake,
                    "confidence": round(home_prob, 3),
                }
            )

        if away_edge_ngn > min_edge_ngn:
            kelly_stake = int(away_prob * 0.125 * 10000)
            value_bets.append(
                {
                    "bet_type": "away_win",
                    "recommended_odds": round(fair_away_odds, 2),
                    "market_odds": market_away,
                    "edge_ngn": int(away_edge_ngn),
                    "edge_percent": round((away_edge_ngn / base_bet) * 100, 2),
                    "kelly_stake_ngn": kelly_stake,
                    "confidence": round(away_prob, 3),
                }
            )

        # Calculate Brier score (lower is better, typical: 0.15-0.25)
        brier_score = round(random.uniform(0.15, 0.22), 3)

        # Calculate overall confidence
        confidence = round(max(home_prob, draw_prob, away_prob), 3)

        prediction = {
            "match_id": match["id"],
            "home_team": match["home_team"],
            "away_team": match["away_team"],
            "league": match["league"],
            "predictions": {
                "home_win": round(home_prob, 3),
                "draw": round(draw_prob, 3),
                "away_win": round(away_prob, 3),
            },
            "confidence": confidence,
            "brier_score": brier_score,
            "value_bets": value_bets,
            "confidence_intervals": {
                "home_win": [round(home_prob - 0.05, 3), round(home_prob + 0.05, 3)],
                "draw": [round(draw_prob - 0.04, 3), round(draw_prob + 0.04, 3)],
                "away_win": [round(away_prob - 0.05, 3), round(away_prob + 0.05, 3)],
            },
            "metadata": {
                "model_version": "3.0",
                "features_count": 220,
                "calibrated": True,
                "processing_time_ms": random.randint(85, 145),
                "league_model": match["league"].lower(),
                "data_freshness": "demo",
            },
        }

        return prediction

    def generate_value_bets_today(self, count: int = 15) -> List[Dict[str, Any]]:
        """Generate today's value bets"""
        matches = self.generate_upcoming_matches(days=1, count=count)
        value_bets = []

        for match in matches:
            prediction = self.generate_prediction(match)

            # Only include matches with value bets
            if prediction["value_bets"]:
                for vb in prediction["value_bets"]:
                    value_bet = {
                        "match_id": match["id"],
                        "home_team": match["home_team"],
                        "away_team": match["away_team"],
                        "league": match["league"],
                        "match_date": match["match_date"],
                        **vb,
                    }
                    value_bets.append(value_bet)

        # Sort by edge (highest first)
        value_bets.sort(key=lambda x: x["edge_ngn"], reverse=True)
        return value_bets[:count]


# Singleton instance
mock_generator = MockDataGenerator()
