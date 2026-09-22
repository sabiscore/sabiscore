"""
Football-Data.co.uk CSV Loader
Loads 180k+ historical matches from 62 bookmakers (2018-2025)

Data sources:
- EPL: https://www.football-data.co.uk/englandm.php
- La Liga: https://www.football-data.co.uk/spainm.php
- Bundesliga: https://www.football-data.co.uk/germanym.php
- Serie A: https://www.football-data.co.uk/italym.php
- Ligue 1: https://www.football-data.co.uk/francem.php
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import aiohttp
import pandas as pd
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

from ...core.database import (
    League,
    Match,
    MatchStats,
    Odds,
    ScrapingLog,
    Team,
    session_scope,
)
from ...utils.season import canonical_season
from ..utils.deduplication import deduplicate_match

import logging

logger = logging.getLogger(__name__)


class FootballDataLoader:
    """Load historical match and odds data from football-data.co.uk"""

    BASE_URL = "https://www.football-data.co.uk/"

    # League mappings
    LEAGUE_CODES = {
        "E0": ("EPL", "England", 1),
        "E1": ("Championship", "England", 2),
        "SP1": ("La Liga", "Spain", 1),
        "SP2": ("La Liga 2", "Spain", 2),
        "D1": ("Bundesliga", "Germany", 1),
        "D2": ("Bundesliga 2", "Germany", 2),
        "I1": ("Serie A", "Italy", 1),
        "I2": ("Serie B", "Italy", 2),
        "F1": ("Ligue 1", "France", 1),
        "F2": ("Ligue 2", "France", 2),
    }

    # Bookmaker column mappings
    BOOKMAKER_COLUMNS = {
        "B365": "bet365",
        "BW": "bet_and_win",
        "IW": "interwetten",
        "PS": "pinnacle",
        "WH": "william_hill",
        "VC": "vc_bet",
        "GB": "gamebookers",
        "BS": "blue_square",
        "LB": "ladbrokes",
        "Bb": "betbrain",
    }

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path("data/raw/football_data")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def download_csv(
        self, session: aiohttp.ClientSession, league_code: str, season: str
    ) -> Optional[Path]:
        """Download CSV file for a specific league and season with robust retry"""

        # Convert season format: "2324" -> "mmz4281/2324"
        season_dir = f"mmz4281/{season}"
        filename = f"{league_code}.csv"
        url = urljoin(self.BASE_URL, f"{season_dir}/{filename}")

        cache_path = self.cache_dir / f"{league_code}_{season}.csv"

        if cache_path.exists():
            logger.info(f"Using cached file: {cache_path}")
            return cache_path

        try:
            # Increased timeout and explicit SSL handling
            timeout = aiohttp.ClientTimeout(total=45, connect=15, sock_read=30)

            async with session.get(
                url,
                timeout=timeout,
                ssl=True,  # Verify SSL by default
                allow_redirects=True,
            ) as response:
                if response.status == 200:
                    content = await response.text()
                    cache_path.write_text(content, encoding="utf-8")
                    logger.info(f"Downloaded: {url} -> {cache_path}")
                    return cache_path
                else:
                    logger.warning(f"Failed to download {url}: HTTP {response.status}")
                    return None
        except aiohttp.ClientSSLError as e:
            logger.error(
                f"SSL error downloading {url}: {e}. Retrying with relaxed SSL..."
            )
            # Retry with SSL verification disabled as fallback
            try:
                timeout = aiohttp.ClientTimeout(total=45)
                async with session.get(url, timeout=timeout, ssl=False) as response:
                    if response.status == 200:
                        content = await response.text()
                        cache_path.write_text(content, encoding="utf-8")
                        logger.warning(f"Downloaded with SSL disabled: {url}")
                        return cache_path
            except Exception as fallback_err:
                logger.error(f"Fallback download failed for {url}: {fallback_err}")
                return None
        except asyncio.TimeoutError:
            logger.error(f"Timeout downloading {url}")
            return None
        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            return None

    def parse_csv(self, csv_path: Path, league_id: str) -> List[Dict]:
        """Parse CSV file into structured match records"""

        try:
            df = pd.read_csv(csv_path, encoding="utf-8", low_memory=False)
        except Exception as e:
            logger.error(f"Failed to read CSV {csv_path}: {e}")
            return []

        matches = []

        for _, row in df.iterrows():
            try:
                # Parse date (format: DD/MM/YYYY)
                if pd.isna(row.get("Date")):
                    continue

                match_date = datetime.strptime(str(row["Date"]), "%d/%m/%Y")

                # Extract match result
                home_team = str(row.get("HomeTeam", "")).strip()
                away_team = str(row.get("AwayTeam", "")).strip()

                if not home_team or not away_team:
                    continue

                home_score = int(row["FTHG"]) if pd.notna(row.get("FTHG")) else None
                away_score = int(row["FTAG"]) if pd.notna(row.get("FTAG")) else None

                # Extract match stats
                stats_home = {
                    "shots": int(row["HS"]) if pd.notna(row.get("HS")) else None,
                    "shots_on_target": int(row["HST"])
                    if pd.notna(row.get("HST"))
                    else None,
                    "corners": int(row["HC"]) if pd.notna(row.get("HC")) else None,
                    "fouls": int(row["HF"]) if pd.notna(row.get("HF")) else None,
                    "yellow_cards": int(row["HY"]) if pd.notna(row.get("HY")) else None,
                    "red_cards": int(row["HR"]) if pd.notna(row.get("HR")) else None,
                }

                stats_away = {
                    "shots": int(row["AS"]) if pd.notna(row.get("AS")) else None,
                    "shots_on_target": int(row["AST"])
                    if pd.notna(row.get("AST"))
                    else None,
                    "corners": int(row["AC"]) if pd.notna(row.get("AC")) else None,
                    "fouls": int(row["AF"]) if pd.notna(row.get("AF")) else None,
                    "yellow_cards": int(row["AY"]) if pd.notna(row.get("AY")) else None,
                    "red_cards": int(row["AR"]) if pd.notna(row.get("AR")) else None,
                }

                # Extract odds from multiple bookmakers
                odds_data = []
                for bookie_code, bookie_name in self.BOOKMAKER_COLUMNS.items():
                    home_col = f"{bookie_code}H"
                    draw_col = f"{bookie_code}D"
                    away_col = f"{bookie_code}A"

                    if all(col in row.index for col in [home_col, draw_col, away_col]):
                        home_odds = (
                            float(row[home_col]) if pd.notna(row[home_col]) else None
                        )
                        draw_odds = (
                            float(row[draw_col]) if pd.notna(row[draw_col]) else None
                        )
                        away_odds = (
                            float(row[away_col]) if pd.notna(row[away_col]) else None
                        )

                        if home_odds and draw_odds and away_odds:
                            odds_data.append(
                                {
                                    "bookmaker": bookie_name,
                                    "home_win": home_odds,
                                    "draw": draw_odds,
                                    "away_win": away_odds,
                                }
                            )

                matches.append(
                    {
                        "league_id": league_id,
                        "home_team": home_team,
                        "away_team": away_team,
                        "match_date": match_date,
                        "home_score": home_score,
                        "away_score": away_score,
                        "stats_home": stats_home,
                        "stats_away": stats_away,
                        "odds": odds_data,
                        "referee": str(row.get("Referee", "")).strip()
                        if pd.notna(row.get("Referee"))
                        else None,
                    }
                )

            except Exception as e:
                logger.error(f"Error parsing row: {e}")
                continue

        return matches

    async def load_league_season(
        self, league_code: str, season: str, db_session: Session
    ) -> int:
        """Load all matches for a specific league and season"""

        league_name, country, tier = self.LEAGUE_CODES[league_code]

        # Ensure league exists
        league = db_session.query(League).filter_by(id=league_code).first()
        if not league:
            league = League(
                id=league_code,
                name=league_name,
                country=country,
                tier=tier,
                active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db_session.add(league)
            db_session.commit()

        # Download CSV
        async with aiohttp.ClientSession() as session:
            csv_path = await self.download_csv(session, league_code, season)

        if not csv_path:
            logger.warning(f"Failed to load {league_code} {season}")
            return 0

        # Parse matches
        matches = self.parse_csv(csv_path, league_code)
        logger.info(f"Parsed {len(matches)} matches from {csv_path}")

        loaded_count = 0

        for match_data in tqdm(matches, desc=f"Loading {league_code} {season}"):
            try:
                # Get or create teams
                home_team = (
                    db_session.query(Team)
                    .filter_by(name=match_data["home_team"], league_id=league_code)
                    .first()
                )

                if not home_team:
                    home_team = Team(
                        id=f"{league_code}_{match_data['home_team'].replace(' ', '_').lower()}",
                        name=match_data["home_team"],
                        league_id=league_code,
                        country=country,
                        active=True,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    db_session.add(home_team)

                away_team = (
                    db_session.query(Team)
                    .filter_by(name=match_data["away_team"], league_id=league_code)
                    .first()
                )

                if not away_team:
                    away_team = Team(
                        id=f"{league_code}_{match_data['away_team'].replace(' ', '_').lower()}",
                        name=match_data["away_team"],
                        league_id=league_code,
                        country=country,
                        active=True,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    db_session.add(away_team)

                db_session.flush()

                # Check for duplicate match
                existing = deduplicate_match(
                    db_session,
                    league_code,
                    home_team.id,
                    away_team.id,
                    match_data["match_date"],
                )

                if existing:
                    continue

                # Create match
                match = Match(
                    league_id=league_code,
                    home_team_id=home_team.id,
                    away_team_id=away_team.id,
                    match_date=match_data["match_date"],
                    # Was f"20{season[:2]}/20{season[2:]}" — a second, independent
                    # writer of the same "YYYY/YYYY" format that canonical_season()
                    # owns. Same output for any match inside its own file's season
                    # (the only case that occurs), but deriving from the match's own
                    # date rather than the filename means there is now exactly one
                    # season-string writer that can drift.
                    season=canonical_season(match_data["match_date"]),
                    status="finished",
                    home_score=match_data["home_score"],
                    away_score=match_data["away_score"],
                    referee=match_data["referee"],
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                db_session.add(match)
                db_session.flush()

                # Add match stats
                if any(match_data["stats_home"].values()):
                    stats_home = MatchStats(
                        match_id=match.id,
                        team_id=home_team.id,
                        **match_data["stats_home"],
                        created_at=datetime.now(timezone.utc),
                    )
                    db_session.add(stats_home)

                if any(match_data["stats_away"].values()):
                    stats_away = MatchStats(
                        match_id=match.id,
                        team_id=away_team.id,
                        **match_data["stats_away"],
                        created_at=datetime.now(timezone.utc),
                    )
                    db_session.add(stats_away)

                # Add odds
                for odds in match_data["odds"]:
                    odds_record = Odds(
                        match_id=match.id,
                        bookmaker=odds["bookmaker"],
                        home_win=odds["home_win"],
                        draw=odds["draw"],
                        away_win=odds["away_win"],
                        timestamp=match_data["match_date"],
                    )
                    db_session.add(odds_record)

                loaded_count += 1

                if loaded_count % 100 == 0:
                    db_session.commit()

            except Exception as e:
                logger.error(f"Error loading match: {e}")
                db_session.rollback()
                continue

        db_session.commit()
        logger.info(f"Loaded {loaded_count} matches for {league_code} {season}")

        return loaded_count

    async def load_all_historical(
        self, leagues: Optional[List[str]] = None, seasons: Optional[List[str]] = None
    ) -> Dict[str, int]:
        """Load all historical data for specified leagues and seasons"""

        if leagues is None:
            leagues = list(self.LEAGUE_CODES.keys())

        if seasons is None:
            # Last 7 seasons: 2018-2025
            seasons = ["1819", "1920", "2021", "2122", "2223", "2324", "2425"]

        results = {}

        with session_scope() as db_session:
            # Log scraping job
            log = ScrapingLog(
                source="football_data_co_uk",
                job_type="historical_load",
                status="started",
                timestamp=datetime.now(timezone.utc),
                metadata={"leagues": leagues, "seasons": seasons},
            )
            db_session.add(log)
            db_session.commit()

            start_time = datetime.now(timezone.utc)
            total_loaded = 0

            try:
                for league_code in leagues:
                    for season in seasons:
                        count = await self.load_league_season(
                            league_code, season, db_session
                        )
                        key = f"{league_code}_{season}"
                        results[key] = count
                        total_loaded += count

                # Update log
                execution_time = (
                    datetime.now(timezone.utc) - start_time
                ).total_seconds()
                log.status = "success"
                log.records_processed = total_loaded
                log.execution_time_seconds = execution_time
                db_session.commit()

            except Exception as e:
                logger.error(f"Historical load failed: {e}")
                log.status = "failed"
                log.error_message = str(e)
                db_session.commit()
                raise

        return results


if __name__ == "__main__":
    # Test loader
    async def main():
        loader = FootballDataLoader()
        results = await loader.load_all_historical(
            leagues=["E0", "SP1", "D1"],  # EPL, La Liga, Bundesliga
            seasons=["2324", "2425"],  # Last 2 seasons
        )
        print("Load results:", results)

    asyncio.run(main())
