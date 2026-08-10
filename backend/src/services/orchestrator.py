# backend/src/services/orchestrator.py
"""
Production Orchestrator - Coordinates entire data pipeline for SabiScore

This is the central coordinator that wires together:
1. DataIngestionService - Real-time scraping and streaming
2. DataProcessingService - Feature engineering
3. ModelOrchestrator - Prediction generation

Pipeline Flow:
Scrapers → Database → DataProcessingService → ModelOrchestrator → API Response
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, field

from sqlalchemy.orm import Session
from sqlalchemy import and_

from src.core.redaction import redact_text, safe_endpoint

logger = logging.getLogger(__name__)


class PipelineStatus(Enum):
    """Status of the production pipeline"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass
class HealthCheckResult:
    """Result of a health check for a component"""
    component: str
    status: str
    latency_ms: float
    last_success: Optional[datetime] = None
    error: Optional[str] = None
    details: Dict = field(default_factory=dict)


@dataclass
class PipelineMetrics:
    """Metrics for the production pipeline"""
    matches_processed: int = 0
    predictions_generated: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    scraper_errors: int = 0
    avg_latency_ms: float = 0.0
    uptime_seconds: float = 0.0
    last_scrape: Optional[datetime] = None
    last_prediction: Optional[datetime] = None


