import pandas as pd
import joblib
import os
import json
import pickle
from typing import Dict, Any, Optional
from sklearn.base import BaseEstimator
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.tree import DecisionTreeClassifier
from sklearn.utils.class_weight import compute_sample_weight
import xgboost as xgb
import lightgbm as lgb
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class ModelLoadError(Exception):
    """Raised when a model file cannot be loaded or is invalid."""


class EnsembleModel:
    """Ensemble model combining RF, XGB, LGBM with meta-learner"""
    
    def __init__(self, optimize: bool = False):
        """Initialize ensemble with optional Optuna optimization"""
        self.optimize = optimize
        self.models = {}
        self.meta_model = None
        self.feature_columns = []
        self.model_metadata = {}
        self.is_trained = False
        self.is_v2 = False
        self.v2_model_data: Dict[str, Any] = {}
        self.v2_scaler = None
        self.v2_feature_names: list[str] = []
        # Declared here so a constructed instance and a loaded one expose the
        # same surface. `PredictionEngine.prime_cache` bridges these by
        # `getattr`, so an attribute that exists only after `load_model` would
        # make an in-memory model behave differently from a deserialized one --
        # which is the shape of the defect in `docs/DEBT.md` item 122.
        self.calibrator: Optional[Any] = None
        self.bivariate_poisson_overlay: Optional[Any] = None

    def build_ensemble(self, X: pd.DataFrame, y: pd.DataFrame) -> None:
        """Build the ensemble model"""
        try:
            logger.info("Building ensemble model...")

            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )

            # Train base models
            self._train_base_models(X_train, y_train)

            # Create meta features
            meta_features_train = self._create_meta_features(X_train)
            meta_features_test = self._create_meta_features(X_test)

            # Train meta model
            self._train_meta_model(meta_features_train, y_train, meta_features_test, y_test)

            self.is_trained = True

            # Evaluate ensemble
            self._evaluate_ensemble(X_test, y_test)

            logger.info("Ensemble model built successfully")

        except Exception as e:
            logger.error(f"Failed to build ensemble: {e}")
            raise

    def _train_base_models(self, X: pd.DataFrame, y: pd.DataFrame) -> None:
        """Train base models"""
        logger.info("Training base models...")
        y_1d = y.values.ravel()
        sample_weights = compute_sample_weight(class_weight='balanced', y=y_1d)

        # Random Forest - increased estimators for better accuracy
        rf_model = RandomForestClassifier(
            n_estimators=300,
            max_depth=12,
            min_samples_split=8,
            min_samples_leaf=4,
            max_features='sqrt',
            class_weight='balanced',
            random_state=42,
            n_jobs=-1,
            warm_start=False
        )
        rf_model.fit(X, y_1d, sample_weight=sample_weights)
        self.models['random_forest'] = rf_model

        # XGBoost - optimized for better calibration
        xgb_model = xgb.XGBClassifier(
            n_estimators=250,
            max_depth=7,
            learning_rate=0.08,
            subsample=0.85,
            colsample_bytree=0.85,
            min_child_weight=3,
            gamma=0.1,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=-1,
            tree_method='hist'
        )
        xgb_model.fit(X, y_1d, sample_weight=sample_weights)
        self.models['xgboost'] = xgb_model

        # LightGBM - fast and memory-efficient
        lgb_model = lgb.LGBMClassifier(
            n_estimators=250,
            max_depth=7,
            learning_rate=0.08,
            subsample=0.85,
            colsample_bytree=0.85,
            min_child_samples=20,
            reg_alpha=0.1,
            reg_lambda=1.0,
            class_weight='balanced',
            random_state=42,
            n_jobs=-1,
            verbose=-1
        )
        lgb_model.fit(X, y_1d, sample_weight=sample_weights)
        self.models['lightgbm'] = lgb_model

        logger.info("Base models trained")

    def _create_meta_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """Create meta features from base model predictions"""
        meta_features = pd.DataFrame()

        for model_name, model in self.models.items():
            # Get probability predictions
            probs = model.predict_proba(X)

            # For multiclass, take probability of positive class (home win)
            if probs.shape[1] > 2:
                meta_features[f'{model_name}_prob_home'] = probs[:, 0]  # Home win probability
                meta_features[f'{model_name}_prob_draw'] = probs[:, 1]  # Draw probability
                meta_features[f'{model_name}_prob_away'] = probs[:, 2]  # Away win probability
            else:
                meta_features[f'{model_name}_prob'] = probs[:, 1]

        return meta_features

    @classmethod
    def _repair_sklearn_compatibility(cls, obj: Any, seen: Optional[set[int]] = None) -> None:
        """Patch trusted legacy sklearn pickles loaded under newer sklearn versions."""
        if seen is None:
            seen = set()

        obj_id = id(obj)
        if obj_id in seen:
            return
        seen.add(obj_id)

        if isinstance(obj, DecisionTreeClassifier) and not hasattr(obj, "monotonic_cst"):
            obj.monotonic_cst = None

        if obj.__class__.__module__.startswith("sklearn.") and getattr(obj, "n_jobs", None) == -1:
            obj.n_jobs = 1

        if isinstance(obj, dict):
            children = obj.values()
        elif isinstance(obj, (list, tuple, set)):
            children = obj
        else:
            children = []
            for attr_name in ("estimators_", "models", "steps", "calibrated_classifiers_"):
                attr = getattr(obj, attr_name, None)
                if attr is not None:
                    children.append(attr)

        for child in children:
            cls._repair_sklearn_compatibility(child, seen)

    def _train_meta_model(self, X_meta: pd.DataFrame, y: pd.DataFrame,
                         X_meta_test: pd.DataFrame, y_test: pd.DataFrame) -> None:
        """Train meta model"""
        logger.info("Training meta model...")
        y_1d = y.values.ravel()
        y_test_1d = y_test.values.ravel()
        sample_weights = compute_sample_weight(class_weight='balanced', y=y_1d)

        base_lr = LogisticRegression(
            random_state=42,
            max_iter=1000,
            class_weight='balanced'
        )

        # Calibrate multiclass probabilities to reduce class-distribution overconfidence.
        self.meta_model = CalibratedClassifierCV(
            estimator=base_lr,
            method='isotonic',
            cv=5
        )

        self.meta_model.fit(X_meta, y_1d, sample_weight=sample_weights)

        # Evaluate meta model
        meta_accuracy = self.meta_model.score(X_meta_test, y_test_1d)
        logger.info(f"Meta model accuracy: {meta_accuracy:.4f}")

    def _evaluate_ensemble(self, X_test: pd.DataFrame, y_test: pd.DataFrame) -> None:
        """Evaluate ensemble performance"""
        logger.info("Evaluating ensemble...")

        # Get predictions
        predictions = self.predict(X_test)

        # Work with 1D target labels for metric calculations
        y_true = y_test['result'] if isinstance(y_test, pd.DataFrame) else y_test

        # Map predicted outcome strings back to encoded integers
        label_mapping = {'home_win': 0, 'draw': 1, 'away_win': 2}
        predicted_labels = predictions['prediction'].map(label_mapping)

        # Calculate metrics
        accuracy = accuracy_score(y_true, predicted_labels)

        # Brier score for probability calibration - use multiclass version
        # For multiclass, calculate Brier score for each class and average
        brier = 0.0
        for label_idx, prob_column in enumerate(['home_win_prob', 'draw_prob', 'away_win_prob']):
            y_binary = (y_true == label_idx).astype(int)
            probs = predictions[prob_column]
            brier += brier_score_loss(y_binary, probs)
        brier /= 3

        # Log loss (explicitly pass label ordering to match probability columns)
        logloss = log_loss(y_true, predictions[['home_win_prob', 'draw_prob', 'away_win_prob']].values, labels=[0, 1, 2])

        logger.info("Ensemble Evaluation:")
        logger.info(f"  Accuracy: {accuracy:.4f}")
        logger.info(f"  Brier Score: {brier:.4f}")
        logger.info(f"  Log Loss: {logloss:.4f}")

        self.model_metadata = {
            'accuracy': accuracy,
            'brier_score': brier,
            'log_loss': logloss,
            'trained_at': datetime.now(timezone.utc).isoformat(),
            'feature_count': len(self.feature_columns)
        }

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        """Make predictions with the ensemble"""
        if not self.is_trained:
            raise ValueError("Model not trained yet")

        try:
            # Check if using V2 model
            if getattr(self, 'is_v2', False):
                return self._predict_v2(X)
            
            # Handle missing values
            X = X.fillna(X.mean())
            
            # Ensure no NaN values remain
            if X.isnull().any().any():
                logger.warning("NaN values still present after fillna, filling with 0")
                X = X.fillna(0)
            # Get meta features
            meta_features = self._create_meta_features(X)

            # Get meta model predictions
            if self.meta_model is None:
                raise ValueError("Meta model is not initialized")
            probs = self.meta_model.predict_proba(meta_features)

            # Create results DataFrame
            results = pd.DataFrame({
                'home_win_prob': probs[:, 0],
                'draw_prob': probs[:, 1],
                'away_win_prob': probs[:, 2]
            })

            # Get prediction — use draw_threshold calibration if stored in metadata
            draw_threshold = self.model_metadata.get('draw_threshold')
            if draw_threshold is not None:
                results['prediction'] = results.apply(
                    lambda r: 'draw' if r['draw_prob'] >= draw_threshold
                    else ('home_win' if r['home_win_prob'] >= r['away_win_prob'] else 'away_win'),
                    axis=1,
                )
            else:
                results['prediction'] = results[['home_win_prob', 'draw_prob', 'away_win_prob']].idxmax(axis='columns')
                results['prediction'] = results['prediction'].map({
                    'home_win_prob': 'home_win',
                    'draw_prob': 'draw',
                    'away_win_prob': 'away_win'
                })

            # Calculate confidence
            results['confidence'] = results[['home_win_prob', 'draw_prob', 'away_win_prob']].max(axis='columns')

            return results

        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            raise
    
    def _predict_v2(self, X: pd.DataFrame) -> pd.DataFrame:
        """Make predictions using V2 production model"""
        try:
            # Get V2 model
            v2_model = self.v2_model_data.get('model')
            scaler = self.v2_scaler
            feature_names = self.v2_feature_names
            if v2_model is None:
                raise ValueError("V2 model not initialized")
            
            # Align features
            X_aligned = X.copy()
            
            # Add missing features with zeros
            for feat in feature_names:
                if feat not in X_aligned.columns:
                    X_aligned[feat] = 0
            
            # Select only the features the model expects
            X_aligned = X_aligned[feature_names] if feature_names else X_aligned
            
            # Handle missing values
            X_aligned = X_aligned.fillna(0)
            
            # Scale if scaler available
            if scaler is not None:
                X_scaled = scaler.transform(X_aligned)
            else:
                X_scaled = X_aligned.values
            
            # Get predictions
            y_pred = v2_model.predict(X_scaled)
            y_proba = v2_model.predict_proba(X_scaled)
            
            # V2 model outputs: 0=Away, 1=Draw, 2=Home
            # Create results DataFrame - note: V2 model's class order may differ
            results = pd.DataFrame({
                'away_win_prob': y_proba[:, 0],
                'draw_prob': y_proba[:, 1],
                'home_win_prob': y_proba[:, 2]
            })
            
            # Map predictions
            pred_map = {0: 'away_win', 1: 'draw', 2: 'home_win'}
            results['prediction'] = [pred_map.get(p, 'draw') for p in y_pred]
            
            # Calculate confidence
            results['confidence'] = results[['home_win_prob', 'draw_prob', 'away_win_prob']].max(axis='columns')

            logger.debug(f"V2 prediction complete: {len(results)} predictions")
            return results
            
        except Exception as e:
            logger.error(f"V2 prediction failed: {e}")
            raise

    def explain_predictions(self, X: pd.DataFrame) -> Dict[str, Any]:
        """Generate SHAP explanations via ModelExplainer on the first available base model.

        Uses a tree-based base model so SHAP TreeExplainer can attribute each of the 58
        canonical features.  Returns {} when SHAP is unavailable or the base model is
        not tree-compatible (fail-closed — callers fall back to deterministic ranking).
        """
        try:
            from .explainer import ModelExplainer

            # Prefer tree models in priority order; accept any available model
            base_model = None
            for name in ('rf', 'random_forest', 'xgb', 'xgboost', 'lgbm', 'lightgbm'):
                candidate = self.models.get(name)
                if candidate is not None:
                    base_model = candidate
                    break
            if base_model is None and self.models:
                base_model = next(iter(self.models.values()))

            if base_model is None:
                logger.warning("No base model available for SHAP explanation")
                return {}

            feature_names = (
                list(self.feature_columns)
                if self.feature_columns
                else [f"feature_{i}" for i in range(X.shape[1])]
            )

            explainer = ModelExplainer(model=base_model)
            explainer.setup_explainer(X, feature_names)
            return explainer.explain_prediction(X.iloc[[0]] if len(X) > 0 else X)

        except Exception as e:
            logger.error(f"SHAP explanation failed: {e}")
            return {}

    def save_model(self, path: str, model_name: str = "ensemble") -> None:
        """Save model to disk"""
        try:
            os.makedirs(path, exist_ok=True)

            model_data = {
                'models': self.models,
                'meta_model': self.meta_model,
                'feature_columns': self.feature_columns,
                'model_metadata': self.model_metadata,
                'is_trained': self.is_trained
            }

            model_path = os.path.join(path, f"{model_name}.pkl")
            joblib.dump(model_data, model_path)

            # Save metadata
            metadata_path = os.path.join(path, f"{model_name}_metadata.json")
            with open(metadata_path, 'w') as f:
                json.dump(self.model_metadata, f, indent=2)

            logger.info(f"Model saved to {model_path}")

        except Exception as e:
            logger.error(f"Failed to save model: {e}")
            raise

    @classmethod
    def load_model(cls, model_path: str) -> 'SabiScoreEnsemble':
        """Load model from disk"""
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")

        try:
            # Quick sanity checks before attempting to unpickle
            size = os.path.getsize(model_path)
            if size == 0:
                raise ModelLoadError(f"Model file appears empty: {model_path}")

            # Try to read a few bytes to detect obvious truncation
            with open(model_path, 'rb') as fh:
                head = fh.read(8)
                if len(head) < 4:
                    raise ModelLoadError(f"Model file too small/corrupt: {model_path}")

            # Use joblib to load; catch pickle/unpickle related errors explicitly
            model_data = joblib.load(model_path)

            instance = cls()
            instance.models = model_data['models']
            instance.meta_model = model_data['meta_model']
            instance.feature_columns = model_data.get('feature_columns', [])
            instance.model_metadata = model_data.get('model_metadata', {})
            instance.is_trained = model_data.get('is_trained', False)
            # Carried so the instance faithfully represents the artifact. This
            # loader previously copied five of the artifact's six keys, so
            # `calibrator` (and any overlay) vanished the moment an artifact was
            # loaded this way -- and this is the loader the production startup
            # path uses. `PredictionEngine.prime_cache` bridges via
            # `getattr(model, "calibrator", None)`, which silently returned None,
            # so a certified calibrator was dropped with no signal anywhere.
            # That is the same two-loader asymmetry that dropped `meta_model`
            # (item 87), one field over. See `docs/DEBT.md` item 113.
            #
            # Carrying it is safe because `PredictionEngine._wrap_artifact`
            # preflights every calibrator before admitting it; an unusable one
            # is rejected there with a logged reason rather than being applied.
            instance.calibrator = model_data.get('calibrator')
            instance.bivariate_poisson_overlay = model_data.get('bivariate_poisson_overlay')
            cls._repair_sklearn_compatibility(instance.models)
            cls._repair_sklearn_compatibility(instance.meta_model)

            logger.info(f"Model loaded from {model_path}")
            return instance

        except (EOFError, pickle.UnpicklingError, IndexError, TypeError) as e:
            # These are commonly raised when the file is truncated or corrupt
            logger.exception(f"Failed to unpickle model file {model_path}: {e}")
            raise ModelLoadError(f"Failed to unpickle model file {model_path}: {e}") from e
        except Exception as e:
            # Convert to a more specific exception so callers can handle
            logger.exception(f"Failed to load model file {model_path}: {e}")
            raise ModelLoadError(f"Failed to load model file {model_path}: {e}") from e

    @classmethod
    def load_latest_model(cls, models_path: str) -> 'SabiScoreEnsemble':
        """Load the latest trained model - supports both V2 (joblib) and legacy (pkl) formats"""
        # Validate path
        if not os.path.exists(models_path) or not os.path.isdir(models_path):
            raise FileNotFoundError(f"Models path not found or is not a directory: {models_path}")

        # First, check for V2 production model (highest priority)
        v2_model_path = os.path.join(models_path, "sabiscore_production_v2.joblib")
        if os.path.exists(v2_model_path):
            try:
                size = os.path.getsize(v2_model_path)
                if size > 10_240:  # At least 10KB
                    logger.info(f"Loading V2 production model from {v2_model_path}")
                    return cls._load_v2_model(v2_model_path)
            except Exception as e:
                logger.warning(f"Failed to load V2 model: {e}, falling back to legacy models")

        # Find candidate model files (newest first)
        model_files = [f for f in os.listdir(models_path) if f.endswith('.pkl')]
        if not model_files:
            raise FileNotFoundError(f"No model files found in {models_path}")

        model_files.sort(key=lambda x: os.path.getmtime(os.path.join(models_path, x)), reverse=True)

        last_exc: Optional[Exception] = None

        for candidate in model_files:
            model_path = os.path.join(models_path, candidate)
            try:
                size = os.path.getsize(model_path)
            except OSError:
                logger.warning(f"Could not stat model file {model_path}, skipping")
                continue

            # Skip obviously tiny files (likely incomplete uploads)
            if size < 10_240:  # 10KB
                logger.warning(f"Skipping candidate {candidate} (size={size} bytes) - too small to be a valid model")
                continue

            try:
                logger.info(f"Attempting to load model candidate: {model_path}")
                return cls.load_model(model_path)
            except ModelLoadError as mle:
                # Log and try next candidate
                logger.warning(f"Model candidate {candidate} is invalid: {mle}")
                last_exc = mle
            except Exception as e:
                logger.exception(f"Unexpected error loading model candidate {candidate}: {e}")
                last_exc = e

        # If we get here, no candidates succeeded
        msg = f"No valid model files found in {models_path}. Tried: {model_files}"
        logger.error(msg)
        if last_exc:
            raise RuntimeError(msg) from last_exc
        raise RuntimeError(msg)
    
    @classmethod
    def _load_v2_model(cls, model_path: str) -> 'EnsembleModel':
        """Load V2 production model (stacked ensemble format)"""
        try:
            save_data = joblib.load(model_path)
            
            instance = cls()
            instance.v2_model_data = save_data  # Store raw V2 data
            instance.models = {'v2_ensemble': save_data.get('model')}  # Wrap in dict for compatibility
            instance.meta_model = save_data.get('model')  # V2 model acts as meta-learner
            instance.feature_columns = save_data.get('feature_names', [])
            instance.model_metadata = {
                'model_name': save_data.get('model_name', 'sabiscore_production_v2'),
                'training_metrics': save_data.get('training_metrics', {}),
                'version': 'v2',
                'trained_at': save_data.get('trained_at', datetime.now(timezone.utc).isoformat())
            }
            instance.is_trained = True
            instance.is_v2 = True
            instance.v2_scaler = save_data.get('scaler')
            instance.v2_feature_names = save_data.get('feature_names', [])
            cls._repair_sklearn_compatibility(instance.models)
            cls._repair_sklearn_compatibility(instance.meta_model)
            
            logger.info(f"V2 production model loaded successfully from {model_path}")
            logger.info(f"Features: {len(instance.feature_columns)}")
            if 'training_metrics' in save_data:
                tm = save_data['training_metrics']
                logger.info(f"CV Accuracy: {tm.get('cv_accuracy_mean', 'N/A'):.4f}")
            
            return instance
            
        except Exception as e:
            logger.exception(f"Failed to load V2 model: {e}")
            raise ModelLoadError(f"Failed to load V2 model from {model_path}: {e}") from e


