"""Phase 8 feature engineering modules.

New features in this package extend CANONICAL_FEATURES_68 → the canonical Phase 8 89-feature schema (legacy CANONICAL_FEATURES_86 alias retained).
All rating engines mirror the elo_engine.py pattern: parquet persistence, idempotent
updates, chronological processing enforced by the caller.
"""
from .pi_ratings import PiRatingSystem, PiContext
from .berrar_ratings import BerrarRatingSystem, BerrarContext
from .form import weighted_form_features
from .draw_recalibration import DrawRecalibrator
from .market import market_movement_features
from .match_context import match_importance_score

__all__ = [
    "PiRatingSystem",
    "PiContext",
    "BerrarRatingSystem",
    "BerrarContext",
    "weighted_form_features",
    "DrawRecalibrator",
    "market_movement_features",
    "match_importance_score",
]
