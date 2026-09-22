import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

from .ensemble import SabiScoreEnsemble
from .pipeline import ChronologicalFeaturePipeline, TargetEncodingSpec
from ..data.transformers import FeatureTransformer
from ..core.config import settings

logger = logging.getLogger(__name__)


class ModelTrainer:
    """Handles model training with leakage-safe chronological features."""

    def __init__(self):
        self.transformer = FeatureTransformer(allow_legacy_defaults=True)
        self.models_path = settings.models_path
        self.data_path = settings.data_path
        self.models_path.mkdir(parents=True, exist_ok=True)
        self.data_path.mkdir(parents=True, exist_ok=True)

    def train_league_models(self, leagues: List[str] = None) -> Dict[str, Any]:
        if leagues is None:
            leagues = ["EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1"]
        results: Dict[str, Any] = {}
        for league in tqdm(leagues, desc="Training league models"):
            try:
                logger.info("Training model for %s", league)
                results[league] = self._train_single_league_model(league)
            except Exception as exc:
                logger.error("Failed to train %s: %s", league, exc)
                results[league] = {"error": str(exc)}
        return results

    def _train_single_league_model(self, league: str) -> Dict[str, Any]:
        training_data = self._load_training_data(league)
        if training_data.empty:
            raise ValueError(f"No training data available for {league}")

        X, y = self._prepare_training_data(training_data)
        ensemble = SabiScoreEnsemble()
        ensemble.feature_columns = list(X.columns)
        ensemble.build_ensemble(X, y)

        dataset_signature = self._compute_dataset_signature(training_data)
        model_filename = f"{self._slugify_league(league)}_ensemble"
        ensemble.model_metadata.update(
            {
                "league": league,
                "dataset_signature": dataset_signature,
                "training_samples": len(X),
            }
        )
        ensemble.save_model(self.models_path, model_filename)
        self._update_league_metadata(model_filename, ensemble.model_metadata)
        return {
            "model_path": os.path.join(self.models_path, f"{model_filename}.pkl"),
            "accuracy": ensemble.model_metadata.get("accuracy", 0),
            "brier_score": ensemble.model_metadata.get("brier_score", 0),
            "log_loss": ensemble.model_metadata.get("log_loss", 0),
            "feature_count": len(ensemble.feature_columns),
            "training_samples": len(X),
            "trained_at": ensemble.model_metadata.get("trained_at"),
            "dataset_signature": dataset_signature,
        }

    def _load_training_data(self, league: str) -> pd.DataFrame:
        league_slug = self._slugify_league(league)
        candidates = [
            self.data_path / f"{league_slug}_training.parquet",
            self.data_path / f"{league_slug}_training.feather",
            self.data_path / f"{league_slug}_training.csv",
        ]
        for path in candidates:
            if path.exists():
                logger.info("Loading training data from %s", path)
                if path.suffix == ".parquet":
                    df = pd.read_parquet(path)
                elif path.suffix == ".feather":
                    df = pd.read_feather(path)
                else:
                    df = pd.read_csv(path)
                if "result" not in df.columns:
                    raise ValueError("Training data must contain result")
                df = df.dropna(subset=["result"]).reset_index(drop=True)
                logger.info(
                    "Loaded %s samples with %s columns for %s",
                    len(df),
                    len(df.columns),
                    league,
                )
                return df
        raise FileNotFoundError(
            f"No processed dataset found for league '{league}'. Expected one of: "
            + ", ".join(str(path.name) for path in candidates)
        )

    @staticmethod
    def _add_encoding_targets(data: pd.DataFrame) -> list[TargetEncodingSpec]:
        """Create target columns without exposing them as model features."""
        result = data["result"].astype(str)
        data["__home_win_flag"] = result.isin(["H", "W", "home_win"]).astype(np.float32)
        data["__away_win_flag"] = result.isin(["A", "L", "away_win"]).astype(np.float32)

        specs = [
            TargetEncodingSpec(
                "home_team", "__home_win_flag", "home_team_home_win_encoded"
            ),
            TargetEncodingSpec(
                "away_team", "__away_win_flag", "away_team_away_win_encoded"
            ),
            TargetEncodingSpec(
                "away_team", "__home_win_flag", "away_team_opponent_home_win_encoded"
            ),
        ]
        if "home_manager" in data.columns:
            specs.append(
                TargetEncodingSpec(
                    "home_manager", "__home_win_flag", "home_manager_home_win_encoded"
                )
            )
        return specs

    def _prepare_training_data(
        self, data: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Engineer chronological features before model fitting."""
        data = data.copy()
        encoding_specs = self._add_encoding_targets(data)
        engineered = ChronologicalFeaturePipeline(
            target_encodings=encoding_specs
        ).transform(data)

        exclude_cols = {
            "result",
            "match_id",
            "match_date",
            "date",
            "season",
            "__home_win_flag",
            "__away_win_flag",
            "home_goals",
            "away_goals",
            "league",
            "home_team",
            "away_team",
            "id",
        }
        feature_cols = [col for col in engineered.columns if col not in exclude_cols]
        feature_cols = [col for col in feature_cols if engineered[col].notna().any()]
        if not feature_cols:
            raise ValueError(
                "Chronological feature pipeline produced no usable features"
            )

        X = engineered[feature_cols].copy()
        # Model-side NaN handling remains explicit; no zero-fill of unavailable
        # evidence occurs during feature construction.
        numeric = X.select_dtypes(include=[np.number]).columns
        X[numeric] = X[numeric].astype(np.float32)
        y = engineered["result"].map(
            {
                "home_win": 0,
                "draw": 1,
                "away_win": 2,
                "H": 0,
                "D": 1,
                "A": 2,
                "W": 0,
                "L": 2,
                0: 0,
                1: 1,
                2: 2,
            }
        )
        if y.isnull().any():
            raise ValueError(
                "Encountered unknown result labels while preparing training data"
            )
        return X, y.astype(np.int64).to_frame(name="result")

    def _compute_dataset_signature(self, df: pd.DataFrame) -> Dict[str, Any]:
        buffer = df.to_csv(index=False).encode("utf-8")
        return {
            "checksum": hashlib.sha256(buffer).hexdigest(),
            "rows": int(len(df)),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _update_league_metadata(
        self, model_filename: str, metadata: Dict[str, Any]
    ) -> None:
        league_key = metadata.get(
            "league", model_filename.split("_ensemble")[0]
        ).upper()
        global_meta = self._load_global_metadata()
        global_meta.setdefault("models", {})[league_key] = metadata
        global_meta["last_updated"] = datetime.now(timezone.utc).isoformat()
        metadata_file = self.models_path / "models_metadata.json"
        with metadata_file.open("w", encoding="utf-8") as fh:
            json.dump(global_meta, fh, indent=2)

    def _load_global_metadata(self) -> Dict[str, Any]:
        metadata_file = self.models_path / "models_metadata.json"
        if metadata_file.exists():
            try:
                with metadata_file.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Failed to read metadata file %s: %s", metadata_file, exc
                )
        return {"models": {}, "last_updated": None}

    def _slugify_league(self, league: str) -> str:
        return league.lower().replace(" ", "_").replace("-", "_")

    def update_model_metadata(self) -> None:
        try:
            metadata = {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "models": {},
            }
            if os.path.exists(self.models_path):
                for file in os.listdir(self.models_path):
                    if file.endswith("_metadata.json"):
                        league = (
                            file.replace("_metadata.json", "")
                            .replace("_ensemble", "")
                            .title()
                        )
                        metadata_path = os.path.join(self.models_path, file)
                        with open(metadata_path, "r", encoding="utf-8") as f:
                            metadata["models"][league] = json.load(f)
            with open(
                os.path.join(self.models_path, "models_metadata.json"),
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(metadata, f, indent=2)
        except Exception as exc:
            logger.error("Failed to update metadata: %s", exc)


def train_league_models(leagues: List[str] = None) -> Dict[str, Any]:
    trainer = ModelTrainer()
    results = trainer.train_league_models(leagues)
    trainer.update_model_metadata()
    return results
