"""
Ultra Prediction Service - Production-Grade Integration Layer
Integrates ml_ultra module with existing FastAPI prediction surface
Target: 90%+ accuracy, <30ms latency
"""

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.cache import cache_manager
from ..core.league_policy import get_league_policy, LeaguePolicyUnavailableError
from ..models.edge_detector import EdgeDetector
from ..models.evaluation.metrics import expected_brier_score
from ..monitoring.metrics import metrics_collector
from ..schemas.prediction import MatchPredictionRequest, PredictionResponse
from ..schemas.value_bet import ValueBetResponse

# Lazy import ml_ultra components with graceful fallback
UltraPredictor = None
LegacyPredictorAdapter = None
AdvancedFeatureEngineer = None
_ml_ultra_available = False

try:
    from ..ml_ultra import is_ultra_available
    if is_ultra_available():
        from ..ml_ultra.ultra_predictor import UltraPredictor
        from ..ml_ultra.feature_engineering import AdvancedFeatureEngineer
        _ml_ultra_available = True
except ImportError as e:
    logging.getLogger(__name__).warning(f"ml_ultra not available: {e}")

logger = logging.getLogger(__name__)


class UltraPredictionService:
    """
    High-performance prediction service using ml_ultra ensemble
    
    Features:
    - Meta-learning ensemble (XGBoost + LightGBM + CatBoost)
    - 120+ advanced features
    - <30ms inference latency with caching
    - Automatic fallback to legacy ensemble
    """
    
    MODEL_VERSION = "v3.0.0-ultra"
    CACHE_TTL = 300  # 5 minutes
    
    def __init__(
        self,
        db_session: Optional[AsyncSession] = None,
        cache_backend: Any = None,
        model_path: Optional[str] = None,
    ) -> None:
        self.db = db_session
        self.cache = cache_backend or cache_manager
        self._default_bankroll = 10_000.0
        
        # Initialize Ultra predictor
        self._ultra_predictor = None
        self._legacy_adapter = None
        self._model_path = model_path
        self._ultra_available = _ml_ultra_available
        
        # Edge detection
        self.edge_detector = EdgeDetector(
            min_edge_threshold=0.042,
            kelly_fraction=0.25,
            max_stake_pct=0.05,
        )
        
        # Feature engineering (only if available)
        self.feature_engineer = AdvancedFeatureEngineer() if AdvancedFeatureEngineer else None
        
        # Metrics
        self.metrics: Dict[str, float] = {
            "predictions_count": 0,
            "ultra_predictions": 0,
            "fallback_predictions": 0,
            "avg_latency_ms": 0.0,
            "cache_hit_rate": 0.0,
        }
        self._cache_hits = 0
        self._total_requests = 0
        
        # Initialize model
        self._initialize_model()
    
    def _initialize_model(self) -> None:
        """Initialize the ultra predictor with fallback"""
        if self._ultra_available and UltraPredictor:
            try:
                self._ultra_predictor = UltraPredictor(model_path=self._model_path)
                if self._ultra_predictor.pipeline is not None:
                    logger.info("✅ Ultra predictor initialized successfully")
                else:
                    logger.warning("⚠️ Ultra model not loaded, will use fallback")
                    self._ultra_predictor = None
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Ultra predictor: {e}")
                self._ultra_predictor = None
        else:
            logger.info("ℹ️ Ultra ML not available, using legacy fallback")
        
        # Initialize legacy adapter as fallback
        try:
            from .prediction import PredictionService
            self._legacy_service = PredictionService()
            logger.info("✅ Legacy fallback service ready")
        except Exception as e:
            logger.warning(f"⚠️ Legacy fallback not available: {e}")
            self._legacy_service = None
    
    @staticmethod
    def _build_cache_key(match_id: str, league: str) -> str:
        """Generate cache key for prediction"""
        key_str = f"ultra:{league}:{match_id}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    async def predict_match(
        self,
        match_id: str,
        request: MatchPredictionRequest,
    ) -> PredictionResponse:
        """
        Generate prediction using Ultra ensemble with fallback
        
        Pipeline:
        1. Check cache (< 1ms)
        2. Build advanced features (< 5ms)
        3. Run Ultra ensemble inference (< 20ms)
        4. Detect value bets (< 3ms)
        5. Cache and return (< 1ms)
        
        Target: <30ms total latency
        """
        start_time = time.time()
        self._total_requests += 1
        
        # Normalize league
        league_slug = self._normalize_league(str(request.league))
        cache_key = self._build_cache_key(match_id, league_slug)
        
        # Check cache first
        cached = self._get_cached_prediction(cache_key)
        if cached is not None:
            self._cache_hits += 1
            self._update_cache_metrics()
            latency_ms = (time.time() - start_time) * 1000
            metrics_collector.record_prediction(
                duration_ms=latency_ms,
                confidence=cached.confidence,
                cache_hit=True
            )
            logger.debug(f"Cache hit for {match_id} in {latency_ms:.1f}ms")
            return cached
        
        # Use Ultra predictor if available
        if self._ultra_predictor is not None and self._ultra_predictor.pipeline is not None:
            try:
                prediction = await self._predict_with_ultra(
                    match_id, request, league_slug, start_time
                )
                self.metrics["ultra_predictions"] += 1
                return prediction
            except Exception as e:
                logger.warning(f"Ultra prediction failed, falling back: {e}")
        
        # Fallback to legacy service
        if self._legacy_service is not None:
            try:
                prediction = await self._legacy_service.predict_match(match_id, request)
                self.metrics["fallback_predictions"] += 1
                return prediction
            except Exception as e:
                logger.error(f"Legacy fallback also failed: {e}")
                raise
        
        raise RuntimeError("No prediction service available")
    
    async def _predict_with_ultra(
        self,
        match_id: str,
        request: MatchPredictionRequest,
        league_slug: str,
        start_time: float,
    ) -> PredictionResponse:
        """Generate prediction using Ultra ensemble"""
        # Zero-fab guard: refuse inference when no real evidence is present.
        # ponytail: mirrors PredictionService.predict_match feature_completeness==0 guard
        has_evidence = (
            bool(getattr(request, "home_form", None))
            or bool(getattr(request, "away_form", None))
            or bool(getattr(request, "home_stats", None))
            or bool(getattr(request, "away_stats", None))
            or bool(getattr(request, "home_squad", None))
            or bool(getattr(request, "away_squad", None))
        )
        if not has_evidence:
            from ..core.exceptions import DataUnavailableError
            raise DataUnavailableError(
                "No evidence sources available — refusing to infer from pure defaults (ultra path)"
            )

        # Build feature dictionary from request
        features = self._extract_features(request)
        
        # Get prediction from Ultra model
        result = self._ultra_predictor.predict_match(
            match_id=match_id,
            home_team_id=hash(request.home_team) % 1000,  # Generate ID from name
            away_team_id=hash(request.away_team) % 1000,
            league_id=hash(league_slug) % 100,
            match_date=datetime.now(timezone.utc),
            features=features
        )
        
        # Build probabilities dict
        probabilities = {
            "home_win": result["home_win_prob"],
            "draw": result["draw_prob"],
            "away_win": result["away_win_prob"],
        }
        
        # Detect value bets
        bankroll = float(request.bankroll or self._default_bankroll)
        odds = self._extract_odds(request)
        value_bets = self._detect_value_bets(match_id, probabilities, odds, bankroll, league_slug)
        
        # Calculate metrics
        processing_ms = int((time.time() - start_time) * 1000)
        confidence = result["confidence"]
        brier_score = self._calculate_brier_score(probabilities)
        
        # Build confidence intervals
        confidence_intervals = self._calculate_confidence_intervals(probabilities)
        
        # Build metadata
        metadata = {
            "model_version": self.MODEL_VERSION,
            "processing_time_ms": processing_ms,
            "engine": "ultra_ensemble",
            "uncertainty": result.get("uncertainty", 0.0),
            "data_freshness": datetime.now(timezone.utc).isoformat(),
        }
        
        # Create response
        prediction = PredictionResponse(
            match_id=match_id,
            home_team=request.home_team,
            away_team=request.away_team,
            league=request.league,
            predictions=probabilities,
            confidence=confidence,
            brier_score=brier_score,
            value_bets=value_bets,
            confidence_intervals=confidence_intervals,
            explanations={},
            metadata=metadata,
        )
        
        # Cache result
        cache_key = self._build_cache_key(match_id, league_slug)
        self._cache_prediction(cache_key, prediction)
        
        # Record metrics
        self.metrics["predictions_count"] += 1
        self._update_latency_metrics(processing_ms)
        
        max_edge_pct = max([vb.edge_percent for vb in value_bets], default=0.0)
        metrics_collector.record_prediction(
            duration_ms=processing_ms,
            confidence=confidence,
            value_bets=len(value_bets),
            edge=max_edge_pct / 100.0 if max_edge_pct > 0 else None,
            cache_hit=False
        )
        
        logger.info(
            f"Ultra prediction for {match_id}: "
            f"H={probabilities['home_win']:.2f} D={probabilities['draw']:.2f} A={probabilities['away_win']:.2f} "
            f"conf={confidence:.2f} latency={processing_ms}ms"
        )
        
        return prediction
    
    def _extract_features(self, request: MatchPredictionRequest) -> Dict[str, float]:
        """Extract features from request for Ultra model"""
        features: Dict[str, float] = {}
        
        # Form features
        if hasattr(request, 'home_form') and request.home_form:
            features['home_last_5_wins'] = sum(1 for r in request.home_form[:5] if r == 'W')
            features['home_last_5_draws'] = sum(1 for r in request.home_form[:5] if r == 'D')
            features['home_last_5_losses'] = sum(1 for r in request.home_form[:5] if r == 'L')
        else:
            features['home_last_5_wins'] = 2
            features['home_last_5_draws'] = 1
            features['home_last_5_losses'] = 2
        
        if hasattr(request, 'away_form') and request.away_form:
            features['away_last_5_wins'] = sum(1 for r in request.away_form[:5] if r == 'W')
            features['away_last_5_draws'] = sum(1 for r in request.away_form[:5] if r == 'D')
            features['away_last_5_losses'] = sum(1 for r in request.away_form[:5] if r == 'L')
        else:
            features['away_last_5_wins'] = 2
            features['away_last_5_draws'] = 1
            features['away_last_5_losses'] = 2
        
        # Goals statistics
        features['home_goals_scored_avg'] = getattr(request, 'home_avg_goals_scored', 1.5)
        features['home_goals_conceded_avg'] = getattr(request, 'home_avg_goals_conceded', 1.2)
        features['away_goals_scored_avg'] = getattr(request, 'away_avg_goals_scored', 1.3)
        features['away_goals_conceded_avg'] = getattr(request, 'away_avg_goals_conceded', 1.4)
        
        # H2H features
        features['h2h_home_wins'] = getattr(request, 'h2h_home_wins', 3)
        features['h2h_draws'] = getattr(request, 'h2h_draws', 2)
        features['h2h_away_wins'] = getattr(request, 'h2h_away_wins', 3)
        
        return features
    
    def _extract_odds(self, request: MatchPredictionRequest) -> Dict[str, float]:
        """Extract odds from request"""
        odds: Dict[str, float] = {}
        
        if hasattr(request, 'odds') and request.odds:
            if hasattr(request.odds, 'home_win'):
                odds['home_win'] = request.odds.home_win or 2.0
            if hasattr(request.odds, 'draw'):
                odds['draw'] = request.odds.draw or 3.3
            if hasattr(request.odds, 'away_win'):
                odds['away_win'] = request.odds.away_win or 3.5
        
        return odds or {'home_win': 2.0, 'draw': 3.3, 'away_win': 3.5}
    
    def _detect_value_bets(
        self,
        match_id: str,
        probabilities: Dict[str, float],
        odds: Dict[str, float],
        bankroll: float,
        league_key: str = "",
    ) -> List[ValueBetResponse]:
        """Detect value betting opportunities"""
        try:
            policy = get_league_policy(league_key)
            kelly_cap = policy.kelly_cap
        except LeaguePolicyUnavailableError:
            kelly_cap = 0.04  # ponytail: conservative fallback for unlisted leagues

        value_bets: List[ValueBetResponse] = []

        for market, prob in probabilities.items():
            if market not in odds:
                continue

            market_odds = odds[market]
            implied_prob = 1.0 / market_odds if market_odds > 1 else 0.0
            edge = prob - implied_prob

            # Only include if edge exceeds threshold (4.2%)
            if edge >= 0.042:
                # Kelly criterion calculation
                kelly_fraction = (prob * market_odds - 1) / (market_odds - 1)
                kelly_fraction = min(kelly_fraction, kelly_cap)
                kelly_stake = bankroll * kelly_fraction
                
                value_bet = ValueBetResponse(
                    match_id=match_id,
                    market=market,
                    odds=market_odds,
                    fair_probability=prob,
                    implied_probability=implied_prob,
                    edge_percent=edge * 100,
                    edge_ngn=edge * kelly_stake,
                    kelly_stake_ngn=kelly_stake,
                    kelly_fraction=kelly_fraction,
                    clv_ngn=0.0,  # True CLV = (model_prob - 1/closing_odds) × stake — post-match only
                    confidence=prob,
                    expected_roi=edge / implied_prob if implied_prob > 0 else 0,
                )
                value_bets.append(value_bet)
        
        return value_bets
    
    def _calculate_brier_score(self, probabilities: Dict[str, float]) -> float:
        """Delegates to the single canonical implementation.

        This site already used the correct SUM convention; the inline copy is
        removed so all three services share one authority. The old 0.33
        per-key defaults are dropped deliberately — silently substituting a
        uniform prior for a missing outcome key would publish a sharpness
        reading for a distribution the model never produced.
        """
        return expected_brier_score(probabilities)
    
    def _calculate_confidence_intervals(
        self,
        probabilities: Dict[str, float],
        sample_size: int = 500,
    ) -> Dict[str, Tuple[float, float]]:
        """Calculate 95% confidence intervals using Wilson score"""
        intervals: Dict[str, Tuple[float, float]] = {}
        z = 1.96  # 95% confidence
        
        for outcome, p in probabilities.items():
            # Wilson score interval
            denominator = 1 + z**2 / sample_size
            center = (p + z**2 / (2 * sample_size)) / denominator
            spread = z * np.sqrt((p * (1 - p) + z**2 / (4 * sample_size)) / sample_size) / denominator
            
            lower = max(0.0, center - spread)
            upper = min(1.0, center + spread)
            intervals[outcome] = (lower, upper)
        
        return intervals
    
    def _normalize_league(self, league: str) -> str:
        """Normalize league name to slug format"""
        league_lower = league.lower().strip()
        mappings = {
            "epl": "epl",
            "premier league": "epl",
            "english premier league": "epl",
            "bundesliga": "bundesliga",
            "german bundesliga": "bundesliga",
            "la liga": "la_liga",
            "laliga": "la_liga",
            "spanish la liga": "la_liga",
            "serie a": "serie_a",
            "seriea": "serie_a",
            "italian serie a": "serie_a",
            "ligue 1": "ligue_1",
            "ligue1": "ligue_1",
            "french ligue 1": "ligue_1",
        }
        return mappings.get(league_lower, league_lower.replace(" ", "_"))
    
    def _get_cached_prediction(self, cache_key: str) -> Optional[PredictionResponse]:
        """Get prediction from cache"""
        try:
            cached = self.cache.get(cache_key)
            if cached is not None:
                if isinstance(cached, dict):
                    return PredictionResponse(**cached)
                return cached
        except Exception as e:
            logger.debug(f"Cache get failed: {e}")
        return None
    
    def _cache_prediction(self, cache_key: str, prediction: PredictionResponse) -> None:
        """Cache prediction result"""
        try:
            self.cache.set(cache_key, prediction.model_dump(), ttl=self.CACHE_TTL)
        except Exception as e:
            logger.debug(f"Cache set failed: {e}")
    
    def _update_latency_metrics(self, latency_ms: float) -> None:
        """Update rolling average latency"""
        count = self.metrics["predictions_count"]
        if count == 0:
            self.metrics["avg_latency_ms"] = latency_ms
        else:
            self.metrics["avg_latency_ms"] = (
                self.metrics["avg_latency_ms"] * (count - 1) + latency_ms
            ) / count
    
    def _update_cache_metrics(self) -> None:
        """Update cache hit rate"""
        if self._total_requests > 0:
            self.metrics["cache_hit_rate"] = self._cache_hits / self._total_requests
    
    def get_service_status(self) -> Dict[str, Any]:
        """Get service status and metrics"""
        return {
            "service": "UltraPredictionService",
            "version": self.MODEL_VERSION,
            "ultra_model_loaded": self._ultra_predictor is not None and self._ultra_predictor.pipeline is not None,
            "legacy_fallback_available": self._legacy_service is not None,
            "metrics": self.metrics,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Singleton instance
_ultra_service: Optional[UltraPredictionService] = None


def get_ultra_prediction_service(
    db_session: Optional[AsyncSession] = None,
) -> UltraPredictionService:
    """Get or create Ultra prediction service singleton"""
    global _ultra_service
    if _ultra_service is None:
        _ultra_service = UltraPredictionService(db_session=db_session)
    return _ultra_service
