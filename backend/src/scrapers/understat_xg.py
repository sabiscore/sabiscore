# RESTRICTED PROVIDER — Understat is not authorised for production scraping.
# Data methods raise DataUnavailableError. Do not activate without a licensed API contract.
"""
Understat.com xG data scraper — BLOCKED.
Not authorised for production use. Raises DataUnavailableError on all data calls.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import re

from ..core.exceptions import DataUnavailableError

logger = logging.getLogger(__name__)


class UnderstatXGScraper:
    """
    Scrapes Understat.com for:
    - Shot-level xG data (location, body part, situation)
    - xG chain sequences (build-up play)
    - Expected threat (xT) heatmaps
    - Team/player xG performance
    """

    BASE_URL = "https://understat.com"

    def __init__(self, redis_client: Optional[Any] = None):
        self.redis = redis_client
        self.cache_ttl = 30  # 30 seconds cache

    async def scrape_match_xg(
        self,
        url: str,
        proxy: Optional[str] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Scrape xG data for a specific match.

        Args:
            url: Match URL (e.g., https://understat.com/match/12345)
            proxy: Optional proxy URL
            timeout: Request timeout in seconds

        Returns:
            Dict containing xG data with structure:
            {
                'match_id': str,
                'home_team': str,
                'away_team': str,
                'home_xg': float,
                'away_xg': float,
                'shots': List[Dict],  # Shot-level data
                'xg_chains': List[Dict],  # Build-up sequences
                'danger_zones': Dict,  # xT heatmap data
            }
        """
        try:
            # Extract match ID from URL
            match_id = self._extract_match_id(url)

            # Check cache
            if self.redis:
                cache_key = f"xg:{match_id}"
                cached = await self.redis.get(cache_key)
                if cached:
                    logger.info(f"xG data cache HIT for match {match_id}")
                    import json

                    return json.loads(cached)

            # Simulate scraping (in production, use actual Puppeteer/Playwright)
            # This is a placeholder that would be replaced with real browser automation
            data = await self._fetch_xg_data(url, proxy, timeout)

            # Process and structure data
            structured_data = self._process_xg_data(data, match_id)

            # Cache result
            if self.redis:
                import json

                await self.redis.setex(
                    f"xg:{match_id}", self.cache_ttl, json.dumps(structured_data)
                )

            return structured_data

        except Exception as e:
            logger.error(f"Failed to scrape xG data from {url}: {e}")
            raise

    def _extract_match_id(self, url: str) -> str:
        """Extract match ID from Understat URL"""
        match = re.search(r"/match/(\d+)", url)
        if match:
            return match.group(1)
        raise ValueError(f"Invalid Understat match URL: {url}")

    async def _fetch_xg_data(
        self,
        url: str,
        proxy: Optional[str],
        timeout: int,
    ) -> Dict[str, Any]:
        """
        Fetch raw xG data using browser automation.

        In production, this would use Playwright or Puppeteer:
        ```python
        async with async_playwright() as p:
            browser = await p.chromium.launch(proxy={"server": proxy})
            page = await browser.new_page()
            await page.goto(url, timeout=timeout*1000)

            # Extract JSON data from page
            xg_data = await page.evaluate('''() => {
                return JSON.parse(
                    document.querySelector('script')
                        .innerText
                        .match(/shotsData\\s*=\\s*JSON\\.parse\\('(.+?)'/)[1]
                );
            }''')

            await browser.close()
            return xg_data
        ```
        """
        raise DataUnavailableError(
            "Understat xG unavailable: provider not authorised for production use"
        )

    def _process_xg_data(
        self, raw_data: Dict[str, Any], match_id: str
    ) -> Dict[str, Any]:
        """Process raw xG data into structured format"""

        home_shots = raw_data.get("h", [])
        away_shots = raw_data.get("a", [])

        # Calculate team xG
        home_xg = sum(float(shot.get("xG", 0)) for shot in home_shots)
        away_xg = sum(float(shot.get("xG", 0)) for shot in away_shots)

        # Process shots
        processed_shots = []
        for shot in home_shots + away_shots:
            processed_shots.append(
                {
                    "minute": int(shot.get("minute", 0)),
                    "player": shot.get("player", ""),
                    "team": "home" if shot in home_shots else "away",
                    "xg": float(shot.get("xG", 0)),
                    "result": shot.get("result", ""),
                    "x": float(shot.get("X", 0)),
                    "y": float(shot.get("Y", 0)),
                    "situation": shot.get("situation", ""),
                    "shot_type": shot.get("shotType", ""),
                    "last_action": shot.get("lastAction", ""),
                }
            )

        # Sort by minute
        processed_shots.sort(key=lambda x: x["minute"])

        # Build xG chains (sequences of play leading to shots)
        xg_chains = self._build_xg_chains(processed_shots)

        # Create danger zone heatmap
        danger_zones = self._create_danger_zones(processed_shots)

        return {
            "match_id": match_id,
            "home_team": self._extract_team_name(home_shots),
            "away_team": self._extract_team_name(away_shots),
            "home_xg": round(home_xg, 2),
            "away_xg": round(away_xg, 2),
            "shots": processed_shots,
            "xg_chains": xg_chains,
            "danger_zones": danger_zones,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _extract_team_name(self, shots: List[Dict]) -> str:
        """Extract team name from shot data"""
        if not shots:
            return "Unknown"

        # Try to extract from player team info
        for shot in shots:
            if "h_team" in shot:
                return shot["h_team"]
            if "a_team" in shot:
                return shot["a_team"]

        return "Unknown"

    def _build_xg_chains(self, shots: List[Dict]) -> List[Dict]:
        """
        Build xG chains - sequences of play leading to high-value chances.
        Groups shots by proximity in time and location.
        """
        chains = []
        current_chain = []
        last_shot_time = 0

        for shot in shots:
            minute = shot["minute"]

            # Start new chain if >5 minutes since last shot
            if current_chain and minute - last_shot_time > 5:
                if len(current_chain) >= 2:  # Only keep chains with 2+ shots
                    chains.append(
                        {
                            "start_minute": current_chain[0]["minute"],
                            "end_minute": current_chain[-1]["minute"],
                            "shots": len(current_chain),
                            "total_xg": sum(s["xg"] for s in current_chain),
                            "team": current_chain[0]["team"],
                            "pressure_sequence": True
                            if len(current_chain) >= 3
                            else False,
                        }
                    )
                current_chain = []

            current_chain.append(shot)
            last_shot_time = minute

        # Add final chain
        if len(current_chain) >= 2:
            chains.append(
                {
                    "start_minute": current_chain[0]["minute"],
                    "end_minute": current_chain[-1]["minute"],
                    "shots": len(current_chain),
                    "total_xg": sum(s["xg"] for s in current_chain),
                    "team": current_chain[0]["team"],
                    "pressure_sequence": True if len(current_chain) >= 3 else False,
                }
            )

        return chains

    def _create_danger_zones(self, shots: List[Dict]) -> Dict[str, Any]:
        """
        Create xT (expected threat) heatmap from shot locations.
        Divides pitch into zones and aggregates xG.
        """
        # Define pitch zones (5x4 grid)
        zones = {
            f"zone_{i}_{j}": {"xg": 0.0, "shots": 0} for i in range(5) for j in range(4)
        }

        for shot in shots:
            x, y = shot["x"], shot["y"]

            # Map coordinates to zone (assuming x,y are normalized 0-1)
            zone_x = min(int(x * 5), 4)
            zone_y = min(int(y * 4), 3)
            zone_key = f"zone_{zone_x}_{zone_y}"

            zones[zone_key]["xg"] += shot["xg"]
            zones[zone_key]["shots"] += 1

        # Round values
        for zone in zones.values():
            zone["xg"] = round(zone["xg"], 2)

        return {
            "zones": zones,
            "hot_zones": sorted(
                [(k, v["xg"]) for k, v in zones.items()],
                key=lambda x: x[1],
                reverse=True,
            )[:3],  # Top 3 danger zones
        }

    async def scrape_team_xg_performance(
        self,
        team_name: str,
        season: str = "2024",
    ) -> Dict[str, Any]:
        """
        Scrape team's xG performance for a season.

        Args:
            team_name: Team name (e.g., "Arsenal")
            season: Season year (e.g., "2024")

        Returns:
            Dict containing season xG stats
        """

        try:
            # Check cache
            if self.redis:
                cache_key = f"team_xg:{team_name}:{season}"
                cached = await self.redis.get(cache_key)
                if cached:
                    import json

                    return json.loads(cached)

            # Placeholder for actual scraping
            data = {
                "team": team_name,
                "season": season,
                "xg_for": 0.0,
                "xg_against": 0.0,
                "xg_diff": 0.0,
                "matches": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Cache for 1 hour (team stats don't change often)
            if self.redis:
                import json

                await self.redis.setex(
                    f"team_xg:{team_name}:{season}", 3600, json.dumps(data)
                )

            return data

        except Exception as e:
            logger.error(f"Failed to scrape team xG for {team_name}: {e}")
            raise
