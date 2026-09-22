"""
Random Forest Classifier Model
Ensemble decision tree model with bagging for robust predictions
"""

import pandas as pd
import logging
from sklearn.ensemble import RandomForestClassifier
from .base_model import BaseModel

logger = logging.getLogger(__name__)


class RandomForestModel(BaseModel):
    """Random Forest classifier for match outcome prediction"""

    def __init__(self, model_version: str = "1.0.0"):
        """
        Initialize Random Forest model

        Args:
            model_version: Model version string
        """
        super().__init__(model_name="random_forest", model_version=model_version)
        self.default_params = {
            "n_estimators": 300,
            "max_depth": 12,
            "min_samples_split": 8,
            "min_samples_leaf": 4,
            "max_features": "sqrt",
            "random_state": 42,
            "n_jobs": -1,
            "class_weight": "balanced",
            "warm_start": False,
        }

    def build(self, **params) -> None:
        """
        Build Random Forest model with specified hyperparameters

        Args:
            **params: Override default hyperparameters
        """
        model_params = {**self.default_params, **params}

        self.model = RandomForestClassifier(**model_params)

        # Store build parameters in metadata
        self.training_metadata["build_params"] = model_params

        logger.info(f"Built {self.model_name} with params: {model_params}")

    def train(self, X: pd.DataFrame, y: pd.DataFrame) -> None:
        """
        Train Random Forest on provided data

        Args:
            X: Feature matrix (n_samples, n_features)
            y: Target labels (n_samples,)
        """
        if self.model is None:
            logger.info("Model not built, building with default params")
            self.build()

        try:
            logger.info(f"Training {self.model_name} on {len(X)} samples...")

            # Store feature columns
            self.feature_columns = list(X.columns)

            # Train model
            self.model.fit(X, y.values.ravel())

            self.is_trained = True

            # Store training metadata
            self.training_metadata.update(
                {
                    "n_samples": len(X),
                    "n_features": len(X.columns),
                    "n_estimators": self.model.n_estimators,
                    "max_depth": self.model.max_depth,
                    "n_classes": len(self.model.classes_),
                    "classes": list(self.model.classes_),
                }
            )

            logger.info(f"{self.model_name} training complete")

        except Exception as e:
            logger.error(f"Training failed for {self.model_name}: {e}")
            self.is_trained = False
            raise

    def get_tree_count(self) -> int:
        """
        Get number of trees in the forest

        Returns:
            Number of decision trees
        """
        if not self.is_trained:
            return 0
        return len(self.model.estimators_)

    def get_oob_score(self) -> float:
        """
        Get Out-of-Bag score if available

        Returns:
            OOB score or None
        """
        if not self.is_trained:
            return None

        if hasattr(self.model, "oob_score_"):
            return float(self.model.oob_score_)

        return None
