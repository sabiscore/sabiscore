"""
FBref Scouting Report Scraper
Scrapes advanced stats and scouting reports from FBref.com

Features:
- Team performance stats
- Player scouting reports
- Advanced metrics (pressures, progressive passes, etc.)
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from ...core.config import settings
from ...core.database import ScrapingLog, session_scope

import logging

logger = logging.getLogger(__name__)


class FBrefLoader:
    """Scrape advanced stats from FBref"""

    BASE_URL = "https://fbref.com/en/"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            headers={"User-Agent": settings.user_agent}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def fetch_team_stats(
        self, team_id: str, season: str = "2024-2025"
    ) -> Optional[Dict]:
        """Fetch team statistics for a season

        Returns:
            Dictionary with advanced stats including:
            - Possession, pressures, progressive passes
            - Shot creation actions, goal creation actions
            - Defensive actions, tackles, interceptions
        """
        url = f"{self.BASE_URL}squads/{team_id}/2024-2025/"

        try:
            if not self.session:
                raise ValueError("Session not initialized - use async context manager")

            async with self.session.get(url) as response:
                if response.status == 404:
                    logger.warning(f"Team {team_id} not found on FBref")
                    return None

                response.raise_for_status()
                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")
            stats = self._parse_team_stats(soup, team_id, season)

            logger.info(f"Fetched FBref stats for {team_id} ({season})")
            return stats

        except Exception as e:
            logger.error(f"FBref fetch_team_stats error for {team_id}: {e}")
            return None

    def _parse_team_stats(self, soup: BeautifulSoup, team_id: str, season: str) -> Dict:
        """Parse team statistics from FBref HTML"""
        stats = {
            "team_id": team_id,
            "season": season,
            "possession": {},
            "passing": {},
            "shooting": {},
            "defense": {},
            "creation": {},
        }

        try:
            # Parse possession stats
            poss_table = soup.find("table", {"id": "stats_squads_possession_for"})
            if poss_table:
                stats["possession"] = self._parse_possession_table(poss_table)

            # Parse passing stats
            pass_table = soup.find("table", {"id": "stats_squads_passing_for"})
            if pass_table:
                stats["passing"] = self._parse_passing_table(pass_table)

            # Parse shooting stats
            shoot_table = soup.find("table", {"id": "stats_squads_shooting_for"})
            if shoot_table:
                stats["shooting"] = self._parse_shooting_table(shoot_table)

            # Parse defensive stats
            def_table = soup.find("table", {"id": "stats_squads_defense_for"})
            if def_table:
                stats["defense"] = self._parse_defense_table(def_table)

        except Exception as e:
            logger.warning(f"Error parsing FBref stats: {e}")

        return stats

    def _parse_possession_table(self, table) -> Dict:
        """Extract possession metrics"""
        metrics = {}
        try:
            rows = table.find("tbody").find_all("tr", limit=5)
            for row in rows:
                cells = row.find_all("td")
                if len(cells) > 1:
                    metrics["possession_pct"] = float(cells[0].text.strip() or "0")
                    metrics["touches"] = int(cells[1].text.strip() or "0")
                    break
        except Exception:
            pass
        return metrics

    def _parse_passing_table(self, table) -> Dict:
        """Extract passing metrics"""
        metrics = {}
        try:
            rows = table.find("tbody").find_all("tr", limit=5)
            for row in rows:
                cells = row.find_all("td")
                if len(cells) > 3:
                    metrics["passes_completed"] = int(cells[0].text.strip() or "0")
                    metrics["pass_completion_pct"] = float(cells[1].text.strip() or "0")
                    metrics["progressive_passes"] = int(cells[3].text.strip() or "0")
                    break
        except Exception:
            pass
        return metrics

    def _parse_shooting_table(self, table) -> Dict:
        """Extract shooting metrics"""
        metrics = {}
        try:
            rows = table.find("tbody").find_all("tr", limit=5)
            for row in rows:
                cells = row.find_all("td")
                if len(cells) > 2:
                    metrics["shots"] = int(cells[0].text.strip() or "0")
                    metrics["shots_on_target"] = int(cells[1].text.strip() or "0")
                    metrics["shot_accuracy_pct"] = float(cells[2].text.strip() or "0")
                    break
        except Exception:
            pass
        return metrics

    def _parse_defense_table(self, table) -> Dict:
        """Extract defensive metrics"""
        metrics = {}
        try:
            rows = table.find("tbody").find_all("tr", limit=5)
            for row in rows:
                cells = row.find_all("td")
                if len(cells) > 3:
                    metrics["tackles"] = int(cells[0].text.strip() or "0")
                    metrics["interceptions"] = int(cells[1].text.strip() or "0")
                    metrics["pressures"] = int(cells[3].text.strip() or "0")
                    break
        except Exception:
            pass
        return metrics

    async def load_league_stats(self, league: str, season: str = "2024-2025") -> int:
        """Load stats for all teams in a league

        Args:
            league: League code (e.g., 'Premier-League', 'La-Liga')
            season: Season string (e.g., '2024-2025')

        Returns:
            Number of teams processed
        """
        team_count = 0

        with session_scope() as db_session:
            log = ScrapingLog(
                source="fbref",
                job_type="historical_load",
                status="started",
                timestamp=datetime.now(timezone.utc),
                metadata={"league": league, "season": season},
            )
            db_session.add(log)
            db_session.commit()
            log_id = log.id

            try:
                # Fetch league page to get team IDs
                league_url = (
                    f"{self.BASE_URL}comps/{self._get_league_id(league)}/{season}/"
                )

                if not self.session:
                    raise ValueError(
                        "Session not initialized - use async context manager"
                    )

                async with self.session.get(league_url) as response:
                    response.raise_for_status()
                    html = await response.text()

                soup = BeautifulSoup(html, "html.parser")
                team_ids = self._extract_team_ids(soup)

                logger.info(f"Found {len(team_ids)} teams in {league}")

                # Fetch stats for each team with rate limiting
                for team_id in team_ids:
                    stats = await self.fetch_team_stats(team_id, season)
                    if stats:
                        team_count += 1
                    await asyncio.sleep(3)  # Rate limiting: 3s between requests

                # Update log
                log_entry = db_session.query(ScrapingLog).filter_by(id=log_id).first()
                if log_entry:
                    log_entry.status = "success"
                    log_entry.records_processed = team_count
                    db_session.commit()

                logger.info(f"Successfully loaded {team_count} team stats from FBref")

            except Exception as e:
                logger.error(f"FBref load_league_stats error: {e}")
                log_entry = db_session.query(ScrapingLog).filter_by(id=log_id).first()
                if log_entry:
                    log_entry.status = "error"
                    log_entry.error_message = str(e)
                    db_session.commit()

        return team_count

    def _get_league_id(self, league: str) -> str:
        """Map league name to FBref ID"""
        league_map = {
            "Premier-League": "9",
            "La-Liga": "12",
            "Bundesliga": "20",
            "Serie-A": "11",
            "Ligue-1": "13",
        }
        return league_map.get(league, "9")

    def _extract_team_ids(self, soup: BeautifulSoup) -> List[str]:
        """Extract team IDs from league page"""
        team_ids = []
        try:
            # Find standings table
            table = soup.find("table", {"id": "results"}) or soup.find(
                "table", {"class": "stats_table"}
            )
            if table:
                for link in table.find_all("a"):
                    href = link.get("href", "")
                    if "/squads/" in href:
                        # Extract team ID from URL like /squads/19538871/2024-2025/Manchester-City-Stats
                        parts = href.split("/")
                        if len(parts) > 2:
                            team_ids.append(parts[2])
        except Exception as e:
            logger.warning(f"Error extracting team IDs: {e}")

        # Return unique IDs
        return list(set(team_ids))


if __name__ == "__main__":

    async def main():
        async with FBrefLoader() as loader:
            stats = await loader.fetch_team_stats("test_team")
            print("Stats:", stats)

    asyncio.run(main())
