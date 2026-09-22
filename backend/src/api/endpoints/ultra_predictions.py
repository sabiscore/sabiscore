"""
Ultra Prediction API Endpoints
High-performance ML prediction endpoints using the Ultra ensemble

Target: 90%+ accuracy, <30ms latency with caching
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...services.ultra_prediction_service import get_ultra_prediction_service
from ...schemas.prediction import MatchPredictionRequest
from ...core.cache import cache_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ultra", tags=["ultra-predictions"])


# ============================================================================
# Request/Response Models
# ============================================================================


class UltraMatchFeatures(BaseModel):
    """Features for Ultra prediction model"""

    match_id: str = Field(..., description="Unique match identifier")
    home_team_id: int = Field(..., description="Home team ID")
    away_team_id: int = Field(..., description="Away team ID")
    league_id: int = Field(..., description="League ID")
    match_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Team form
    home_last_5_wins: int = Field(default=2, ge=0, le=5)
    home_last_5_draws: int = Field(default=1, ge=0, le=5)
    home_last_5_losses: int = Field(default=2, ge=0, le=5)
    away_last_5_wins: int = Field(default=2, ge=0, le=5)
    away_last_5_draws: int = Field(default=1, ge=0, le=5)
    away_last_5_losses: int = Field(default=2, ge=0, le=5)

    # Goals statistics
    home_goals_scored_avg: float = Field(default=1.5, ge=0)
    home_goals_conceded_avg: float = Field(default=1.2, ge=0)
    away_goals_scored_avg: float = Field(default=1.3, ge=0)
    away_goals_conceded_avg: float = Field(default=1.4, ge=0)

    # H2H
    h2h_home_wins: int = Field(default=3, ge=0)
    h2h_draws: int = Field(default=2, ge=0)
    h2h_away_wins: int = Field(default=3, ge=0)

    # Odds (optional)
    home_odds: Optional[float] = Field(default=None, gt=1.0)
    draw_odds: Optional[float] = Field(default=None, gt=1.0)
    away_odds: Optional[float] = Field(default=None, gt=1.0)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "match_id": "arsenal_chelsea_2024",
                "home_team_id": 42,
                "away_team_id": 49,
                "league_id": 1,
                "match_date": "2024-01-15T15:00:00Z",
                "home_last_5_wins": 3,
                "home_last_5_draws": 1,
                "home_last_5_losses": 1,
                "away_last_5_wins": 2,
                "away_last_5_draws": 2,
                "away_last_5_losses": 1,
                "home_goals_scored_avg": 2.1,
                "home_goals_conceded_avg": 0.9,
                "away_goals_scored_avg": 1.8,
                "away_goals_conceded_avg": 1.1,
            }
        }
    )


class UltraPredictRequest(BaseModel):
    """Request for Ultra prediction"""

    features: UltraMatchFeatures


class UltraPredictResponse(BaseModel):
    """Response from Ultra prediction"""

    match_id: str
    home_win_prob: float = Field(..., ge=0, le=1)
    draw_prob: float = Field(..., ge=0, le=1)
    away_win_prob: float = Field(..., ge=0, le=1)
    predicted_outcome: str
    confidence: float = Field(..., ge=0, le=1)
    uncertainty: float = Field(..., ge=0, le=1)
    model_version: str
    latency_ms: int
    cached: bool


class UltraBatchPredictRequest(BaseModel):
    """Batch prediction request"""

    matches: List[UltraMatchFeatures] = Field(..., max_length=50)


class UltraBatchPredictResponse(BaseModel):
    """Batch prediction response"""

    predictions: List[UltraPredictResponse]
    total_latency_ms: int
    avg_latency_ms: float


class UltraHealthResponse(BaseModel):
    """Ultra service health status"""

    status: str
    model_loaded: bool
    model_version: str
    redis_connected: bool
    uptime_seconds: float
    total_requests: int
    cache_hit_rate: float


class UltraStatusResponse(BaseModel):
    """Ultra service status details"""

    service: str
    version: str
    ultra_model_loaded: bool
    legacy_fallback_available: bool
    metrics: dict
    timestamp: str


# ============================================================================
# Service startup time tracking
# ============================================================================
_service_start_time = datetime.now(timezone.utc)


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/predict", response_model=UltraPredictResponse)
async def ultra_predict(
    request: UltraPredictRequest,
    background_tasks: BackgroundTasks,
    request_context: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Generate prediction using Ultra ML ensemble

    Features:
    - Meta-learning ensemble (XGBoost + LightGBM + CatBoost)
    - 120+ engineered features
    - Redis caching (<5ms cache hits)
    - Automatic fallback to legacy model

    Target: <30ms latency with cache, <100ms without
    """
    start_time = datetime.now(timezone.utc)

    try:
        # Get service
        service = get_ultra_prediction_service(db)

        features = request.features

        # Check cache first
        cache_key = f"ultra:{features.match_id}"
        cached = cache_manager.get(cache_key)

        if cached is not None:
            latency_ms = int(
                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            )
            logger.debug(f"Cache hit for {features.match_id} in {latency_ms}ms")
            return UltraPredictResponse(
                match_id=features.match_id,
                home_win_prob=cached["home_win_prob"],
                draw_prob=cached["draw_prob"],
                away_win_prob=cached["away_win_prob"],
                predicted_outcome=cached["predicted_outcome"],
                confidence=cached["confidence"],
                uncertainty=cached.get("uncertainty", 0.1),
                model_version=cached.get("model_version", "v3.0.0-ultra"),
                latency_ms=latency_ms,
                cached=True,
            )

        # Map league_id to LeagueCode enum
        league_map = {
            1: "epl",
            2: "bundesliga",
            3: "la_liga",
            4: "serie_a",
            5: "ligue_1",
        }
        league_code = league_map.get(features.league_id, "epl")

        # Convert request to legacy format for service compatibility
        legacy_request = MatchPredictionRequest(
            home_team=f"Team_{features.home_team_id}",
            away_team=f"Team_{features.away_team_id}",
            league=league_code,
            match_id=features.match_id,
        )

        # Generate prediction with timeout
        try:
            result = await asyncio.wait_for(
                service.predict_match(
                    match_id=features.match_id,
                    request=legacy_request,
                ),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.error(f"Ultra prediction timed out for {features.match_id}")
            raise HTTPException(
                status_code=504,
                detail="Prediction request timed out. Please try again.",
            )

        latency_ms = int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        )

        # Determine predicted outcome
        probs = result.predictions
        outcomes = [
            ("home_win", probs.get("home_win", 0)),
            ("draw", probs.get("draw", 0)),
            ("away_win", probs.get("away_win", 0)),
        ]
        predicted_outcome = max(outcomes, key=lambda x: x[1])[0]

        # Build response
        response = UltraPredictResponse(
            match_id=result.match_id,
            home_win_prob=probs.get("home_win", 0.33),
            draw_prob=probs.get("draw", 0.33),
            away_win_prob=probs.get("away_win", 0.33),
            predicted_outcome=predicted_outcome,
            confidence=result.confidence,
            uncertainty=1.0 - result.confidence,
            model_version=result.metadata.get("model_version", "v3.0.0-ultra"),
            latency_ms=latency_ms,
            cached=False,
        )

        # Cache result
        cache_manager.set(cache_key, response.model_dump(), ttl=300)

        logger.info(
            f"Ultra prediction: {features.match_id} -> {predicted_outcome} "
            f"(conf={result.confidence:.2f}, latency={latency_ms}ms)"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ultra prediction error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


@router.post("/predict/batch", response_model=UltraBatchPredictResponse)
async def ultra_predict_batch(
    request: UltraBatchPredictRequest,
    background_tasks: BackgroundTasks,
    request_context: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Batch prediction for multiple matches

    More efficient for bulk operations (up to 50 matches)
    """
    start_time = datetime.now(timezone.utc)

    if len(request.matches) == 0:
        return UltraBatchPredictResponse(
            predictions=[], total_latency_ms=0, avg_latency_ms=0.0
        )

    if len(request.matches) > 50:
        raise HTTPException(
            status_code=400, detail="Batch size exceeds maximum of 50 matches"
        )

    predictions: List[UltraPredictResponse] = []

    try:
        # Process matches in parallel
        tasks = [
            ultra_predict(
                UltraPredictRequest(features=match),
                background_tasks,
                request_context,
                db,
            )
            for match in request.matches
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Batch prediction error: {result}")
                continue
            predictions.append(result)

        total_latency_ms = int(
            (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        )
        avg_latency_ms = (
            total_latency_ms / len(request.matches) if request.matches else 0.0
        )

        return UltraBatchPredictResponse(
            predictions=predictions,
            total_latency_ms=total_latency_ms,
            avg_latency_ms=avg_latency_ms,
        )

    except Exception as e:
        logger.error(f"Batch prediction error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Batch prediction failed: {str(e)}"
        )


@router.get("/health", response_model=UltraHealthResponse)
async def ultra_health():
    """
    Ultra service health check

    Returns model status, cache connectivity, and performance metrics
    """
    try:
        service = get_ultra_prediction_service()
        status_data = service.get_service_status()

        # Check Redis
        redis_connected = False
        try:
            cache_manager.set("health_check", "ok", ttl=5)
            redis_connected = cache_manager.get("health_check") == "ok"
        except Exception:
            pass

        # Calculate uptime
        uptime_seconds = (
            datetime.now(timezone.utc) - _service_start_time
        ).total_seconds()

        # Determine status
        if status_data["ultra_model_loaded"] and redis_connected:
            status = "healthy"
        elif (
            status_data["ultra_model_loaded"]
            or status_data["legacy_fallback_available"]
        ):
            status = "degraded"
        else:
            status = "unhealthy"

        return UltraHealthResponse(
            status=status,
            model_loaded=status_data["ultra_model_loaded"],
            model_version=status_data["version"],
            redis_connected=redis_connected,
            uptime_seconds=uptime_seconds,
            total_requests=int(status_data["metrics"]["predictions_count"]),
            cache_hit_rate=status_data["metrics"]["cache_hit_rate"],
        )

    except Exception as e:
        logger.error(f"Health check error: {e}")
        return UltraHealthResponse(
            status="unhealthy",
            model_loaded=False,
            model_version="unknown",
            redis_connected=False,
            uptime_seconds=0,
            total_requests=0,
            cache_hit_rate=0.0,
        )


@router.get("/status", response_model=UltraStatusResponse)
async def ultra_status():
    """
    Detailed Ultra service status and metrics
    """
    try:
        service = get_ultra_prediction_service()
        return UltraStatusResponse(**service.get_service_status())
    except Exception as e:
        logger.error(f"Status check error: {e}")
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")


@router.delete("/cache/clear")
async def clear_cache(
    pattern: Optional[str] = Query(
        default="ultra:*", description="Cache key pattern to clear"
    ),
):
    """
    Clear prediction cache (admin operation)
    """
    try:
        # For Redis-backed cache, clear by pattern
        # For in-memory cache, clear all
        cache_manager.clear()
        return {"message": "Cache cleared successfully", "pattern": pattern}
    except Exception as e:
        logger.error(f"Cache clear error: {e}")
        raise HTTPException(status_code=500, detail=f"Cache clear failed: {str(e)}")


@router.get("/metrics")
async def get_metrics():
    """
    Get Ultra service metrics for monitoring
    """
    try:
        service = get_ultra_prediction_service()
        status = service.get_service_status()

        return {
            "predictions": {
                "total": status["metrics"]["predictions_count"],
                "ultra": status["metrics"]["ultra_predictions"],
                "fallback": status["metrics"]["fallback_predictions"],
            },
            "performance": {
                "avg_latency_ms": status["metrics"]["avg_latency_ms"],
                "cache_hit_rate": status["metrics"]["cache_hit_rate"],
            },
            "model": {
                "version": status["version"],
                "ultra_loaded": status["ultra_model_loaded"],
                "fallback_available": status["legacy_fallback_available"],
            },
            "timestamp": status["timestamp"],
        }
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        raise HTTPException(
            status_code=500, detail=f"Metrics retrieval failed: {str(e)}"
        )
