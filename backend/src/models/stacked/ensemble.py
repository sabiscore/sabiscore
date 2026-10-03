"""Stacked Machine Learning Ensemble with Walk-Forward Validation.

Combines XGBoost and LightGBM base models stacked via a Logistic Regression
meta-learner to output calibrated 3-class match probabilities (Home, Draw, Away).
Supports chronological walk-forward splitting and direct-memory referencing to
comply with strict RAM ceilings (8GB–16GB limit).
"""

from __future__ import annotations

import gc
import logging
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
import xgboost as xgb

from .data_staging import StagedDataset

logger = logging.getLogger(__name__)


@dataclass
class StackedEnsembleArtifacts:
    """Trained stacked ensemble models and metadata."""

    xgb_model: xgb.Booster | xgb.XGBClassifier
    lgb_model: lgb.Booster | lgb.LGBMClassifier
    meta_learner: LogisticRegression
    feature_names: list[str]
    training_seasons: list[str]
    is_fitted: bool = False


@dataclass
class WalkForwardEvaluationResult:
    """Results from chronological walk-forward cross-validation."""

    seasons: list[str]
    fold_log_loss: list[float]
    fold_accuracy: list[float]
    meta_weights: np.ndarray
    final_artifacts: StackedEnsembleArtifacts

    @property
    def fold_losses(self) -> list[float]:
        return self.fold_log_loss


