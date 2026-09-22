"""
Team strength database for SabiScore predictions.

This module provides baseline strength ratings for major football teams
to ensure predictions vary by team even when live data is unavailable.

Ratings are based on:
- Historical performance (ELO-style rating)
- Squad value estimates
- Recent form approximations
- Home/away performance differentials

Values are normalized where applicable (0-1 scales or realistic ranges).
"""

import hashlib
from typing import Dict

# Team ELO ratings (approximately based on clubelo.com data, scaled for the model)
# Higher = stronger team, typical range 1300-2000
TEAM_ELO_RATINGS: Dict[str, float] = {
    # Premier League (EPL)
    "Manchester City": 1980,
    "Arsenal": 1920,
    "Liverpool": 1900,
    "Chelsea": 1840,
    "Manchester United": 1820,
    "Newcastle United": 1800,
    "Tottenham": 1790,
    "Tottenham Hotspur": 1790,
    "Brighton": 1750,
    "Brighton & Hove Albion": 1750,
    "Aston Villa": 1760,
    "West Ham": 1720,
    "West Ham United": 1720,
    "Brentford": 1680,
    "Crystal Palace": 1660,
    "Fulham": 1650,
    "Wolverhampton": 1630,
    "Wolves": 1630,
    "Bournemouth": 1620,
    "Nottingham Forest": 1610,
    "Everton": 1600,
    "Leicester City": 1580,
    "Leicester": 1580,
    "Leeds United": 1560,
    "Southampton": 1540,
    "Ipswich Town": 1520,
    "Ipswich": 1520,
    "Luton Town": 1510,
    "Burnley": 1530,
    "Sheffield United": 1520,
    # La Liga
    "Real Madrid": 1970,
    "Barcelona": 1940,
    "Atletico Madrid": 1860,
    "Athletic Bilbao": 1780,
    "Real Sociedad": 1760,
    "Villarreal": 1740,
    "Real Betis": 1720,
    "Sevilla": 1700,
    "Girona": 1680,
    "Valencia": 1660,
    "Osasuna": 1620,
    "Celta Vigo": 1600,
    "Mallorca": 1580,
    "Rayo Vallecano": 1570,
    "Las Palmas": 1550,
    "Getafe": 1560,
    "Alaves": 1540,
    "Cadiz": 1520,
    "Granada": 1510,
    "Almeria": 1500,
    # Bundesliga
    "Bayern Munich": 1960,
    "Bayer Leverkusen": 1900,
    "Borussia Dortmund": 1880,
    "RB Leipzig": 1860,
    "Union Berlin": 1750,
    "SC Freiburg": 1740,
    "Freiburg": 1740,
    "Eintracht Frankfurt": 1730,
    "VfB Stuttgart": 1720,
    "Stuttgart": 1720,
    "Werder Bremen": 1680,
    "Hoffenheim": 1670,
    "Wolfsburg": 1660,
    "VfL Wolfsburg": 1660,
    "Mainz": 1640,
    "Mainz 05": 1640,
    "Augsburg": 1620,
    "FC Augsburg": 1620,
    "Borussia Monchengladbach": 1610,
    "Monchengladbach": 1610,
    "FC Koln": 1590,
    "Cologne": 1590,
    "Heidenheim": 1560,
    "Darmstadt": 1520,
    # Serie A
    "Inter Milan": 1920,
    "Napoli": 1880,
    "AC Milan": 1860,
    "Juventus": 1850,
    "Atalanta": 1840,
    "Roma": 1800,
    "AS Roma": 1800,
    "Lazio": 1780,
    "Fiorentina": 1740,
    "Bologna": 1720,
    "Torino": 1680,
    "Monza": 1640,
    "Udinese": 1630,
    "Sassuolo": 1610,
    "Genoa": 1600,
    "Lecce": 1580,
    "Cagliari": 1570,
    "Empoli": 1560,
    "Verona": 1550,
    "Hellas Verona": 1550,
    "Frosinone": 1530,
    "Salernitana": 1510,
    # Ligue 1
    "Paris Saint-Germain": 1920,
    "PSG": 1920,
    "Monaco": 1800,
    "AS Monaco": 1800,
    "Marseille": 1780,
    "Olympique Marseille": 1780,
    "Lyon": 1760,
    "Olympique Lyon": 1760,
    "Lille": 1750,
    "LOSC Lille": 1750,
    "Lens": 1740,
    "RC Lens": 1740,
    "Nice": 1720,
    "OGC Nice": 1720,
    "Rennes": 1700,
    "Stade Rennais": 1700,
    "Brest": 1660,
    "Stade Brestois": 1660,
    "Montpellier": 1640,
    "Toulouse": 1630,
    "Strasbourg": 1620,
    "Nantes": 1610,
    "FC Nantes": 1610,
    "Reims": 1600,
    "Stade de Reims": 1600,
    "Le Havre": 1560,
    "Lorient": 1550,
    "Metz": 1530,
    "Clermont": 1510,
}

