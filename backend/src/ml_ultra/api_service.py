"""
SabiScore Ultra - FastAPI Production Service
Target: <30ms latency, 1000+ req/s throughput
Features: Redis caching, async handlers, request batching, GZIP compression
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime
from functools import wraps
from typing import Dict, List, Optional, Any

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field, validator
import numpy as np
import pandas as pd

from .training_pipeline import ProductionMLPipeline

# ============================================================================
# CONFIGURATION
# ============================================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
MODEL_PATH = os.getenv("MODEL_PATH", "models/ultra")  # Directory path, not file
API_KEY = os.getenv("API_KEY")
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))  # 5 minutes
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "50"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# REDIS CONNECTION
# ============================================================================

redis_client: Optional[redis.Redis] = None

async def get_redis() -> redis.Redis:
    """Get Redis client (singleton pattern)"""
    global redis_client
    if redis_client is None:
        redis_client = await redis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50
        )
    return redis_client

async def close_redis():
    """Close Redis connection"""
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class MatchFeatures(BaseModel):
    """Input features for a single match prediction"""
    match_id: str = Field(..., description="Unique match identifier")
    home_team_id: int = Field(..., description="Home team ID")
    away_team_id: int = Field(..., description="Away team ID")
    league_id: int = Field(..., description="League ID")
    match_date: str = Field(..., description="Match date (ISO format)")
    
    # Team form (last 5 matches)
    home_last_5_wins: int = Field(0, ge=0, le=5)
    home_last_5_draws: int = Field(0, ge=0, le=5)
    home_last_5_losses: int = Field(0, ge=0, le=5)
    away_last_5_wins: int = Field(0, ge=0, le=5)
    away_last_5_draws: int = Field(0, ge=0, le=5)
    away_last_5_losses: int = Field(0, ge=0, le=5)
    
    # Goals statistics
    home_goals_scored_avg: float = Field(0.0, ge=0.0)
    home_goals_conceded_avg: float = Field(0.0, ge=0.0)
    away_goals_scored_avg: float = Field(0.0, ge=0.0)
    away_goals_conceded_avg: float = Field(0.0, ge=0.0)
    
    # Head-to-head
    h2h_home_wins: int = Field(0, ge=0)
    h2h_draws: int = Field(0, ge=0)
    h2h_away_wins: int = Field(0, ge=0)
    
    # Additional context (optional)
    home_odds: Optional[float] = Field(None, gt=1.0)
    draw_odds: Optional[float] = Field(None, gt=1.0)
    away_odds: Optional[float] = Field(None, gt=1.0)

    @validator('match_date')
    def validate_date(cls, v):
        try:
            datetime.fromisoformat(v.replace('Z', '+00:00'))
            return v
        except ValueError:
            raise ValueError("match_date must be in ISO format")

class PredictionRequest(BaseModel):
    """Single prediction request"""
    features: MatchFeatures

class BatchPredictionRequest(BaseModel):
    """Batch prediction request"""
    matches: List[MatchFeatures] = Field(..., max_items=MAX_BATCH_SIZE)

class PredictionResponse(BaseModel):
    """Prediction response"""
    match_id: str
    home_win_prob: float = Field(..., ge=0.0, le=1.0)
    draw_prob: float = Field(..., ge=0.0, le=1.0)
    away_win_prob: float = Field(..., ge=0.0, le=1.0)
    predicted_outcome: str = Field(..., pattern="^(home_win|draw|away_win)$")
    confidence: float = Field(..., ge=0.0, le=1.0)
    uncertainty: float = Field(..., ge=0.0, le=1.0)
    model_version: str
    latency_ms: float
    cached: bool = False

class BatchPredictionResponse(BaseModel):
    """Batch prediction response"""
    predictions: List[PredictionResponse]
    total_latency_ms: float
    avg_latency_ms: float

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    model_loaded: bool
    model_version: str
    redis_connected: bool
    uptime_seconds: float
    total_requests: int
    cache_hit_rate: float

# ============================================================================
# MODEL MANAGER
# ============================================================================

class ModelManager:
    """Manages ML model lifecycle"""
    
    def __init__(self):
        self.pipeline: Optional[ProductionMLPipeline] = None
        self.model_version: str = "unknown"
        self.load_time: float = 0
        
    def load_model(self, model_path: str) -> None:
        """Load trained model from directory"""
        start_time = time.time()
        logger.info(f"Loading model from {model_path}...")
        
        try:
            self.pipeline = ProductionMLPipeline.load_trained_model(model_path)
            
            # Load metadata from directory
            metadata_path = os.path.join(model_path, 'metadata.json')
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                    self.model_version = metadata.get('model_version', 'v1.0.0')
            
            self.load_time = time.time() - start_time
            logger.info(f"✅ Model loaded in {self.load_time:.2f}s (version: {self.model_version})")
            
        except Exception as e:
            logger.error(f"❌ Failed to load model: {e}")
            raise
    
    def predict(self, features_dict: Dict[str, Any]) -> Dict[str, float]:
        """Make prediction from pre-computed features"""
        if not self.pipeline:
            raise RuntimeError("Model not loaded")
        
        # The API receives pre-computed features, so we need to use the ensemble directly
        # rather than going through feature engineering
        
        # Create DataFrame with features
        feature_names = self.pipeline.feature_names
        
        # Build feature vector from input dict, filling missing features with 0
        feature_values = {}
        for feat_name in feature_names:
            feature_values[feat_name] = features_dict.get(feat_name, 0.0)
        
        # Create single-row DataFrame
        df = pd.DataFrame([feature_values])
        
        # Get predictions from ensemble
        probas = self.pipeline.ensemble.predict_proba(df)
        
        # probas is [away_win, draw, home_win] (0, 1, 2)
        return {
            'home_win_prob': float(probas[0, 2]),
            'draw_prob': float(probas[0, 1]),
            'away_win_prob': float(probas[0, 0])
        }

# Global model manager
model_manager = ModelManager()

# ============================================================================
# CACHING DECORATOR
# ============================================================================

def cache_prediction(ttl: int = CACHE_TTL):
    """Decorator to cache predictions in Redis"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract request from args
            request = None
            for arg in args:
                if isinstance(arg, (PredictionRequest, BatchPredictionRequest)):
                    request = arg
                    break
            
            if not request:
                return await func(*args, **kwargs)
            
            # Generate cache key
            cache_key = _generate_cache_key(request)
            
            # Try to get from cache
            redis_conn = await get_redis()
            cached_result = await redis_conn.get(cache_key)
            
            if cached_result:
                logger.info(f"Cache HIT: {cache_key}")
                result = json.loads(cached_result)
                if isinstance(result, dict):
                    result['cached'] = True
                return result
            
            # Cache miss - call function
            logger.info(f"Cache MISS: {cache_key}")
            result = await func(*args, **kwargs)
            
            # Store in cache
            await redis_conn.setex(
                cache_key,
                ttl,
                json.dumps(result if isinstance(result, dict) else result.dict())
            )
            
            return result
        
        return wrapper
    return decorator

