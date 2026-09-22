"""
Data Ingestion Service
Orchestrates real-time data collection from multiple sources and persists to PostgreSQL

Integrates 7 ethical scrapers:
- FootballDataEnhancedScraper: Historical matches with Pinnacle odds (CLV benchmark)
- BetfairExchangeScraper: Exchange odds with back/lay spreads
- SoccerwayScraper: Standings, fixtures, and form data
- TransfermarktScraper: Market values and injuries
- OddsPortalScraper: Historical closing lines
- UnderstatScraper: xG statistics
- FlashscoreScraper: Live scores and H2H

Note: WhoScored scraper removed due to persistent 403 blocks.
Form features now reconstructed from Soccerway results + Understat xG trends.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from ..core.cache import cache_manager
from ..db.session import get_db_session
from ..db.models import Match, Odds, MatchStats
from ..monitoring.metrics import metrics_collector

# Import all 7 ethical scrapers (WhoScored removed due to 403 blocks)
from ..data.scrapers import (
    FootballDataEnhancedScraper,
    BetfairExchangeScraper,
    SoccerwayScraper,
    TransfermarktScraper,
    OddsPortalScraper,
    UnderstatScraper,
    FlashscoreScraper,
)

logger = logging.getLogger(__name__)


class DataIngestionService:
    """
    Coordinates data collection from all 7 ethical scrapers and persists to database.

    Data sources and polling intervals:
    - FlashscoreScraper: Live scores (5s polling)
    - BetfairExchangeScraper: Live odds (10s polling)
    - OddsPortalScraper: Closing lines (60s polling)
    - UnderstatScraper: xG data enrichment (300s - 5 min)
    - FootballDataEnhancedScraper: Historical Pinnacle odds (daily)
    - SoccerwayScraper: Standings and form (daily)
    - TransfermarktScraper: Market values, injuries (daily)

    Note: WhoScored removed; form features rebuilt from Soccerway + Understat.
    """

    def __init__(self):
        # Initialize all 7 ethical scrapers (WhoScored removed)
        self.football_data = FootballDataEnhancedScraper()
        self.betfair = BetfairExchangeScraper()
        self.soccerway = SoccerwayScraper()
        self.transfermarkt = TransfermarktScraper()
        self.oddsportal = OddsPortalScraper()
        self.understat = UnderstatScraper()
        self.flashscore = FlashscoreScraper()

        self._running = False
        self._tasks: List[asyncio.Task] = []

        logger.info("DataIngestionService initialized with 7 ethical scrapers")

    async def start(self):
        """Start all data ingestion loops"""
        if self._running:
            logger.warning("Data ingestion already running")
            return

        self._running = True
        logger.info("Starting data ingestion service with 8 scrapers")

        # Start concurrent ingestion tasks
        self._tasks = [
            # High-frequency real-time data (5-10s polling)
            asyncio.create_task(self._ingest_live_scores()),
            asyncio.create_task(self._ingest_live_odds()),
            # Medium-frequency enrichment (60s polling)
            asyncio.create_task(self._ingest_closing_lines()),
            # Low-frequency enrichment (5min+ polling)
            asyncio.create_task(self._enrich_xg_data()),
            asyncio.create_task(self._enrich_daily_data()),
        ]

        logger.info(f"Started {len(self._tasks)} ingestion tasks")

    async def stop(self):
        """Stop all data ingestion loops gracefully"""
        if not self._running:
            return

        self._running = False
        logger.info("Stopping data ingestion service")

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for cancellation
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        logger.info("Data ingestion service stopped")

    async def _ingest_live_scores(self):
        """Poll Flashscore for live scores every 5 seconds"""
        logger.info("Starting live scores ingestion (Flashscore)")

        while self._running:
            try:
                async with get_db_session() as db:
                    # Fetch live matches
                    now = datetime.now(timezone.utc)
                    query = select(Match).where(
                        Match.status.in_(["scheduled", "live"]),
                        Match.match_date <= now + timedelta(hours=2),
                        Match.match_date >= now - timedelta(hours=3),
                    )
                    result = await db.execute(query)
                    matches = result.scalars().all()

                    logger.debug(f"Checking {len(matches)} live/upcoming matches")

                    # For each match, fetch latest score from Flashscore
                    for match in matches:
                        try:
                            score_data = await self._fetch_flashscore_live(match)
                            if score_data:
                                await self._update_match_score(db, match.id, score_data)
                        except Exception as e:
                            logger.warning(
                                f"Failed to fetch score for match {match.id}: {e}"
                            )

                    await db.commit()

            except Exception as e:
                logger.error(f"Error in live scores ingestion: {e}", exc_info=True)

            # Poll every 5 seconds
            await asyncio.sleep(5)

    async def _ingest_live_odds(self):
        """Poll Betfair Exchange for live odds every 10 seconds"""
        logger.info("Starting live odds ingestion (Betfair Exchange)")

        while self._running:
            try:
                async with get_db_session() as db:
                    # Get active markets
                    now = datetime.now(timezone.utc)
                    query = select(Match).where(
                        Match.status.in_(["scheduled", "live"]),
                        Match.match_date >= now - timedelta(hours=1),
                        Match.match_date <= now + timedelta(days=7),
                    )
                    result = await db.execute(query)
                    matches = result.scalars().all()

                    # Fetch odds for each match from Betfair Exchange
                    for match in matches[:20]:  # Limit to 20 concurrent markets
                        try:
                            odds_data = await self._fetch_betfair_exchange_odds(match)
                            if odds_data:
                                await self._persist_odds_snapshot(
                                    db, match.id, odds_data
                                )
                        except Exception as e:
                            logger.warning(
                                f"Failed to fetch Betfair odds for {match.id}: {e}"
                            )

                    await db.commit()

            except Exception as e:
                logger.error(f"Error in odds ingestion: {e}", exc_info=True)

            # Poll every 10 seconds
            await asyncio.sleep(10)

    async def _ingest_closing_lines(self):
        """Track Pinnacle closing lines for CLV calculation via OddsPortal"""
        logger.info("Starting closing line tracking (OddsPortal + FootballData)")

        while self._running:
            try:
                async with get_db_session() as db:
                    # Get matches about to start (within 30 minutes)
                    now = datetime.now(timezone.utc)
                    query = select(Match).where(
                        Match.status == "scheduled",
                        Match.match_date >= now,
                        Match.match_date <= now + timedelta(minutes=30),
                    )
                    result = await db.execute(query)
                    matches = result.scalars().all()

                    for match in matches:
                        try:
                            # Try to get closing line from OddsPortal
                            closing_odds = await self._fetch_closing_line(match)
                            if closing_odds:
                                await self._persist_closing_line(
                                    db, match.id, closing_odds
                                )
                        except Exception as e:
                            logger.warning(
                                f"Failed to fetch closing line for {match.id}: {e}"
                            )

                    await db.commit()

            except Exception as e:
                logger.error(f"Error in closing line ingestion: {e}", exc_info=True)

            # Check every 60 seconds
            await asyncio.sleep(60)

    async def _enrich_xg_data(self):
        """Scrape Understat for xG data enrichment every 5 minutes"""
        logger.info("Starting xG data enrichment (Understat)")

        while self._running:
            try:
                async with get_db_session() as db:
                    # Find matches needing xG enrichment
                    query = select(Match).where(
                        Match.status.in_(["scheduled", "live"]),
                        Match.match_date >= datetime.now(timezone.utc),
                        Match.match_date
                        <= datetime.now(timezone.utc) + timedelta(days=3),
                    )
                    result = await db.execute(query)
                    matches = result.scalars().all()

                    for match in matches[:10]:  # Process 10 at a time
                        # Check if already enriched (via cache)
                        cache_key = f"xg_enrichment:{match.id}"
                        if cache_manager.exists(cache_key):
                            continue

                        try:
                            # Fetch xG data from Understat
                            xg_data = await self._fetch_understat_xg(match)
                            if xg_data:
                                await self._persist_xg_enrichment(db, match.id, xg_data)
                                cache_manager.set(cache_key, True, ttl=86400)  # 24h
                        except Exception as e:
                            logger.warning(f"Failed to fetch xG for {match.id}: {e}")

                    await db.commit()

            except Exception as e:
                logger.error(f"Error in xG enrichment: {e}", exc_info=True)

            # Run every 5 minutes
            await asyncio.sleep(300)

    async def _enrich_daily_data(self):
        """Daily enrichment: standings, form (Understat), injuries, market values"""
        logger.info(
            "Starting daily data enrichment (Soccerway, Understat, Transfermarkt)"
        )

        while self._running:
            try:
                async with get_db_session() as db:
                    # Get unique leagues from upcoming matches
                    now = datetime.now(timezone.utc)
                    query = (
                        select(Match.league_id)
                        .distinct()
                        .where(
                            Match.match_date >= now,
                            Match.match_date <= now + timedelta(days=7),
                        )
                    )
                    result = await db.execute(query)
                    league_ids = [row[0] for row in result.fetchall()]

                    for league_id in league_ids[:5]:  # Limit to 5 leagues per cycle
                        try:
                            # Fetch standings from Soccerway
                            standings = await self._fetch_soccerway_standings(league_id)

                            # Fetch team form from Understat xG trends (replaces WhoScored)
                            form_data = await self._fetch_understat_form(league_id)

                            # Persist daily enrichment
                            if standings or form_data:
                                await self._persist_daily_enrichment(
                                    db, league_id, standings, form_data
                                )

                        except Exception as e:
                            logger.warning(
                                f"Failed daily enrichment for league {league_id}: {e}"
                            )

                    await db.commit()

            except Exception as e:
                logger.error(f"Error in daily enrichment: {e}", exc_info=True)

            # Run every 6 hours (4x daily)
            await asyncio.sleep(21600)

    # ==========================================================================
    # Scraper Integration Methods
    # ==========================================================================

    async def _fetch_flashscore_live(self, match) -> Optional[Dict]:
        """Fetch live score from Flashscore scraper"""
        start_time = time.time()
        success = False
        try:
            # Use Flashscore scraper to fetch live data
            result = self.flashscore.fetch_data(
                home_team=match.home_team.name
                if hasattr(match, "home_team")
                else str(match.home_team_id),
                away_team=match.away_team.name
                if hasattr(match, "away_team")
                else str(match.away_team_id),
                use_cache=False,  # Always get fresh data for live scores
            )

            if result and isinstance(result, dict):
                success = True
                return {
                    "home_score": result.get("home_score"),
                    "away_score": result.get("away_score"),
                    "status": result.get("status", "live"),
                    "minute": result.get("minute"),
                }
            return None
        except Exception as e:
            logger.debug(f"Flashscore fetch error: {e}")
            return None
        finally:
            duration_ms = (time.time() - start_time) * 1000
            metrics_collector.record_scraper_call("flashscore", duration_ms, success)

    async def _fetch_betfair_exchange_odds(self, match) -> Optional[Dict]:
        """Fetch odds from Betfair Exchange scraper"""
        cache_key = f"betfair_market:{match.id}"
        cached = cache_manager.get(cache_key)
        if cached:
            return cached

        start_time = time.time()
        success = False
        try:
            # Use Betfair scraper to fetch exchange odds
            odds_data = self.betfair.fetch_data(
                home_team=match.home_team.name
                if hasattr(match, "home_team")
                else str(match.home_team_id),
                away_team=match.away_team.name
                if hasattr(match, "away_team")
                else str(match.away_team_id),
                use_cache=True,
            )

            if odds_data:
                success = True
                result = {
                    "market_id": f"market_{match.id}",
                    "status": "OPEN",
                    "inplay": match.status == "live",
                    "runners": [
                        {
                            "selection_id": 1,
                            "last_price_traded": odds_data.get("home_back", 2.0),
                            "status": "ACTIVE",
                        },
                        {
                            "selection_id": 2,
                            "last_price_traded": odds_data.get("draw_back", 3.2),
                            "status": "ACTIVE",
                        },
                        {
                            "selection_id": 3,
                            "last_price_traded": odds_data.get("away_back", 3.5),
                            "status": "ACTIVE",
                        },
                    ],
                    "back_lay_spread": {
                        "home": odds_data.get("home_spread", 0.02),
                        "draw": odds_data.get("draw_spread", 0.03),
                        "away": odds_data.get("away_spread", 0.02),
                    },
                    "total_matched": odds_data.get("total_matched", 0),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                # Cache for 30 seconds
                cache_manager.set(cache_key, result, ttl=30)
                return result

            return None

        except Exception as e:
            logger.debug(f"Betfair Exchange fetch error: {e}")
            return None
        finally:
            duration_ms = (time.time() - start_time) * 1000
            metrics_collector.record_scraper_call(
                "betfair_exchange", duration_ms, success
            )

    async def _fetch_closing_line(self, match) -> Optional[Dict]:
        """Fetch closing line from OddsPortal or FootballData"""
        try:
            # Try OddsPortal first for most accurate closing lines
            closing_odds = self.oddsportal.fetch_data(
                home_team=match.home_team.name
                if hasattr(match, "home_team")
                else str(match.home_team_id),
                away_team=match.away_team.name
                if hasattr(match, "away_team")
                else str(match.away_team_id),
                use_cache=True,
            )

            if closing_odds and isinstance(closing_odds, dict):
                return {
                    "home": closing_odds.get("pinnacle_home")
                    or closing_odds.get("home"),
                    "draw": closing_odds.get("pinnacle_draw")
                    or closing_odds.get("draw"),
                    "away": closing_odds.get("pinnacle_away")
                    or closing_odds.get("away"),
                    "source": "OddsPortal",
                }

            # Fallback to FootballData for historical Pinnacle odds
            league_code = self._get_league_code(match.league_id)
            fd_data = self.football_data.download_season_data(
                league=league_code,
                season=datetime.now(timezone.utc).strftime("%y")
                + str(int(datetime.now(timezone.utc).strftime("%y")) + 1),
                use_cache=True,
            )

            if not fd_data.empty:
                # Find matching game
                home_name = match.home_team.name if hasattr(match, "home_team") else ""
                away_name = match.away_team.name if hasattr(match, "away_team") else ""
                match_row = fd_data[
                    (fd_data["home_team"].str.contains(home_name, case=False, na=False))
                    & (
                        fd_data["away_team"].str.contains(
                            away_name, case=False, na=False
                        )
                    )
                ]
                if not match_row.empty:
                    row = match_row.iloc[0]
                    return {
                        "home": row.get("pinnacle_home"),
                        "draw": row.get("pinnacle_draw"),
                        "away": row.get("pinnacle_away"),
                        "source": "FootballData",
                    }

            return None

        except Exception as e:
            logger.debug(f"Closing line fetch error: {e}")
            return None

    async def _fetch_understat_xg(self, match) -> Optional[Dict]:
        """Fetch xG data from Understat scraper"""
        try:
            # Get team xG data
            home_team = (
                match.home_team.name
                if hasattr(match, "home_team")
                else str(match.home_team_id)
            )
            away_team = (
                match.away_team.name
                if hasattr(match, "away_team")
                else str(match.away_team_id)
            )
            league = self._get_understat_league(match.league_id)

            xg_data = self.understat.fetch_data(
                team=home_team, league=league, use_cache=True
            )

            if xg_data:
                return {
                    "home_team_xg": xg_data.get("xg_for", 0),
                    "home_team_xga": xg_data.get("xg_against", 0),
                    "away_team": away_team,
                    "league": league,
                }
            return None

        except Exception as e:
            logger.debug(f"Understat fetch error: {e}")
            return None

    async def _fetch_soccerway_standings(self, league_id) -> Optional[Dict]:
        """Fetch league standings from Soccerway"""
        try:
            standings = self.soccerway.fetch_data(
                league=self._get_league_name(league_id), use_cache=True
            )
            return standings
        except Exception as e:
            logger.debug(f"Soccerway fetch error: {e}")
            return None

    async def _fetch_understat_form(self, league_id) -> Optional[Dict]:
        """Fetch team form data from Understat xG trends (replaces WhoScored)"""
        try:
            form_data = self.understat.fetch_data(
                league=self._get_league_name(league_id), use_cache=True
            )
            return form_data
        except Exception as e:
            logger.debug(f"Understat form fetch error: {e}")
            return None

    # ==========================================================================
    # Helper methods for data persistence
    # ==========================================================================

    async def _fetch_espn_score(self, match_id: str) -> Optional[Dict]:
        """Deprecated: Use _fetch_flashscore_live instead"""
        return None

    async def _fetch_betfair_odds(self, match_id: str) -> Optional[Dict]:
        """Deprecated: Use _fetch_betfair_exchange_odds instead"""
        return None

    async def _update_match_score(
        self, db: AsyncSession, match_id: str, score_data: Dict
    ):
        """Update match with live score"""
        stmt = (
            update(Match)
            .where(Match.id == match_id)
            .values(
                home_score=score_data.get("home_score"),
                away_score=score_data.get("away_score"),
                status=score_data.get("status", "live"),
            )
        )
        await db.execute(stmt)

    async def _persist_odds_snapshot(
        self, db: AsyncSession, match_id: str, odds_data: Dict
    ):
        """Save odds snapshot to database"""
        runners = odds_data.get("runners", [])
        if len(runners) < 3:
            return

        odds = Odds(
            match_id=match_id,
            bookmaker="Betfair",
            home_win=runners[0].get("last_price_traded"),
            draw=runners[1].get("last_price_traded") if len(runners) > 1 else None,
            away_win=runners[2].get("last_price_traded") if len(runners) > 2 else None,
            timestamp=datetime.now(timezone.utc),
            market_type="MATCH_ODDS",
        )
        db.add(odds)

    async def _persist_closing_line(
        self, db: AsyncSession, match_id: str, closing_data: Dict
    ):
        """Save Pinnacle closing line for CLV analysis"""
        if not closing_data:
            return

        odds = Odds(
            match_id=match_id,
            bookmaker=f"Pinnacle ({closing_data.get('source', 'unknown')})",
            home_win=closing_data.get("home"),
            draw=closing_data.get("draw"),
            away_win=closing_data.get("away"),
            timestamp=datetime.now(timezone.utc),
            market_type="CLOSING_LINE",
        )
        db.add(odds)
        logger.info(f"Persisted closing line for match {match_id}")

    async def _persist_xg_enrichment(
        self, db: AsyncSession, match_id: str, xg_data: Dict
    ):
        """Save xG enrichment data as match stats"""
        if not xg_data:
            return

        stats = MatchStats(
            match_id=match_id,
            team_id=xg_data.get("team_id"),
            xg=xg_data.get("home_team_xg"),
            xg_against=xg_data.get("home_team_xga"),
        )
        db.add(stats)
        logger.info(f"Persisted xG data for match {match_id}")

    async def _persist_daily_enrichment(
        self,
        db: AsyncSession,
        league_id: str,
        standings: Optional[Dict],
        form_data: Optional[Dict],
    ):
        """Save daily enrichment data (standings, form)"""
        # Cache standings and form for prediction service access
        if standings:
            cache_manager.set(f"standings:{league_id}", standings, ttl=86400)
        if form_data:
            cache_manager.set(f"form:{league_id}", form_data, ttl=86400)

        logger.info(f"Persisted daily enrichment for league {league_id}")

    async def _persist_enrichment(
        self,
        db: AsyncSession,
        match_id: str,
        xg_data: Optional[Dict],
        scouting_data: Optional[Dict],
    ):
        """Legacy method - Save enrichment data as match stats"""
        stats = MatchStats(
            match_id=match_id,
            team_id=xg_data.get("team_id") if xg_data else None,
            xg=xg_data.get("xg") if xg_data else None,
            xg_against=xg_data.get("xg_against") if xg_data else None,
            shots=xg_data.get("shots") if xg_data else None,
            possession=scouting_data.get("possession") if scouting_data else None,
            passes_completed=scouting_data.get("passes") if scouting_data else None,
        )
        db.add(stats)

    # ==========================================================================
    # Utility methods
    # ==========================================================================

    def _get_league_code(self, league_id) -> str:
        """Map league ID to football-data.co.uk code"""
        league_map = {
            "epl": "E0",
            "premier_league": "E0",
            "la_liga": "SP1",
            "bundesliga": "D1",
            "serie_a": "I1",
            "ligue_1": "F1",
            "championship": "E1",
            "eredivisie": "N1",
        }
        return league_map.get(str(league_id).lower(), "E0")

    def _get_understat_league(self, league_id) -> str:
        """Map league ID to Understat league code"""
        league_map = {
            "epl": "EPL",
            "premier_league": "EPL",
            "la_liga": "La_liga",
            "bundesliga": "Bundesliga",
            "serie_a": "Serie_A",
            "ligue_1": "Ligue_1",
        }
        return league_map.get(str(league_id).lower(), "EPL")

    def _get_league_name(self, league_id) -> str:
        """Map league ID to display name"""
        league_map = {
            "epl": "Premier League",
            "premier_league": "Premier League",
            "la_liga": "La Liga",
            "bundesliga": "Bundesliga",
            "serie_a": "Serie A",
            "ligue_1": "Ligue 1",
            "championship": "Championship",
            "eredivisie": "Eredivisie",
        }
        return league_map.get(str(league_id).lower(), "Premier League")


# Global singleton instance
ingestion_service = DataIngestionService()
