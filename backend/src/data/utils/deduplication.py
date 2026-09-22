"""
Utility functions for data loading and processing
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ...core.database import Match


def deduplicate_match(
    db_session: Session,
    league_id: str,
    home_team_id: str,
    away_team_id: str,
    match_date: datetime,
    tolerance_hours: int = 24,
) -> Optional[Match]:
    """
    Check if a match already exists in the database

    Args:
        db_session: Database session
        league_id: League ID
        home_team_id: Home team ID
        away_team_id: Away team ID
        match_date: Match date
        tolerance_hours: Time window for duplicate detection (default: 24 hours)

    Returns:
        Existing match if found, None otherwise
    """

    start_window = match_date - timedelta(hours=tolerance_hours)
    end_window = match_date + timedelta(hours=tolerance_hours)

    existing = (
        db_session.query(Match)
        .filter(
            Match.league_id == league_id,
            Match.home_team_id == home_team_id,
            Match.away_team_id == away_team_id,
            Match.match_date >= start_window,
            Match.match_date <= end_window,
        )
        .first()
    )

    return existing


def normalize_team_name(name: str) -> str:
    """Normalize team name for matching across data sources"""

    # Common replacements
    replacements = {
        "manchester united": "man united",
        "manchester city": "man city",
        "tottenham hotspur": "tottenham",
        "wolverhampton wanderers": "wolves",
        "brighton & hove albion": "brighton",
        "newcastle united": "newcastle",
        "sheffield united": "sheffield utd",
        "west ham united": "west ham",
        "aston villa": "villa",
        "nottingham forest": "nott'm forest",
    }

    normalized = name.lower().strip()

    return replacements.get(normalized, normalized)


def calculate_season_string(date: datetime) -> str:
    """
    Calculate season string from match date

    Args:
        date: Match date

    Returns:
        Season string in format "2023/2024"
    """

    year = date.year
    month = date.month

    # Football season typically runs August-May
    if month >= 8:
        return f"{year}/{year + 1}"
    else:
        return f"{year - 1}/{year}"
