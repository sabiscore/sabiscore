"""Prediction endpoints for generating match predictions and value bets."""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging
import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import ValidationError

from ...core.exceptions import DataUnavailableError
from ...db.session import get_async_session
from ...services.prediction import PredictionService
from ...schemas.prediction import MatchPredictionRequest, PredictionResponse
from ...schemas.value_bet import ValueBetResponse
from ...core.database import Prediction as PredictionModel
from ...db.models import MatchPredictionLog
from ...core.cache import cache_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/predictions", tags=["predictions"])

# Rate limiting configuration
RATE_LIMIT_REQUESTS = 100  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds
_rate_limit_store: dict = defaultdict(list)
_rate_limit_lock = asyncio.Lock()


async def check_rate_limit(client_ip: str) -> None:
    """Simple in-memory rate limiter for prediction endpoints."""
    async with _rate_limit_lock:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
        
        # Clean old entries
        _rate_limit_store[client_ip] = [
            ts for ts in _rate_limit_store[client_ip] if ts > window_start
        ]
        
        # Check limit
        if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW}s"
            )
        
        _rate_limit_store[client_ip].append(now)

# Convenience alias for /predictions endpoint
@router.post("/predict", response_model=PredictionResponse, include_in_schema=False)
async def predict_match_alias(
    request: MatchPredictionRequest,
    background_tasks: BackgroundTasks,
    request_context: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Alias for POST /predictions/ - convenience endpoint for match prediction."""
    return await create_prediction(request, background_tasks, request_context, db)


@router.post("/", response_model=PredictionResponse)
async def create_prediction(
    request: MatchPredictionRequest,
    background_tasks: BackgroundTasks,
    request_context: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Generate comprehensive match prediction with value bet analysis
    
    Pipeline:
    1. Fetch historical data (180k+ matches)
    2. Engineer 220+ features
    3. Run ensemble models (RF, XGBoost, LightGBM)
    4. Apply Platt calibration
    5. Detect value bets (min edge: 4.2%)
    6. Calculate Smart Kelly stakes (⅛ Kelly)
    
    Target: <150ms response time @ 10k CCU
    Rate Limited: 100 req/min per IP
    """
    # Rate limiting
    client_ip = request_context.client.host if request_context.client else "unknown"
    await check_rate_limit(client_ip)
    
    try:
        # Initialize prediction service
        app_state = request_context.app.state
        ensemble_hint = getattr(app_state, "model_instance", None)
        cache_backend = getattr(app_state, "cache", cache_manager)

        prediction_service = PredictionService(
            db_session=db,
            cache_backend=cache_backend,
            ensemble_model=ensemble_hint,
        )
        
        # Generate prediction
        logger.info(f"Generating prediction for {request.home_team} vs {request.away_team}")
        start_time = datetime.now(timezone.utc)
        
        if request.match_id:
            match_identifier = request.match_id
        else:
            # Minting a synthetic key makes the prediction permanently
            # unjoinable by get_settled_predictions() — DEBT item 5.
            # Callers must supply a real fixture ID from /api/v1/fixtures/upcoming.
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "FIXTURE_IDENTITY_REQUIRED",
                    "message": (
                        "match_id is required. Supply a real fixture ID "
                        "from GET /api/v1/fixtures/upcoming."
                    ),
                },
            )

        try:
            # Add timeout to prevent hanging requests
            result = await asyncio.wait_for(
                prediction_service.predict_match(
                    match_id=match_identifier,
                    request=request,
                ),
                timeout=10.0  # 10 second timeout
            )
        except asyncio.TimeoutError:
            logger.error("Prediction timed out for %s vs %s", request.home_team, request.away_team)
            raise HTTPException(
                status_code=504,
                detail="Prediction request timed out. Please try again."
            )
        except FileNotFoundError as exc:
            logger.warning("Model not available: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="Model artifacts not available. System initializing."
            ) from exc
        except DataUnavailableError as exc:
            logger.warning("Prediction refused — no evidence: %s", exc)
            raise HTTPException(
                status_code=422,
                detail=f"Insufficient evidence for prediction: {exc}",
            ) from exc
        except ValueError as exc:
            logger.warning("Prediction input rejected: %s", exc)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except MemoryError as exc:
            logger.error("Out of memory during prediction: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="Service temporarily unavailable due to high load"
            ) from exc
        
        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        logger.info(f"Prediction generated in {processing_time:.1f}ms")
        
        # Provide a simple cache alias for lookup endpoints
        try:
            cache_backend.set(f"prediction:{match_identifier}", result.model_dump(), ttl=900)
        except Exception as cache_exc:
            logger.debug("Failed to write alias cache for %s: %s", match_identifier, cache_exc)

        # Save to database in background
        background_tasks.add_task(
            _save_prediction_to_db,
            db=db,
            prediction_data=result,
            match_id=match_identifier,
        )

        try:
            preds = result.predictions if isinstance(result.predictions, dict) else {}
            predicted_outcome = max(preds, key=preds.get) if preds else None
            edge_pct = None
            if result.value_bets:
                first_bet = result.value_bets[0]
                edge_pct = getattr(first_bet, "edge_percent", None)

            metadata = result.metadata if isinstance(result.metadata, dict) else {}
            request_context.state.prediction_result = {
                "match_id": result.match_id,
                "league": result.league.value if hasattr(result.league, "value") else str(result.league),
                "predicted_outcome": predicted_outcome,
                "confidence": result.confidence,
                "edge_pct": edge_pct,
                "feature_quality": metadata.get("feature_quality"),
                "model_version": metadata.get("model_version"),
                "value_bet": bool(result.value_bets),
            }
        except Exception as log_exc:
            logger.debug("Failed to prepare prediction log payload: %s", log_exc)
        
        return result
        
    except Exception as e:
        logger.error(f"Error generating prediction: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate prediction: {str(e)}"
        )


