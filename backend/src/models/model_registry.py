"""
Model Registry with MLflow Integration
Manages model versioning, tracking, and deployment lifecycle
"""

import importlib
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd

from ..core.redaction import redact_text

logger = logging.getLogger(__name__)


def _load_mlflow() -> Any | None:
    """Import MLflow only when experiment tracking is explicitly configured.

    Settlement validation imports this module in the API process. Eagerly importing
    MLflow adds a large optional dependency tree to that hot path even when tracking
    is disabled, and import-time warnings made an optional training component look
    like a production readiness failure.
    """

    try:
        module = importlib.import_module("mlflow")
        importlib.import_module("mlflow.sklearn")
        return module
    except ImportError:
        return None


class ModelRegistry:
    """
    Centralized model registry for versioning and tracking
    
    Features:
    - Model versioning with semantic versioning
    - Performance metrics tracking
    - Model comparison and rollback
    - MLflow integration for experiment tracking
    - Read-only production lookup; release-manifest promotion is external
    """
    
    def __init__(
        self, 
        registry_path: str,
        mlflow_tracking_uri: Optional[str] = None,
        experiment_name: str = "SabiScore_Ensemble"
    ):
        """
        Initialize Model Registry
        
        Args:
            registry_path: Local directory for model storage
            mlflow_tracking_uri: MLflow tracking server URI
            experiment_name: MLflow experiment name
        """
        self.registry_path = Path(registry_path)
        self.registry_path.mkdir(parents=True, exist_ok=True)
        
        self.metadata_path = self.registry_path / "metadata.json"
        self.models_dir = self.registry_path / "models"
        self.models_dir.mkdir(exist_ok=True)
        
        # MLflow is offline/research observability only. The committed active-
        # generation manifest remains the sole production promotion authority.
        self._mlflow = None
        self.mlflow_enabled = False
        if mlflow_tracking_uri:
            self._mlflow = _load_mlflow()
            if self._mlflow is None:
                logger.warning("MLflow tracking requested but the optional package is unavailable")
            else:
                self._mlflow.set_tracking_uri(mlflow_tracking_uri)
                self._mlflow.set_experiment(experiment_name)
                self.mlflow_enabled = True
                # Never log the URI: it may contain userinfo, tokens, or signed query data.
                logger.info("MLflow experiment tracking enabled")
        else:
            logger.debug("MLflow tracking disabled; using local research registry only")
        
        # Load or initialize registry metadata
        self.metadata = self._load_metadata()
    
    def _load_metadata(self) -> Dict[str, Any]:
        """Load registry metadata from disk"""
        if self.metadata_path.exists():
            with open(self.metadata_path, 'r') as f:
                return json.load(f)
        
        return {
            'models': {},
            'production_model': None,
            'staging_model': None
        }
    
    def _save_metadata(self) -> None:
        """Save registry metadata to disk"""
        with open(self.metadata_path, 'w') as f:
            json.dump(self.metadata, f, indent=2)
    
    def register_model(
        self,
        model: Any,
        model_name: str,
        model_version: str,
        metrics: Dict[str, float],
        params: Dict[str, Any],
        tags: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Register a new model version
        
        Args:
            model: Trained model object
            model_name: Model identifier
            model_version: Semantic version string (e.g., "1.0.0")
            metrics: Performance metrics (accuracy, brier_score, etc.)
            params: Model hyperparameters
            tags: Optional metadata tags
            
        Returns:
            Model ID (name + version)
        """
        model_id = f"{model_name}_v{model_version}"
        model_path = self.models_dir / f"{model_id}.pkl"
        
        try:
            # Save model locally
            joblib.dump(model, model_path)
            logger.info(f"Model saved locally: {model_path}")
            
            # Update registry metadata
            self.metadata['models'][model_id] = {
                'model_name': model_name,
                'model_version': model_version,
                'model_path': str(model_path),
                'metrics': metrics,
                'params': params,
                'tags': tags or {},
                'registered_at': datetime.now(timezone.utc).isoformat(),
                'status': 'staging'  # Default to staging
            }
            self._save_metadata()
            
            # MLflow tracking
            if self.mlflow_enabled and self._mlflow is not None:
                with self._mlflow.start_run(run_name=model_id):
                    # Log parameters
                    self._mlflow.log_params(params)
                    
                    # Log metrics
                    self._mlflow.log_metrics(metrics)
                    
                    # Log tags
                    if tags:
                        self._mlflow.set_tags(tags)
                    
                    # Log model
                    self._mlflow.sklearn.log_model(model, "model")
                    
                    logger.info(f"Model logged to MLflow: {model_id}")
            
            return model_id
            
        except Exception as e:
            logger.error("Failed to register model %s: %s", model_id, redact_text(e))
            raise
    
    def get_model(self, model_id: str) -> Any:
        """
        Load a registered model
        
        Args:
            model_id: Model identifier (name + version)
            
        Returns:
            Loaded model object
        """
        if model_id not in self.metadata['models']:
            raise ValueError(f"Model {model_id} not found in registry")
        
        model_path = Path(self.metadata['models'][model_id]['model_path'])
        
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")
        
        return joblib.load(model_path)
    
    def get_production_model(self) -> Optional[Any]:
        """
        Get the current production model
        
        Returns:
            Production model or None if not set
        """
        prod_id = self.metadata.get('production_model')
        
        if not prod_id:
            logger.warning("No production model set")
            return None
        
        return self.get_model(prod_id)
    
    def promote_to_production(self, model_id: str) -> None:
        """Reject local-registry promotion outside the active-generation release.

        MLflow and this registry may record research or shadow candidates, but a
        mutable metadata.json file cannot atomically promote the artifact/metadata
        set consumed by both production loaders. Promotion must update the committed
        hash-validated active-generation manifest in a reviewed release commit.
        """

        raise RuntimeError(
            "Local ModelRegistry promotion is disabled; promote the complete "
            "hash-validated active generation through the release workflow"
        )
    
    def compare_models(
        self,
        model_ids: List[str],
        metric: str = 'rps'
    ) -> pd.DataFrame:
        """
        Compare performance metrics across models
        
        Args:
            model_ids: List of model IDs to compare
            metric: Primary metric for ranking
            
        Returns:
            DataFrame with comparison results
        """
        comparison = []
        
        for model_id in model_ids:
            if model_id not in self.metadata['models']:
                logger.warning(f"Model {model_id} not found, skipping")
                continue
            
            model_info = self.metadata['models'][model_id]
            comparison.append({
                'model_id': model_id,
                'model_name': model_info['model_name'],
                'version': model_info['model_version'],
                'status': model_info['status'],
                **model_info['metrics'],
                'registered_at': model_info['registered_at']
            })
        
        df = pd.DataFrame(comparison)
        
        if not df.empty and metric in df.columns:
            # rps is minimised (lower = better); all other metrics are maximised
            df = df.sort_values(by=metric, ascending=(metric == "rps"))
        
        return df
    
    def list_models(
        self, 
        status: Optional[str] = None
    ) -> List[str]:
        """
        List all registered models
        
        Args:
            status: Filter by status ('production', 'staging', 'archived')
            
        Returns:
            List of model IDs
        """
        models = []
        
        for model_id, info in self.metadata['models'].items():
            if status is None or info['status'] == status:
                models.append(model_id)
        
        return models
    
    def get_model_info(self, model_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a model
        
        Args:
            model_id: Model identifier
            
        Returns:
            Model metadata dictionary
        """
        if model_id not in self.metadata['models']:
            raise ValueError(f"Model {model_id} not found")
        
        return self.metadata['models'][model_id]
    
    def archive_model(self, model_id: str) -> None:
        """
        Archive a model (keep metadata, remove from active use)
        
        Args:
            model_id: Model to archive
        """
        if model_id not in self.metadata['models']:
            raise ValueError(f"Model {model_id} not found")
        
        if self.metadata.get('production_model') == model_id:
            raise ValueError("Cannot archive production model. Promote another model first.")
        
        self.metadata['models'][model_id]['status'] = 'archived'
        self.metadata['models'][model_id]['archived_at'] = datetime.now(timezone.utc).isoformat()

        self._save_metadata()
        logger.info(f"Model {model_id} archived")

    def walk_forward_validate(
        self,
        records: List[Dict[str, Any]],
        n_splits: int = 5,
    ) -> Dict[str, Any]:
        """Temporal walk-forward RPS validation.

        Args:
            records: List of dicts with keys: ``date`` (ISO str), ``outcome``
                (0=home_win, 1=draw, 2=away_win), ``probs`` (3-element list
                [p_home, p_draw, p_away]). Must be sorted chronologically or
                this method will sort them.
            n_splits: Number of temporal folds (train+test windows).

        Returns:
            Dict with per-fold and aggregate RPS, plus validation metadata.
            Returns an empty result (``{"skipped": True}``) when fewer than
            ``n_splits * 2`` records are available.
        """
        try:
            from .evaluation.metrics import brier_score_decomposition, ranked_probability_score
        except ImportError:
            logger.warning("ranked_probability_score not available; walk-forward skipped")
            return {"skipped": True, "reason": "metrics module unavailable"}

        if not records:
            return {"skipped": True, "reason": "no_records"}

        sorted_records = sorted(records, key=lambda r: r.get("date", ""))
        n = len(sorted_records)
        min_records = n_splits * 2
        if n < min_records:
            return {"skipped": True, "reason": f"need >= {min_records} records, got {n}"}

        fold_size = n // (n_splits + 1)
        fold_results: List[Dict[str, Any]] = []
        # Pooled across every fold's validated records, for the Brier decomposition
        # below — a per-fold decomposition would fragment an already-thin sample
        # across bins the same way rps_overall avoids by scoring folds separately
        # but reporting one aggregate.
        pooled_outcomes: List[int] = []
        pooled_probs: List[List[float]] = []

        for fold in range(n_splits):
            train_end = (fold + 1) * fold_size
            test_start = train_end
            test_end = min(test_start + fold_size, n)
            test_records = sorted_records[test_start:test_end]

            if not test_records:
                continue

            rps_scores = []
            brier_scores = []
            correct = 0
            for rec in test_records:
                outcome = rec.get("outcome")
                probs = rec.get("probs", [])
                if outcome is None or len(probs) != 3:
                    continue
                try:
                    outcome_index = int(outcome)
                    probabilities = [float(probability) for probability in probs]
                except (TypeError, ValueError):
                    continue

                if outcome_index not in (0, 1, 2):
                    continue
                if any(not math.isfinite(probability) for probability in probabilities):
                    continue
                if any(probability < 0.0 or probability > 1.0 for probability in probabilities):
                    continue
                if not math.isclose(sum(probabilities), 1.0, rel_tol=0.0, abs_tol=1e-6):
                    continue

                rps_scores.append(ranked_probability_score(outcome_index, probabilities))
                # Multi-category Brier score (Brier 1950): sum of squared errors
                # against the one-hot outcome vector. Distinct from RPS (which
                # credits distance along the ordered outcome axis) — this is the
                # metric brier_score_decomposition() below breaks into
                # reliability/resolution/uncertainty.
                one_hot = [1.0 if outcome_index == i else 0.0 for i in range(3)]
                brier_scores.append(
                    sum((p - t) ** 2 for p, t in zip(probabilities, one_hot))
                )
                pooled_outcomes.append(outcome_index)
                pooled_probs.append(probabilities)
                # Top-class hit rate, scored over the same validated records as RPS so the
                # two metrics can never describe different populations. RPS stays the
                # primary scoring rule (it credits distance, not just the argmax); accuracy
                # is carried because it is the number a reader understands without a
                # glossary. Ties resolve to the first max — deterministic, and only
                # reachable on an exactly-uniform vector, which a real model does not emit.
                if probabilities.index(max(probabilities)) == outcome_index:
                    correct += 1

            if not rps_scores:
                continue

            fold_results.append({
                "fold": fold,
                "train_end_idx": train_end,
                "test_size": len(rps_scores),
                "rps_mean": sum(rps_scores) / len(rps_scores),
                "rps_min": min(rps_scores),
                "rps_max": max(rps_scores),
                "brier_mean": sum(brier_scores) / len(brier_scores),
                "accuracy": correct / len(rps_scores),
                "date_range": {
                    "from": test_records[0].get("date"),
                    "to": test_records[-1].get("date"),
                },
            })

        if not fold_results:
            return {"skipped": True, "reason": "no_valid_folds"}

        all_rps = [f["rps_mean"] for f in fold_results]
        all_brier = [f["brier_mean"] for f in fold_results]
        all_accuracy = [f["accuracy"] for f in fold_results]

        # Diagnostic layer, not a promotion gate (RPS keeps that role): needs its
        # own floor, since binning below ~10 pooled records is not meaningful even
        # when enough records existed to form RPS folds.
        MIN_RECORDS_FOR_DECOMPOSITION = 10
        if len(pooled_outcomes) >= MIN_RECORDS_FOR_DECOMPOSITION:
            brier_decomposition = brier_score_decomposition(
                np.array(pooled_outcomes), np.array(pooled_probs)
            )
        else:
            brier_decomposition = {
                "skipped": True,
                "reason": (
                    f"need >= {MIN_RECORDS_FOR_DECOMPOSITION} pooled validated records, "
                    f"got {len(pooled_outcomes)}"
                ),
            }

        return {
            "skipped": False,
            "n_splits": len(fold_results),
            "total_records": n,
            "rps_overall": sum(all_rps) / len(all_rps),
            "rps_std": float(pd.Series(all_rps).std()) if len(all_rps) > 1 else 0.0,
            # Mean of fold means, matching rps_overall's convention rather than
            # introducing a second aggregation rule in the same payload.
            "accuracy_overall": sum(all_accuracy) / len(all_accuracy),
            "brier_overall": sum(all_brier) / len(all_brier),
            "brier_decomposition": brier_decomposition,
            "folds": fold_results,
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }
