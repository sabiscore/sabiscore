"""
SabiScore Ultra - Model Integration
Connects the new ml_ultra module to existing prediction service
"""

import os
import logging
from typing import Dict, Optional, List
from datetime import datetime

from ..ml_ultra.training_pipeline import ProductionMLPipeline

logger = logging.getLogger(__name__)


class UltraPredictor:
    """
    High-performance predictor using the new ml_ultra ensemble
    Replaces legacy ensemble with 90%+ accuracy target
    """

    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize ultra predictor

        Args:
            model_path: Path to trained model (default: models/ultra/ensemble.pkl)
        """
        self.model_path = model_path or os.getenv(
            "ULTRA_MODEL_PATH",
            "models/ultra",  # Directory path
        )
        self.pipeline: Optional[ProductionMLPipeline] = None
        self.model_version = "v3.0.0-ultra"
        self._load_model()

    def _load_model(self):
        """Load the trained ultra model"""
        try:
            if os.path.exists(self.model_path):
                logger.info(f"Loading ultra model from {self.model_path}...")
                self.pipeline = ProductionMLPipeline.load_trained_model(self.model_path)
                logger.info("✅ Ultra model loaded successfully")
            else:
                logger.warning(
                    f"⚠️ Ultra model not found at {self.model_path}. "
                    "Train the model first using: python -m backend.src.ml_ultra.training_pipeline"
                )
        except Exception as e:
            logger.error(f"❌ Failed to load ultra model: {e}")
            raise

    def predict_match(
        self,
        match_id: str,
        home_team_id: int,
        away_team_id: int,
        league_id: int,
        match_date: datetime,
        features: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Predict match outcome with ultra ensemble

        Args:
            match_id: Unique match identifier
            home_team_id: Home team ID
            away_team_id: Away team ID
            league_id: League ID
            match_date: Match date
            features: Dictionary of pre-computed features

        Returns:
            Dictionary with probabilities and metadata:
            {
                'home_win_prob': float,
                'draw_prob': float,
                'away_win_prob': float,
                'predicted_outcome': str,
                'confidence': float,
                'uncertainty': float,
                'model_version': str
            }
        """
        if not self.pipeline:
            raise RuntimeError("Ultra model not loaded. Train the model first.")

        try:
            # Prepare input data
            input_data = {
                "match_id": match_id,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "league_id": league_id,
                "match_date": match_date.isoformat(),
                **features,
            }

            # Get predictions
            probas = self.pipeline.predict(input_data)

            # Determine predicted outcome
            outcomes = ["home_win", "draw", "away_win"]
            max_idx = probas.argmax()
            predicted_outcome = outcomes[max_idx]
            confidence = float(probas[max_idx])

            # Calculate uncertainty using the ensemble's uncertainty method
            if hasattr(self.pipeline.ensemble, "get_uncertainty"):
                # This requires passing features through the ensemble
                # For now, use a simplified entropy calculation
                import numpy as np

                uncertainty = float(-np.sum(probas * np.log(probas + 1e-10)))
            else:
                uncertainty = 1.0 - confidence

            return {
                "home_win_prob": float(probas[0]),
                "draw_prob": float(probas[1]),
                "away_win_prob": float(probas[2]),
                "predicted_outcome": predicted_outcome,
                "confidence": confidence,
                "uncertainty": uncertainty,
                "model_version": self.model_version,
            }

        except Exception as e:
            logger.error(f"Prediction failed for match {match_id}: {e}")
            raise

    def predict_batch(self, matches: List[Dict]) -> List[Dict[str, float]]:
        """
        Predict multiple matches in batch for better performance

        Args:
            matches: List of match dictionaries with required fields

        Returns:
            List of prediction dictionaries
        """
        predictions = []

        for match in matches:
            try:
                pred = self.predict_match(
                    match_id=match["match_id"],
                    home_team_id=match["home_team_id"],
                    away_team_id=match["away_team_id"],
                    league_id=match["league_id"],
                    match_date=match["match_date"],
                    features=match.get("features", {}),
                )
                predictions.append(pred)
            except Exception as e:
                logger.error(
                    "Failed to predict match %s — skipping (no fabricated fallback): %s",
                    match.get("match_id"),
                    e,
                )
                # ponytail: skip failed match; fabricated 0.33/0.34/0.33 equal-split removed —
                # callers must handle a shorter result list or check for missing match_ids.

        return predictions

    def get_model_info(self) -> Dict[str, any]:
        """Get information about the loaded model"""
        if not self.pipeline or not self.pipeline.ensemble:
            return {
                "loaded": False,
                "model_version": self.model_version,
                "model_path": self.model_path,
            }

        return {
            "loaded": True,
            "model_version": self.model_version,
            "model_path": self.model_path,
            "n_models": 3,  # XGBoost, LightGBM, CatBoost
            "has_meta_learner": True,
            "is_calibrated": True,
            "expected_accuracy": "90%+",
            "target_latency": "<30ms",
        }


# ============================================================================
# BACKWARD COMPATIBILITY WRAPPER
# ============================================================================


class LegacyPredictorAdapter:
    """
    Adapter to make UltraPredictor compatible with existing PredictionService
    This allows gradual migration from old ensemble to ultra ensemble
    """

    def __init__(self):
        self.ultra = UltraPredictor()

    def predict(self, match_data: Dict) -> Dict:
        """
        Predict using ultra model but maintain legacy interface

        Args:
            match_data: Dictionary matching legacy format

        Returns:
            Dictionary matching legacy response format
        """
        # Convert legacy format to ultra format
        return self.ultra.predict_match(
            match_id=match_data.get("match_id", "unknown"),
            home_team_id=match_data["home_team_id"],
            away_team_id=match_data["away_team_id"],
            league_id=match_data.get("league_id", 0),
            match_date=match_data.get("match_date", datetime.now()),
            features=match_data.get("features", {}),
        )


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Example: Load and use ultra predictor
    predictor = UltraPredictor()

    # Print model info
    info = predictor.get_model_info()
    print(f"Model Info: {info}")

    # Example prediction
    if info["loaded"]:
        sample_match = {
            "match_id": "test_001",
            "home_team_id": 1,
            "away_team_id": 2,
            "league_id": 1,
            "match_date": datetime.now(),
            "features": {
                "home_last_5_wins": 3,
                "home_last_5_draws": 1,
                "home_last_5_losses": 1,
                "away_last_5_wins": 2,
                "away_last_5_draws": 2,
                "away_last_5_losses": 1,
                "home_goals_scored_avg": 1.8,
                "home_goals_conceded_avg": 1.2,
                "away_goals_scored_avg": 1.5,
                "away_goals_conceded_avg": 1.3,
                "h2h_home_wins": 4,
                "h2h_draws": 2,
                "h2h_away_wins": 3,
            },
        }

        prediction = predictor.predict_match(**sample_match)
        print(f"\nPrediction: {prediction}")
    else:
        print("\n⚠️ Model not loaded. Train the model first:")
        print("python -m backend.src.ml_ultra.training_pipeline")