class ProductionOrchestrator:
    """
    Central orchestrator for SabiScore production pipeline
    
    Responsibilities:
    - Coordinate data flow between services
    - Monitor component health
    - Manage graceful degradation
    - Provide unified API for predictions
    - Handle caching and rate limiting
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        self.status = PipelineStatus.STOPPED
        self.metrics = PipelineMetrics()
        self.started_at: Optional[datetime] = None
        self._running = False
        self._background_tasks: List[asyncio.Task] = []
        
        # Initialize Redis (with fallback)
        self._init_redis(redis_url)
        
        # Lazy-load services to avoid circular imports
        self._data_processing = None
        self._model_orchestrator = None
        self._ingestion_service = None
        
        # Component health cache
        self._health_cache: Dict[str, HealthCheckResult] = {}
        self._health_check_interval = 30  # seconds
        
    def _init_redis(self, redis_url: Optional[str] = None):
        """Initialize Redis connection with fallback"""
        try:
            import redis
            url = redis_url or "redis://localhost:6379"
            self.redis = redis.from_url(url, decode_responses=True)
            self.redis.ping()
            logger.info("Redis connected: %s", safe_endpoint(url))
        except Exception as exc:
            logger.warning(
                "Redis unavailable at %s (%s), using DummyRedis",
                safe_endpoint(url),
                redact_text(exc),
            )
            self.redis = DummyRedis()
    
    @property
    def data_processing(self):
        """Lazy-load DataProcessingService"""
        if self._data_processing is None:
            from .data_processing import DataProcessingService
            self._data_processing = DataProcessingService()
        return self._data_processing
    
    @property
    def model_orchestrator(self):
        """Lazy-load ModelOrchestrator"""
        if self._model_orchestrator is None:
            try:
                from ..models.orchestrator import orchestrator
                self._model_orchestrator = orchestrator
            except ImportError:
                logger.warning("ModelOrchestrator not available, using mock")
                self._model_orchestrator = MockModelOrchestrator()
        return self._model_orchestrator
    
    @property
    def ingestion_service(self):
        """Lazy-load DataIngestionService"""
        if self._ingestion_service is None:
            from .data_ingestion import ingestion_service
            self._ingestion_service = ingestion_service
        return self._ingestion_service
    
    async def start(self):
        """Start the production pipeline"""
        if self._running:
            logger.warning("Pipeline already running")
            return
        
        self.status = PipelineStatus.STARTING
        logger.info("🚀 Starting SabiScore Production Pipeline...")
        
        try:
            # Start background tasks
            self._running = True
            self.started_at = datetime.now(timezone.utc)
            
            self._background_tasks = [
                asyncio.create_task(self._health_check_loop()),
                asyncio.create_task(self._metrics_aggregation_loop()),
            ]
            
            # Start data ingestion if available
            try:
                await self.ingestion_service.start()
                logger.info("✅ Data ingestion service started")
            except Exception as e:
                logger.warning(f"Data ingestion service unavailable: {e}")
            
            self.status = PipelineStatus.RUNNING
            logger.info("✅ Production Pipeline RUNNING")
            
        except Exception as e:
            self.status = PipelineStatus.ERROR
            logger.error(f"❌ Pipeline start failed: {e}")
            raise
    
    async def stop(self):
        """Stop the production pipeline gracefully"""
        if not self._running:
            return
        
        logger.info("🛑 Stopping SabiScore Production Pipeline...")
        self._running = False
        
        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
        
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()
        
        # Stop data ingestion
        try:
            await self.ingestion_service.stop()
        except Exception as e:
            logger.warning(f"Error stopping ingestion: {e}")
        
        self.status = PipelineStatus.STOPPED
        logger.info("✅ Production Pipeline STOPPED")
    
    # ===========================================
    # PREDICTION API
    # ===========================================
    
    def predict(
        self,
        league: str,
        home_team: str,
        away_team: str,
        match_date: Optional[datetime] = None,
        include_odds: bool = True,
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Generate prediction for a match
        
        This is the main entry point for predictions. It:
        1. Fetches features from DataProcessingService
        2. Generates predictions via ModelOrchestrator
        3. Caches results for performance
        
        Args:
            league: League name (e.g., 'premier_league', 'la_liga')
            home_team: Home team name
            away_team: Away team name
            match_date: Match datetime (default: now)
            include_odds: Whether to include odds analysis
            db: SQLAlchemy session
            
        Returns:
            Dict with predictions, confidence, and optional edge analysis
        """
        import time
        start_time = time.time()
        
        match_date = match_date or datetime.now(timezone.utc)
        cache_key = f"pred:{league}:{home_team}:{away_team}:{match_date.date()}"
        
        # Check cache first
        cached = self.redis.get(cache_key)
        if cached:
            self.metrics.cache_hits += 1
            import json
            result = json.loads(cached)
            result['cached'] = True
            return result
        
        self.metrics.cache_misses += 1
        
        try:
            # Step 1: Get match from database or create placeholder
            match_id = self._find_or_create_match(
                db, league, home_team, away_team, match_date
            )
            
            # Step 2: Extract features via DataProcessingService
            features = {}
            if db:
                features = self.data_processing.get_match_features(
                    db, match_id
                )
            
            # Step 3: Prepare match data for model
            match_data = {
                'match_id': match_id,
                'home_team': home_team,
                'away_team': away_team,
                'league': league,
                'match_date': match_date.isoformat(),
                **features
            }
            
            # Step 4: Get odds if requested
            odds = None
            if include_odds and db:
                odds = self._get_latest_odds(db, match_id)
            
            # Step 5: Generate prediction via ModelOrchestrator
            prediction = self.model_orchestrator.predict(
                league=league,
                match_data=match_data,
                odds=odds
            )
            
            # Step 6: Enrich response
            result = {
                'match_id': match_id,
                'home_team': home_team,
                'away_team': away_team,
                'league': league,
                'match_date': match_date.isoformat(),
                'predictions': prediction.get('predictions', {}),
                'confidence': self._calculate_confidence(prediction, features),
                'model_version': prediction.get('model_version', 'v3.0'),
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'cached': False,
                'latency_ms': round((time.time() - start_time) * 1000, 2)
            }
            
            # Add edge analysis if odds provided
            if odds and 'value_bets' in prediction:
                result['value_bets'] = prediction['value_bets']
                result['has_edge'] = prediction.get('has_edge', False)
            
            # Cache for 5 minutes
            import json
            self.redis.setex(cache_key, 300, json.dumps(result))
            
            # Update metrics
            self.metrics.predictions_generated += 1
            self.metrics.last_prediction = datetime.now(timezone.utc)
            self._update_latency(time.time() - start_time)
            
            return result
            
        except Exception as e:
            logger.error(f"Prediction error: {e}", exc_info=True)
            return {
                'error': str(e),
                'home_team': home_team,
                'away_team': away_team,
                'league': league,
                'generated_at': datetime.now(timezone.utc).isoformat()
            }
    
    def batch_predict(
        self,
        matches: List[Dict],
        db: Optional[Session] = None
    ) -> List[Dict]:
        """
        Generate predictions for multiple matches
        
        Args:
            matches: List of dicts with league, home_team, away_team, match_date
            db: SQLAlchemy session
            
        Returns:
            List of prediction results
        """
        results = []
        for match in matches:
            result = self.predict(
                league=match.get('league', 'premier_league'),
                home_team=match['home_team'],
                away_team=match['away_team'],
                match_date=match.get('match_date'),
                include_odds=match.get('include_odds', True),
                db=db
            )
            results.append(result)
        
        return results
    
    # ===========================================
    # HEALTH & MONITORING
    # ===========================================
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Comprehensive health check of all pipeline components
        
        Returns:
            Dict with overall status and component health
        """
        components = {}
        overall_healthy = True
        
        # Check Redis
        redis_health = await self._check_redis_health()
        components['redis'] = redis_health
        if redis_health.status != 'healthy':
            overall_healthy = False
        
        # Check Database
        db_health = await self._check_database_health()
        components['database'] = db_health
        if db_health.status != 'healthy':
            overall_healthy = False
        
        # Check Model Orchestrator
        model_health = await self._check_model_health()
        components['model_orchestrator'] = model_health
        if model_health.status != 'healthy':
            overall_healthy = False
        
        # Check Data Processing
        dp_health = await self._check_data_processing_health()
        components['data_processing'] = dp_health
        if dp_health.status != 'healthy':
            overall_healthy = False
        
        return {
            'status': 'healthy' if overall_healthy else 'degraded',
            'pipeline_status': self.status.value,
            'uptime_seconds': self._get_uptime(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'components': {
                name: {
                    'status': h.status,
                    'latency_ms': h.latency_ms,
                    'error': h.error,
                    **h.details
                }
                for name, h in components.items()
            },
            'metrics': {
                'predictions_generated': self.metrics.predictions_generated,
                'cache_hit_rate': self._get_cache_hit_rate(),
                'avg_latency_ms': self.metrics.avg_latency_ms,
                'last_prediction': self.metrics.last_prediction.isoformat() if self.metrics.last_prediction else None
            }
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current pipeline metrics"""
        return {
            'matches_processed': self.metrics.matches_processed,
            'predictions_generated': self.metrics.predictions_generated,
            'cache_hits': self.metrics.cache_hits,
            'cache_misses': self.metrics.cache_misses,
            'cache_hit_rate': self._get_cache_hit_rate(),
            'scraper_errors': self.metrics.scraper_errors,
            'avg_latency_ms': self.metrics.avg_latency_ms,
            'uptime_seconds': self._get_uptime(),
            'status': self.status.value,
            'last_scrape': self.metrics.last_scrape.isoformat() if self.metrics.last_scrape else None,
            'last_prediction': self.metrics.last_prediction.isoformat() if self.metrics.last_prediction else None
        }
    
    # ===========================================
    # HELPER METHODS
    # ===========================================
    
    def _find_or_create_match(
        self,
        db: Optional[Session],
        league: str,
        home_team: str,
        away_team: str,
        match_date: datetime
    ) -> str:
        """Find existing match or return a generated ID"""
        if not db:
            import hashlib
            key = f"{league}:{home_team}:{away_team}:{match_date.date()}"
            return hashlib.md5(key.encode()).hexdigest()[:12]
        
        try:
            from ..core.database import Match
            
            # Try to find existing match
            match = db.query(Match).filter(
                and_(
                    Match.home_team == home_team,
                    Match.away_team == away_team,
                    Match.match_date >= match_date - timedelta(hours=12),
                    Match.match_date <= match_date + timedelta(hours=12)
                )
            ).first()
            
            if match:
                return str(match.id)
            
            # Generate ID for non-existent match
            import hashlib
            key = f"{league}:{home_team}:{away_team}:{match_date.date()}"
            return hashlib.md5(key.encode()).hexdigest()[:12]
            
        except Exception as e:
            logger.warning(f"Error finding match: {e}")
            import hashlib
            key = f"{league}:{home_team}:{away_team}:{match_date.date()}"
            return hashlib.md5(key.encode()).hexdigest()[:12]
    
    def _get_latest_odds(self, db: Session, match_id: str) -> Optional[Dict]:
        """Get latest odds for a match"""
        try:
            from ..core.database import Odds
            
            odds = db.query(Odds).filter(
                Odds.match_id == match_id
            ).order_by(Odds.timestamp.desc()).first()
            
            if odds:
                return {
                    'home_win': odds.home_odds,
                    'draw': odds.draw_odds,
                    'away_win': odds.away_odds,
                    'bookmaker': odds.bookmaker,
                    'timestamp': odds.timestamp.isoformat() if odds.timestamp else None
                }
            return None
            
        except Exception as e:
            logger.warning(f"Error fetching odds: {e}")
            return None
    
    def _calculate_confidence(self, prediction: Dict, features: Dict) -> float:
        """Calculate prediction confidence based on data quality"""
        base_confidence = 0.5
        
        # Higher confidence with more features
        feature_count = len([v for v in features.values() if v is not None])
        feature_bonus = min(feature_count * 0.02, 0.3)
        
        # Higher confidence with strong predictions
        predictions = prediction.get('predictions', {})
        if predictions:
            max_prob = max(predictions.values()) if isinstance(predictions, dict) else 0.33
            certainty_bonus = (max_prob - 0.33) * 0.5  # Bonus for certainty
        else:
            certainty_bonus = 0
        
        return min(base_confidence + feature_bonus + certainty_bonus, 0.95)
    
    def _update_latency(self, latency_seconds: float):
        """Update rolling average latency"""
        latency_ms = latency_seconds * 1000
        if self.metrics.predictions_generated == 1:
            self.metrics.avg_latency_ms = latency_ms
        else:
            # Exponential moving average
            alpha = 0.1
            self.metrics.avg_latency_ms = (
                alpha * latency_ms + (1 - alpha) * self.metrics.avg_latency_ms
            )
    
    def _get_uptime(self) -> float:
        """Get pipeline uptime in seconds"""
        if self.started_at:
            return (datetime.now(timezone.utc) - self.started_at).total_seconds()
        return 0.0
    
    def _get_cache_hit_rate(self) -> float:
        """Calculate cache hit rate"""
        total = self.metrics.cache_hits + self.metrics.cache_misses
        if total == 0:
            return 0.0
        return round(self.metrics.cache_hits / total * 100, 2)
    
    # ===========================================
    # HEALTH CHECK IMPLEMENTATIONS
    # ===========================================
    
    async def _check_redis_health(self) -> HealthCheckResult:
        """Check Redis connectivity"""
        import time
        start = time.time()
        try:
            self.redis.ping()
            return HealthCheckResult(
                component='redis',
                status='healthy',
                latency_ms=round((time.time() - start) * 1000, 2),
                last_success=datetime.now(timezone.utc)
            )
        except Exception as e:
            return HealthCheckResult(
                component='redis',
                status='unhealthy',
                latency_ms=round((time.time() - start) * 1000, 2),
                error=str(e)
            )
    
    async def _check_database_health(self) -> HealthCheckResult:
        """Check database connectivity"""
        import time
        start = time.time()
        try:
            from ..core.database import engine
            from sqlalchemy import text
            
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            return HealthCheckResult(
                component='database',
                status='healthy',
                latency_ms=round((time.time() - start) * 1000, 2),
                last_success=datetime.now(timezone.utc)
            )
        except Exception as e:
            return HealthCheckResult(
                component='database',
                status='unhealthy',
                latency_ms=round((time.time() - start) * 1000, 2),
                error=str(e)
            )
    
    async def _check_model_health(self) -> HealthCheckResult:
        """Check model orchestrator health"""
        import time
        start = time.time()
        try:
            # Simple check - can we access the model?
            model_keys = list(self.model_orchestrator.models.keys())
            return HealthCheckResult(
                component='model_orchestrator',
                status='healthy',
                latency_ms=round((time.time() - start) * 1000, 2),
                last_success=datetime.now(timezone.utc),
                details={'loaded_models': len(model_keys), 'leagues': model_keys}
            )
        except Exception as e:
            return HealthCheckResult(
                component='model_orchestrator',
                status='unhealthy',
                latency_ms=round((time.time() - start) * 1000, 2),
                error=str(e)
            )
    
    async def _check_data_processing_health(self) -> HealthCheckResult:
        """Check data processing service health"""
        import time
        start = time.time()
        try:
            # Simple check - can we instantiate?
            _ = self.data_processing
            return HealthCheckResult(
                component='data_processing',
                status='healthy',
                latency_ms=round((time.time() - start) * 1000, 2),
                last_success=datetime.now(timezone.utc)
            )
        except Exception as e:
            return HealthCheckResult(
                component='data_processing',
                status='unhealthy',
                latency_ms=round((time.time() - start) * 1000, 2),
                error=str(e)
            )
    
    # ===========================================
    # BACKGROUND TASKS
    # ===========================================
    
    async def _health_check_loop(self):
        """Periodic health checks"""
        while self._running:
            try:
                health = await self.health_check()
                
                # Update status based on health
                if health['status'] == 'healthy':
                    self.status = PipelineStatus.RUNNING
                else:
                    self.status = PipelineStatus.DEGRADED
                
                # Cache health for API
                import json
                self.redis.setex(
                    'pipeline:health',
                    self._health_check_interval,
                    json.dumps(health)
                )
                
            except Exception as e:
                logger.error(f"Health check error: {e}")
            
            await asyncio.sleep(self._health_check_interval)
    
    async def _metrics_aggregation_loop(self):
        """Periodic metrics aggregation"""
        while self._running:
            try:
                # Update uptime
                self.metrics.uptime_seconds = self._get_uptime()
                
                # Cache metrics
                import json
                self.redis.setex(
                    'pipeline:metrics',
                    60,  # 1 minute TTL
                    json.dumps(self.get_metrics())
                )
                
            except Exception as e:
                logger.error(f"Metrics aggregation error: {e}")
            
            await asyncio.sleep(60)


