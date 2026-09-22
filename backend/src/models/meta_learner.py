"""
Meta Learner Model
Stacks base model predictions using Logistic Regression for final ensemble output
"""

import pandas as pd
import numpy as np
import logging
from typing import List, Dict
from sklearn.linear_model import LogisticRegression
from .base_model import BaseModel

logger = logging.getLogger(__name__)


class MetaLearner(BaseModel):
    """Meta-learning model that combines base model predictions"""

    def __init__(self, base_models: List[BaseModel], model_version: str = "1.0.0"):
        """
        Initialize Meta Learner

        Args:
            base_models: List of trained base models
            model_version: Model version string
        """
        super().__init__(model_name="meta_learner", model_version=model_version)
        self.base_models = base_models
        self.default_params = {
            "random_state": 42,
            "max_iter": 1000,
            "multi_class": "ovr",
            "solver": "lbfgs",
            "C": 1.0,
        }

    def build(self, **params) -> None:
        """
        Build Meta Learner with specified hyperparameters

        Args:
            **params: Override default hyperparameters
        """
        model_params = {**self.default_params, **params}

        self.model = LogisticRegression(**model_params)

        # Store build parameters in metadata
        self.training_metadata["build_params"] = model_params
        self.training_metadata["base_model_count"] = len(self.base_models)
        self.training_metadata["base_models"] = [
            model.model_name for model in self.base_models
        ]

        logger.info(f"Built {self.model_name} with params: {model_params}")

    def create_meta_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Create meta features from base model predictions

        Args:
            X: Original feature matrix

        Returns:
            Meta feature matrix with base model probabilities
        """
        meta_features = pd.DataFrame()

        for base_model in self.base_models:
            if not base_model.is_trained:
                logger.warning(f"{base_model.model_name} not trained, skipping")
                continue

            # Get probability predictions from base model
            probs = base_model.predict_proba(X)

            # Store probabilities for each class
            meta_features[f"{base_model.model_name}_prob_home"] = probs[:, 0]
            meta_features[f"{base_model.model_name}_prob_draw"] = probs[:, 1]
            meta_features[f"{base_model.model_name}_prob_away"] = probs[:, 2]

        # Store meta feature columns
        self.feature_columns = list(meta_features.columns)

        return meta_features

    def train(self, X: pd.DataFrame, y: pd.DataFrame) -> None:
        """
        Train Meta Learner on base model predictions

        Args:
            X: Original feature matrix (used to generate meta features)
            y: Target labels
        """
        if self.model is None:
            logger.info("Model not built, building with default params")
            self.build()

        try:
            logger.info(f"Training {self.model_name} on {len(X)} samples...")

            # Create meta features from base model predictions
            meta_features = self.create_meta_features(X)

            if meta_features.empty:
                raise ValueError("No meta features generated. Check base models.")

            # Train meta learner on meta features
            self.model.fit(meta_features, y.values.ravel())

            self.is_trained = True

            # Store training metadata
            self.training_metadata.update(
                {
                    "n_samples": len(X),
                    "n_meta_features": len(meta_features.columns),
                    "n_classes": len(self.model.classes_),
                    "classes": list(self.model.classes_),
                }
            )

            # Evaluate meta learner accuracy
            train_accuracy = self.model.score(meta_features, y.values.ravel())
            self.training_metadata["train_accuracy"] = float(train_accuracy)

            logger.info(
                f"{self.model_name} training complete. "
                f"Train accuracy: {train_accuracy:.4f}"
            )

        except Exception as e:
            logger.error(f"Training failed for {self.model_name}: {e}")
            self.is_trained = False
            raise

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        Generate class predictions using meta learner

        Args:
            X: Original feature matrix

        Returns:
            Array of class predictions
        """
        meta_features = self.create_meta_features(X)
        return super().predict(meta_features)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """
        Generate probability predictions using meta learner

        Args:
            X: Original feature matrix

        Returns:
            Array of class probabilities [home, draw, away]
        """
        meta_features = self.create_meta_features(X)
        return super().predict_proba(meta_features)

    def get_base_model_weights(self) -> Dict[str, float]:
        """
        Get effective weights of base models in final predictions

        Returns:
            Dictionary mapping base model names to their weights
        """
        if not self.is_trained:
            return {}

        # Extract coefficients from logistic regression
        coefs = self.model.coef_[0]  # For binary or first class

        # Average absolute coefficient magnitude for each base model
        weights = {}
        for i, model in enumerate(self.base_models):
            # Each base model contributes 3 features (home/draw/away probs)
            start_idx = i * 3
            end_idx = start_idx + 3
            avg_weight = np.mean(np.abs(coefs[start_idx:end_idx]))
            weights[model.model_name] = float(avg_weight)

        return weights
