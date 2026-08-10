"""Service for production upcoming fixtures with API-first and DB fallback strategy."""

from __future__ import annotations

import copy
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..core.cache import cache_manager
from ..core.config import settings
from ..core.portfolio_exposure import compute_portfolio_exposure
from ..data.loaders.football_data_api import FootballDataAPIClient
from ..db.models import Match, Team
from ..monitoring.metrics import metrics_collector
from .upcoming_match_feature_service import UpcomingMatchFeatureProjector
from ..models.prediction import PredictionEngine
from .odds_service import OddsService

logger = logging.getLogger(__name__)


def _select_feature_vector(features_result: Dict[str, Any]) -> np.ndarray:
    """Pick the widest available feature vector from a projection result.

    ponytail: this must be an explicit ``is not None`` scan. A plain
    ``a or b or c`` chain calls ``bool()`` on a multi-element ndarray, which
    raises "The truth value of an array with more than one element is
    ambiguous". That exception was swallowed by the enrichment loop's broad
    ``except Exception``, so every fixture silently returned
    ``predictions: None`` / ``data_gaps: ["prediction_failed"]`` — the whole
    platform served zero predictions while models loaded fine.
    """
    for key in ("features", "features_68", "features_58"):
        value = features_result.get(key)
        if value is not None:
            return np.asarray(value, dtype=np.float32)
    return np.array(
        list(features_result.get("features_dict", {}).values()),
        dtype=np.float32,
    )


def _is_fallback_prediction(predictions: Dict[str, Any]) -> bool:
    """True when PredictionEngine.predict() returned its uniform fallback.

    A missing/failed model artifact yields a well-formed but fabricated
    0.333/0.333/0.334 result (model_version="fallback") — indistinguishable
    from a real prediction by shape alone. Callers must gate value-bet math
    on this, mirroring the check in full_analysis.py.
    """
    return str(predictions.get("model_version", "")).casefold() == "fallback"


