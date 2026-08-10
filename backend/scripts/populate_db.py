#!/usr/bin/env python3
"""Populate database with authenticated open football data feeds."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import requests
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import settings
from src.core.database import Match, League, SessionLocal, Team

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


DATA_SOURCES: Dict[str, str] = {
    "EPL": "https://raw.githubusercontent.com/openfootball/football.json/master/2023-24/en.1.json",
    "La Liga": "https://raw.githubusercontent.com/openfootball/football.json/master/2023-24/es.1.json",
    "Bundesliga": "https://raw.githubusercontent.com/openfootball/football.json/master/2023-24/de.1.json",
    "Serie A": "https://raw.githubusercontent.com/openfootball/football.json/master/2023-24/it.1.json",
    "Ligue 1": "https://raw.githubusercontent.com/openfootball/football.json/master/2023-24/fr.1.json",
}

CACHE_DIR = (Path(__file__).resolve().parents[2] / "data" / "processed").resolve()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

HTTP_HEADERS = {"User-Agent": settings.user_agent}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or name.lower()


def load_league_matches(league_id: str) -> List[Dict[str, str]]:
    source_url = DATA_SOURCES[league_id]
    cache_path = CACHE_DIR / f"{league_id.lower()}_matches.json"

    if cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        response = requests.get(source_url, headers=HTTP_HEADERS, timeout=settings.request_timeout * 3)
        response.raise_for_status()
        payload = response.json()
        cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _team_name(team_entry: Any) -> Optional[str]:
        if isinstance(team_entry, dict):
            return team_entry.get("name") or team_entry.get("code") or team_entry.get("id")
        if isinstance(team_entry, str):
            return team_entry
        return None

    def _score_value(value: Any, index: int) -> Optional[int]:
        if isinstance(value, list) and len(value) > index:
            return value[index]
        if isinstance(value, str):
            parts = value.split("-")
            if len(parts) == 2 and parts[index].strip().isdigit():
                return int(parts[index].strip())
        return None

    matches: List[Dict[str, Any]] = []

    rounds = payload.get("rounds")
    fixtures = payload.get("matches")

    iterable = []
    if isinstance(rounds, list) and rounds:
        for round_info in rounds:
            for match in round_info.get("matches", []):
                iterable.append((round_info.get("name"), match))
    elif isinstance(fixtures, list):
        iterable = [(match.get("round"), match) for match in fixtures]

    for round_name, match in iterable:
        home_name = _team_name(match.get("team1"))
        away_name = _team_name(match.get("team2"))

        if not home_name or not away_name:
            logger.debug("Skipping match with missing team names", extra={"match": match})
            continue

        date_str = match.get("date")
        time_str = match.get("time")
        if date_str and time_str:
            date_value = f"{date_str} {time_str}"
        else:
            date_value = date_str

        score = match.get("score", {})
        ft_value = score.get("ft")

        matches.append(
            {
                "date": date_value,
                "home": home_name,
                "away": away_name,
                "home_score": _score_value(ft_value, 0),
                "away_score": _score_value(ft_value, 1),
                "round": round_name,
            }
        )

    return matches


def ensure_team(session: Session, league: League, team_name: str) -> Team:
    team_id = slugify(team_name)
    team = session.get(Team, team_id)
    if team:
        return team

    team = Team(
        id=team_id,
        name=team_name,
        league_id=league.id,
        country=league.country,
        active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(team)
    session.flush()
    return team


def ensure_league_teams(session: Session, league: League, matches: Iterable[Dict[str, str]]) -> None:
    team_names: Set[str] = set()
    for record in matches:
        if record.get("home"):
            team_names.add(record["home"])
        if record.get("away"):
            team_names.add(record["away"])

    for name in sorted(team_names):
        try:
            ensure_team(session, league, name)
        except SQLAlchemyError as error:
            session.rollback()
            logger.error("Failed to ensure team %s in league %s: %s", name, league.id, error)
        else:
            session.commit()


def parse_match_date(raw_date: str) -> datetime:
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw_date, fmt)
        except (TypeError, ValueError):
            continue
    raise ValueError(f"Unsupported date format: {raw_date}")


def season_label(dt: datetime) -> str:
    return f"{dt.year}/{dt.year + 1}" if dt.month >= 7 else f"{dt.year - 1}/{dt.year}"


def upsert_league_matches(session: Session, league: League, matches: Iterable[Dict[str, Any]]) -> int:
    inserted = 0
    for record in matches:
        logger.debug("Processing match record", extra={"record": record})
        try:
            home = ensure_team(session, league, record["home"])
            away = ensure_team(session, league, record["away"])
            match_date = parse_match_date(record["date"])

            existing = (
                session.query(Match)
                .filter(
                    Match.league_id == league.id,
                    Match.home_team_id == home.id,
                    Match.away_team_id == away.id,
                    Match.match_date == match_date,
                )
                .first()
            )
            if existing:
                continue

            match = Match(
                league_id=league.id,
                home_team_id=home.id,
                away_team_id=away.id,
                match_date=match_date,
                season=season_label(match_date),
                status="finished" if record.get("home_score") is not None else "scheduled",
                home_score=record.get("home_score"),
                away_score=record.get("away_score"),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(match)
            inserted += 1
            logger.debug(
                "Staged match %s vs %s (%s)",
                home.name,
                away.name,
                match_date.isoformat(),
            )
        except Exception as error:  # noqa: BLE001
            session.rollback()
            logger.warning(
                "Skipped match %s vs %s on %s due to error: %s",
                record.get("home"),
                record.get("away"),
                record.get("date"),
                error,
            )
        else:
            session.flush()
            session.commit()

    return inserted


def populate_database() -> None:
    logger.info("Starting database population from openfootball datasets...")
    session = SessionLocal()

    try:
        target_leagues = session.query(League).filter(League.id.in_(DATA_SOURCES.keys())).all()
        if not target_leagues:
            logger.error("No target leagues found. Ensure init_db.py has seeded league metadata.")
            return

        for league in target_leagues:
            logger.info("Processing league %s (%s)", league.name, league.id)

            try:
                matches = load_league_matches(league.id)
                ensure_league_teams(session, league, matches)

                inserted = upsert_league_matches(session, league, matches)
                session.commit()
                logger.info("Inserted %d matches for %s", inserted, league.name)
            except (requests.RequestException, ValueError) as error:
                session.rollback()
                logger.error("Failed to ingest league %s: %s", league.id, error)
            except SQLAlchemyError as error:
                session.rollback()
                logger.error("Database error for league %s: %s", league.id, error)

    finally:
        session.close()
        logger.info("Database population finished.")


if __name__ == "__main__":
    populate_database()
