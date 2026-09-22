"""
Base Model Abstract Class
Defines interface for all prediction models in the ensemble
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
import pandas as pd
import numpy as np
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class BaseModel(ABC):
    """Abstract base class for all prediction models"""

    def __init__(self, model_name: str, model_version: str = "1.0.0"):
        """
        Initialize base model

        Args:
            model_name: Name identifier for the model
            model_version: Semantic version string
        """
        self.model_name = model_name
        self.model_version = model_version
        self.model = None
        self.is_trained = False
        self.feature_columns = []
        self.training_metadata = {}

    @abstractmethod
    def build(self, **params) -> None:
        """
        Build the model with specified hyperparameters

        Args:
            **params: Model-specific hyperparameters
        """
        pass

    @abstractmethod
    def train(self, X: pd.DataFrame, y: pd.DataFrame) -> None:
        """
        Train the model on provided data

        Args:
            X: Feature matrix
            y: Target labels
        """
        pass

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        Generate class predictions

        Args:
            X: Feature matrix

        Returns:
            Array of class predictions
        """
        if not self.is_trained:
            raise ValueError(f"{self.model_name} not trained yet")

        return self.model.predict(X)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Generate probability predictions

        Args:
            X: Feature matrix

        Returns:
            Array of class probabilities [home, draw, away]
        """
        if not self.is_trained:
            raise ValueError(f"{self.model_name} not trained yet")

        return self.model.predict_proba(X)

    def evaluate(self, X: pd.DataFrame, y: pd.DataFrame) -> Dict[str, float]:
        """
        Evaluate model performance on test data

        Args:
            X: Test feature matrix
            y: Test labels

        Returns:
            Dictionary of evaluation metrics
        """
        if not self.is_trained:
            raise ValueError(f"{self.model_name} not trained yet")

        try:
            # Get predictions
            y_pred = self.predict(X)
            y_proba = self.predict_proba(X)

            # Calculate metrics
            accuracy = accuracy_score(y, y_pred)

            # Multiclass Brier score (average across classes)
            brier = self._calculate_multiclass_brier(y, y_proba)

            # Log loss
            logloss = log_loss(y, y_proba)

            metrics = {
                "accuracy": float(accuracy),
                "brier_score": float(brier),
                "log_loss": float(logloss),
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }

            logger.info(f"{self.model_name} Evaluation: {metrics}")

            return metrics

        except Exception as e:
            logger.error(f"Evaluation failed for {self.model_name}: {e}")
            raise

    def _calculate_multiclass_brier(
        self, y_true: pd.DataFrame, y_proba: np.ndarray
    ) -> float:
        """
        Calculate Brier score for multiclass classification

        Args:
            y_true: True labels
            y_proba: Predicted probabilities

        Returns:
            Average Brier score across all classes
        """
        # Encode labels to integers
        label_mapping = {"home_win": 0, "draw": 1, "away_win": 2}
        y_encoded = y_true.values.ravel()
        y_encoded = np.array([label_mapping.get(label, label) for label in y_encoded])

        # Calculate Brier score for each class
        brier_scores = []
        for i in range(3):
            y_binary = (y_encoded == i).astype(int)
            brier_scores.append(brier_score_loss(y_binary, y_proba[:, i]))

        return np.mean(brier_scores)

    def get_feature_importance(self, top_n: int = 20) -> Dict[str, float]:
        """
        Get feature importance scores

        Args:
            top_n: Number of top features to return

        Returns:
            Dictionary mapping feature names to importance scores
        """
        if not self.is_trained:
            raise ValueError(f"{self.model_name} not trained yet")

        if not hasattr(self.model, "feature_importances_"):
            return {}

        importance = self.model.feature_importances_
        feature_importance = dict(zip(self.feature_columns, importance))

        # Sort by importance and return top N
        sorted_features = sorted(
            feature_importance.items(), key=lambda x: x[1], reverse=True
        )[:top_n]

        return dict(sorted_features)

    def get_metadata(self) -> Dict[str, Any]:
        """
        Get model metadata for tracking and versioning

        Returns:
            Dictionary of model metadata
        """
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "is_trained": self.is_trained,
            "feature_count": len(self.feature_columns),
            "training_metadata": self.training_metadata,
        }

    def __repr__(self) -> str:
        return f"{self.model_name}(version={self.model_version}, trained={self.is_trained})"
