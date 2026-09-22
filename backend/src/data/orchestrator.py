"""
Data Pipeline Orchestrator - Coordinates scrapers, database writes, and cache population
Runs periodic scraping jobs, handles errors, and maintains data freshness
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import json
from sqlalchemy import select, and_
import redis

from .loaders.fbref import FBrefLoader
from .loaders.understat import UnderstatLoader
from ..core.config import settings
from ..core.database import Match, Team, MatchStats
from ..db.session import async_session_maker


logger = logging.getLogger(__name__)


class DataPipelineOrchestrator:
    """
    Orchestrates data scraping and loading pipeline

    Pipeline stages:
    1. Scrape FBref for tactical metrics (possession, PPDA, pressing)
    2. Scrape Understat for xG data
    3. Write to PostgreSQL database (MatchStats table)
    4. Populate Redis cache for DataProcessingService
    5. Log scraping results

    Scheduling:
    - Tactical metrics: Daily (slow-changing data)
    - xG data: Every 6 hours (match-dependent)
    - On-demand: Via API trigger
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.fbref_loader = FBrefLoader()
        self.understat_loader = UnderstatLoader()

        effective_redis_url = redis_url or settings.redis_url

        try:
            self.redis = redis.from_url(effective_redis_url, decode_responses=True)
            self.redis.ping()
            logger.info("Connected to Redis for cache population")
        except redis.ConnectionError as e:
            logger.warning(
                f"Redis connection failed: {e}. Cache population will be skipped."
            )
            self.redis = None

        # Job tracking
        self.job_history: List[Dict] = []
        self.max_history = 100

        # Scheduling intervals (seconds)
        self.TACTICAL_INTERVAL = 86400  # 24 hours
        self.XG_INTERVAL = 21600  # 6 hours

    async def run_full_pipeline(
        self, leagues: List[str], season: str = "2024-2025"
    ) -> Dict:
        """
        Run complete data pipeline for all specified leagues

        Args:
            leagues: List of league names (e.g., ["Premier League", "Bundesliga"])
            season: Season identifier (e.g., "2024-2025")

        Returns:
            Summary dict with stats for each stage
        """
        job_start = datetime.now(timezone.utc)
        job_id = f"pipeline_{job_start.strftime('%Y%m%d_%H%M%S')}"

        logger.info(f"Starting pipeline job {job_id} for leagues: {leagues}")

        results = {
            "job_id": job_id,
            "start_time": job_start.isoformat(),
            "leagues": leagues,
            "season": season,
            "tactical_metrics": {},
            "xg_data": {},
            "errors": [],
        }

        try:
            # Stage 1: Scrape FBref tactical metrics
            logger.info("Stage 1: Scraping FBref tactical metrics")
            tactical_results = await self._scrape_fbref_tactical(leagues, season)
            results["tactical_metrics"] = tactical_results

            # Stage 2: Scrape Understat xG data
            logger.info("Stage 2: Scraping Understat xG data")
            xg_results = await self._scrape_understat_xg(leagues, season)
            results["xg_data"] = xg_results

            # Stage 3: Write to database
            logger.info("Stage 3: Writing to database")
            db_results = await self._write_to_database(tactical_results, xg_results)
            results["db_writes"] = db_results

            # Stage 4: Populate Redis cache
            logger.info("Stage 4: Populating Redis cache")
            cache_results = await self._populate_redis_cache(tactical_results, season)
            results["cache_population"] = cache_results

        except Exception as e:
            logger.error(f"Pipeline job {job_id} failed: {e}", exc_info=True)
            results["errors"].append({"stage": "pipeline", "error": str(e)})

        job_end = datetime.now(timezone.utc)
        results["end_time"] = job_end.isoformat()
        results["duration_seconds"] = (job_end - job_start).total_seconds()

        # Store in job history
        self._add_to_history(results)

        logger.info(
            f"Pipeline job {job_id} completed in {results['duration_seconds']:.2f}s"
        )
        return results

    async def _scrape_fbref_tactical(self, leagues: List[str], season: str) -> Dict:
        """
        Scrape tactical metrics from FBref for all teams in specified leagues

        Returns:
            Dict with team_name -> tactical_metrics mapping
        """
        results = {}
        errors = []

        try:
            async with self.fbref_loader:
                for league in leagues:
                    try:
                        logger.info(f"Scraping FBref tactical metrics for {league}")

                        # Load all teams in league
                        league_stats = await self.fbref_loader.load_league_stats(
                            league=league,
                            season=season,
                            stat_type="possession",  # Includes possession, PPDA, pressing
                        )

                        if league_stats:
                            results[league] = league_stats
                            logger.info(
                                f"Scraped {len(league_stats)} teams from {league}"
                            )
                        else:
                            logger.warning(f"No tactical data scraped for {league}")

                    except Exception as e:
                        error_msg = f"FBref scraping failed for {league}: {e}"
                        logger.error(error_msg)
                        errors.append({"league": league, "error": str(e)})

        except Exception as e:
            logger.error(f"FBref loader initialization failed: {e}")
            errors.append({"stage": "fbref_init", "error": str(e)})

        return {
            "teams_scraped": sum(len(v) for v in results.values()),
            "leagues_success": len(results),
            "leagues_failed": len(errors),
            "data": results,
            "errors": errors,
        }

    async def _scrape_understat_xg(self, leagues: List[str], season: str) -> Dict:
        """
        Scrape xG data from Understat for recent matches

        Returns:
            Dict with match_id -> xg_data mapping
        """
        results = {}
        errors = []

        # Map league names to Understat league codes
        league_map = {
            "Premier League": "EPL",
            "La Liga": "La_liga",
            "Bundesliga": "Bundesliga",
            "Serie A": "Serie_A",
            "Ligue 1": "Ligue_1",
        }

        try:
            for league in leagues:
                understat_league = league_map.get(league)
                if not understat_league:
                    logger.warning(f"No Understat mapping for league: {league}")
                    continue

                try:
                    logger.info(f"Scraping Understat xG for {league}")

                    # Get current season year (e.g., "2024" for 2024-2025)
                    season_year = season.split("-")[0]

                    # Fetch league xG data
                    league_xg = await self.understat_loader.fetch_league_xg(
                        league=understat_league, season=season_year
                    )

                    if league_xg:
                        results[league] = league_xg
                        logger.info(
                            f"Scraped xG for {len(league_xg)} matches from {league}"
                        )
                    else:
                        logger.warning(f"No xG data scraped for {league}")

                except Exception as e:
                    error_msg = f"Understat scraping failed for {league}: {e}"
                    logger.error(error_msg)
                    errors.append({"league": league, "error": str(e)})

        except Exception as e:
            logger.error(f"Understat loader failed: {e}")
            errors.append({"stage": "understat", "error": str(e)})

        return {
            "matches_scraped": sum(len(v) for v in results.values()),
            "leagues_success": len(results),
            "leagues_failed": len(errors),
            "data": results,
            "errors": errors,
        }

    async def _write_to_database(
        self, tactical_results: Dict, xg_results: Dict
    ) -> Dict:
        """
        Write scraped data to PostgreSQL database

        Updates:
        - MatchStats table with xG data
        - Team metadata with tactical metrics (stored in JSON)
        """
        written = 0
        errors = []

        try:
            async with async_session_maker() as session:
                # Write xG data to MatchStats
                xg_data = xg_results.get("data", {})
                for league, matches in xg_data.items():
                    for match_data in matches:
                        try:
                            # Find match by teams and date
                            home_team = match_data.get("home_team")
                            away_team = match_data.get("away_team")
                            match_date = match_data.get("date")

                            if not all([home_team, away_team, match_date]):
                                continue

                            # Query match
                            stmt = (
                                select(Match)
                                .join(Team, Team.id == Match.home_team_id)
                                .where(
                                    and_(
                                        Team.name == home_team,
                                        Match.match_date >= match_date,
                                        Match.match_date
                                        < match_date + timedelta(days=1),
                                    )
                                )
                            )
                            result = await session.execute(stmt)
                            match = result.scalar_one_or_none()

                            if not match:
                                logger.debug(
                                    f"Match not found: {home_team} vs {away_team} on {match_date}"
                                )
                                continue

                            # Update or create MatchStats
                            home_stats_stmt = select(MatchStats).where(
                                and_(
                                    MatchStats.match_id == match.id,
                                    MatchStats.team_id == match.home_team_id,
                                )
                            )
                            home_stats_result = await session.execute(home_stats_stmt)
                            home_stats = home_stats_result.scalar_one_or_none()

                            if not home_stats:
                                home_stats = MatchStats(
                                    match_id=match.id, team_id=match.home_team_id
                                )
                                session.add(home_stats)

                            home_stats.expected_goals = match_data.get("home_xg", 0.0)

                            # Away team stats
                            away_stats_stmt = select(MatchStats).where(
                                and_(
                                    MatchStats.match_id == match.id,
                                    MatchStats.team_id == match.away_team_id,
                                )
                            )
                            away_stats_result = await session.execute(away_stats_stmt)
                            away_stats = away_stats_result.scalar_one_or_none()

                            if not away_stats:
                                away_stats = MatchStats(
                                    match_id=match.id, team_id=match.away_team_id
                                )
                                session.add(away_stats)

                            away_stats.expected_goals = match_data.get("away_xg", 0.0)

                            written += 1

                        except Exception as e:
                            logger.error(f"Failed to write match xG data: {e}")
                            errors.append({"match": match_data, "error": str(e)})

                await session.commit()
                logger.info(f"Wrote {written} MatchStats records to database")

        except Exception as e:
            logger.error(f"Database write failed: {e}", exc_info=True)
            errors.append({"stage": "db_write", "error": str(e)})

        return {
            "records_written": written,
            "errors": len(errors),
            "error_details": errors,
        }

    async def _populate_redis_cache(self, tactical_results: Dict, season: str) -> Dict:
        """
        Populate Redis cache with tactical metrics for DataProcessingService

        Key format: fbref_tactical:{team_name}:{season}
        Value: JSON with possession_avg, ppda, pressure_success_pct
        """
        if not self.redis:
            logger.warning("Redis not available, skipping cache population")
            return {"cached": 0, "skipped": "redis_unavailable"}

        cached = 0
        errors = []

        try:
            tactical_data = tactical_results.get("data", {})
            for league, teams in tactical_data.items():
                for team_name, metrics in teams.items():
                    try:
                        cache_key = f"fbref_tactical:{team_name}:{season}"
                        cache_value = json.dumps(
                            {
                                "possession_avg": metrics.get("possession", 50.0),
                                "ppda": metrics.get("ppda", 10.0),
                                "pressure_success_pct": metrics.get(
                                    "press_success", 30.0
                                ),
                            }
                        )

                        # Cache for 24 hours (tactical metrics are slow-changing)
                        self.redis.setex(cache_key, 86400, cache_value)
                        cached += 1

                    except Exception as e:
                        logger.error(
                            f"Failed to cache tactical metrics for {team_name}: {e}"
                        )
                        errors.append({"team": team_name, "error": str(e)})

            logger.info(f"Cached {cached} team tactical metrics in Redis")

        except Exception as e:
            logger.error(f"Redis cache population failed: {e}")
            errors.append({"stage": "cache_population", "error": str(e)})

        return {"teams_cached": cached, "errors": len(errors), "error_details": errors}

    def _add_to_history(self, job_result: Dict) -> None:
        """Add job result to history, maintaining max size"""
        self.job_history.append(job_result)
        if len(self.job_history) > self.max_history:
            self.job_history = self.job_history[-self.max_history :]

    def get_job_history(self, limit: int = 10) -> List[Dict]:
        """Get recent job history"""
        return self.job_history[-limit:]

    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get status of specific job"""
        for job in reversed(self.job_history):
            if job.get("job_id") == job_id:
                return job
        return None

    async def run_scheduler(self, leagues: List[str], season: str = "2024-2025"):
        """
        Run periodic scraping scheduler

        Schedules:
        - Tactical metrics: Every 24 hours
        - xG data: Every 6 hours
        """
        logger.info("Starting data pipeline scheduler")

        last_tactical_run = datetime.now(timezone.utc) - timedelta(
            seconds=self.TACTICAL_INTERVAL
        )
        last_xg_run = datetime.now(timezone.utc) - timedelta(seconds=self.XG_INTERVAL)

        while True:
            try:
                now = datetime.now(timezone.utc)

                # Check if tactical scraping is due
                if (now - last_tactical_run).total_seconds() >= self.TACTICAL_INTERVAL:
                    logger.info("Running scheduled tactical metrics scraping")
                    await self.run_full_pipeline(leagues, season)
                    last_tactical_run = now
                    last_xg_run = now  # Reset xG timer since full pipeline was run

                # Check if xG scraping is due (and not just run with tactical)
                elif (now - last_xg_run).total_seconds() >= self.XG_INTERVAL:
                    logger.info("Running scheduled xG data scraping")
                    # Run only xG pipeline
                    xg_results = await self._scrape_understat_xg(leagues, season)
                    await self._write_to_database({}, xg_results)
                    last_xg_run = now

                # Sleep for 5 minutes before next check
                await asyncio.sleep(300)

            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait 1 minute on error


# Singleton instance
_orchestrator: Optional[DataPipelineOrchestrator] = None


def get_orchestrator() -> DataPipelineOrchestrator:
    """Get or create orchestrator singleton"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = DataPipelineOrchestrator()
    return _orchestrator