# Squad values in millions EUR (approximate)
TEAM_SQUAD_VALUES: Dict[str, float] = {
    # EPL
    "Manchester City": 1200,
    "Arsenal": 950,
    "Liverpool": 900,
    "Chelsea": 850,
    "Manchester United": 800,
    "Newcastle United": 600,
    "Tottenham": 650,
    "Tottenham Hotspur": 650,
    "Brighton": 450,
    "Aston Villa": 500,
    "West Ham": 400,
    # La Liga
    "Real Madrid": 1100,
    "Barcelona": 900,
    "Atletico Madrid": 500,
    # Bundesliga
    "Bayern Munich": 950,
    "Bayer Leverkusen": 550,
    "Borussia Dortmund": 500,
    # Serie A
    "Inter Milan": 600,
    "AC Milan": 450,
    "Juventus": 500,
    "Napoli": 450,
    # Ligue 1
    "Paris Saint-Germain": 850,
    "PSG": 850,
    "Monaco": 380,
    "Marseille": 350,
}


def get_team_elo(team_name: str) -> float:
    """
    Get ELO rating for a team.

    Returns the team's ELO if known, otherwise generates a consistent
    hash-based rating between 1500-1650 to ensure different teams
    get different (but stable) ratings.
    """
    # Direct lookup
    if team_name in TEAM_ELO_RATINGS:
        return TEAM_ELO_RATINGS[team_name]

    # Try case-insensitive lookup
    for name, elo in TEAM_ELO_RATINGS.items():
        if name.lower() == team_name.lower():
            return elo

    # Try partial match (for variations like "FC Barcelona" -> "Barcelona")
    team_lower = team_name.lower()
    for name, elo in TEAM_ELO_RATINGS.items():
        if name.lower() in team_lower or team_lower in name.lower():
            return elo

    # Generate a stable hash-based rating for unknown teams
    # This ensures different teams always get different ratings
    hash_val = int(hashlib.md5(team_name.encode()).hexdigest()[:8], 16)
    # Range: 1500 to 1650 (average/unknown team range)
    return 1500 + (hash_val % 150)


def get_team_squad_value(team_name: str) -> float:
    """
    Get squad value for a team in millions EUR.

    Returns the team's value if known, otherwise generates a consistent
    hash-based value between 150-300 million.
    """
    # Direct lookup
    if team_name in TEAM_SQUAD_VALUES:
        return TEAM_SQUAD_VALUES[team_name]

    # Try case-insensitive lookup
    for name, value in TEAM_SQUAD_VALUES.items():
        if name.lower() == team_name.lower():
            return value

    # Try partial match
    team_lower = team_name.lower()
    for name, value in TEAM_SQUAD_VALUES.items():
        if name.lower() in team_lower or team_lower in name.lower():
            return value

    # Generate stable hash-based value for unknown teams
    hash_val = int(hashlib.md5(team_name.encode()).hexdigest()[:8], 16)
    # Range: 150 to 300 million (average team range)
    return 150 + (hash_val % 150)


def get_team_stats(team_name: str, is_home: bool = True) -> Dict[str, float]:
    """
    Generate team statistics based on ELO rating and squad value.

    This provides realistic stats differentiation between teams
    even when live data is unavailable.

    Args:
        team_name: Name of the team
        is_home: Whether this team is playing at home

    Returns:
        Dict with team statistics for feature generation
    """
    elo = get_team_elo(team_name)
    squad_value = get_team_squad_value(team_name)

    # Normalize ELO to 0-1 scale (1300-2000 range)
    elo_norm = (elo - 1300) / 700  # 0 = weakest, 1 = strongest
    elo_norm = max(0, min(1, elo_norm))  # Clamp to 0-1

    # Home advantage boost
    home_boost = 0.05 if is_home else 0

    # Generate differentiated statistics based on team strength
    return {
        # Form features (0-1 scale) - stronger teams have better form
        "win_rate": min(0.7, 0.35 + elo_norm * 0.35 + home_boost),
        "goals_per_game": 1.0 + elo_norm * 1.2,  # Range: 1.0 - 2.2
        "goals_conceded_per_game": 1.8 - elo_norm * 0.8,  # Range: 1.0 - 1.8 (inverted)
        # Attacking/defensive strength
        "attacking_strength": 0.5 + elo_norm * 0.4 + home_boost,
        "defensive_strength": 0.5 + elo_norm * 0.35,
        # xG-related
        "xg_avg": 1.0 + elo_norm * 1.0 + (0.15 if is_home else 0),
        "xg_conceded_avg": 1.6 - elo_norm * 0.6,
        # Squad value (for model features)
        "squad_value": squad_value,
        # Momentum/form (slight variation based on position)
        "form_5": 0.4 + elo_norm * 0.3 + home_boost,
        "form_10": 0.42 + elo_norm * 0.28,
        "form_20": 0.44 + elo_norm * 0.26,
        # Streaks (stronger teams maintain longer streaks)
        "win_streak": int(elo_norm * 4),
        "unbeaten_streak": int(2 + elo_norm * 6),
        # Clean sheets (better teams keep more)
        "clean_sheet_rate": 0.15 + elo_norm * 0.25,
        # Consistency
        "scoring_consistency": 0.55 + elo_norm * 0.25,
    }


