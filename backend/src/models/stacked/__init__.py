"""Stacked Ensemble Machine Learning Package."""

from .calibration_evaluation import (
    CalibrationDeltaReport,
    CalibrationMetrics,
    compute_brier_score,
    compute_ece,
    compute_rps,
    evaluate_predictions,
    generate_calibration_delta_report,
)
from .data_staging import (
    FEATURE_COLUMNS,
    TARGET_COLUMNS,
    StagedDataset,
    build_staged_feature_record,
    devig_1x2_odds,
    iter_staged_chunks,
    stage_features_and_targets,
)
from .ensemble import (
    StackedEnsembleArtifacts,
    StackedMatchEnsemble,
    WalkForwardEvaluationResult,
)

__all__ = [
    # Data staging
    "FEATURE_COLUMNS",
    "TARGET_COLUMNS",
    "StagedDataset",
    "devig_1x2_odds",
    "build_staged_feature_record",
    "stage_features_and_targets",
    "iter_staged_chunks",
    # Ensemble
    "StackedMatchEnsemble",
    "StackedEnsembleArtifacts",
    "WalkForwardEvaluationResult",
    # Calibration & Evaluation
    "CalibrationMetrics",
    "CalibrationDeltaReport",
    "compute_rps",
    "compute_brier_score",
    "compute_ece",
    "evaluate_predictions",
    "generate_calibration_delta_report",
]