def _generate_cache_key(request) -> str:
    """Generate cache key from request"""
    if isinstance(request, PredictionRequest):
        data = request.features.dict()
    else:
        data = [m.dict() for m in request.matches]
    
    key_string = json.dumps(data, sort_keys=True)
    hash_key = hashlib.md5(key_string.encode()).hexdigest()
    return f"pred:{hash_key}"

# ============================================================================
# METRICS TRACKER
# ============================================================================

class MetricsTracker:
    """Track API metrics"""
    
    def __init__(self):
        self.start_time = time.time()
        self.total_requests = 0
        self.cache_hits = 0
        self.cache_misses = 0
        
    def record_request(self, cached: bool = False):
        self.total_requests += 1
        if cached:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
    
    def get_cache_hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.cache_hits / self.total_requests
    
    def get_uptime(self) -> float:
        return time.time() - self.start_time

metrics = MetricsTracker()

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="SabiScore Ultra API",
    description="Ultra-fast football prediction API with <30ms latency",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ============================================================================
# AUTHENTICATION
# ============================================================================

async def verify_api_key(x_api_key: str = Header(...)):
    """Verify API key"""
    if not API_KEY:
        raise HTTPException(status_code=503, detail="API key is not configured")
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

# ============================================================================
# STARTUP/SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Load model and connect to Redis on startup"""
    logger.info("🚀 Starting SabiScore Ultra API...")
    
    # Load model
    if os.path.exists(MODEL_PATH):
        model_manager.load_model(MODEL_PATH)
    else:
        logger.warning(f"⚠️ Model not found at {MODEL_PATH}, running without model")
    
    # Connect to Redis
    try:
        await get_redis()
        logger.info("✅ Connected to Redis")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Redis: {e}")
    
    logger.info("✅ API ready to serve requests")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down...")
    await close_redis()

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    redis_conn = await get_redis()
    redis_ok = await redis_conn.ping()
    
    return HealthResponse(
        status="healthy" if model_manager.pipeline and redis_ok else "degraded",
        model_loaded=model_manager.pipeline is not None,
        model_version=model_manager.model_version,
        redis_connected=redis_ok,
        uptime_seconds=metrics.get_uptime(),
        total_requests=metrics.total_requests,
        cache_hit_rate=metrics.get_cache_hit_rate()
    )

