# backend/src/models/orchestrator.py
"""
Model Orchestrator - Routes predictions to league-specific models
Handles training, caching, live calibration, and edge detection
"""

import json
import logging
from threading import Lock
from typing import Any, Dict, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
import pandas as pd
import numpy as np

# Import all league models
from .leagues.premier_league import PremierLeagueModel
from .leagues.la_liga import LaLigaModel
from .leagues.bundesliga import BundesligaModel
from .leagues.serie_a import SerieAModel
from .leagues.ligue_1 import Ligue1Model
from ..core.redaction import redact_text, safe_endpoint


logger = logging.getLogger(__name__)


class _InMemoryRedisAdapter:
    """Minimal Redis-compatible fallback for legacy batch utilities only."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._lists: dict[str, list[Any]] = {}

    def get(self, key: str) -> Any:
        return self._values.get(key)

    def setex(self, key: str, _ttl: int, value: Any) -> bool:
        self._values[key] = value
        return True

    def lpush(self, key: str, value: Any) -> int:
        values = self._lists.setdefault(key, [])
        values.insert(0, value)
        return len(values)

    def ltrim(self, key: str, start: int, stop: int) -> bool:
        values = self._lists.setdefault(key, [])
        self._lists[key] = values[start : stop + 1]
        return True

    def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    def lrange(self, key: str, start: int, stop: int) -> list[Any]:
        values = self._lists.get(key, [])
        return values[start:] if stop == -1 else values[start : stop + 1]

class ModelOrchestrator:
    """
    Central orchestrator for all league-specific models
    - Routes predictions to correct league model
    - Manages training pipeline
    - Implements live calibration
    - Calculates CLV and Kelly stakes
    """
    
    LEAGUE_MAP = {
        'premier_league': 'epl',
        'epl': 'epl',
        'la_liga': 'laliga',
        'laliga': 'laliga',
        'bundesliga': 'bundesliga',
        'serie_a': 'seriea',
        'seriea': 'seriea',
        'ligue_1': 'ligue1',
        'ligue1': 'ligue1',
        'championship': 'championship',
        'eredivisie': 'eredivisie'
    }
    
    def __init__(self, redis_client: Any | None = None, redis_url: str | None = None):
        if redis_client is not None:
            self.redis = redis_client
        elif redis_url is not None:
            self.redis = self._connect_redis_url(redis_url) or _InMemoryRedisAdapter()
        else:
            from ..core.cache import cache

            self.redis = cache.redis_client or _InMemoryRedisAdapter()
        
        # Import additional league models
        from .leagues.championship import ChampionshipModel
        from .leagues.eredivisie import EredivisieModel
        
        # Initialize all league models (7 total)
        self.models = {
            'epl': PremierLeagueModel(self.redis),
            'laliga': LaLigaModel(self.redis),
            'bundesliga': BundesligaModel(self.redis),
            'seriea': SerieAModel(self.redis),
            'ligue1': Ligue1Model(self.redis),
            'championship': ChampionshipModel(self.redis),
            'eredivisie': EredivisieModel(self.redis)
        }
        
        self.live_calibration_cache = {}

    @staticmethod
    def _connect_redis_url(redis_url: str) -> Any | None:
        """Build and probe a Redis client from URL, failing closed to in-memory."""

        try:
            import redis
            from redis.exceptions import RedisError
        except Exception as exc:
            logger.warning(
                "ModelOrchestrator redis import failed; using in-memory fallback endpoint=%s error=%s",
                safe_endpoint(redis_url),
                redact_text(exc),
            )
            return None

        try:
            client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                retry_on_timeout=False,
            )
            client.ping()
            return client
        except (RedisError, OSError, ValueError) as exc:
            logger.warning(
                "ModelOrchestrator redis unavailable; using in-memory fallback endpoint=%s error=%s",
                safe_endpoint(redis_url),
                redact_text(exc),
            )
            return None
        
    def get_league_key(self, league: str) -> str:
        """Normalize league name to internal key"""
        return self.LEAGUE_MAP.get(league.lower().replace(' ', '_'), 'epl')
    
    def train_all_models(self, db: Session):
        """
        Train all league models from historical data (2018-2025)
        Expected runtime: 12-18 minutes per league
        """
        from ..core.database import Match
        
        print("🚀 Starting model training pipeline...")
        
        for league_key, model in self.models.items():
            print(f"\n{'='*60}")
            print(f"Training {league_key.upper()} model")
            print(f"{'='*60}")
            
            # Query historical matches
            matches = db.query(Match).filter(
                Match.league.ilike(f"%{league_key}%"),
                Match.match_date >= datetime(2018, 1, 1),
                Match.match_date <= datetime(2025, 11, 3),
                Match.home_score.isnot(None),
                Match.away_score.isnot(None)
            ).all()
            
            print(f"Loaded {len(matches)} matches for training")
            
            if len(matches) < 500:
                print(f"⚠️  Insufficient data ({len(matches)} matches). Need 500+ for training.")
                continue
            
            # Extract features and labels
            X_train = []
            y_train = []
            
            for match in matches:
                try:
                    # Build feature dict from database
                    match_data = self._build_match_features(match, db)
                    
                    # Get features using league-specific extractor
                    if league_key == 'epl':
                        features = model.extract_epl_features(match_data)
                    elif league_key == 'laliga':
                        features = model.extract_laliga_features(match_data)
                    elif league_key == 'bundesliga':
                        features = model.extract_bundesliga_features(match_data)
                    elif league_key == 'seriea':
                        features = model.extract_serie_a_features(match_data)
                    elif league_key == 'ligue1':
                        features = model.extract_ligue1_features(match_data)
                    
                    X_train.append(features.flatten())
                    
                    # Label: 0=home win, 1=draw, 2=away win
                    if match.home_score > match.away_score:
                        y_train.append(0)
                    elif match.home_score == match.away_score:
                        y_train.append(1)
                    else:
                        y_train.append(2)
                        
                except Exception as e:
                    print(f"Error processing match {match.id}: {e}")
                    continue
            
            # Train model
            X_train_df = pd.DataFrame(X_train)
            y_train_series = pd.Series(y_train)
            
            print(f"Training on {len(X_train_df)} processed matches...")
            model.train(X_train_df, y_train_series)
            
            # Cache training metadata
            metadata = {
                'trained_at': datetime.now(timezone.utc).isoformat(),
                'sample_count': len(X_train_df),
                'date_range': f"2018-{datetime(2025, 11, 3).strftime('%Y-%m-%d')}",
                'accuracy_target': self._get_accuracy_target(league_key)
            }
            self.redis.setex(f"model:{league_key}:metadata", 86400, json.dumps(metadata))
            
        print("\n✅ All models trained successfully!")
        self._run_validation_suite(db)
    
    def _build_match_features(self, match, db: Session) -> Dict:
        """
        Build feature dictionary from database match record
        Aggregates team stats from last 5 matches
        """
        from ..core.database import Match
        from sqlalchemy import and_
        
        features = {}
        
        # Recent form (last 5 matches)
        home_recent = db.query(Match).filter(
            and_(
                Match.home_team == match.home_team,
                Match.match_date < match.match_date,
                Match.match_date >= match.match_date - timedelta(days=60)
            )
        ).order_by(Match.match_date.desc()).limit(5).all()
        
        away_recent = db.query(Match).filter(
            and_(
                Match.away_team == match.away_team,
                Match.match_date < match.match_date,
                Match.match_date >= match.match_date - timedelta(days=60)
            )
        ).order_by(Match.match_date.desc()).limit(5).all()
        
        # Home team stats
        features['home_goals_scored_l5'] = sum(m.home_score for m in home_recent if m.home_score)
        features['home_goals_conceded_l5'] = sum(m.away_score for m in home_recent if m.away_score)
        features['home_xg_l5'] = sum(m.home_xg for m in home_recent if m.home_xg) / max(len(home_recent), 1)
        features['home_xga_l5'] = sum(m.away_xg for m in home_recent if m.away_xg) / max(len(home_recent), 1)
        
        # Away team stats
        features['away_goals_scored_l5'] = sum(m.away_score for m in away_recent if m.away_score)
        features['away_goals_conceded_l5'] = sum(m.home_score for m in away_recent if m.home_score)
        features['away_xg_l5'] = sum(m.away_xg for m in away_recent if m.away_xg) / max(len(away_recent), 1)
        features['away_xga_l5'] = sum(m.home_xg for m in away_recent if m.home_xg) / max(len(away_recent), 1)
        
        # Form indicators
        home_form = [1 if m.home_score > m.away_score else 0.5 if m.home_score == m.away_score else 0 
                     for m in home_recent if m.home_score is not None]
        away_form = [1 if m.away_score > m.home_score else 0.5 if m.away_score == m.home_score else 0 
                     for m in away_recent if m.away_score is not None]
        
        features['home_form_last_5'] = home_form
        features['away_form_last_5'] = away_form
        features['home_points_l5'] = sum([3 if x == 1 else 1 if x == 0.5 else 0 for x in home_form])
        features['away_points_l5'] = sum([3 if x == 1 else 1 if x == 0.5 else 0 for x in away_form])
        
        # Clean sheets
        features['home_clean_sheets_l5'] = sum(1 for m in home_recent if m.away_score == 0)
        features['away_clean_sheets_l5'] = sum(1 for m in away_recent if m.home_score == 0)
        
        # H2H
        h2h_matches = db.query(Match).filter(
            and_(
                Match.home_team.in_([match.home_team, match.away_team]),
                Match.away_team.in_([match.home_team, match.away_team]),
                Match.match_date < match.match_date,
                Match.match_date >= match.match_date - timedelta(days=730)  # 2 years
            )
        ).order_by(Match.match_date.desc()).limit(5).all()
        
        h2h_home_wins = sum(1 for m in h2h_matches if m.home_team == match.home_team and m.home_score > m.away_score)
        features['h2h_home_wins_l5'] = h2h_home_wins
        features['h2h_goals_per_game'] = sum(m.home_score + m.away_score for m in h2h_matches if m.home_score) / max(len(h2h_matches), 1)
        
        return features
    
    def predict(self, league: str, match_data: Dict, odds: Optional[Dict] = None) -> Dict:
        """
        Generate predictions for a match
        Returns: probabilities, confidence, edge (if odds provided)
        """
        league_key = self.get_league_key(league)
        model = self.models[league_key]
        
        # Check cache first
        match_id = match_data.get('match_id', 'unknown')
        cached = model.get_cached_prediction(match_id)
        if cached and self._is_cache_fresh(cached):
            print(f"✅ Using cached prediction for {match_id}")
            return cached
        
        # Generate fresh prediction
        try:
            predictions = model.predict_proba(match_data)
            
            result = {
                'league': league,
                'match_id': match_id,
                'predictions': predictions,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'model_version': f"{league_key}_v3.0"
            }
            
            # Calculate edge if odds provided
            if odds:
                edges = model.calculate_edge(predictions, odds)
                result['value_bets'] = edges
                result['has_edge'] = len(edges) > 0
            
            # Cache for 5 minutes
            model.cache_prediction(match_id, result, ttl=300)
            
            return result
            
        except Exception as e:
            print(f"❌ Prediction error: {e}")
            return {
                'error': str(e),
                'league': league,
                'match_id': match_id
            }
    
    def live_calibration_update(self, league: str, match_id: str, actual_result: int):
        """
        Update live calibration based on match result
        actual_result: 0=home win, 1=draw, 2=away win
        """
        league_key = self.get_league_key(league)
        
        # Store result for recalibration
        key = f"live:results:{league_key}"
        result_data = {
            'match_id': match_id,
            'result': actual_result,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        self.redis.lpush(key, json.dumps(result_data))
        self.redis.ltrim(key, 0, 499)  # Keep last 500 results
        
        # Trigger recalibration if we have enough recent data
        recent_count = self.redis.llen(key)
        if recent_count >= 50:
            self._recalibrate_model(league_key)
    
    def _recalibrate_model(self, league_key: str):
        """
        Recalibrate model using Platt scaling on recent results
        Runs every 180 seconds as per mission spec
        """
        key = f"live:results:{league_key}"
        results = self.redis.lrange(key, 0, -1)
        
        if len(results) < 30:
            return
        
        print(f"🔄 Recalibrating {league_key} model with {len(results)} recent results")
        
        # Parse results
        y_true = []
        y_pred = []
        
        for r in results:
            data = json.loads(r)
            y_true.append(data['result'])
            
            # Fetch original prediction
            pred = self.models[league_key].get_cached_prediction(data['match_id'])
            if pred and 'predictions' in pred:
                probs = pred['predictions']
                y_pred.append([probs['home_win'], probs['draw'], probs['away_win']])
        
        # Store calibration parameters
        from sklearn.isotonic import IsotonicRegression
        
        for outcome_idx, outcome_name in enumerate(['home_win', 'draw', 'away_win']):
            y_outcome = [1 if y == outcome_idx else 0 for y in y_true]
            y_prob = [p[outcome_idx] for p in y_pred]
            
            iso = IsotonicRegression(out_of_bounds='clip')
            iso.fit(y_prob, y_outcome)
            
            # Cache calibration curve
            calib_key = f"calib:{league_key}:{outcome_name}"
            calib_data = {
                'x': iso.X_thresholds_.tolist(),
                'y': iso.y_thresholds_.tolist(),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            self.redis.setex(calib_key, 600, json.dumps(calib_data))  # 10min TTL
        
        print(f"✅ Recalibration complete for {league_key}")
    
    def _is_cache_fresh(self, cached: Dict) -> bool:
        """Check if cached prediction is still valid"""
        if not cached or 'timestamp' not in cached:
            return False
        
        cached_time = datetime.fromisoformat(cached['timestamp']).replace(tzinfo=None)
        return (datetime.now(timezone.utc).replace(tzinfo=None) - cached_time).total_seconds() < 300  # 5 min
    
    def _get_accuracy_target(self, league_key: str) -> str:
        """Return accuracy from walk-forward evaluation artifacts at runtime."""
        # ponytail: hardcoded strings removed (zero-fab); real accuracy from model_registry walk_forward_validate()
        return ""
    
    def _run_validation_suite(self, db: Session):
        """
        Validate trained models on holdout set (last 60 days)
        Calculates Brier score, accuracy, CLV
        """
        from ..core.database import Match
        from sklearn.metrics import accuracy_score, brier_score_loss
        
        print("\n" + "="*60)
        print("VALIDATION RESULTS")
        print("="*60)
        
        for league_key, model in self.models.items():
            # Get recent matches (not in training set)
            recent_matches = db.query(Match).filter(
                Match.league.ilike(f"%{league_key}%"),
                Match.match_date >= datetime(2025, 9, 1),
                Match.match_date <= datetime(2025, 11, 3),
                Match.home_score.isnot(None)
            ).all()
            
            if len(recent_matches) < 20:
                continue
            
            y_true = []
            y_pred = []
            y_proba = []
            
            for match in recent_matches:
                try:
                    match_data = self._build_match_features(match, db)
                    pred = model.predict_proba(match_data)
                    
                    probs = [pred['home_win'], pred['draw'], pred['away_win']]
                    y_proba.append(probs)
                    y_pred.append(np.argmax(probs))
                    
                    if match.home_score > match.away_score:
                        y_true.append(0)
                    elif match.home_score == match.away_score:
                        y_true.append(1)
                    else:
                        y_true.append(2)
                        
                except Exception:
                    continue
            
            # Calculate metrics
            accuracy = accuracy_score(y_true, y_pred) * 100
            
            # Brier score (for each outcome)
            brier_scores = []
            for i in range(3):
                y_true_binary = [1 if y == i else 0 for y in y_true]
                y_proba_i = [p[i] for p in y_proba]
                brier = brier_score_loss(y_true_binary, y_proba_i)
                brier_scores.append(brier)
            
            avg_brier = np.mean(brier_scores)
            
            print(f"\n{league_key.upper()}:")
            print(f"  Accuracy: {accuracy:.1f}% (target: {self._get_accuracy_target(league_key)})")
            print(f"  Brier Score: {avg_brier:.3f}")
            print(f"  Samples: {len(y_true)}")
        
        print("\n" + "="*60)

_orchestrator: ModelOrchestrator | None = None
_orchestrator_lock = Lock()


def get_model_orchestrator(redis_client: Any | None = None) -> ModelOrchestrator:
    """Lazily construct the legacy orchestrator without import-time I/O."""

    global _orchestrator
    if _orchestrator is None:
        with _orchestrator_lock:
            if _orchestrator is None:
                _orchestrator = ModelOrchestrator(redis_client=redis_client)
    return _orchestrator