# Backward compatibility alias
SabiScoreEnsemble = EnsembleModel



class LogOddsResidualWrapper(BaseEstimator):
    def __init__(self, base_estimator):
        self.base_estimator = base_estimator
        self.classes_ = getattr(base_estimator, 'classes_', [0, 1, 2])

    def _get_base_margin(self, X):
        import numpy as np
        X_arr = np.asarray(X)
        from src.models.feature_registry import CANONICAL_FEATURES_68
        try:
            idx_loh = CANONICAL_FEATURES_68.index("log_odds_home")
            idx_lod = CANONICAL_FEATURES_68.index("log_odds_draw")
            idx_loa = CANONICAL_FEATURES_68.index("log_odds_away")
            log_odds = X_arr[:, [idx_loh, idx_lod, idx_loa]]
            raw_odds = np.exp(log_odds)
            from src.models.evaluation.market_baseline import shin_devig
            base_margins = []
            for odds in raw_odds:
                try:
                    p = shin_devig(tuple(odds)).fair_probs
                except Exception:
                    p = (0.333, 0.333, 0.334)
                # Clip to prevent log(0) and ensure valid simplex limits
                p = np.clip(p, 1e-6, 1.0 - 1e-6)
                p = p / np.sum(p)
                base_margins.append(np.log(p))
            return np.array(base_margins)
        except ValueError:
            # If log odds features are missing, return 0 margins
            return np.zeros((X.shape[0], 3))

    def fit(self, X, y, **kwargs):
        base_margin = self._get_base_margin(X)
        
        # XGBoost
        if hasattr(self.base_estimator, 'fit') and 'xgboost' in type(self.base_estimator).__module__:
            self.base_estimator.fit(X, y, base_margin=base_margin, **kwargs)
        # LightGBM
        elif hasattr(self.base_estimator, 'fit') and 'lightgbm' in type(self.base_estimator).__module__:
            self.base_estimator.fit(X, y, init_score=base_margin, **kwargs)
        # LogisticRegression / others not supporting base_margin natively
        else:
            self.base_estimator.fit(X, y, **kwargs)
            
        self.classes_ = getattr(self.base_estimator, 'classes_', [0, 1, 2])
        return self

    def predict_proba(self, X):
        from scipy.special import softmax
        base_margin = self._get_base_margin(X)
        
        # XGBoost
        if hasattr(self.base_estimator, 'predict_proba') and 'xgboost' in type(self.base_estimator).__module__:
            return self.base_estimator.predict_proba(X, base_margin=base_margin)
            
        # LightGBM
        elif hasattr(self.base_estimator, 'predict') and 'lightgbm' in type(self.base_estimator).__module__:
            # LightGBM predict_proba does not accept init_score/base_margin.
            # We must get raw scores, add base margin, and softmax.
            raw_preds = self.base_estimator.predict(X, raw_score=True)
            return softmax(raw_preds + base_margin, axis=1)
            
        # Fallback
        else:
            return self.base_estimator.predict_proba(X)
