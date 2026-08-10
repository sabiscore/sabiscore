from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, aliased
from sqlalchemy import or_, func
from typing import List, Optional, Dict, Any
import logging
import time
import json
from datetime import datetime, timezone
from pydantic import ValidationError

from ..core.database import (
    get_db,
    check_database_health,
    Match,
    Team,
)
from ..core.cache import cache
from ..core.exceptions import DataUnavailableError
from ..models.active_generation import load_active_generation
from ..schemas.requests import InsightsRequest
from ..schemas.responses import (
    ErrorResponse,
    InsightsResponse,
    MatchSearchResponse,
    HealthResponse,
    CacheMetricsResponse,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # avoid importing heavy ML dependencies at import time during tests
    from ..models.ensemble import SabiScoreEnsemble  # pragma: no cover - only for type checking

logger = logging.getLogger(__name__)

router = APIRouter()

def _http_error(status_code: int, detail: str, error_code: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(detail=detail, error_code=error_code).model_dump(mode="json"),
    )


def _load_model_from_app(request: Request) -> Optional["SabiScoreEnsemble"]:
    model = getattr(request.app.state, "model_instance", None)
    if model is not None and getattr(model, "is_trained", False):
        return model

    # Do not import api.main here (it defines a FastAPI app and causes side-effects
    # when imported). Rely on request.app.state which is populated by the running
    # application process to access loaded model instances.
    return None


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request, db: Session = Depends(get_db)):
    """Enhanced health check with database and cache status"""
    start_time = time.time()

    try:
        # Test database connection
        db_healthy = check_database_health()

        # Test cache connection
        cache_healthy = cache.ping()

        # Test model availability using in-memory instance
        model_instance = getattr(request.app.state, "model_instance", None)
        models_healthy = bool(model_instance and getattr(model_instance, "is_trained", False))
        # indicate if a background model load is in progress
        model_loading = bool(getattr(request.app.state, "model_load_in_progress", False))
        model_error = getattr(request.app.state, "model_load_error_message", None)

        metrics_snapshot = cache.metrics_snapshot()
        latency_ms = (time.time() - start_time) * 1000

        status = "healthy" if all([db_healthy, cache_healthy, models_healthy]) else "degraded"

        return HealthResponse(
            status=status,
            database=db_healthy,
            models=models_healthy,
            model_loading=model_loading,
            model_error=model_error,
            cache=cache_healthy,
            cache_metrics=CacheMetricsResponse(**metrics_snapshot),
            latency_ms=latency_ms,
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        latency_ms = (time.time() - start_time) * 1000
        return HealthResponse(
            status="unhealthy",
            database=False,
            models=False,
            model_loading=False,
            model_error=None,
            cache=False,
            cache_metrics=None,
            latency_ms=latency_ms,
        )

@router.get("/matches/search", response_model=List[MatchSearchResponse])
async def search_matches(
    q: str = Query(..., description="Search query for teams or matches", min_length=2),
    league: Optional[str] = Query(None, description="Filter by league"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results to return"),
    db: Session = Depends(get_db),
):
    """Search for matches with filtering, pagination, and caching."""
    query = q.strip()
    if not query:
        raise _http_error(400, "Query must not be empty", "VALIDATION_ERROR")

    cache_key = f"matches:search:{query.lower()}:{league or '*'}:{limit}"
    cached_results = cache.get(cache_key)
    if cached_results is not None:
        return [MatchSearchResponse(**item) for item in cached_results]

    try:
        home_team = aliased(Team)
        away_team = aliased(Team)

        stmt = (
            db.query(Match, home_team, away_team)
            .join(home_team, Match.home_team_id == home_team.id)
            .join(away_team, Match.away_team_id == away_team.id)
        )

        like_pattern = f"%{query}%"
        stmt = stmt.filter(
            or_(
                func.lower(home_team.name).like(func.lower(like_pattern)),
                func.lower(away_team.name).like(func.lower(like_pattern)),
            )
        )

        if league:
            stmt = stmt.filter(func.lower(Match.league_id) == league.lower())

        stmt = stmt.order_by(Match.match_date.asc()).limit(limit)

        results = []
        for match, home, away in stmt.all():
            results.append(
                MatchSearchResponse(
                    id=str(match.id),
                    home_team=home.name,
                    away_team=away.name,
                    league=match.league_id,
                    match_date=match.match_date.isoformat() if match.match_date else None,
                    venue=match.venue or "",
                )
            )

        payload = [result.model_dump() for result in results]
        cache.set(cache_key, payload, ttl=300)
        return results

    except Exception:
        logger.exception("Match search failed", extra={"query": query, "league": league})
        # Graceful degrade: return an empty list on backend errors to keep UX responsive
        return []

@router.post("/insights", response_model=InsightsResponse)
async def generate_insights(
    request: Request,
    body: InsightsRequest,
    db: Session = Depends(get_db),
):
    """
    Generate comprehensive betting insights for a match.
    
    This endpoint analyzes a specific matchup and provides:
    - Win/draw/loss probabilities with confidence scores
    - Expected goals (xG) analysis
    - Value betting opportunities with Kelly criterion stakes
    - Monte Carlo simulation results with scenario analysis
    - Risk assessment and recommendations
    - AI-generated narrative explanation
    
    Args:
        body: Match details including matchup (e.g., "Arsenal vs Chelsea") and league (e.g., "EPL")
    
    Returns:
        Comprehensive insights including predictions, betting analysis, and risk assessment
    
    Raises:
        400: Invalid input parameters
        503: Prediction model unavailable
        500: Internal server error during insights generation
    """
    start_time = time.time()

    try:
        # Validate input parameters
        if not body.matchup or not body.matchup.strip():
            raise _http_error(400, "Matchup parameter is required and cannot be empty", "INVALID_MATCHUP")
        
        if " vs " not in body.matchup and " v " not in body.matchup:
            raise _http_error(
                400, 
                "Matchup must be in format 'Team1 vs Team2' or 'Team1 v Team2'", 
                "INVALID_MATCHUP_FORMAT"
            )
        
        league = body.league or "EPL"
        valid_leagues = ["EPL", "La Liga", "Serie A", "Bundesliga", "Ligue 1", "Eredivisie"]
        if league not in valid_leagues:
            logger.warning(f"Unknown league '{league}', proceeding with fallback")
        
        # Check cache first (cache key based on normalized matchup and league)
        cache_key = f"insights:{body.matchup.lower().strip()}:{league.lower()}"
        cached_insights = cache.get(cache_key)
        if cached_insights is not None:
            logger.info(
                "insights_cache_hit",
                extra={"matchup": body.matchup, "league": league, "cache_key": cache_key}
            )
            try:
                # Coerce cached payload into schema to prevent MagicMock or non-serializable leaks
                if isinstance(cached_insights, InsightsResponse):
                    return cached_insights
                coerced = InsightsResponse(**cached_insights)
                return coerced
            except Exception:
                # Purge bad cache entry and continue to regenerate
                cache.delete(cache_key)
        
        # Load model
        model = _load_model_from_app(request)
        if model is None:
            logger.error("Prediction model unavailable", extra={"matchup": body.matchup, "league": league})
            raise _http_error(503, "Prediction model unavailable - please try again later", "MODEL_UNAVAILABLE")

    # Reuse explicitly assigned insights engine (tests may provide mocked engine)
        engine = None
        if hasattr(model, "__dict__"):
            engine = model.__dict__.get("engine")

        if not engine or not hasattr(engine, "generate_match_insights"):
            # Lazy import to avoid heavy ML imports during test collection
            from ..insights.engine import InsightsEngine  # local import

            engine = InsightsEngine(model=model)
            setattr(model, "engine", engine)
        
        # Generate insights
        insights = engine.generate_match_insights(
            matchup=body.matchup,
            league=league,
        )

        # Validate the payload, then cache it (TTL: 1 hour for match insights).
        # Note this must not reuse the name `model` — that still holds the ML model.
        response = insights if isinstance(insights, InsightsResponse) else InsightsResponse(**insights)
        try:
            cache.set(cache_key, response.model_dump(mode="json"), ttl=3600)
        except Exception as cache_exc:
            logger.warning(f"Failed to cache insights: {cache_exc}")

        processing_time = time.time() - start_time
        logger.info(
            "insights_generated_successfully",
            extra={
                "matchup": body.matchup, 
                "league": league, 
                "duration_ms": round(processing_time * 1000, 2),
                "confidence": insights.get("confidence_level", 0),
                "cached": False
            },
        )

        return response

    except HTTPException:
        raise
    except DataUnavailableError as exc:
        # Fail closed: required evidence is absent, so there is nothing honest to return.
        logger.warning(
            "Insights refused — insufficient evidence",
            extra={"matchup": body.matchup, "league": body.league, "reason": str(exc)},
        )
        raise _http_error(
            422, f"Insufficient verified evidence: {exc}", "INSUFFICIENT_EVIDENCE"
        ) from exc
    except ValidationError as exc:
        raise _http_error(500, f"Insights validation error: {exc}", "INSIGHTS_VALIDATION_ERROR") from exc
    except ValueError as exc:
        # Handle validation errors from downstream components
        logger.warning(f"Validation error: {str(exc)}", extra={"matchup": body.matchup, "league": body.league})
        raise _http_error(400, f"Invalid input: {str(exc)}", "VALIDATION_ERROR") from exc
    except Exception as exc:
        processing_time = time.time() - start_time
        logger.exception(
            "Insights generation failed", 
            extra={
                "matchup": body.matchup, 
                "league": body.league,
                "duration_ms": round(processing_time * 1000, 2),
                "error_type": type(exc).__name__
            }
        )
        raise _http_error(500, "Failed to generate insights - internal server error", "INSIGHTS_ERROR") from exc

@router.get("/models/status")
async def model_status(league: Optional[str] = None):
    """Return authoritative active-artifact metadata without optimistic defaults."""

    cache_key = f"model-status:{league or '*'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        metadata = _active_model_metadata()

        if league:
            league_key = league.upper()
            league_meta = metadata.get("models", {}).get(league_key)
            if not league_meta:
                raise _http_error(404, f"No metadata available for league '{league}'", "MODEL_METADATA_NOT_FOUND")
            response = {"models_loaded": True, "league": league_key, **league_meta}
        else:
            response = {
                "models_loaded": bool(metadata.get("models")),
                **metadata,
            }

        cache.set(cache_key, response, ttl=3600)
        return response

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Model status check failed", extra={"league": league})
        raise _http_error(500, "Failed to get model status", "MODEL_STATUS_ERROR") from exc


def _active_model_metadata() -> Dict[str, Any]:
    """Summarize artifacts the prediction engine can actually discover.

    Missing governance fields remain ``UNKNOWN``/``UNVERIFIED``. A training
    report or filename alone is never treated as certification evidence.
    """

    generation = load_active_generation()
    models: Dict[str, Any] = {}
    for league_slug, entry in generation["artifacts"].items():
        metadata_file = entry["metadata_path"]
        with metadata_file.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid model metadata for {league_slug}")
        models[league_slug.upper()] = {
            "active_version": generation["active_version"],
            "generation": generation["generation"],
            "feature_schema_version": generation["feature_schema_version"],
            "feature_count": data.get("feature_count"),
            "training_corpus_samples": data.get("training_samples"),
            "training_window": data.get("training_window"),
            "holdout_season": data.get("holdout_season"),
            "served_head": generation["served_head"],
            "calibration_status": data.get("calibration_status", "UNKNOWN"),
            "certification_state": generation["certification_state"],
            "validation_status": generation["certification_state"],
            "artifact_type": entry["artifact_path"].suffix.lstrip("."),
            "artifact_sha256": entry["artifact_sha256"],
            "metrics": {
                key: data.get(key)
                for key in ("rps", "brier_score", "log_loss", "accuracy", "holdout_samples")
            },
            "trained_at": data.get("trained_at"),
            "data_source": data.get("data_source"),
            "stake_permitted": generation["certification_state"] == "CERTIFIED",
        }

    return {
        "active_version": generation["active_version"],
        "generation": generation["generation"],
        "generation_hash": generation["manifest_sha256"],
        "manifest_valid": True,
        "feature_schema_version": generation["feature_schema_version"],
        "served_head": generation["served_head"],
        "certification_state": generation["certification_state"],
        "validation_status": generation["certification_state"],
        "promotion_state": generation["promotion_state"],
        "promoted_at": generation.get("promoted_at"),
        "stake_permitted": generation["certification_state"] == "CERTIFIED",
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": models,
    }


@router.get("/metrics/cache", response_model=CacheMetricsResponse)
async def cache_metrics():
    """Expose cache metrics and current circuit breaker state."""

    metrics = cache.metrics_snapshot()
    return CacheMetricsResponse(**metrics)


@router.get("/metrics", include_in_schema=False)
async def system_metrics(request: Request):
    """System-wide metrics for monitoring."""
    from ..core.cache import cache

    try:
        # Database connection count (approximation)
        db_connections = 1  # Placeholder - implement actual count if available

        # Cache hit rate
        cache_hit_rate = getattr(cache, 'hit_rate', lambda: 0.85)()

        # Model version
        model = _load_model_from_app(request)
        model_version = getattr(model, 'version', '1.0.0') if model else 'unloaded'

        return {
            "db_connections": db_connections,
            "cache_hit_rate": cache_hit_rate,
            "model_version": model_version,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Metrics collection failed: {e}")
        return {
            "error": "Metrics unavailable",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# Note: Modular routers are already included via api/__init__.py
# No need to duplicate them here in legacy_endpoints