class StackedMatchEnsemble:
    """Memory-efficient stacked ensemble (XGBoost + LightGBM + LogisticRegression)."""

    def __init__(
        self,
        xgb_params: dict[str, Any] | None = None,
        lgb_params: dict[str, Any] | None = None,
        meta_c: float = 1.0,
    ) -> None:
        self.xgb_params = xgb_params or {
            "objective": "multi:softprob",
            "num_class": 3,
            "eval_metric": "mlogloss",
            "learning_rate": 0.05,
            "max_depth": 5,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "tree_method": "hist",
            "seed": 42,
        }
        self.lgb_params = lgb_params or {
            "objective": "multiclass",
            "num_class": 3,
            "metric": "multi_logloss",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "verbose": -1,
            "seed": 42,
        }
        self.meta_c = meta_c

        self.xgb_model: xgb.Booster | None = None
        self.lgb_model: lgb.Booster | None = None
        self.meta_learner: LogisticRegression = LogisticRegression(
            C=self.meta_c,
            max_iter=1000,
            solver="lbfgs",
            random_state=42,
        )
        self.feature_names: list[str] = []
        self.is_fitted: bool = False

    def _fit_base_models(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        num_boost_round: int = 150,
    ) -> tuple[xgb.Booster, lgb.Booster]:
        """Fit XGBoost and LightGBM using direct memory references."""
        # XGBoost DMatrix creation with direct memory pointer
        dtrain_xgb = xgb.DMatrix(X_train, label=y_train)
        evallist_xgb = [(dtrain_xgb, "train")]
        if X_val is not None and y_val is not None:
            dval_xgb = xgb.DMatrix(X_val, label=y_val)
            evallist_xgb.append((dval_xgb, "val"))

        xgb_booster = xgb.train(
            self.xgb_params,
            dtrain_xgb,
            num_boost_round=num_boost_round,
            evals=evallist_xgb,
            verbose_eval=False,
        )
        del dtrain_xgb
        gc.collect()

        # LightGBM Dataset creation with direct reference
        dtrain_lgb = lgb.Dataset(X_train, label=y_train, free_raw_data=True)
        valid_sets_lgb = [dtrain_lgb]
        if X_val is not None and y_val is not None:
            dval_lgb = lgb.Dataset(X_val, label=y_val, reference=dtrain_lgb, free_raw_data=True)
            valid_sets_lgb.append(dval_lgb)

        lgb_booster = lgb.train(
            self.lgb_params,
            dtrain_lgb,
            num_boost_round=num_boost_round,
            valid_sets=valid_sets_lgb,
            callbacks=[lgb.log_evaluation(period=0)],
        )
        del dtrain_lgb
        gc.collect()

        return xgb_booster, lgb_booster

    def _create_meta_features(
        self,
        X: np.ndarray,
        xgb_booster: xgb.Booster,
        lgb_booster: lgb.Booster,
    ) -> np.ndarray:
        """Generate concatenated meta-feature probabilities [xgb_probs (3), lgb_probs (3)]."""
        dx = xgb.DMatrix(X)
        xgb_preds = xgb_booster.predict(dx)  # shape (N, 3)
        lgb_preds = lgb_booster.predict(X)  # shape (N, 3)
        del dx
        gc.collect()

        # Concatenate base predictions into 6-dimensional meta-features
        meta_features = np.hstack([xgb_preds, lgb_preds])
        return np.ascontiguousarray(meta_features, dtype=np.float32)

    def train_walk_forward(
        self,
        dataset: StagedDataset,
        num_splits: int = 4,
        num_boost_round: int = 150,
    ) -> WalkForwardEvaluationResult:
        """Perform chronological walk-forward cross-validation and fit the final stacked model.

        Mimics live betting conditions with expanding-window chronological splits.

        Args:
            dataset: StagedDataset containing features X and targets y.
            num_splits: Number of time-series folds for expanding-window splits.
            num_boost_round: Boosting iterations for base trees.

        Returns:
            WalkForwardEvaluationResult containing fold metrics and trained artifacts.
        """
        X = dataset.X
        y = dataset.y
        self.feature_names = list(dataset.feature_names)
        n_samples = len(X)

        if n_samples < 50:
            raise ValueError(f"Insufficient samples ({n_samples}) for walk-forward validation.")

        tscv = TimeSeriesSplit(n_splits=num_splits)
        fold_losses: list[float] = []
        fold_accs: list[float] = []

        # Out-of-fold meta-features for fitting the final meta-learner
        oof_meta_X: list[np.ndarray] = []
        oof_meta_y: list[np.ndarray] = []

        logger.info("Executing %d-fold chronological walk-forward validation...", num_splits)

        for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
            X_tr, y_tr = X[train_idx], y[train_idx]
            X_va, y_val = X[val_idx], y[val_idx]

            fold_xgb, fold_lgb = self._fit_base_models(
                X_train=X_tr,
                y_train=y_tr,
                X_val=X_va,
                y_val=y_val,
                num_boost_round=num_boost_round,
            )

            # Generate meta-features for validation fold
            val_meta_X = self._create_meta_features(X_va, fold_xgb, fold_lgb)
            oof_meta_X.append(val_meta_X)
            oof_meta_y.append(y_val)

            # Local fold evaluation with simple average
            blended_probs = 0.5 * (val_meta_X[:, :3] + val_meta_X[:, 3:])
            pred_classes = np.argmax(blended_probs, axis=1)
            acc = float(np.mean(pred_classes == y_val))
            eps = 1e-15
            clipped_probs = np.clip(blended_probs, eps, 1.0 - eps)
            norm_probs = clipped_probs / clipped_probs.sum(axis=1, keepdims=True)
            logloss = -float(np.mean(np.log(norm_probs[np.arange(len(y_val)), y_val])))

            fold_accs.append(acc)
            fold_losses.append(logloss)
            logger.info("Fold %d: Accuracy=%.4f, LogLoss=%.4f", fold + 1, acc, logloss)

            del X_tr, y_tr, X_va, y_val, fold_xgb, fold_lgb
            gc.collect()

        # Concatenate out-of-fold meta-features and fit the Logistic Regression meta-learner
        full_oof_X = np.vstack(oof_meta_X)
        full_oof_y = np.concatenate(oof_meta_y)

        logger.info("Fitting Logistic Regression meta-learner on %d OOF samples...", len(full_oof_X))
        self.meta_learner.fit(full_oof_X, full_oof_y)

        # Train final base models on the entire dataset
        logger.info("Training final base models on full historical dataset (%d samples)...", n_samples)
        self.xgb_model, self.lgb_model = self._fit_base_models(
            X_train=X,
            y_train=y,
            num_boost_round=num_boost_round,
        )
        self.is_fitted = True

        artifacts = StackedEnsembleArtifacts(
            xgb_model=self.xgb_model,
            lgb_model=self.lgb_model,
            meta_learner=self.meta_learner,
            feature_names=self.feature_names,
            training_seasons=sorted(dataset.metadata["season"].dropna().unique().tolist())
            if not dataset.metadata.empty and "season" in dataset.metadata
            else [],
            is_fitted=True,
        )

        return WalkForwardEvaluationResult(
            seasons=artifacts.training_seasons,
            fold_log_loss=fold_losses,
            fold_accuracy=fold_accs,
            meta_weights=self.meta_learner.coef_,
            final_artifacts=artifacts,
        )

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict calibrated 3-class probabilities [Home, Draw, Away].

        Args:
            X: Pre-match feature matrix with shape (N, num_features).

        Returns:
            Probability matrix with shape (N, 3), strictly forming a valid probability simplex.
        """
        if not self.is_fitted or self.xgb_model is None or self.lgb_model is None:
            raise RuntimeError("Ensemble is not fitted. Call train_walk_forward first.")

        # Create meta-features
        meta_X = self._create_meta_features(X, self.xgb_model, self.lgb_model)

        # Output probabilities from Logistic Regression meta-learner
        probs = self.meta_learner.predict_proba(meta_X)

        # Strictly enforce probability simplex normalization: sum(p) == 1.0
        row_sums = probs.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1.0
        normalized_probs = probs / row_sums

        return np.ascontiguousarray(normalized_probs, dtype=np.float32)


__all__ = [
    "StackedMatchEnsemble",
    "StackedEnsembleArtifacts",
    "WalkForwardEvaluationResult",
]