class DummyRedis:
    """Fallback Redis implementation for local development"""
    
    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._expiry: Dict[str, datetime] = {}
    
    def get(self, key: str) -> Optional[str]:
        if key in self._expiry:
            if datetime.now(timezone.utc) > self._expiry[key]:
                del self._data[key]
                del self._expiry[key]
                return None
        return self._data.get(key)
    
    def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        self._data[key] = value
        if ex:
            self._expiry[key] = datetime.now(timezone.utc) + timedelta(seconds=ex)
        return True
    
    def setex(self, key: str, ttl: int, value: Any) -> bool:
        return self.set(key, value, ex=ttl)
    
    def exists(self, key: str) -> bool:
        return key in self._data
    
    def ping(self) -> bool:
        return True
    
    def delete(self, *keys) -> int:
        deleted = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                deleted += 1
        return deleted


class MockModelOrchestrator:
    """Mock ModelOrchestrator for testing when models aren't available"""
    
    def __init__(self):
        self.models = {}
    
    def predict(self, league: str, match_data: Dict, odds: Optional[Dict] = None) -> Dict:
        """Return mock predictions"""
        import random
        
        # Generate somewhat realistic probabilities
        home = random.uniform(0.35, 0.50)
        away = random.uniform(0.25, 0.40)
        draw = 1.0 - home - away
        
        return {
            'predictions': {
                'home_win': round(home, 3),
                'draw': round(draw, 3),
                'away_win': round(away, 3)
            },
            'model_version': 'mock_v1.0',
            'value_bets': [],
            'has_edge': False
        }
    
    def get_league_key(self, league: str) -> str:
        return league.lower().replace(' ', '_')


# ===========================================
# GLOBAL SINGLETON
# ===========================================

# Export singleton instance
production_orchestrator = ProductionOrchestrator()

# Convenience alias
orchestrator = production_orchestrator
