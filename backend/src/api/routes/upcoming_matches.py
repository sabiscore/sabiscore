"""
API routes for upcoming matches with predictions and value bets.

Endpoints:
- GET /api/v1/upcoming/matches - Fetch upcoming matches with predictions
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...services.upcoming_match_service import UpcomingMatchService
from ...core.redaction import redact_text
from ...monitoring.metrics import metrics_collector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upcoming", tags=["upcoming"])
_PREDICTION_DEADLINE_SECONDS = 5.5
_DISCOVERY_DEADLINE_SECONDS = 3.0


# Pydantic response models
class PredictionSchema(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    home_win: float
    draw: float
    away_win: float
    model_version: str = "1.0.0"
    calibration_method: str = "isotonic"
    confidence: float


class OddsSchema(BaseModel):
    home_win: float
    draw: float
    away_win: float
    source: str
    timestamp: Optional[str] = None
    bookmaker: Optional[str] = None


class ValueBetSchema(BaseModel):
    outcome: str
    edge_pct: float
    kelly_stake_pct: float
    clv_cents: float
    recommended_stake_ngn: int
    confidence: float


class DataQualitySchema(BaseModel):
    historical_data_ratio: float
    defaults_used_count: int
    feature_defaulted_ratio: float
    is_synthetic: bool


class UpcomingMatchSchema(BaseModel):
    match_id: str
    home_team: str
    away_team: str
    league: str
    match_date: str
    venue: Optional[str] = None
    status: str
    predictions: Optional[PredictionSchema] = None
    odds: Optional[OddsSchema] = None
    value_bets: List[ValueBetSchema] = []
    has_value: bool = False
    data_quality: Optional[DataQualitySchema] = None
    source: str


class UpcomingMatchesResponseSchema(BaseModel):
    upcoming_matches: List[UpcomingMatchSchema]
    total: int
    matches_with_value: int
    avg_edge_pct: float
    cache_hit: bool = False
    ttl_seconds: int = 300
    source: str
    status: str = "OK"
    data_gap: bool = False
    reason: Optional[str] = None
    retryable: bool = False
    freshness: Optional[Dict[str, Any]] = None
    provenance: List[str] = Field(default_factory=list)
    generated_at: Optional[str] = None
    deadline_ms: Optional[int] = None


@router.get("/matches", response_model=UpcomingMatchesResponseSchema)
async def get_upcoming_matches(
    league: Optional[str] = Query(
        None,
        description="Filter by league (EPL, LaLiga, Bundesliga, Serie A, Ligue 1, Championship)",
        example="EPL",
    ),
    days_ahead: int = Query(
        7, ge=1, le=30, description="Number of days ahead to fetch matches"
    ),
    limit: int = Query(
        20, ge=1, le=50, description="Maximum number of matches to return"
    ),
    include_predictions: bool = Query(
        True, description="Include ML predictions and value bets"
    ),
    include_value_bets: bool = Query(
        True, description="Include value bet calculations"
    ),
    db: AsyncSession = Depends(get_async_session),
) -> UpcomingMatchesResponseSchema:
    """
    Get upcoming football matches with optional ML predictions and value bets.

    **Response fields:**
    - `upcoming_matches`: List of matches with predictions
      - `predictions`: Calibrated probabilities (Home Win, Draw, Away Win)
      - `odds`: Market odds from bookmakers
      - `value_bets`: Recommended bets with positive edge
      - `data_quality`: Metadata about feature completeness
    - `total`: Total number of matches
    - `matches_with_value`: Matches with identified value bets
    - `avg_edge_pct`: Average edge across all value bets

    **Query Parameters:**
    - `league`: Filter by league (optional)
    - `days_ahead`: Forecast horizon (default: 7 days)
    - `limit`: Max matches (default: 20, max: 50)
    - `include_predictions`: Attach ML predictions (default: true)
    - `include_value_bets`: Calculate value bets (default: true)

    **Cache:**
    - 5 minutes for prediction results
    - Falls back to database if external API unavailable

    **Example:**
    ```
    GET /api/v1/upcoming/matches?league=EPL&days_ahead=7&limit=10
    ```

    **Response (success):**
    ```json
    {
      "upcoming_matches": [
        {
          "match_id": "fd-631821",
          "home_team": "Arsenal",
          "away_team": "Chelsea",
          "league": "Premier League",
          "match_date": "2026-05-31T15:00:00Z",
          "predictions": {
            "home_win": 0.483,
            "draw": 0.218,
            "away_win": 0.299,
            "model_version": "1.0.0",
            "calibration_method": "isotonic",
            "confidence": 0.87
          },
          "odds": {
            "home_win": 2.10,
            "draw": 3.40,
            "away_win": 3.80,
            "source": "pinnacle"
          },
          "value_bets": [
            {
              "outcome": "draw",
              "edge_pct": 8.5,
              "kelly_stake_pct": "<calculated quarter-Kelly, capped at 5%>",
              "clv_cents": "<calculated from closing-line comparison>",
              "recommended_stake_ngn": "<calculated from bankroll>",
              "confidence": "<model calibration output>"
            }
          ],
          "has_value": true,
          "data_quality": {
            "historical_data_ratio": "<fraction of features from real data>",
            "defaults_used_count": "<count of features filled from league averages>",
            "feature_defaulted_ratio": "<fraction of canonical features still at registry default>",
            "is_synthetic": false
          }
        }
      ],
      "total": 15,
      "matches_with_value": 7,
      "avg_edge_pct": 4.8,
      "cache_hit": false,
      "ttl_seconds": 300,
      "source": "football-data.org+predictions"
    }
    ```

    **Errors:**
    - 400: Invalid league name or parameters
    - 500: Internal server error (will still return matches without predictions)
    """

    try:
        started = time.perf_counter()
        service = UpcomingMatchService()

        if include_predictions:
            try:
                response = await asyncio.wait_for(
                    service.get_upcoming_matches_with_predictions(
                        db,
                        league=league,
                        days_ahead=days_ahead,
                        limit=limit,
                        include_value_bets=include_value_bets,
                    ),
                    timeout=_PREDICTION_DEADLINE_SECONDS,
                )
            except TimeoutError:
                metrics_collector.increment("upcoming.prediction_deadline_exceeded")
                response = await asyncio.wait_for(
                    service.get_upcoming_matches_cached_or_db(
                        db, league=league, days_ahead=days_ahead, limit=limit
                    ),
                    timeout=1.5,
                )
                response.update({
                    "status": "PARTIAL",
                    "data_gap": True,
                    "reason": "prediction_deadline_exceeded",
                    "retryable": True,
                })
        else:
            response = await asyncio.wait_for(
                service.get_upcoming_matches_cached_or_db(
                    db, league=league, days_ahead=days_ahead, limit=limit
                ),
                timeout=_DISCOVERY_DEADLINE_SECONDS,
            )

        response["deadline_ms"] = int(
            (_PREDICTION_DEADLINE_SECONDS if include_predictions else _DISCOVERY_DEADLINE_SECONDS)
            * 1000
        )
        metrics_collector.record_timer(
            "upcoming.total_request_ms", (time.perf_counter() - started) * 1000
        )
        return response

    except Exception as e:
        logger.error("Upcoming matches unavailable: %s", redact_text(e), exc_info=True)
        return JSONResponse(
            status_code=503,
            content={
                "upcoming_matches": [],
                "total": 0,
                "matches_with_value": 0,
                "avg_edge_pct": 0.0,
                "cache_hit": False,
                "ttl_seconds": 0,
                "source": "database",
                "status": "UNAVAILABLE",
                "data_gap": True,
                "reason": "fixture_store_unavailable",
                "retryable": True,
                "freshness": None,
                "provenance": ["database"],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "deadline_ms": int(
                    (_PREDICTION_DEADLINE_SECONDS if include_predictions else _DISCOVERY_DEADLINE_SECONDS)
                    * 1000
                ),
            },
        )


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint for upcoming matches service."""
    return {
        "status": "healthy",
        "service": "upcoming_matches",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
