"""
Enhanced API Service with V2 Model Support
==========================================

Features:
- Loads production_ml_model.py models
- Market odds integration
- Value betting recommendations
- Comprehensive match insights
"""

import hashlib
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Import production model
try:
    from .production_ml_model import ProductionMLModel

    HAS_V2_MODEL = True
except ImportError:
    ProductionMLModel = None  # type: ignore[misc,assignment]
    HAS_V2_MODEL = False
    logger.warning("V2 model not available, falling back to V1")

# Import V1 model as fallback
try:
    from .training_pipeline import ProductionMLPipeline

    HAS_V1_MODEL = True
except ImportError:
    ProductionMLPipeline = None  # type: ignore[misc,assignment]
    HAS_V1_MODEL = False


class EnhancedMatchInput(BaseModel):
    """Enhanced input for match prediction with validation"""

    match_id: str
    home_team: str
    away_team: str
    league: str = "EPL"

    # Form features (required)
    home_ppg_5: float = Field(
        1.5, ge=0.0, le=3.0, description="Home team points per game (last 5)"
    )
    away_ppg_5: float = Field(
        1.2, ge=0.0, le=3.0, description="Away team points per game (last 5)"
    )
    home_goals_for_5: float = Field(
        1.5, description="Home team goals scored per game (last 5)"
    )
    home_goals_against_5: float = Field(
        1.2, description="Home team goals conceded per game (last 5)"
    )
    away_goals_for_5: float = Field(
        1.2, description="Away team goals scored per game (last 5)"
    )
    away_goals_against_5: float = Field(
        1.5, description="Away team goals conceded per game (last 5)"
    )

    # Win rates
    home_win_rate_5: float = Field(0.4, ge=0.0, le=1.0)
    away_win_rate_5: float = Field(0.3, ge=0.0, le=1.0)

    # Venue performance
    home_team_home_win_rate: float = Field(0.45, ge=0.0, le=1.0)
    away_team_away_win_rate: float = Field(0.30, ge=0.0, le=1.0)

    # H2H
    h2h_home_win_rate: float = Field(0.45, ge=0.0, le=1.0)
    h2h_draw_rate: float = Field(0.25, ge=0.0, le=1.0)
    h2h_away_win_rate: float = Field(0.30, ge=0.0, le=1.0)
    h2h_matches: int = Field(0, ge=0)

    # Market odds (highly predictive - optional but recommended)
    home_odds: Optional[float] = Field(
        None, gt=1.0, description="Decimal odds for home win"
    )
    draw_odds: Optional[float] = Field(
        None, gt=1.0, description="Decimal odds for draw"
    )
    away_odds: Optional[float] = Field(
        None, gt=1.0, description="Decimal odds for away win"
    )


class PredictionInsight(BaseModel):
    """Detailed prediction with insights"""

    match_id: str
    home_team: str
    away_team: str

    # Probabilities
    home_win_prob: float = Field(..., ge=0.0, le=1.0)
    draw_prob: float = Field(..., ge=0.0, le=1.0)
    away_win_prob: float = Field(..., ge=0.0, le=1.0)

    # Prediction
    predicted_outcome: str
    confidence: float

    # Market comparison (if odds provided)
    market_probs: Optional[Dict[str, float]] = None
    value_edges: Optional[Dict[str, float]] = None
    value_bet_recommendation: Optional[str] = None

    # Insights
    key_factors: List[str] = []
    risk_level: str = "medium"

    # Meta
    model_version: str
    latency_ms: float


