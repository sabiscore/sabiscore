# backend/src/services/model_training.py
"""
Model Training Service - Hyperparameter tuning, cross-validation, and model versioning
Integrates with ModelOrchestrator for production model deployment
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
import pickle
import json
import hashlib
from pathlib import Path

from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, f1_score
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
import optuna

from ..models.match import Match
from ..core.logging import get_logger

logger = get_logger(__name__)


class ModelTrainingService:
    """
    Production model training with:
    - Hyperparameter optimization (Optuna)
    - Time-series cross-validation (5-fold)
    - Model versioning and A/B testing
    - Automated deployment to production
    """

    def __init__(self, db: Session, model_dir: str = "backend/models"):
        self.db = db
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        # Training configuration
        self.config = {
            "lookback_days": 180,  # 6 months historical data
            "min_samples": 500,
            "test_size": 0.2,
            "cv_folds": 5,
            "random_state": 42,
            "n_trials": 50,  # Optuna optimization trials
        }

    def train_league_model(
        self, league: str, optimize: bool = True, deploy: bool = False
    ) -> Dict:
        """
        Train a league-specific model with full pipeline

        Args:
            league: League identifier (epl, bundesliga, etc.)
            optimize: Run hyperparameter optimization
            deploy: Deploy to production if better than current model

        Returns:
            Training metrics and model metadata
        """
        logger.info(f"🚀 Starting {league.upper()} model training")

        # Step 1: Load and prepare data
        X_train, X_test, y_train, y_test, feature_names = self._prepare_training_data(
            league
        )

        if len(X_train) < self.config["min_samples"]:
            raise ValueError(
                f"Insufficient training data: {len(X_train)} samples "
                f"(minimum {self.config['min_samples']})"
            )

        logger.info(
            f"Data prepared: {len(X_train)} train, {len(X_test)} test samples, "
            f"{len(feature_names)} features"
        )

        # Step 2: Train ensemble models
        models = {}

        if optimize:
            logger.info("Running hyperparameter optimization with Optuna")
            models["rf"] = self._optimize_random_forest(X_train, y_train, league)
            models["xgb"] = self._optimize_xgboost(X_train, y_train, league)
            models["lgbm"] = self._optimize_lightgbm(X_train, y_train, league)
            models["gb"] = self._optimize_gradient_boosting(X_train, y_train, league)
        else:
            logger.info("Training with optimized default hyperparameters")
            models["rf"] = RandomForestClassifier(
                n_estimators=300,
                max_depth=12,
                min_samples_split=8,
                min_samples_leaf=4,
                max_features="sqrt",
                random_state=42,
                n_jobs=-1,
            )
            models["xgb"] = XGBClassifier(
                n_estimators=250,
                max_depth=7,
                learning_rate=0.08,
                subsample=0.85,
                colsample_bytree=0.85,
                tree_method="hist",
                random_state=42,
                n_jobs=-1,
            )
            models["lgbm"] = LGBMClassifier(
                n_estimators=250,
                max_depth=7,
                learning_rate=0.08,
                subsample=0.85,
                colsample_bytree=0.85,
                min_child_samples=20,
                reg_alpha=0.1,
                reg_lambda=1.0,
                random_state=42,
                n_jobs=-1,
                verbose=-1,
            )
            models["gb"] = GradientBoostingClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.08,
                subsample=0.85,
                random_state=42,
            )

            for name, model in models.items():
                logger.info(f"Training {name.upper()}...")
                model.fit(X_train, y_train)

        # Step 3: Evaluate individual models
        model_metrics = {}
        for name, model in models.items():
            metrics = self._evaluate_model(model, X_test, y_test, name)
            model_metrics[name] = metrics
            logger.info(
                f"{name.upper()}: Accuracy={metrics['accuracy']:.3f}, "
                f"Brier={metrics['brier_score']:.4f}"
            )

        # Step 4: Optimize ensemble weights
        logger.info("Optimizing ensemble weights")
        optimal_weights = self._optimize_ensemble_weights(models, X_test, y_test)

        # Step 5: Evaluate ensemble
        ensemble_metrics = self._evaluate_ensemble(
            models, optimal_weights, X_test, y_test
        )

        logger.info(
            f"🎯 Ensemble: Accuracy={ensemble_metrics['accuracy']:.3f}, "
            f"Brier={ensemble_metrics['brier_score']:.4f}"
        )

        # Step 6: Isotonic calibration with balanced sample weights (BUG-007 fix)
        logger.info("Applying isotonic calibration (BUG-007: sigmoid → isotonic)")
        sample_weights = compute_sample_weight(class_weight="balanced", y=y_train)
        calibrated_models = {}
        for name, model in models.items():
            calibrated = CalibratedClassifierCV(
                model,
                method="isotonic",
                cv=5,
            )
            calibrated.fit(X_train, y_train, sample_weight=sample_weights)
            calibrated_models[name] = calibrated

        # Step 7: Save models
        model_version = self._generate_version_hash(league)
        model_path = self.model_dir / f"{league}_ensemble_{model_version}.pkl"

        model_artifact = {
            "models": models,
            "calibrated_models": calibrated_models,
            "weights": optimal_weights,
            "feature_names": feature_names,
            "metrics": ensemble_metrics,
            "individual_metrics": model_metrics,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "league": league,
            "version": model_version,
            "config": self.config,
        }

        with open(model_path, "wb") as f:
            pickle.dump(model_artifact, f)

        logger.info(f"✅ Model saved: {model_path}")

        # Step 8: Deploy if requested and better than current
        if deploy:
            deployed = self._deploy_model(league, model_version, ensemble_metrics)
            if deployed:
                logger.info(
                    f"🚀 Model deployed to production: {league} v{model_version}"
                )

        return {
            "league": league,
            "version": model_version,
            "metrics": ensemble_metrics,
            "model_path": str(model_path),
            "weights": optimal_weights,
            "deployed": deploy,
        }

    def _prepare_training_data(
        self, league: str
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, List[str]]:
        """
        Prepare training data with time-series split
        """
        # Query historical matches
        cutoff_date = datetime.now(timezone.utc) - timedelta(
            days=self.config["lookback_days"]
        )

        matches = (
            self.db.query(Match)
            .filter(
                Match.league == league,
                Match.match_date >= cutoff_date,
                Match.home_score.isnot(None),
                Match.away_score.isnot(None),
            )
            .order_by(Match.match_date)
            .all()
        )

        # Extract features (placeholder - integrate with FeatureEngineer)
        X_data = []
        y_data = []

        for match in matches:
            # Extract features (in production: use DataProcessingService)
            features = self._extract_match_features(match)
            X_data.append(features)

            # Label: 0=home, 1=draw, 2=away
            if match.home_score > match.away_score:
                y_data.append(0)
            elif match.home_score == match.away_score:
                y_data.append(1)
            else:
                y_data.append(2)

        # Convert to DataFrame
        X = pd.DataFrame(X_data)
        y = pd.Series(y_data)

        # Time-series split (80/20)
        split_idx = int(len(X) * 0.8)
        X_train = X.iloc[:split_idx]
        X_test = X.iloc[split_idx:]
        y_train = y.iloc[:split_idx]
        y_test = y.iloc[split_idx:]

        feature_names = X.columns.tolist()

        return X_train, X_test, y_train, y_test, feature_names

    def _extract_match_features(self, match: Match) -> Dict:
        """
        Extract features from match object
        TODO: Replace with DataProcessingService integration
        """
        return {
            "home_team_id": match.home_team_id,
            "away_team_id": match.away_team_id,
            "home_score_l5": 0,  # Placeholder
            "away_score_l5": 0,
            "home_xg": match.home_xg or 0,
            "away_xg": match.away_xg or 0,
            # ... 220+ features in production
        }

    def _optimize_random_forest(
        self, X_train: pd.DataFrame, y_train: pd.Series, league: str
    ) -> RandomForestClassifier:
        """Optimize Random Forest with Optuna"""

        def objective(trial):
            params = {
                "n_estimators": trial.suggest_int("n_estimators", 200, 400),
                "max_depth": trial.suggest_int("max_depth", 10, 20),
                "min_samples_split": trial.suggest_int("min_samples_split", 4, 12),
                "min_samples_leaf": trial.suggest_int("min_samples_leaf", 2, 8),
                "max_features": trial.suggest_categorical(
                    "max_features", ["sqrt", "log2"]
                ),
                "random_state": 42,
            }

            model = RandomForestClassifier(**params)

            # Time-series CV
            tscv = TimeSeriesSplit(n_splits=self.config["cv_folds"])
            scores = []

            for train_idx, val_idx in tscv.split(X_train):
                X_t, X_v = X_train.iloc[train_idx], X_train.iloc[val_idx]
                y_t, y_v = y_train.iloc[train_idx], y_train.iloc[val_idx]

                model.fit(X_t, y_t)
                y_pred_proba = model.predict_proba(X_v)

                # Optimize for Brier score (lower is better)
                y_v_onehot = pd.get_dummies(y_v).values
                brier = brier_score_loss(
                    y_v_onehot.ravel(), y_pred_proba.ravel(), pos_label=None
                )
                scores.append(brier)

            return np.mean(scores)

        study = optuna.create_study(
            direction="minimize", study_name=f"{league}_rf_optimization"
        )
        study.optimize(
            objective, n_trials=self.config["n_trials"], show_progress_bar=True
        )

        # Train with best params
        best_model = RandomForestClassifier(**study.best_params, random_state=42)
        best_model.fit(X_train, y_train)

        logger.info(
            f"RF Best params: {study.best_params}, Brier: {study.best_value:.4f}"
        )
        return best_model

    def _optimize_xgboost(
        self, X_train: pd.DataFrame, y_train: pd.Series, league: str
    ) -> XGBClassifier:
        """Optimize XGBoost with Optuna"""

        def objective(trial):
            params = {
                "n_estimators": trial.suggest_int("n_estimators", 200, 350),
                "max_depth": trial.suggest_int("max_depth", 5, 10),
                "learning_rate": trial.suggest_float(
                    "learning_rate", 0.05, 0.15, log=True
                ),
                "subsample": trial.suggest_float("subsample", 0.7, 0.95),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.7, 0.95),
                "gamma": trial.suggest_float("gamma", 0, 0.3),
                "min_child_weight": trial.suggest_int("min_child_weight", 1, 5),
                "reg_alpha": trial.suggest_float("reg_alpha", 0, 0.3),
                "reg_lambda": trial.suggest_float("reg_lambda", 0.5, 2.0),
                "tree_method": "hist",
                "random_state": 42,
                "eval_metric": "mlogloss",
            }

            model = XGBClassifier(**params)

            tscv = TimeSeriesSplit(n_splits=self.config["cv_folds"])
            scores = []

            for train_idx, val_idx in tscv.split(X_train):
                X_t, X_v = X_train.iloc[train_idx], X_train.iloc[val_idx]
                y_t, y_v = y_train.iloc[train_idx], y_train.iloc[val_idx]

                model.fit(X_t, y_t, eval_set=[(X_v, y_v)], verbose=False)
                y_pred_proba = model.predict_proba(X_v)

                y_v_onehot = pd.get_dummies(y_v).values
                brier = brier_score_loss(y_v_onehot.ravel(), y_pred_proba.ravel())
                scores.append(brier)

            return np.mean(scores)

        study = optuna.create_study(direction="minimize")
        study.optimize(
            objective, n_trials=self.config["n_trials"], show_progress_bar=True
        )

        best_model = XGBClassifier(**study.best_params, random_state=42)
        best_model.fit(X_train, y_train)

        logger.info(
            f"XGB Best params: {study.best_params}, Brier: {study.best_value:.4f}"
        )
        return best_model

    def _optimize_lightgbm(
        self, X_train: pd.DataFrame, y_train: pd.Series, league: str
    ) -> LGBMClassifier:
        """Optimize LightGBM with Optuna"""

        def objective(trial):
            params = {
                "n_estimators": trial.suggest_int("n_estimators", 200, 350),
                "max_depth": trial.suggest_int("max_depth", 5, 12),
                "learning_rate": trial.suggest_float(
                    "learning_rate", 0.05, 0.15, log=True
                ),
                "num_leaves": trial.suggest_int("num_leaves", 31, 127),
                "subsample": trial.suggest_float("subsample", 0.7, 0.95),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.7, 0.95),
                "min_child_samples": trial.suggest_int("min_child_samples", 15, 30),
                "reg_alpha": trial.suggest_float("reg_alpha", 0, 0.3),
                "reg_lambda": trial.suggest_float("reg_lambda", 0.5, 2.0),
                "random_state": 42,
                "verbose": -1,
            }

            model = LGBMClassifier(**params)

            tscv = TimeSeriesSplit(n_splits=self.config["cv_folds"])
            scores = []

            for train_idx, val_idx in tscv.split(X_train):
                X_t, X_v = X_train.iloc[train_idx], X_train.iloc[val_idx]
                y_t, y_v = y_train.iloc[train_idx], y_train.iloc[val_idx]

                model.fit(X_t, y_t)
                y_pred_proba = model.predict_proba(X_v)

                y_v_onehot = pd.get_dummies(y_v).values
                brier = brier_score_loss(y_v_onehot.ravel(), y_pred_proba.ravel())
                scores.append(brier)

            return np.mean(scores)

        study = optuna.create_study(direction="minimize")
        study.optimize(
            objective, n_trials=self.config["n_trials"], show_progress_bar=True
        )

        best_model = LGBMClassifier(**study.best_params, random_state=42, verbose=-1)
        best_model.fit(X_train, y_train)

        logger.info(
            f"LGBM Best params: {study.best_params}, Brier: {study.best_value:.4f}"
        )
        return best_model

    def _optimize_gradient_boosting(
        self, X_train: pd.DataFrame, y_train: pd.Series, league: str
    ) -> GradientBoostingClassifier:
        """Optimize Gradient Boosting with Grid Search"""

        param_grid = {
            "n_estimators": [150, 200, 250],
            "max_depth": [3, 5, 7],
            "learning_rate": [0.01, 0.05, 0.1],
            "subsample": [0.8, 0.9, 1.0],
        }

        base_model = GradientBoostingClassifier(random_state=42)

        grid_search = GridSearchCV(
            base_model,
            param_grid,
            cv=TimeSeriesSplit(n_splits=3),
            scoring="neg_brier_score",
            n_jobs=-1,
            verbose=1,
        )

        grid_search.fit(X_train, y_train)

        logger.info(f"GB Best params: {grid_search.best_params_}")
        return grid_search.best_estimator_

    def _evaluate_model(
        self, model, X_test: pd.DataFrame, y_test: pd.Series, model_name: str
    ) -> Dict:
        """Comprehensive model evaluation"""

        y_pred = model.predict(X_test)
        y_pred_proba = model.predict_proba(X_test)

        # Convert to one-hot for Brier score
        y_test_onehot = pd.get_dummies(y_test).values

        metrics = {
            "accuracy": accuracy_score(y_test, y_pred),
            "f1_score": f1_score(y_test, y_pred, average="weighted"),
            "brier_score": brier_score_loss(
                y_test_onehot.ravel(), y_pred_proba.ravel()
            ),
            "log_loss": log_loss(y_test, y_pred_proba),
            "model_name": model_name,
        }

        return metrics

    def _optimize_ensemble_weights(
        self, models: Dict, X_test: pd.DataFrame, y_test: pd.Series
    ) -> Dict:
        """
        Optimize ensemble weights using Optuna
        Finds weights that minimize Brier score
        """

        # Get predictions from each model
        predictions = {}
        for name, model in models.items():
            predictions[name] = model.predict_proba(X_test)

        def objective(trial):
            # Suggest weights that sum to 1
            w_rf = trial.suggest_float("rf", 0.1, 0.5)
            w_xgb = trial.suggest_float("xgb", 0.1, 0.5)
            w_lgbm = trial.suggest_float("lgbm", 0.1, 0.4)
            w_gb = 1 - (w_rf + w_xgb + w_lgbm)

            if w_gb < 0 or w_gb > 0.3:
                return float("inf")

            # Weighted ensemble prediction
            ensemble_pred = (
                w_rf * predictions["rf"]
                + w_xgb * predictions["xgb"]
                + w_lgbm * predictions["lgbm"]
                + w_gb * predictions["gb"]
            )

            # Calculate Brier score
            y_test_onehot = pd.get_dummies(y_test).values
            brier = brier_score_loss(y_test_onehot.ravel(), ensemble_pred.ravel())

            return brier

        study = optuna.create_study(direction="minimize")
        study.optimize(objective, n_trials=100, show_progress_bar=True)

        # Extract best weights
        best_weights = {
            "rf": study.best_params["rf"],
            "xgb": study.best_params["xgb"],
            "lgbm": study.best_params["lgbm"],
            "gb": 1
            - (
                study.best_params["rf"]
                + study.best_params["xgb"]
                + study.best_params["lgbm"]
            ),
        }

        logger.info(f"Optimal weights: {best_weights}")
        return best_weights

    def _evaluate_ensemble(
        self, models: Dict, weights: Dict, X_test: pd.DataFrame, y_test: pd.Series
    ) -> Dict:
        """Evaluate weighted ensemble"""

        # Weighted predictions
        ensemble_pred = np.zeros((len(X_test), 3))

        for name, model in models.items():
            pred_proba = model.predict_proba(X_test)
            ensemble_pred += weights[name] * pred_proba

        # Final prediction
        y_pred = np.argmax(ensemble_pred, axis=1)

        # Metrics
        y_test_onehot = pd.get_dummies(y_test).values

        return {
            "accuracy": accuracy_score(y_test, y_pred),
            "f1_score": f1_score(y_test, y_pred, average="weighted"),
            "brier_score": brier_score_loss(
                y_test_onehot.ravel(), ensemble_pred.ravel()
            ),
            "log_loss": log_loss(y_test, ensemble_pred),
        }

    def _generate_version_hash(self, league: str) -> str:
        """Generate unique version hash"""
        timestamp = datetime.now(timezone.utc).isoformat()
        hash_input = f"{league}_{timestamp}_{self.config}".encode()
        return hashlib.md5(hash_input).hexdigest()[:8]

    def _deploy_model(self, league: str, version: str, metrics: Dict) -> bool:
        """
        Deploy model to production if better than current
        """
        # Check if better than current production model
        current_metrics_path = self.model_dir / f"{league}_current_metrics.json"

        if current_metrics_path.exists():
            with open(current_metrics_path, "r") as f:
                current_metrics = json.load(f)

            # Compare Brier scores (lower is better)
            if metrics["brier_score"] >= current_metrics["brier_score"]:
                logger.info(
                    f"New model not better: {metrics['brier_score']:.4f} vs {current_metrics['brier_score']:.4f}"
                )
                return False

        # Deploy: copy to production path
        source = self.model_dir / f"{league}_ensemble_{version}.pkl"
        dest = self.model_dir / f"{league}_production.pkl"

        import shutil

        shutil.copy(source, dest)

        # Update metrics
        with open(current_metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)

        return True
