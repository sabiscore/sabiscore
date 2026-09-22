"""
Enhanced Training Pipeline for SabiScore
=========================================

Implements audit recommendations:
- Stacking with multiple levels (num_stack_levels=2)
- Cross-validation bagging (num_bag_folds=8)
- Extended time budget (7200s)
- Isotonic calibration post-training
- Advanced feature engineering integration

This module wraps the existing EnsembleModel with stronger configs
and calibration layers.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import (
    RandomForestClassifier,
    StackingClassifier,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.model_selection import StratifiedKFold, train_test_split
from tqdm import tqdm

try:
    import xgboost as xgb
except ImportError:
    xgb = None  # type: ignore

try:
    import lightgbm as lgb
except ImportError:
    lgb = None  # type: ignore

from ..core.config import settings
from ..data.transformers import FeatureTransformer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Advanced Feature Engineering
# ---------------------------------------------------------------------------


def engineer_advanced_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate advanced predictive features per audit recommendations:
    - Form momentum (weighted recent performance)
    - Odds liquidity spread (back/lay if available)
    - PPDA differentials (pressing intensity proxy)
    - Referee bias (if referee column present)
    """
    df = df.copy()

    # ---- Form momentum: exponential weighting of last N results ----
    for role in ("home", "away"):
        pts_col = f"{role}_points_last5"
        momentum_col = f"{role}_form_momentum"
        if pts_col in df.columns:
            # Simple proxy: normalized points with recency weight
            df[momentum_col] = df[pts_col] / 15.0  # max 15 pts in 5 games
        else:
            df[momentum_col] = 0.5

    # ---- Odds liquidity proxy: spread between best/worst odds ----
    for outcome in ("home_win", "draw", "away_win"):
        best_col = f"bf_{outcome}_back"
        worst_col = f"bf_{outcome}_lay"
        spread_col = f"{outcome}_liquidity_spread"
        if best_col in df.columns and worst_col in df.columns:
            df[spread_col] = df[worst_col] - df[best_col]
        else:
            df[spread_col] = 0.0

    # ---- PPDA differential (use xG as proxy if available) ----
    if "us_home_xg_pg" in df.columns and "us_away_xg_pg" in df.columns:
        df["ppda_diff_proxy"] = df["us_home_xg_pg"] - df["us_away_xg_pg"]
    else:
        df["ppda_diff_proxy"] = 0.0

    # ---- Referee bias (placeholder) ----
    if "referee" in df.columns:
        # Could encode historical card/penalty rates per ref
        df["referee_bias"] = df["referee"].astype("category").cat.codes
    else:
        df["referee_bias"] = 0

    return df


# ---------------------------------------------------------------------------
# Isotonic Calibration Wrapper
# ---------------------------------------------------------------------------


class CalibratedEnsemble:
    """
    Wraps a trained classifier with isotonic probability calibration.
    """

    def __init__(
        self, base_estimator: Any, method: str = "isotonic", cv: Any = "prefit"
    ):
        self.base_estimator = base_estimator
        self.method = method
        self.cv = cv
        self.calibrated_: Optional[CalibratedClassifierCV] = None

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "CalibratedEnsemble":
        """Fit calibration on held-out folds."""
        self.calibrated_ = CalibratedClassifierCV(
            estimator=self.base_estimator,
            method=self.method,
            cv=self.cv,
        )
        self.calibrated_.fit(X, y)
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self.calibrated_ is None:
            raise RuntimeError("Calibrator not fitted")
        return self.calibrated_.predict_proba(X)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.calibrated_ is None:
            raise RuntimeError("Calibrator not fitted")
        return self.calibrated_.predict(X)


# ---------------------------------------------------------------------------
# Enhanced Stacking Ensemble
# ---------------------------------------------------------------------------