class EnhancedModelManager:
    """
    Manages both V1 and V2 models with graceful fallback.
    Includes prediction caching and batch prediction support.
    """

    def __init__(self):
        self.v2_model: Optional[Any] = None
        self.v1_model: Optional[Any] = None
        self.model_version = "unknown"
        self.is_loaded = False
        self._prediction_cache: Dict[
            str, tuple
        ] = {}  # cache_key -> (result, timestamp)
        self._cache_ttl_seconds = 300  # 5 minute cache
        self._feature_count = 0
        self._model_accuracy = 0.0

    def load_model(self, model_dir: Optional[str] = None) -> bool:
        """Load best available model"""

        if model_dir is None:
            model_path = Path(__file__).parent.parent.parent / "models"
        else:
            model_path = Path(model_dir)

        # Try V2 model first
        v2_path = model_path / "sabiscore_production_v2.joblib"
        if HAS_V2_MODEL and ProductionMLModel is not None and v2_path.exists():
            try:
                self.v2_model = ProductionMLModel.load(v2_path)
                self.model_version = "v2.0"
                self.is_loaded = True
                logger.info(f"✅ Loaded V2 production model from {v2_path}")
                return True
            except Exception as e:
                logger.warning(f"Failed to load V2 model: {e}")

        # Try V2 with alternate name
        v2_alt_path = model_path / "sabiscore_v2.joblib"
        if HAS_V2_MODEL and ProductionMLModel is not None and v2_alt_path.exists():
            try:
                self.v2_model = ProductionMLModel.load(v2_alt_path)
                self.model_version = "v2.0"
                self.is_loaded = True
                logger.info(f"✅ Loaded V2 model from {v2_alt_path}")
                return True
            except Exception as e:
                logger.warning(f"Failed to load V2 model: {e}")

        # Fallback to V1
        v1_path = model_path / "ultra"
        if HAS_V1_MODEL and ProductionMLPipeline is not None and v1_path.exists():
            try:
                self.v1_model = ProductionMLPipeline.load_trained_model(str(v1_path))
                self.model_version = "v1.0"
                self.is_loaded = True
                logger.info(f"✅ Loaded V1 model from {v1_path}")
                return True
            except Exception as e:
                logger.warning(f"Failed to load V1 model: {e}")

        logger.warning("⚠️ No model loaded - will use baseline predictions")
        return False

    def _get_cache_key(self, match: EnhancedMatchInput) -> str:
        """Generate cache key from match input"""
        key_parts = [
            match.home_team,
            match.away_team,
            match.league,
            f"{match.home_ppg_5:.2f}",
            f"{match.away_ppg_5:.2f}",
            f"{match.home_odds or 0:.2f}",
            f"{match.away_odds or 0:.2f}",
        ]
        return hashlib.md5(":".join(key_parts).encode()).hexdigest()

    def _check_cache(self, cache_key: str) -> Optional[PredictionInsight]:
        """Check if prediction is in cache and still valid"""
        if cache_key in self._prediction_cache:
            result, timestamp = self._prediction_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl_seconds:
                return result
            del self._prediction_cache[cache_key]
        return None

    def predict(self, match: EnhancedMatchInput) -> PredictionInsight:
        """
        Make prediction with full insights.
        Uses caching for repeated predictions.
        """
        start_time = time.time()

        # Check cache first
        cache_key = self._get_cache_key(match)
        cached_result = self._check_cache(cache_key)
        if cached_result is not None:
            # Update latency for cached result
            cached_result.latency_ms = (time.time() - start_time) * 1000
            return cached_result

        # Build feature dict
        features = self._build_features(match)

        # Get model predictions
        if self.v2_model is not None:
            probs = self._predict_v2(features, match)
        elif self.v1_model is not None:
            probs = self._predict_v1(features)
        else:
            probs = self._predict_baseline(match)

        # Determine outcome
        outcomes = ["away_win", "draw", "home_win"]
        prob_values = [probs["away"], probs["draw"], probs["home"]]
        predicted_idx = np.argmax(prob_values)
        predicted_outcome = outcomes[predicted_idx]
        confidence = max(prob_values)

        # Build insight
        latency = (time.time() - start_time) * 1000

        insight = PredictionInsight(
            match_id=match.match_id,
            home_team=match.home_team,
            away_team=match.away_team,
            home_win_prob=probs["home"],
            draw_prob=probs["draw"],
            away_win_prob=probs["away"],
            predicted_outcome=predicted_outcome,
            confidence=confidence,
            model_version=self.model_version,
            latency_ms=latency,
        )

        # Add market analysis if odds provided
        if match.home_odds and match.draw_odds and match.away_odds:
            (
                insight.market_probs,
                insight.value_edges,
                insight.value_bet_recommendation,
            ) = self._analyze_market(probs, match)

        # Add key factors
        insight.key_factors = self._get_key_factors(match, probs)

        # Risk assessment
        insight.risk_level = self._assess_risk(probs, confidence)

        # Cache the result
        self._prediction_cache[cache_key] = (insight, time.time())

        # Limit cache size (LRU-style cleanup)
        if len(self._prediction_cache) > 1000:
            oldest_keys = sorted(
                self._prediction_cache.keys(),
                key=lambda k: self._prediction_cache[k][1],
            )[:500]
            for k in oldest_keys:
                del self._prediction_cache[k]

        return insight

    def _build_features(self, match: EnhancedMatchInput) -> Dict[str, float]:
        """Build feature dictionary from match input"""

        features = {
            # Form features
            "home_ppg_5": match.home_ppg_5,
            "away_ppg_5": match.away_ppg_5,
            "home_ppg_3": match.home_ppg_5,  # Use same value for now
            "away_ppg_3": match.away_ppg_5,
            "home_ppg_10": match.home_ppg_5,
            "away_ppg_10": match.away_ppg_5,
            # Goals
            "home_goals_for_5": match.home_goals_for_5,
            "home_goals_against_5": match.home_goals_against_5,
            "away_goals_for_5": match.away_goals_for_5,
            "away_goals_against_5": match.away_goals_against_5,
            "home_goals_for_3": match.home_goals_for_5,
            "home_goals_against_3": match.home_goals_against_5,
            "away_goals_for_3": match.away_goals_for_5,
            "away_goals_against_3": match.away_goals_against_5,
            # Goal differences
            "home_goal_diff_5": match.home_goals_for_5 - match.home_goals_against_5,
            "away_goal_diff_5": match.away_goals_for_5 - match.away_goals_against_5,
            # Win rates
            "home_win_rate_5": match.home_win_rate_5,
            "away_win_rate_5": match.away_win_rate_5,
            "home_win_rate_3": match.home_win_rate_5,
            "away_win_rate_3": match.away_win_rate_5,
            # Clean sheets (estimate)
            "home_clean_sheet_rate_5": 0.3 if match.home_goals_against_5 < 1.0 else 0.2,
            "away_clean_sheet_rate_5": 0.2
            if match.away_goals_against_5 < 1.0
            else 0.15,
            # Venue
            "home_team_home_win_rate": match.home_team_home_win_rate,
            "away_team_away_win_rate": match.away_team_away_win_rate,
            "home_team_home_goals_avg": match.home_goals_for_5 * 1.1,  # Home boost
            "away_team_away_goals_avg": match.away_goals_for_5 * 0.9,  # Away penalty
            # H2H
            "h2h_home_win_rate": match.h2h_home_win_rate,
            "h2h_draw_rate": match.h2h_draw_rate,
            "h2h_away_win_rate": match.h2h_away_win_rate,
            "h2h_matches": match.h2h_matches,
            "h2h_avg_goals": 2.5,
            "h2h_home_team_avg_goals": 1.3,
            # Interactions
            "form_diff": match.home_ppg_5 - match.away_ppg_5,
            "form_ratio": match.home_ppg_5 / (match.away_ppg_5 + 0.1),
            "combined_form": match.home_ppg_5 + match.away_ppg_5,
            "attack_vs_defense_home": match.home_goals_for_5
            / (match.away_goals_against_5 + 0.1),
            "attack_vs_defense_away": match.away_goals_for_5
            / (match.home_goals_against_5 + 0.1),
            # League (one-hot style)
            "league_encoded": 0 if match.league == "EPL" else 1,
            "league_avg_goals": 2.8 if match.league == "EPL" else 2.6,
            # Temporal (defaults)
            "day_of_week": 5,  # Saturday
            "is_weekend": 1,
            "month": datetime.now().month,
            # Games played
            "home_games_played": 20,
            "away_games_played": 20,
        }

        # Add market features if odds available
        if match.home_odds and match.draw_odds and match.away_odds:
            imp_home = 1 / match.home_odds
            imp_draw = 1 / match.draw_odds
            imp_away = 1 / match.away_odds
            total_imp = imp_home + imp_draw + imp_away

            features["market_home_prob"] = imp_home / total_imp
            features["market_draw_prob"] = imp_draw / total_imp
            features["market_away_prob"] = imp_away / total_imp
            features["market_margin"] = total_imp - 1
            features["home_favorite"] = 1 if imp_home > imp_away else 0
            features["heavy_favorite"] = 1 if max(imp_home, imp_away) > 0.6 else 0
            features["prob_diff_home_away"] = (imp_home - imp_away) / total_imp
            features["log_odds_home"] = np.log(match.home_odds)
            features["log_odds_draw"] = np.log(match.draw_odds)
            features["log_odds_away"] = np.log(match.away_odds)
            features["home_away_ratio"] = match.home_odds / match.away_odds

        return features

    def _predict_v2(
        self, features: Dict, match: EnhancedMatchInput
    ) -> Dict[str, float]:
        """Predict using V2 model"""

        if self.v2_model is None:
            return self._predict_baseline(match)

        # Use predict_match which handles market odds
        market_odds = None
        if match.home_odds and match.draw_odds and match.away_odds:
            market_odds = {
                "home": match.home_odds,
                "draw": match.draw_odds,
                "away": match.away_odds,
            }

        result = self.v2_model.predict_match(features, market_odds)

        # Get blended probabilities if available
        if "blended_probabilities" in result:
            probs = result["blended_probabilities"]
        else:
            probs = result["model_probabilities"]

        return probs

    def _predict_v1(self, features: Dict) -> Dict[str, float]:
        """Predict using V1 model"""

        assert self.v1_model is not None
        # Build feature DataFrame
        feature_names = self.v1_model.feature_names
        feature_values = {name: features.get(name, 0.0) for name in feature_names}
        df = pd.DataFrame([feature_values])

        # Get predictions
        probas = self.v1_model.ensemble.predict_proba(df)

        return {
            "home": float(probas[0, 2]),
            "draw": float(probas[0, 1]),
            "away": float(probas[0, 0]),
        }

    def _predict_baseline(self, match: EnhancedMatchInput) -> Dict[str, float]:
        """
        Baseline prediction when no model is loaded.
        Uses market odds if available, otherwise form-based heuristics.
        """

        # If odds available, use them (market is usually right)
        if match.home_odds and match.draw_odds and match.away_odds:
            imp_home = 1 / match.home_odds
            imp_draw = 1 / match.draw_odds
            imp_away = 1 / match.away_odds
            total = imp_home + imp_draw + imp_away

            return {
                "home": imp_home / total,
                "draw": imp_draw / total,
                "away": imp_away / total,
            }

        # Form-based heuristic
        home_strength = (
            (match.home_ppg_5 / 3.0) * 0.5 + match.home_win_rate_5 * 0.3 + 0.15
        )  # Home advantage
        away_strength = (match.away_ppg_5 / 3.0) * 0.5 + match.away_win_rate_5 * 0.3

        # Normalize to probabilities
        total_strength = home_strength + away_strength + 0.25  # Draw base

        return {
            "home": home_strength / total_strength,
            "draw": 0.25 / total_strength,
            "away": away_strength / total_strength,
        }

    def _analyze_market(
        self, model_probs: Dict[str, float], match: EnhancedMatchInput
    ) -> tuple:
        """Analyze model vs market for value opportunities"""

        # Market implied probabilities
        assert match.home_odds is not None
        assert match.draw_odds is not None
        assert match.away_odds is not None
        imp_home = 1 / match.home_odds
        imp_draw = 1 / match.draw_odds
        imp_away = 1 / match.away_odds
        total = imp_home + imp_draw + imp_away

        market_probs = {
            "home": imp_home / total,
            "draw": imp_draw / total,
            "away": imp_away / total,
        }

        # Calculate edges (model - market)
        value_edges = {
            "home": model_probs["home"] - market_probs["home"],
            "draw": model_probs["draw"] - market_probs["draw"],
            "away": model_probs["away"] - market_probs["away"],
        }

        # Find value bet
        value_threshold = 0.03  # 3% edge
        best_value = max(value_edges.items(), key=lambda x: x[1])

        recommendation = None
        if best_value[1] > value_threshold:
            odds = {
                "home": match.home_odds,
                "draw": match.draw_odds,
                "away": match.away_odds,
            }
            recommendation = f"VALUE: {best_value[0].upper()} @ {odds[best_value[0]]:.2f} (Edge: +{best_value[1] * 100:.1f}%)"

        return market_probs, value_edges, recommendation

    def _get_key_factors(self, match: EnhancedMatchInput, probs: Dict) -> List[str]:
        """Identify key factors influencing prediction"""

        factors = []

        # Form difference
        form_diff = match.home_ppg_5 - match.away_ppg_5
        if abs(form_diff) > 0.5:
            team = match.home_team if form_diff > 0 else match.away_team
            factors.append(f"Strong form advantage for {team}")

        # Home advantage
        if match.home_team_home_win_rate > 0.55:
            factors.append(
                f"{match.home_team} has strong home record ({match.home_team_home_win_rate * 100:.0f}%)"
            )

        # Defensive concerns
        if match.home_goals_against_5 > 2.0:
            factors.append(
                f"{match.home_team} defensive vulnerability (conceding {match.home_goals_against_5:.1f} per game)"
            )
        if match.away_goals_against_5 > 2.0:
            factors.append(
                f"{match.away_team} defensive vulnerability (conceding {match.away_goals_against_5:.1f} per game)"
            )

        # H2H dominance
        if match.h2h_matches >= 3:
            if match.h2h_home_win_rate > 0.6:
                factors.append(
                    f"{match.home_team} dominates H2H ({match.h2h_home_win_rate * 100:.0f}% wins)"
                )
            elif match.h2h_away_win_rate > 0.4:
                factors.append(
                    f"{match.away_team} good H2H record ({match.h2h_away_win_rate * 100:.0f}% wins)"
                )

        # Close game indicator
        if abs(probs["home"] - probs["away"]) < 0.1:
            factors.append("Very competitive matchup - expect close game")

        return factors[:5]  # Max 5 factors

    def _assess_risk(self, probs: Dict, confidence: float) -> str:
        """Assess prediction risk level"""

        if confidence < 0.4:
            return "high"
        elif confidence < 0.5:
            return "medium"
        else:
            return "low"


# Global instance
enhanced_model_manager = EnhancedModelManager()


def get_enhanced_manager() -> EnhancedModelManager:
    """Get the global model manager"""
    return enhanced_model_manager
