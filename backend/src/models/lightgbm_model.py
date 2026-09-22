"""
LightGBM Classifier Model
Fast gradient boosting framework optimized for efficiency and low memory usage
"""

import pandas as pd
import logging
import lightgbm as lgb
from .base_model import BaseModel

logger = logging.getLogger(__name__)


class LightGBMModel(BaseModel):
    """LightGBM classifier for match outcome prediction"""

    def __init__(self, model_version: str = "1.0.0"):
        """
        Initialize LightGBM model

        Args:
            model_version: Model version string
        """
        super().__init__(model_name="lightgbm", model_version=model_version)
        self.default_params = {
            "n_estimators": 250,
            "max_depth": 7,
            "learning_rate": 0.08,
            "subsample": 0.85,
            "colsample_bytree": 0.85,
            "min_child_samples": 20,
            "num_leaves": 63,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "random_state": 42,
            "n_jobs": -1,
            "verbose": -1,
            "objective": "multiclass",
            "metric": "multi_logloss",
        }

    def build(self, **params) -> None:
        """
        Build LightGBM model with specified hyperparameters

        Args:
            **params: Override default hyperparameters
        """
        model_params = {**self.default_params, **params}

        self.model = lgb.LGBMClassifier(**model_params)

        # Store build parameters in metadata
        self.training_metadata["build_params"] = model_params

        logger.info(f"Built {self.model_name} with params: {model_params}")

    def train(self, X: pd.DataFrame, y: pd.DataFrame) -> None:
        """
        Train LightGBM on provided data

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
                    "learning_rate": self.model.learning_rate,
                    "num_leaves": self.model.num_leaves,
                    "n_classes": len(self.model.classes_),
                    "classes": list(self.model.classes_),
                }
            )

            logger.info(f"{self.model_name} training complete")

        except Exception as e:
            logger.error(f"Training failed for {self.model_name}: {e}")
            self.is_trained = False
            raise

    def get_booster_info(self) -> dict:
        """
        Get information about the LightGBM booster

        Returns:
            Dictionary of booster information
        """
        if not self.is_trained:
            return {}

        return {
            "n_boosting_rounds": self.model.booster_.num_trees(),
            "best_iteration": self.model.best_iteration_
            if hasattr(self.model, "best_iteration_")
            else None,
            "num_leaves": self.model.num_leaves,
        }