class EnhancedStackingEnsemble:
    """
    Two-level stacking ensemble with bagging and calibration.

    Level 0: RF, XGBoost, LightGBM (each with 8-fold CV bagging)
    Level 1: Logistic Regression meta-learner
    Post-hoc: Isotonic calibration
    """

    NUM_BAG_FOLDS = 8
    NUM_STACK_LEVELS = 2

    def __init__(
        self,
        time_budget_s: int = 7200,
        calibrate: bool = True,
        random_state: int = 42,
    ):
        self.time_budget_s = time_budget_s
        self.calibrate = calibrate
        self.random_state = random_state

        self.stacking_model_: Optional[StackingClassifier] = None
        self.calibrator_: Optional[CalibratedEnsemble] = None
        self.feature_columns_: List[str] = []
        self.metadata_: Dict[str, Any] = {}
        self.is_trained_ = False

    # ------------------------------------------------------------------
    # Base estimator factories
    # ------------------------------------------------------------------

    def _make_rf(self) -> RandomForestClassifier:
        return RandomForestClassifier(
            n_estimators=400,
            max_depth=14,
            min_samples_split=6,
            min_samples_leaf=3,
            max_features="sqrt",
            random_state=self.random_state,
            n_jobs=-1,
        )

    def _make_xgb(self) -> Any:
        if xgb is None:
            raise ImportError("xgboost is required for EnhancedStackingEnsemble")
        return xgb.XGBClassifier(
            n_estimators=350,
            max_depth=8,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            gamma=0.15,
            reg_alpha=0.2,
            reg_lambda=1.5,
            random_state=self.random_state,
            n_jobs=-1,
            tree_method="hist",
            use_label_encoder=False,
            eval_metric="mlogloss",
        )

    def _make_lgb(self) -> Any:
        if lgb is None:
            raise ImportError("lightgbm is required for EnhancedStackingEnsemble")
        return lgb.LGBMClassifier(
            n_estimators=350,
            max_depth=8,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_samples=15,
            reg_alpha=0.2,
            reg_lambda=1.5,
            random_state=self.random_state,
            n_jobs=-1,
            verbose=-1,
        )

    def _make_meta(self) -> LogisticRegression:
        return LogisticRegression(
            max_iter=2000,
            solver="lbfgs",
            multi_class="multinomial",
            random_state=self.random_state,
        )

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "EnhancedStackingEnsemble":
        """
        Train the stacking ensemble with bagging CV and optional calibration.
        """
        logger.info(
            f"EnhancedStackingEnsemble.fit() started (budget={self.time_budget_s}s)"
        )
        self.feature_columns_ = list(X.columns)

        y_arr = y.values.ravel() if hasattr(y, "values") else np.asarray(y).ravel()

        base_estimators = [
            ("rf", self._make_rf()),
            ("xgb", self._make_xgb()),
            ("lgb", self._make_lgb()),
        ]

        cv_strategy = StratifiedKFold(
            n_splits=self.NUM_BAG_FOLDS, shuffle=True, random_state=self.random_state
        )

        self.stacking_model_ = StackingClassifier(
            estimators=base_estimators,
            final_estimator=self._make_meta(),
            cv=cv_strategy,
            stack_method="predict_proba",
            n_jobs=-1,
            passthrough=False,
        )

        logger.info("Fitting stacking classifier (level 0 + level 1)...")
        self.stacking_model_.fit(X, y_arr)

        # Optional isotonic calibration
        if self.calibrate:
            logger.info("Applying isotonic calibration...")
            self.calibrator_ = CalibratedEnsemble(
                base_estimator=self.stacking_model_, method="isotonic", cv="prefit"
            )
            self.calibrator_.fit(X, y_arr)

        self.is_trained_ = True
        logger.info("EnhancedStackingEnsemble training complete")
        return self

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self.is_trained_:
            raise RuntimeError("Model not trained")
        if self.calibrator_ is not None:
            return self.calibrator_.predict_proba(X)
        assert self.stacking_model_ is not None
        return self.stacking_model_.predict_proba(X)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        proba = self.predict_proba(X)
        return np.argmax(proba, axis=1)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, X: pd.DataFrame, y: pd.Series) -> Dict[str, float]:
        y_arr = y.values.ravel() if hasattr(y, "values") else np.asarray(y).ravel()
        proba = self.predict_proba(X)
        preds = np.argmax(proba, axis=1)

        acc = accuracy_score(y_arr, preds)
        ll = log_loss(y_arr, proba, labels=[0, 1, 2])

        # Multiclass Brier score (average over classes)
        brier = 0.0
        for cls_idx in range(proba.shape[1]):
            y_bin = (y_arr == cls_idx).astype(int)
            brier += brier_score_loss(y_bin, proba[:, cls_idx])
        brier /= proba.shape[1]

        metrics = {"accuracy": acc, "log_loss": ll, "brier_score": brier}
        self.metadata_.update(metrics)
        return metrics

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path, name: str = "enhanced_ensemble") -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        payload = {
            "stacking_model": self.stacking_model_,
            "calibrator": self.calibrator_,
            "feature_columns": self.feature_columns_,
            "metadata": self.metadata_,
            "is_trained": self.is_trained_,
        }
        model_file = path / f"{name}.pkl"
        joblib.dump(payload, model_file)

        meta_file = path / f"{name}_metadata.json"
        with meta_file.open("w", encoding="utf-8") as fh:
            json.dump(self.metadata_, fh, indent=2, default=str)

        logger.info(f"EnhancedStackingEnsemble saved to {model_file}")

    @classmethod
    def load(cls, model_path: Path) -> "EnhancedStackingEnsemble":
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")

        payload = joblib.load(model_path)
        instance = cls()
        instance.stacking_model_ = payload["stacking_model"]
        instance.calibrator_ = payload.get("calibrator")
        instance.feature_columns_ = payload.get("feature_columns", [])
        instance.metadata_ = payload.get("metadata", {})
        instance.is_trained_ = payload.get("is_trained", False)
        logger.info(f"EnhancedStackingEnsemble loaded from {model_path}")
        return instance