def get_matchup_features(
    home_team: str, away_team: str, league: str = "EPL"
) -> Dict[str, float]:
    """
    Generate complete feature set for a matchup based on team strengths.

    This is used as a fallback when live data is unavailable, ensuring
    that different matchups produce different predictions.

    Args:
        home_team: Name of home team
        away_team: Name of away team
        league: League name (for context)

    Returns:
        Dict with all features needed for prediction
    """
    home_stats = get_team_stats(home_team, is_home=True)
    away_stats = get_team_stats(away_team, is_home=False)

    home_elo = get_team_elo(home_team)
    away_elo = get_team_elo(away_team)

    home_value = get_team_squad_value(home_team)
    away_value = get_team_squad_value(away_team)

    return {
        # Home team form features
        "home_form_5": home_stats["form_5"],
        "home_form_10": home_stats["form_10"],
        "home_form_20": home_stats["form_20"],
        "home_win_rate_5": home_stats["win_rate"],
        "home_goals_per_match_5": home_stats["goals_per_game"],
        # Away team form features
        "away_form_5": away_stats["form_5"],
        "away_form_10": away_stats["form_10"],
        "away_form_20": away_stats["form_20"],
        "away_win_rate_5": away_stats["win_rate"],
        "away_goals_per_match_5": away_stats["goals_per_game"],
        # xG features
        "home_xg_avg_5": home_stats["xg_avg"],
        "home_xg_conceded_avg_5": home_stats["xg_conceded_avg"],
        "home_xg_diff_5": home_stats["xg_avg"] - home_stats["xg_conceded_avg"],
        "home_xg_overperformance": 0.05 + (home_elo - 1500) / 5000,
        "home_xg_consistency": home_stats["scoring_consistency"],
        "away_xg_avg_5": away_stats["xg_avg"],
        "away_xg_conceded_avg_5": away_stats["xg_conceded_avg"],
        "away_xg_diff_5": away_stats["xg_avg"] - away_stats["xg_conceded_avg"],
        "away_xg_overperformance": 0.05 + (away_elo - 1500) / 5000,
        "away_xg_consistency": away_stats["scoring_consistency"],
        "xg_differential": home_stats["xg_avg"] - away_stats["xg_avg"],
        # ELO ratings
        "home_elo": home_elo,
        "away_elo": away_elo,
        "elo_difference": home_elo - away_elo,
        # Squad values
        "home_squad_value": home_value,
        "away_squad_value": away_value,
        "squad_value_diff": home_value - away_value,
        # Momentum features
        "home_momentum_lambda": 0.5 + home_stats["win_rate"] * 0.3,
        "home_momentum_weighted": home_stats["form_5"],
        "home_win_streak": home_stats["win_streak"],
        "home_unbeaten_streak": home_stats["unbeaten_streak"],
        "away_momentum_lambda": 0.5 + away_stats["win_rate"] * 0.3,
        "away_momentum_weighted": away_stats["form_5"],
        "away_win_streak": away_stats["win_streak"],
        "away_unbeaten_streak": away_stats["unbeaten_streak"],
        # Goal/GD features
        "home_goals_conceded_per_match_5": home_stats["goals_conceded_per_game"],
        "home_gd_avg_5": home_stats["goals_per_game"]
        - home_stats["goals_conceded_per_game"],
        "home_gd_trend": 0.05 if home_elo > 1600 else -0.02,
        "home_clean_sheets_5": home_stats["clean_sheet_rate"],
        "home_scoring_consistency": home_stats["scoring_consistency"],
        "away_goals_conceded_per_match_5": away_stats["goals_conceded_per_game"],
        "away_gd_avg_5": away_stats["goals_per_game"]
        - away_stats["goals_conceded_per_game"],
        "away_gd_trend": 0.05 if away_elo > 1600 else -0.02,
        "away_clean_sheets_5": away_stats["clean_sheet_rate"],
        "away_scoring_consistency": away_stats["scoring_consistency"],
        # Home advantage
        "home_advantage_win_rate": 0.50 + (home_elo - away_elo) / 2000,
        "home_goals_advantage": 0.25 + (home_elo - away_elo) / 3000,
        "away_win_rate_away": away_stats["win_rate"] * 0.85,
        "home_crowd_boost": 0.10 if home_elo > 1700 else 0.05,
        "home_advantage_coefficient": 1.10 + (home_elo - 1500) / 5000,
        "referee_home_bias": 0.52,
    }
