"""
SabiScore Models Module

This module exposes:
1. SQLAlchemy Database Models (from src.core.database)
2. Machine Learning Models (from src.models.*)

This unified interface allows importing any model (DB or ML) from `src.models`.
"""

# 1. Database Models (Re-export from core.database)
from ..core.database import (
    Base,
    League,
    Team,
    Player,
    Match,
    MatchStats,
    Prediction,
    Odds,
    ValueBet,
    MatchEvent,
    OddsHistory,
    FeatureVector,
    PlayerValuation,
    ScrapingLog,
    LeagueStanding,
)

# 2. Machine Learning Models
from .base_model import BaseModel
from .random_forest import RandomForestModel
from .xgboost_model import XGBoostModel
from .lightgbm_model import LightGBMModel
from .ensemble import EnsembleModel, SabiScoreEnsemble
from .meta_learner import MetaLearner
from .model_registry import ModelRegistry
from .vector_embeddings import MatchVectorEmbeddings as VectorEmbeddings
from .explainer import ModelExplainer
from .edge_detector import EdgeDetector
from .live_calibrator import PlattCalibrator
from .orchestrator import ModelOrchestrator


def __getattr__(name: str):
    if name == "ModelTrainer":
        from .training import ModelTrainer

        return ModelTrainer
    if name == "EnhancedStackingEnsemble":
        from .enhanced_training import EnhancedStackingEnsemble

        return EnhancedStackingEnsemble
    if name == "EnhancedModelTrainer":
        from .enhanced_training import EnhancedModelTrainer

        return EnhancedModelTrainer
    if name == "CalibratedEnsemble":
        from .enhanced_training import CalibratedEnsemble

        return CalibratedEnsemble
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # DB Models
    "Base",
    "League",
    "Team",
    "Player",
    "Match",
    "MatchStats",
    "Prediction",
    "Odds",
    "ValueBet",
    "MatchEvent",
    "OddsHistory",
    "FeatureVector",
    "PlayerValuation",
    "ScrapingLog",
    "LeagueStanding",
    # ML Models
    "BaseModel",
    "RandomForestModel",
    "XGBoostModel",
    "LightGBMModel",
    "EnsembleModel",
    "SabiScoreEnsemble",
    "MetaLearner",
    "ModelRegistry",
    "VectorEmbeddings",
    "ModelExplainer",
    "EdgeDetector",
    "PlattCalibrator",
    "ModelOrchestrator",
    "ModelTrainer",
    "EnhancedStackingEnsemble",
    "EnhancedModelTrainer",
    "CalibratedEnsemble",
]