@router.get("/{match_id}", response_model=PredictionResponse)
async def get_prediction(
    match_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Retrieve existing prediction for a match
    
    Returns cached prediction if available (< 1 hour old),
    otherwise returns 404 prompting client to generate new prediction.
    """
    try:
        # Check cache first
        cache_key = f"prediction:{match_id}"
        cached_result = cache_manager.get(cache_key)
        
        if cached_result:
            logger.info(f"Cache hit for prediction {match_id}")
            if isinstance(cached_result, dict):
                return PredictionResponse(**cached_result)
            return cached_result
        
        # Fetch from database
        from sqlalchemy import select
        query = select(PredictionModel).where(PredictionModel.match_id == match_id)
        result = await db.execute(query)
        prediction = result.scalar_one_or_none()
        
        if not prediction:
            raise HTTPException(
                status_code=404,
                detail=f"No prediction found for match {match_id}. Generate a new prediction."
            )
        
        # Check if prediction is stale (> 1 hour old)
        age_minutes = (datetime.now(timezone.utc) - prediction.created_at).total_seconds() / 60
        if age_minutes > 60:
            raise HTTPException(
                status_code=410,
                detail=f"Prediction is {age_minutes:.0f} minutes old. Generate a fresh prediction."
            )
        
        payload = prediction.features
        response: PredictionResponse
        if payload:
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError as decode_err:
                    logger.warning("Failed to decode stored prediction payload for %s: %s", match_id, decode_err)
                    payload = None
            if isinstance(payload, dict):
                try:
                    response = PredictionResponse(**payload)
                except ValidationError as val_err:
                    logger.warning("Stored prediction payload invalid for %s: %s", match_id, val_err)
                    payload = None
            if not payload:
                raise HTTPException(
                    status_code=410,
                    detail="Stored prediction payload unavailable or corrupt; please regenerate.",
                )
        else:
            raise HTTPException(
                status_code=410,
                detail="Prediction stored without payload; please regenerate.",
            )
        
        # Cache for 30 minutes
        cache_manager.set(cache_key, response, ttl=1800)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching prediction for {match_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch prediction")


@router.get("/value-bets/today", response_model=list[ValueBetResponse])
async def get_todays_value_bets(
    min_edge: float = 0.042,  # 4.2% minimum
    min_confidence: float = 0.70,  # 70% confidence
    league: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get all value bets for today's matches
    
    Filters:
    - min_edge: Minimum edge threshold (default: 4.2%)
    - min_confidence: Minimum model confidence (default: 70%)
    - league: Optional league filter
    
    Returns sorted by edge (highest first)
    """
    try:
        # Check cache first
        cache_key = f"value_bets:today:{min_edge}:{min_confidence}:{league}"
        cached_result = cache_manager.get(cache_key)
        
        if cached_result:
            return cached_result

        # For production with real data, query from database
        # Currently returning empty list as we're building up data
        logger.info("No value bets available yet - building historical data")
        empty_response = []
        
        # Cache empty response for 5 minutes to reduce DB load
        cache_manager.set(cache_key, empty_response, ttl=300)
        return empty_response
        
    except Exception as e:
        logger.error(f"Error fetching value bets: {e}", exc_info=True)
        # Return empty list instead of 500 error during development
        return []


async def _save_prediction_to_db(
    db: AsyncSession,
    prediction_data: PredictionResponse,
    match_id: Optional[str]
):
    """Background task to save prediction to database"""
    try:
        payload = prediction_data.model_dump(mode="json")
        prediction = PredictionModel(
            match_id=match_id or prediction_data.match_id,
            home_win_prob=prediction_data.predictions['home_win'],
            draw_prob=prediction_data.predictions['draw'],
            away_win_prob=prediction_data.predictions['away_win'],
            confidence=prediction_data.confidence,
            model_version=str(
                prediction_data.metadata.get('model_version')
                or prediction_data.metadata.get('model_key')
                or '3.0'
            ),
            features=payload,
            shap_values=prediction_data.explanations,
            created_at=prediction_data.created_at,
        )
        
        db.add(prediction)

        # WP-3.3: also log to match_prediction_logs, the settled-join source
        # walk_forward_validate() needs for real RPS scoring. canonical_fixture_id
        # stays NULL — it FKs the separate canonical_fixtures spine, which nothing
        # in this codebase populates today (see WP-1 identity work); match_id is
        # the legacy Match.id namespace, which is what WP-1's resolve_team_id()/
        # canonical_season() and get_settled_predictions() below actually operate on.
        from ...services.canonical_identity_service import canonical_fixture_id_for_provider_event

        persisted_match_id = match_id or prediction_data.match_id
        canonical_fixture_id = await canonical_fixture_id_for_provider_event(
            db,
            provider="football-data.org",
            provider_event_id=persisted_match_id,
        )
        db.add(
            MatchPredictionLog(
                match_id=persisted_match_id,
                canonical_fixture_id=canonical_fixture_id,
                model_version=str(
                    prediction_data.metadata.get('model_version')
                    or prediction_data.metadata.get('model_key')
                    or '3.0'
                ),
                calibration_method=prediction_data.metadata.get('calibration_method'),
                home_probability=prediction_data.predictions['home_win'],
                draw_probability=prediction_data.predictions['draw'],
                away_probability=prediction_data.predictions['away_win'],
                confidence=prediction_data.confidence,
                input_hash=None,
                decision_id=None,
                payload=None,
                created_at=prediction_data.created_at,
            )
        )

        await db.commit()
        logger.info(f"Saved prediction to database: {match_id}")

    except Exception as e:
        logger.error(f"Failed to save prediction to DB: {e}")
        await db.rollback()
