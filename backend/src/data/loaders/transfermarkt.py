"""
Transfermarkt Player Valuation Loader
Scrapes player market valuations from Transfermarkt.com

Features:
- Player market values
- Squad valuations
- Transfer history
- Injury tracking
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential
from sqlalchemy.orm import Session

from ...core.config import settings
from ...core.database import (
    PlayerValuation,
    ScrapingLog,
    session_scope,
)

import logging

logger = logging.getLogger(__name__)


class TransfermarktLoader:
    """Scrape player valuations from Transfermarkt"""

    BASE_URL = "https://www.transfermarkt.com/"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            headers={
                "User-Agent": settings.user_agent,
                "Accept-Language": "en-US,en;q=0.9",
            }
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
    async def fetch_player_value(self, player_id: str) -> Optional[Dict]:
        """Fetch current market value for a player

        Args:
            player_id: Transfermarkt player ID

        Returns:
            Dictionary with player valuation and metadata
        """
        url = f"{self.BASE_URL}player/profil/spieler/{player_id}"

        try:
            if not self.session:
                raise ValueError("Session not initialized - use async context manager")

            async with self.session.get(url) as response:
                if response.status == 404:
                    logger.warning(f"Player {player_id} not found on Transfermarkt")
                    return None

                response.raise_for_status()
                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")

            # Extract market value
            value_elem = soup.find(
                "div", {"class": "tm-player-market-value-development__current-value"}
            )
            if not value_elem:
                value_elem = soup.find(
                    "a", {"class": "data-header__market-value-wrapper"}
                )

            market_value = 0.0
            currency = "EUR"

            if value_elem:
                value_text = value_elem.text.strip()
                market_value = self._parse_value_string(value_text)

            # Extract player info
            name_elem = soup.find("h1", {"class": "data-header__headline-wrapper"})
            player_name = name_elem.text.strip() if name_elem else "Unknown"

            # Extract position
            position_elem = soup.find("span", string="Position:")
            position = "Unknown"
            if position_elem and position_elem.parent:
                position = position_elem.parent.text.replace("Position:", "").strip()

            # Extract age
            age_elem = soup.find("span", {"itemprop": "birthDate"})
            age = None
            if age_elem:
                from datetime import datetime, timezone

                birth_date = age_elem.get("data-birthdate")
                if birth_date:
                    birth_year = int(birth_date.split("-")[0])
                    age = datetime.now().year - birth_year

            result = {
                "player_id": player_id,
                "player_name": player_name,
                "market_value": market_value,
                "currency": currency,
                "position": position,
                "age": age,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

            logger.info(f"Fetched valuation for {player_name}: €{market_value:,.0f}")
            return result

        except Exception as e:
            logger.error(f"Transfermarkt fetch_player_value error for {player_id}: {e}")
            return None

    def _parse_value_string(self, value_str: str) -> float:
        """Parse market value string like '€25.0m' or '€150k'"""
        try:
            # Remove currency symbols and spaces
            value_str = (
                value_str.replace("€", "").replace("$", "").replace("£", "").strip()
            )

            # Handle millions
            if "m" in value_str.lower():
                return float(value_str.lower().replace("m", "")) * 1_000_000

            # Handle thousands
            if "k" in value_str.lower():
                return float(value_str.lower().replace("k", "")) * 1_000

            # Handle plain numbers
            return float(value_str.replace(",", "").replace(".", ""))

        except Exception as e:
            logger.warning(f"Failed to parse value string '{value_str}': {e}")
            return 0.0

    async def update_squad_values(self, team_id: str, db_session: Session) -> int:
        """Update valuations for all players in a squad

        Args:
            team_id: Transfermarkt team ID
            db_session: Database session

        Returns:
            Number of players updated
        """
        updated_count = 0

        try:
            # Fetch team squad page
            url = f"{self.BASE_URL}club/kader/verein/{team_id}"

            if not self.session:
                raise ValueError("Session not initialized - use async context manager")

            async with self.session.get(url) as response:
                response.raise_for_status()
                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")

            # Extract player IDs from squad table
            player_ids = []
            squad_table = soup.find("table", {"class": "items"})
            if squad_table:
                for link in squad_table.find_all("a", {"class": "spielprofil_tooltip"}):
                    href = link.get("href", "")
                    if "/profil/spieler/" in href:
                        player_id = href.split("/")[-1]
                        player_ids.append(player_id)

            logger.info(f"Found {len(player_ids)} players for team {team_id}")

            # Fetch valuation for each player
            for player_id in player_ids:
                valuation = await self.fetch_player_value(player_id)

                if valuation:
                    # Store in database
                    player_val = PlayerValuation(
                        player_id=valuation["player_id"],
                        player_name=valuation["player_name"],
                        market_value=valuation["market_value"],
                        currency=valuation["currency"],
                        position=valuation.get("position"),
                        age=valuation.get("age"),
                        valuation_date=datetime.now(timezone.utc),
                    )
                    db_session.add(player_val)
                    updated_count += 1

                # Rate limiting
                await asyncio.sleep(2)

            db_session.commit()
            logger.info(f"Updated {updated_count} player valuations for team {team_id}")

        except Exception as e:
            logger.error(f"Error updating squad values for team {team_id}: {e}")
            db_session.rollback()

        return updated_count

    async def load_league_valuations(self, league: str) -> int:
        """Load valuations for all players in a league

        Args:
            league: League identifier (e.g., 'GB1' for Premier League, 'ES1' for La Liga)

        Returns:
            Total number of players processed
        """
        total_players = 0

        with session_scope() as db_session:
            log = ScrapingLog(
                source="transfermarkt",
                job_type="historical_load",
                status="started",
                timestamp=datetime.now(timezone.utc),
                metadata={"league": league},
            )
            db_session.add(log)
            db_session.commit()
            log_id = log.id

            try:
                # Fetch league page to get team IDs
                league_id = self._get_league_id(league)
                url = f"{self.BASE_URL}{league}/startseite/wettbewerb/{league_id}"

                if not self.session:
                    raise ValueError(
                        "Session not initialized - use async context manager"
                    )

                async with self.session.get(url) as response:
                    response.raise_for_status()
                    html = await response.text()

                soup = BeautifulSoup(html, "html.parser")
                team_ids = self._extract_team_ids_from_league(soup)

                logger.info(f"Found {len(team_ids)} teams in league {league}")

                # Update valuations for each team
                for team_id in team_ids:
                    count = await self.update_squad_values(team_id, db_session)
                    total_players += count
                    await asyncio.sleep(5)  # Rate limiting between teams

                # Update log
                log_entry = db_session.query(ScrapingLog).filter_by(id=log_id).first()
                if log_entry:
                    log_entry.status = "success"
                    log_entry.records_processed = total_players
                    db_session.commit()

                logger.info(
                    f"Loaded {total_players} player valuations from Transfermarkt"
                )

            except Exception as e:
                logger.error(f"Error in load_league_valuations: {e}")
                log_entry = db_session.query(ScrapingLog).filter_by(id=log_id).first()
                if log_entry:
                    log_entry.status = "error"
                    log_entry.error_message = str(e)
                    db_session.commit()

        return total_players

    def _get_league_id(self, league_code: str) -> str:
        """Map league code to Transfermarkt ID"""
        league_map = {
            "GB1": "GB1",  # Premier League
            "ES1": "ES1",  # La Liga
            "L1": "L1",  # Bundesliga
            "IT1": "IT1",  # Serie A
            "FR1": "FR1",  # Ligue 1
        }
        return league_map.get(league_code, "GB1")

    def _extract_team_ids_from_league(self, soup: BeautifulSoup) -> List[str]:
        """Extract team IDs from league page"""
        team_ids = []
        try:
            # Find teams table
            teams_table = soup.find("table", {"class": "items"})
            if teams_table:
                for link in teams_table.find_all("a", title=True):
                    href = link.get("href", "")
                    if "/verein/" in href or "/startseite/verein/" in href:
                        # Extract team ID
                        parts = href.split("/")
                        for i, part in enumerate(parts):
                            if part in ["verein", "club"] and i + 1 < len(parts):
                                team_ids.append(parts[i + 1])
                                break
        except Exception as e:
            logger.warning(f"Error extracting team IDs: {e}")

        # Return unique IDs
        return list(set(team_ids))


if __name__ == "__main__":

    async def main():
        async with TransfermarktLoader() as loader:
            value = await loader.fetch_player_value("test_player")
            print("Value:", value)

    asyncio.run(main())
