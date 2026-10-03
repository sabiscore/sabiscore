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
    CANDIDATE_MA_FEATURE_COLUMNS,
    CANDIDATE_M_FEATURE_COLUMNS,
    FEATURE_COLUMNS,
    TARGET_COLUMNS,
    InsufficientEvidenceError,
    MarketContaminationError,
    StagedDataset,
    assert_candidate_m_purity,
    build_staged_feature_record,
    devig_1x2_odds,
    feature_list_sha256,
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
    "CANDIDATE_M_FEATURE_COLUMNS",
    "CANDIDATE_MA_FEATURE_COLUMNS",
    "FEATURE_COLUMNS",
    "TARGET_COLUMNS",
    "InsufficientEvidenceError",
    "MarketContaminationError",
    "StagedDataset",
    "assert_candidate_m_purity",
    "feature_list_sha256",
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
