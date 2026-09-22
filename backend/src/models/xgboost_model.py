"""
XGBoost Classifier Model
Gradient boosting with extreme optimization for speed and performance
"""

import pandas as pd
import logging
import xgboost as xgb
from .base_model import BaseModel

logger = logging.getLogger(__name__)


class XGBoostModel(BaseModel):
    """XGBoost classifier for match outcome prediction"""

    def __init__(self, model_version: str = "1.0.0"):
        """
        Initialize XGBoost model

        Args:
            model_version: Model version string
        """
        super().__init__(model_name="xgboost", model_version=model_version)
        self.default_params = {
            "n_estimators": 250,
            "max_depth": 7,
            "learning_rate": 0.08,
            "subsample": 0.85,
            "colsample_bytree": 0.85,
            "gamma": 0.1,
            "min_child_weight": 3,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "random_state": 42,
            "n_jobs": -1,
            "tree_method": "hist",
            "objective": "multi:softprob",
            "eval_metric": "mlogloss",
        }

    def build(self, **params) -> None:
        """
        Build XGBoost model with specified hyperparameters

        Args:
            **params: Override default hyperparameters
        """
        model_params = {**self.default_params, **params}

        self.model = xgb.XGBClassifier(**model_params)

        # Store build parameters in metadata
        self.training_metadata["build_params"] = model_params

        logger.info(f"Built {self.model_name} with params: {model_params}")

    def train(self, X: pd.DataFrame, y: pd.DataFrame) -> None:
        """
        Train XGBoost on provided data

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
            self.model.fit(X, y.values.ravel(), verbose=False)

            self.is_trained = True

            # Store training metadata
            self.training_metadata.update(
                {
                    "n_samples": len(X),
                    "n_features": len(X.columns),
                    "n_estimators": self.model.n_estimators,
                    "max_depth": self.model.max_depth,
                    "learning_rate": self.model.learning_rate,
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
        Get information about the XGBoost booster

        Returns:
            Dictionary of booster information
        """
        if not self.is_trained:
            return {}

        return {
            "n_boosting_rounds": self.model.get_booster().num_boosted_rounds(),
            "best_iteration": self.model.best_iteration
            if hasattr(self.model, "best_iteration")
            else None,
        }