class UpcomingMatchService:
    """Fetch upcoming matches with cache and resilient fallback chain."""

    def __init__(
        self,
        api_client: Optional[FootballDataAPIClient] = None,
        odds_service: Optional[OddsService] = None,
    ):
        self.api_client = api_client or FootballDataAPIClient()
        self.odds_service = odds_service or OddsService()

    async def get_upcoming_matches(
        self,
        db: AsyncSession,
        league: Optional[str] = None,
        days_ahead: int = 7,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Read the request-path fixture snapshot from cache/PostgreSQL only.

        Provider acquisition belongs to ``run_fixture_sync()``. Calling
        football-data.org here previously made a seven-competition, rate-limit
        aware provider loop part of every public request; one cold miss could
        therefore outlive Vercel's 30 second function budget. The background
        synchronizer already owns freshness and recovery, so this method is a
        deliberately bounded serving read.
        """
        started_at = time.perf_counter()
        cache_key = f"upcoming:v2:{league or '*'}:{days_ahead}:{limit}"
        cached = cache_manager.get(cache_key)
        if isinstance(cached, dict) and "matches" in cached:
            metrics_collector.increment("upcoming.cache.hit")
            metrics_collector.record_timer(
                "upcoming.base.latency",
                (time.perf_counter() - started_at) * 1000,
            )
            response = copy.deepcopy(cached)
            response["cache_hit"] = True
            return response

        metrics_collector.increment("upcoming.cache.miss")
        try:
            payload = await self._get_upcoming_matches_from_db(
                db,
                league=league,
                days_ahead=days_ahead,
                limit=limit,
            )
            payload.update(
                {
                    "source": "database",
                    "cache_hit": False,
                    "ttl_seconds": settings.fixture_cache_ttl,
                    "data_gap": False,
                    "unavailable_reasons": [],
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            cache_manager.set(cache_key, payload, ttl=settings.fixture_cache_ttl)
            metrics_collector.increment("upcoming.database.success")
            return copy.deepcopy(payload)
        except Exception:
            metrics_collector.increment("upcoming.database.failure")
            raise
        finally:
            metrics_collector.record_timer(
                "upcoming.base.latency",
                (time.perf_counter() - started_at) * 1000,
            )

    async def get_upcoming_matches_cached_or_db(
        self,
        db: AsyncSession,
        league: Optional[str] = None,
        days_ahead: int = 7,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Interactive database/cache-only fixture discovery.

        Provider traffic belongs to the background synchronization path. This
        method is deliberately separate so callers can prove that disabling
        predictions also disables provider and model work.
        """

        cache_key = f"upcoming:v2:{league or '*'}:{days_ahead}:{limit}"
        cached = cache_manager.get(cache_key)
        if isinstance(cached, dict) and "matches" in cached:
            payload = dict(cached)
            cache_hit = True
        else:
            payload = await self._get_upcoming_matches_from_db(
                db, league=league, days_ahead=days_ahead, limit=limit
            )
            payload["source"] = "database"
            cache_manager.set(cache_key, payload, ttl=settings.fixture_cache_ttl)
            cache_hit = False

        matches = list(payload.get("matches") or [])
        return {
            "upcoming_matches": matches,
            "total": len(matches),
            "matches_with_value": 0,
            "avg_edge_pct": 0.0,
            "cache_hit": cache_hit,
            "ttl_seconds": settings.fixture_cache_ttl,
            "source": payload.get("source", "database"),
            "status": "OK",
            "data_gap": False,
            "reason": None,
            "retryable": False,
            "freshness": {"ttl_seconds": settings.fixture_cache_ttl},
            "provenance": [payload.get("source", "database")],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _get_upcoming_matches_from_db(
        self,
        db: AsyncSession,
        league: Optional[str],
        days_ahead: int,
        limit: int,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).replace(tzinfo=None)  # ponytail: match_date is TIMESTAMP WITHOUT TIME ZONE
        end_date = now + timedelta(days=max(days_ahead, 1))

        home_team = aliased(Team)
        away_team = aliased(Team)
        query = (
            select(
                Match,
                home_team.name.label("home_team_name"),
                away_team.name.label("away_team_name"),
            )
            .outerjoin(home_team, home_team.id == Match.home_team_id)
            .outerjoin(away_team, away_team.id == Match.away_team_id)
            .where(
                and_(
                    Match.match_date >= now,
                    Match.match_date <= end_date,
                    Match.status == "scheduled",
                )
            )
            .order_by(Match.match_date.asc())
            .limit(limit)
        )
        if league:
            query = query.where(func.lower(Match.league_id) == league.lower())

        result = await db.execute(query)
        matches = result.all()

        rows: List[Dict[str, Any]] = []
        for match, home_team_name, away_team_name in matches:
            identity_gaps = []
            if not home_team_name:
                identity_gaps.append("HOME_TEAM_NAME_UNRESOLVED")
            if not away_team_name:
                identity_gaps.append("AWAY_TEAM_NAME_UNRESOLVED")
            rows.append(
                {
                    "id": str(match.id),
                    "home_team": home_team_name or "Unknown home team",
                    "away_team": away_team_name or "Unknown away team",
                    "league": match.league_id,
                    "match_date": match.match_date.isoformat() if match.match_date else None,
                    "venue": match.venue,
                    "status": match.status or "scheduled",
                    "has_odds": False,
                    "data_gaps": identity_gaps,
                    "team_identity_status": "VERIFIED" if not identity_gaps else "UNKNOWN",
                    "source": "database",
                }
            )

        return {
            "matches": rows,
            "total": len(rows),
            "league_filter": league,
            "date_range_days": days_ahead,
        }

    async def get_upcoming_matches_with_predictions(
        self,
        db: AsyncSession,
        league: Optional[str] = None,
        days_ahead: int = 7,
        limit: int = 20,
        include_value_bets: bool = True,
    ) -> Dict[str, Any]:
        """
        Fetch upcoming matches and attach predictions + value bets.

        Args:
            db: Database session
            league: Optional league filter
            days_ahead: Days ahead to look
            limit: Max matches to return
            include_value_bets: Include value bet calculations

        Returns:
            {
                "upcoming_matches": [
                    {
                        match data + predictions + odds + value_bets
                    }
                ],
                "total": int,
                "matches_with_value": int,
                "avg_edge_pct": float,
                "source": str,
                "ttl_seconds": int
            }
        """

        cache_key = f"upcoming:predictions:v2:{league or '*'}:{days_ahead}:{limit}"
        cached = cache_manager.get(cache_key)
        if isinstance(cached, dict) and "upcoming_matches" in cached:
            logger.debug(f"Prediction cache hit for {league}")
            return cached

        # Initialize services
        feature_projector = UpcomingMatchFeatureProjector(odds_service=self.odds_service)
        prediction_engine = PredictionEngine()
        odds_service = self.odds_service

        # Get base upcoming matches
        try:
            matches_response = await self.get_upcoming_matches(
                db, league=league, days_ahead=days_ahead, limit=limit
            )
            matches = matches_response.get("matches", [])
            source = matches_response.get("source", "unknown")
        except Exception as e:
            logger.error(f"Failed to get upcoming matches: {e}")
            return {
                "upcoming_matches": [],
                "total": 0,
                "matches_with_value": 0,
                "avg_edge_pct": 0.0,
                "source": "error",
                "error": str(e),
            }

        # Project features and get predictions for each match
        enriched_matches = []
        matches_with_value = 0
        total_edge_pct = 0.0

        for match in matches:
            try:
                match_id = str(match.get("match_id") or match.get("id") or "")
                match["match_id"] = match_id

                # 1. Project features via the same enrichment wrapper every other
                # prediction surface uses (full_analysis.py, monitoring/baseline.py,
                # phase8_features.py). The bare project_match_features() deliberately
                # excludes Elo/StatsBomb/Phase8 (27 of 68 features — see its own
                # _CALLER_RESOLVED_FEATURES comment) and defers them to this wrapper;
                # calling the bare projector directly here produced near-identical
                # feature vectors across fixtures and left staleness_seconds pinned
                # at 0 (a key absent from the bare projector's return shape).
                features_result = await feature_projector.build_live_feature_vector(
                    match_id=match_id, league=match.get("league", ""), db=db
                )
                full_features = _select_feature_vector(features_result)

                # 2. Get predictions via canonical PredictionEngine path
                pred_result = await prediction_engine.predict(
                    features=full_features,
                    league=match.get("league", ""),
                    match_id=match_id,
                )
                predictions = pred_result.to_dict()
                data_gaps: list = sorted(
                    set(match.get("data_gaps", []))
                    | set(features_result.get("data_gaps", []))
                )
                data_quality = dict(features_result.get("data_quality") or {})

                # A prediction is diagnostic — never publishable as an official
                # forecast — when the model fell back to uniform output, or when
                # the feature vector was built entirely from defaults because the
                # teams have no verified history. Mirrors the
                # REQUIRED_MODEL_INPUTS_UNAVAILABLE critical gap in full_analysis.py.
                is_fallback = _is_fallback_prediction(predictions)
                is_synthetic = bool(data_quality.get("is_synthetic"))
                if is_fallback:
                    data_gaps.append("model_prediction_fallback")
                if is_synthetic:
                    data_gaps.append("required_model_inputs_unavailable")
                publishable = not is_fallback and not is_synthetic

                # 3. Get odds
                odds = await odds_service.get_match_odds(
                    match.get("home_team", ""),
                    match.get("away_team", ""),
                    match.get("league", ""),
                )
                odds_available = {"home_win", "draw", "away_win"}.issubset(odds)

                # 4. Calculate value bets — never on a fabricated fallback or
                # synthetic-input prediction, even against real odds.
                value_bets = []
                if include_value_bets and odds_available and publishable:
                    value_bets = PredictionEngine.calculate_value_bets(
                        predictions, odds, league=match.get("league", "")
                    )

                # 5. Add enriched data to match
                match["predictions"] = predictions if publishable else None
                match["odds"] = odds if odds_available else None
                match["value_bets"] = value_bets
                match["has_value"] = len(value_bets) > 0
                match["best_value_bet"] = value_bets[0] if value_bets else None
                match["data_quality"] = data_quality
                match["data_gaps"] = data_gaps
                match["staleness_seconds"] = features_result.get("staleness_seconds", 0)
                match["source"] = str(match.get("source", source))

                if value_bets:
                    matches_with_value += 1
                    # Calculate average edge from value bets
                    if value_bets:
                        total_edge_pct += value_bets[0].get("edge_pct", 0)

                enriched_matches.append(match)

            except Exception as e:
                logger.warning(
                    f"Failed to enrich match {match.get('id')}: {e}", exc_info=True
                )
                # Still include match without predictions
                match["predictions"] = None
                match["odds"] = None
                match["value_bets"] = []
                match["has_value"] = False
                match["best_value_bet"] = None
                match["data_gaps"] = sorted(
                    set(match.get("data_gaps", [])) | {"prediction_failed"}
                )
                match["staleness_seconds"] = 0
                match["match_id"] = str(match.get("match_id") or match.get("id") or "")
                match["source"] = str(match.get("source", source))
                enriched_matches.append(match)

        # Build response
        avg_edge_pct = (
            total_edge_pct / matches_with_value if matches_with_value > 0 else 0.0
        )
        # Advisory only (ADR-0005) — flags/haircuts a display number, never
        # gates or resizes what's already been computed above.
        portfolio_exposure = compute_portfolio_exposure(enriched_matches)

        response = {
            "upcoming_matches": enriched_matches,
            "total": len(enriched_matches),
            "matches_with_value": matches_with_value,
            "avg_edge_pct": round(avg_edge_pct, 2),
            "cache_hit": False,
            "ttl_seconds": settings.fixture_cache_ttl,
            "source": f"{source}+predictions",
            "portfolio_exposure": portfolio_exposure,
        }

        # Cache result
        cache_manager.set(cache_key, response, ttl=settings.fixture_cache_ttl)

        return response
