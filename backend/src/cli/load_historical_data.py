"""
Historical Data Loader - Import matches and odds from football-data.co.uk CSV files

This script downloads and imports historical match data from football-data.co.uk,
which provides comprehensive historical data for top European leagues including:
- Match results (home/away scores)
- Bookmaker odds (62 bookmakers for closing lines)
- Match statistics (shots, corners, cards)

Usage: python -m backend.src.cli.load_historical_data
"""

import logging
import pandas as pd
from datetime import datetime
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import SSLError, RequestException
from urllib3.util.retry import Retry
import urllib3
import uuid
from typing import Dict
from sqlalchemy.orm import Session

from ..core.logging import configure_logging
from ..core.database import get_db, Match, MatchStats, Odds, Team, League
from ..core.config import settings

configure_logging()
logger = logging.getLogger(__name__)


class HistoricalDataLoader:
    """Load historical match data from football-data.co.uk"""

    # Map football-data.co.uk league codes to our league names
    LEAGUE_MAPPING = {
        "E0": ("Premier League", "England"),
        "D1": ("Bundesliga", "Germany"),
        "SP1": ("La Liga", "Spain"),
        "I1": ("Serie A", "Italy"),
        "F1": ("Ligue 1", "France"),
    }

    # Seasons to load (last 6 years for training)
    SEASONS = ["1819", "1920", "2021", "2122", "2223", "2324", "2425"]

    BASE_URL = "https://www.football-data.co.uk/mmz4281"

    def __init__(self):
        self.db_session: Session = next(get_db())
        self.data_path = settings.data_path / "raw"
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.session = self._create_http_session()

    def _create_http_session(self) -> requests.Session:
        """Configure resilient HTTP session for football-data downloads"""
        session = requests.Session()
        retry = Retry(
            total=5,
            read=5,
            connect=5,
            backoff_factor=1.2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; SabiScoreDataLoader/1.0; +https://sabiscore.com)",
                "Accept": "text/csv,application/octet-stream;q=0.9,*/*;q=0.8",
            }
        )
        return session

    def load_all_leagues(self):
        """Load historical data for all leagues"""
        results = {}

        for league_code, (league_name, country) in self.LEAGUE_MAPPING.items():
            logger.info(f"Loading {league_name} ({country})...")
            try:
                result = self._load_league(league_code, league_name, country)
                results[league_name] = result
            except Exception as e:
                logger.error(f"Failed to load {league_name}: {e}", exc_info=True)
                results[league_name] = {"error": str(e)}

        return results

    def _load_league(self, league_code: str, league_name: str, country: str) -> Dict:
        """Load data for a single league across all seasons"""

        # Map league names to IDs
        league_id_map = {
            "Premier League": "EPL",
            "Bundesliga": "Bundesliga",
            "La Liga": "La Liga",
            "Serie A": "Serie A",
            "Ligue 1": "Ligue 1",
        }

        # Ensure league exists
        league_id = league_id_map.get(league_name)
        league = self.db_session.query(League).filter_by(id=league_id).first()
        if not league:
            league = League(id=league_id, name=league_name, country=country, tier=1)
            self.db_session.add(league)
            self.db_session.commit()
            logger.info(f"Created league: {league_name} ({league_id})")

        total_matches = 0
        total_odds = 0

        for season in self.SEASONS:
            logger.info(f"Loading season {season}...")

            # Download CSV
            csv_path = self._download_season_data(league_code, season)
            if not csv_path:
                logger.warning(f"Skipping {season} - download failed")
                continue

            # Parse and import
            matches, odds_count = self._import_season_data(csv_path, league, season)
            total_matches += matches
            total_odds += odds_count

        return {
            "matches": total_matches,
            "odds": total_odds,
        }

    def _download_season_data(self, league_code: str, season: str) -> Path:
        """Download CSV file for a specific league/season"""
        url = f"{self.BASE_URL}/{season}/{league_code}.csv"
        filename = self.data_path / f"{league_code}_{season}.csv"

        if filename.exists():
            logger.info(f"Using cached file: {filename}")
            return filename

        try:
            logger.info(f"Downloading {url}...")
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

        except SSLError as ssl_error:
            logger.warning(
                f"TLS handshake failed for {url}: {ssl_error}. Retrying with backoff..."
            )
            # Exponential backoff for SSL/EOF errors (3 attempts)
            for attempt in range(3):
                try:
                    import time

                    wait_time = (2**attempt) * 0.5  # 0.5s, 1s, 2s
                    if attempt > 0:
                        logger.info(
                            f"Retry attempt {attempt + 1}/3 after {wait_time}s delay..."
                        )
                        time.sleep(wait_time)

                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                    response = requests.get(
                        url,
                        timeout=30,
                        headers=self.session.headers,
                        verify=False,
                    )
                    response.raise_for_status()
                    logger.info(
                        f"Successfully downloaded after {attempt + 1} attempt(s)"
                    )
                    break
                except Exception as retry_error:
                    if attempt == 2:  # Last attempt
                        logger.error(
                            f"Failed to download {url} after 3 retry attempts: {retry_error}"
                        )
                        return None
                    logger.warning(f"Attempt {attempt + 1} failed: {retry_error}")
        except RequestException as e:
            logger.error(f"Failed to download {url}: {e}")
            return None

        filename.write_bytes(response.content)
        logger.info(f"Saved to {filename}")
        return filename

    def _import_season_data(self, csv_path: Path, league: League, season: str) -> tuple:
        """Import matches and odds from CSV file"""

        try:
            df = pd.read_csv(csv_path, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, encoding="iso-8859-1")

        matches_imported = 0
        odds_imported = 0

        for _, row in df.iterrows():
            try:
                # Parse date
                date_str = row.get("Date")
                if pd.isna(date_str):
                    continue

                # Try different date formats
                for fmt in ["%d/%m/%Y", "%d/%m/%y"]:
                    try:
                        match_date = datetime.strptime(str(date_str), fmt)
                        break
                    except ValueError:
                        continue
                else:
                    logger.warning(f"Could not parse date: {date_str}")
                    continue

                # Get teams
                home_team_name = str(row.get("HomeTeam", "")).strip()
                away_team_name = str(row.get("AwayTeam", "")).strip()

                if not home_team_name or not away_team_name:
                    continue

                # Ensure teams exist
                home_team = self._get_or_create_team(home_team_name, league)
                away_team = self._get_or_create_team(away_team_name, league)

                # Check if match already exists
                existing = (
                    self.db_session.query(Match)
                    .filter(
                        Match.league_id == league.id,
                        Match.home_team_id == home_team.id,
                        Match.away_team_id == away_team.id,
                        Match.match_date == match_date,
                    )
                    .first()
                )

                if existing:
                    continue  # Skip duplicates

                # Create match
                match = Match(
                    league_id=league.id,
                    home_team_id=home_team.id,
                    away_team_id=away_team.id,
                    match_date=match_date,
                    season=season,
                    status="completed",
                    home_score=int(row.get("FTHG", 0))
                    if not pd.isna(row.get("FTHG"))
                    else None,
                    away_score=int(row.get("FTAG", 0))
                    if not pd.isna(row.get("FTAG"))
                    else None,
                )
                self.db_session.add(match)
                self.db_session.flush()  # Get match ID

                matches_imported += 1

                # Import match stats if available
                if not pd.isna(row.get("HS")):  # Home shots
                    home_stats = MatchStats(
                        match_id=match.id,
                        team_id=home_team.id,
                        shots=int(row.get("HS", 0)),
                        shots_on_target=int(row.get("HST", 0))
                        if not pd.isna(row.get("HST"))
                        else None,
                        corners=int(row.get("HC", 0))
                        if not pd.isna(row.get("HC"))
                        else None,
                        fouls=int(row.get("HF", 0))
                        if not pd.isna(row.get("HF"))
                        else None,
                        yellow_cards=int(row.get("HY", 0))
                        if not pd.isna(row.get("HY"))
                        else None,
                        red_cards=int(row.get("HR", 0))
                        if not pd.isna(row.get("HR"))
                        else None,
                    )
                    self.db_session.add(home_stats)

                    away_stats = MatchStats(
                        match_id=match.id,
                        team_id=away_team.id,
                        shots=int(row.get("AS", 0)),
                        shots_on_target=int(row.get("AST", 0))
                        if not pd.isna(row.get("AST"))
                        else None,
                        corners=int(row.get("AC", 0))
                        if not pd.isna(row.get("AC"))
                        else None,
                        fouls=int(row.get("AF", 0))
                        if not pd.isna(row.get("AF"))
                        else None,
                        yellow_cards=int(row.get("AY", 0))
                        if not pd.isna(row.get("AY"))
                        else None,
                        red_cards=int(row.get("AR", 0))
                        if not pd.isna(row.get("AR"))
                        else None,
                    )
                    self.db_session.add(away_stats)

                # Import closing odds (use Pinnacle/B365 as they're most reliable)
                bookmakers = {
                    "Pinnacle": ("PS", "PSH", "PSD", "PSA"),
                    "Bet365": ("B365", "B365H", "B365D", "B365A"),
                }

                for bookmaker, (prefix, h_col, d_col, a_col) in bookmakers.items():
                    home_odds = row.get(h_col)
                    draw_odds = row.get(d_col)
                    away_odds = row.get(a_col)

                    if not pd.isna(home_odds) and not pd.isna(away_odds):
                        odds = Odds(
                            match_id=match.id,
                            bookmaker=bookmaker,
                            home_win=float(home_odds),
                            draw=float(draw_odds) if not pd.isna(draw_odds) else None,
                            away_win=float(away_odds),
                            timestamp=match_date,  # Closing odds
                        )
                        self.db_session.add(odds)
                        odds_imported += 1

            except Exception as e:
                logger.error(f"Failed to import row: {e}")
                self.db_session.rollback()  # Rollback failed transaction
                continue

        # Commit all changes for this season
        try:
            self.db_session.commit()
            logger.info(
                f"Imported {matches_imported} matches, {odds_imported} odds records"
            )
        except Exception as e:
            logger.error(f"Failed to commit season data: {e}")
            self.db_session.rollback()

        return matches_imported, odds_imported

    def _get_or_create_team(self, team_name: str, league: League) -> Team:
        """Get or create team by name"""
        team = (
            self.db_session.query(Team)
            .filter_by(name=team_name, league_id=league.id)
            .first()
        )

        if not team:
            team = Team(
                id=str(uuid.uuid4()),
                name=team_name,
                league_id=league.id,
            )
            self.db_session.add(team)
            self.db_session.flush()
            logger.info(f"Created team: {team_name}")

        return team


def main():
    """Main entry point"""
    logger.info("=== SabiScore Historical Data Loader ===")

    try:
        loader = HistoricalDataLoader()
        results = loader.load_all_leagues()

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("IMPORT SUMMARY")
        logger.info("=" * 60)

        total_matches = 0
        total_odds = 0

        for league, result in results.items():
            if "error" in result:
                logger.error(f"✗ {league}: {result['error']}")
            else:
                logger.info(f"✓ {league}:")
                logger.info(f"  - Matches: {result['matches']:,}")
                logger.info(f"  - Odds: {result['odds']:,}")
                total_matches += result["matches"]
                total_odds += result["odds"]

        logger.info("=" * 60)
        logger.info(f"Total Matches: {total_matches:,}")
        logger.info(f"Total Odds: {total_odds:,}")
        logger.info("=" * 60)

    except KeyboardInterrupt:
        logger.info("Import interrupted by user")
    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)


if __name__ == "__main__":
    main()