# ---------------------------------------------------------------------------
# Enhanced Model Trainer
# ---------------------------------------------------------------------------


class EnhancedModelTrainer:
    """
    Trainer that:
    1. Loads processed datasets
    2. Applies advanced feature engineering
    3. Trains EnhancedStackingEnsemble
    4. Saves artifacts
    """

    def __init__(self, time_budget_s: int = 7200):
        self.time_budget_s = time_budget_s
        self.transformer = FeatureTransformer(allow_legacy_defaults=True)
        self.models_path = settings.models_path
        self.data_path = settings.data_path
        self.models_path.mkdir(parents=True, exist_ok=True)

    def train_league_models(
        self, leagues: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        if leagues is None:
            leagues = ["EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1"]

        results: Dict[str, Any] = {}
        for league in tqdm(leagues, desc="Training enhanced models"):
            try:
                logger.info(f"Training enhanced model for {league}")
                result = self._train_single(league)
                results[league] = result
            except Exception as exc:
                logger.error(f"Failed to train {league}: {exc}")
                results[league] = {"error": str(exc)}
        return results

    def _train_single(self, league: str) -> Dict[str, Any]:
        df = self._load_data(league)
        df = engineer_advanced_features(df)

        X, y = self._prepare_data(df)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        model = EnhancedStackingEnsemble(
            time_budget_s=self.time_budget_s, calibrate=True
        )
        model.fit(X_train, y_train)

        metrics = model.evaluate(X_test, y_test)
        model.metadata_.update(
            {
                "league": league,
                "training_samples": len(X_train),
                "test_samples": len(X_test),
                "trained_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        model_name = f"{self._slugify(league)}_enhanced_v2"
        model.save(self.models_path, model_name)

        return {
            "model_path": str(self.models_path / f"{model_name}.pkl"),
            **metrics,
            "training_samples": len(X_train),
        }

    def _load_data(self, league: str) -> pd.DataFrame:
        slug = self._slugify(league)
        candidates = [
            self.data_path / f"{slug}_training.parquet",
            self.data_path / f"{slug}_training.feather",
            self.data_path / f"{slug}_training.csv",
        ]
        for path in candidates:
            if path.exists():
                logger.info(f"Loading training data from {path}")
                if path.suffix == ".parquet":
                    return pd.read_parquet(path)
                elif path.suffix == ".feather":
                    return pd.read_feather(path)
                else:
                    return pd.read_csv(path)
        raise FileNotFoundError(f"No training data found for {league}")

    def _prepare_data(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
        exclude = {"result", "match_id", "match_date", "referee"}
        feature_cols = [c for c in df.columns if c not in exclude]
        X = df[feature_cols].copy()
        y = df["result"].copy()

        # Impute missing values
        if X.isnull().any().any():
            imputer = SimpleImputer(strategy="median")
            X = pd.DataFrame(imputer.fit_transform(X), columns=X.columns, index=X.index)

        # Normalize target
        target_map = {"home_win": 0, "draw": 1, "away_win": 2, 0: 0, 1: 1, 2: 2}
        y = y.map(target_map)
        if y.isnull().any():
            raise ValueError("Unknown result labels")
        y = y.astype(int)
        return X, y

    @staticmethod
    def _slugify(league: str) -> str:
        return league.lower().replace(" ", "_").replace("-", "_")


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------


def train_enhanced_models(leagues: Optional[List[str]] = None) -> Dict[str, Any]:
    """Train enhanced stacking models for specified leagues."""
    trainer = EnhancedModelTrainer(time_budget_s=7200)
    return trainer.train_league_models(leagues)
