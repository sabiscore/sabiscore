#!/usr/bin/env python3
"""
Meta-Learning Ensemble System
Diverse model ensemble targeting 90%+ accuracy through complementary predictions
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import cross_val_predict, StratifiedKFold
import xgboost as xgb
import lightgbm as lgb
from catboost import CatBoostClassifier
import joblib
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class DiverseEnsemble(BaseEstimator, ClassifierMixin):
    """
    Meta-learning ensemble with model diversity maximization
    Combines: XGBoost, LightGBM, CatBoost with meta-learner
    Target: 90%+ accuracy through complementary predictions
    """

    def __init__(self, random_state=42):
        self.random_state = random_state
        self.models: Dict[str, BaseEstimator] = {}
        self.meta_learner: Optional[LogisticRegression] = None
        self.calibrated_models: Dict[str, CalibratedClassifierCV] = {}
        self.feature_names: List[str] = []
        self.is_trained = False

    def _create_diverse_models(self) -> Dict[str, BaseEstimator]:
        """Create models with different inductive biases"""
        return {
            # Tree-based (handles non-linearity)
            "xgb": xgb.XGBClassifier(
                n_estimators=800,
                learning_rate=0.03,
                max_depth=8,
                min_child_weight=3,
                gamma=0.2,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=0.5,
                reg_lambda=2.0,
                tree_method="hist",
                enable_categorical=False,
                random_state=self.random_state,
                n_jobs=-1,
                eval_metric="mlogloss",
                verbosity=0,
            ),
            # Leaf-wise growth (different tree strategy)
            "lgb": lgb.LGBMClassifier(
                n_estimators=800,
                learning_rate=0.03,
                num_leaves=64,
                max_depth=8,
                min_child_samples=25,
                feature_fraction=0.8,
                bagging_fraction=0.8,
                bagging_freq=5,
                reg_alpha=0.5,
                reg_lambda=2.0,
                random_state=self.random_state,
                n_jobs=-1,
                verbose=-1,
                force_col_wise=True,
            ),
            # Ordered boosting (handles overfitting differently)
            "cat": CatBoostClassifier(
                iterations=800,
                learning_rate=0.03,
                depth=8,
                l2_leaf_reg=5,
                bootstrap_type="Bernoulli",
                subsample=0.8,
                random_seed=self.random_state,
                verbose=False,
                thread_count=-1,
            ),
        }

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "DiverseEnsemble":
        """Train all models and meta-learner"""
        logger.info("🔧 Training diverse ensemble...")

        if isinstance(X, pd.DataFrame):
            self.feature_names = X.columns.tolist()
            X = X.values

        y_array = y.values if isinstance(y, pd.Series) else y

        self.models = self._create_diverse_models()

        # Train base models with cross-validation for meta-features
        n_classes = len(np.unique(y_array))
        meta_features = np.zeros((len(X), len(self.models) * n_classes))

        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=self.random_state)

        for idx, (name, model) in enumerate(self.models.items()):
            logger.info(f"Training {name}...")

            # Get out-of-fold predictions for meta-learner
            try:
                oof_preds = cross_val_predict(
                    model, X, y_array, cv=cv, method="predict_proba", n_jobs=-1
                )
            except Exception as e:
                logger.warning(f"Cross-validation failed for {name}: {e}")
                # Train normally and predict on training data
                model.fit(X, y_array)
                oof_preds = model.predict_proba(X)

            meta_features[:, idx * n_classes : (idx + 1) * n_classes] = oof_preds

            # Train on full data
            logger.info(f"Training {name} on full dataset...")
            model.fit(X, y_array)

            # Calibrate probabilities
            logger.info(f"Calibrating {name}...")
            self.calibrated_models[name] = CalibratedClassifierCV(
                model, method="isotonic", cv="prefit", n_jobs=-1
            )
            # Use a small portion for calibration
            cal_size = min(len(X), 1000)
            cal_indices = np.random.choice(len(X), cal_size, replace=False)
            self.calibrated_models[name].fit(X[cal_indices], y_array[cal_indices])

        # Train meta-learner (logistic regression on probabilities)
        logger.info("Training meta-learner...")
        self.meta_learner = LogisticRegression(
            C=1.0,
            max_iter=1000,
            multi_class="multinomial",
            random_state=self.random_state,
            n_jobs=-1,
        )
        self.meta_learner.fit(meta_features, y_array)

        self.is_trained = True
        logger.info("✅ Ensemble training complete!")

        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Generate calibrated ensemble predictions"""
        if not self.is_trained:
            raise ValueError("Model must be trained before prediction")

        if isinstance(X, pd.DataFrame):
            X = X.values

        # Get predictions from all calibrated models
        n_classes = 3  # home, draw, away
        meta_features = np.zeros((len(X), len(self.calibrated_models) * n_classes))

        for idx, (name, model) in enumerate(self.calibrated_models.items()):
            preds = model.predict_proba(X)
            meta_features[:, idx * n_classes : (idx + 1) * n_classes] = preds

        # Meta-learner combines predictions
        final_probs = self.meta_learner.predict_proba(meta_features)

        return final_probs

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict class labels"""
        probs = self.predict_proba(X)
        return np.argmax(probs, axis=1)

    def get_uncertainty(self, X: pd.DataFrame) -> np.ndarray:
        """Calculate prediction uncertainty using entropy"""
        probs = self.predict_proba(X)
        # Return entropy as uncertainty measure
        epsilon = 1e-10
        entropy = -np.sum(probs * np.log(probs + epsilon), axis=1)
        return entropy

    def save(self, filepath: Path) -> None:
        """Save trained ensemble to disk"""
        if not self.is_trained:
            raise ValueError("Cannot save untrained model")

        save_dict = {
            "models": self.models,
            "meta_learner": self.meta_learner,
            "calibrated_models": self.calibrated_models,
            "feature_names": self.feature_names,
            "is_trained": self.is_trained,
            "random_state": self.random_state,
        }

        filepath.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(save_dict, filepath)
        logger.info(f"✅ Ensemble saved to {filepath}")

    @classmethod
    def load(cls, filepath: Path) -> "DiverseEnsemble":
        """Load trained ensemble from disk"""
        save_dict = joblib.load(filepath)

        instance = cls(random_state=save_dict.get("random_state", 42))
        instance.models = save_dict["models"]
        instance.meta_learner = save_dict["meta_learner"]
        instance.calibrated_models = save_dict["calibrated_models"]
        instance.feature_names = save_dict["feature_names"]
        instance.is_trained = save_dict["is_trained"]

        logger.info(f"✅ Ensemble loaded from {filepath}")
        return instance

    def get_model_weights(self) -> Dict[str, float]:
        """Get meta-learner weights for each base model"""
        if not self.is_trained or self.meta_learner is None:
            return {}

        # Extract coefficients from meta-learner
        coef = self.meta_learner.coef_
        n_classes = coef.shape[0]
        len(self.models)

        weights = {}
        for idx, name in enumerate(self.models.keys()):
            # Average absolute coefficient across classes
            model_coef = coef[:, idx * n_classes : (idx + 1) * n_classes]
            weights[name] = float(np.mean(np.abs(model_coef)))

        # Normalize
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}

        return weights