@app.post("/predict", response_model=PredictionResponse)
@cache_prediction(ttl=CACHE_TTL)
async def predict(
    request: PredictionRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Make a single match prediction
    Target latency: <30ms (cache hit), <100ms (cache miss)
    """
    start_time = time.time()
    
    try:
        # Make prediction
        result = model_manager.predict(request.features.dict())
        
        # Determine predicted outcome
        probs = [result['home_win_prob'], result['draw_prob'], result['away_win_prob']]
        max_prob = max(probs)
        outcomes = ['home_win', 'draw', 'away_win']
        predicted_outcome = outcomes[probs.index(max_prob)]
        
        # Calculate uncertainty (entropy)
        probs_array = np.array(probs)
        uncertainty = -np.sum(probs_array * np.log(probs_array + 1e-10))
        
        latency_ms = (time.time() - start_time) * 1000
        
        response = PredictionResponse(
            match_id=request.features.match_id,
            home_win_prob=result['home_win_prob'],
            draw_prob=result['draw_prob'],
            away_win_prob=result['away_win_prob'],
            predicted_outcome=predicted_outcome,
            confidence=max_prob,
            uncertainty=float(uncertainty),
            model_version=model_manager.model_version,
            latency_ms=latency_ms,
            cached=False
        )
        
        metrics.record_request(cached=False)
        logger.info(f"Prediction completed in {latency_ms:.2f}ms")
        
        return response
        
    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/predict/batch", response_model=BatchPredictionResponse)
async def predict_batch(
    request: BatchPredictionRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Make batch predictions for multiple matches
    Target throughput: 1000+ predictions/second
    """
    start_time = time.time()
    
    if len(request.matches) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size exceeds maximum of {MAX_BATCH_SIZE}"
        )
    
    try:
        # Process predictions in parallel
        tasks = []
        for match_features in request.matches:
            single_request = PredictionRequest(features=match_features)
            tasks.append(predict(single_request, api_key))
        
        predictions = await asyncio.gather(*tasks)
        
        total_latency_ms = (time.time() - start_time) * 1000
        avg_latency_ms = total_latency_ms / len(predictions)
        
        logger.info(
            f"Batch prediction: {len(predictions)} matches in {total_latency_ms:.2f}ms "
            f"(avg: {avg_latency_ms:.2f}ms/match)"
        )
        
        return BatchPredictionResponse(
            predictions=predictions,
            total_latency_ms=total_latency_ms,
            avg_latency_ms=avg_latency_ms
        )
        
    except Exception as e:
        logger.error(f"Batch prediction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/cache/clear")
async def clear_cache(api_key: str = Depends(verify_api_key)):
    """Clear all cached predictions"""
    try:
        redis_conn = await get_redis()
        keys = await redis_conn.keys("pred:*")
        if keys:
            await redis_conn.delete(*keys)
        
        return {"message": f"Cleared {len(keys)} cached predictions"}
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "SabiScore Ultra API",
        "version": "3.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }

# ============================================================================
# DEVELOPMENT SERVER
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    # Run with: python -m backend.src.ml_ultra.api_service
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True,
        workers=4  # For production
    )
