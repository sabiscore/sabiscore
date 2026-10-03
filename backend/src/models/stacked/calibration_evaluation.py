"""Probability Calibration & Diagnostic Evaluation.

Evaluates multi-class probabilistic calibration for football betting models:
- Ranked Probability Score (RPS)
- Multi-class Brier Score
- Expected Calibration Error (ECE < 5%)
Generates a structured Calibration Delta Report comparing the xG-integrated
stacked ensemble against non-xG baseline models.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalibrationMetrics:
    """Diagnostic calibration and accuracy metrics."""

    rps: float
    brier_score: float
    ece_mean: float
    ece_home: float
    ece_draw: float
    ece_away: float
    sample_count: int


@dataclass(frozen=True)
class CalibrationDeltaReport:
    """Comparative diagnostic report between baseline and new ensemble."""

    baseline_metrics: CalibrationMetrics
    ensemble_metrics: CalibrationMetrics
    rps_improvement_pct: float
    brier_improvement_pct: float
    ece_improvement_pct: float
    passes_ece_gate: bool  # True if ensemble ECE < 0.05
    formatted_report: str


def compute_rps(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    """Calculate mean Ranked Probability Score for 3 outcomes (0=Home, 1=Draw, 2=Away).

    RPS = (1 / (2 * N)) * sum_k sum_{r=1}^2 (sum_{i=1}^r p_i - sum_{i=1}^r e_i)^2
    Lower is better. Range: [0, 1].
    """
    n = len(y_true)
    if n == 0:
        return 0.0

    # Cumulative probabilities
    cum_probs = np.cumsum(y_proba, axis=1)  # shape (N, 3)

    # One-hot truth and cumulative truth
    one_hot = np.zeros_like(y_proba)
    one_hot[np.arange(n), y_true] = 1.0
    cum_true = np.cumsum(one_hot, axis=1)

    # Sum squared differences across outcome splits 0 and 1
    # Note: at index 2 (away), cumulative sum is always 1.0 for both, difference is 0
    diff_0 = cum_probs[:, 0] - cum_true[:, 0]
    diff_1 = cum_probs[:, 1] - cum_true[:, 1]

    rps_per_match = 0.5 * (diff_0**2 + diff_1**2)
    return float(np.mean(rps_per_match))


def compute_brier_score(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    """Calculate multi-class Brier score.

    BS = (1 / N) * sum_k sum_c (p_{k,c} - y_{k,c})^2
    Lower is better (0 is perfect, 1 is total failure).
    """
    n = len(y_true)
    if n == 0:
        return 0.0

    one_hot = np.zeros_like(y_proba)
    one_hot[np.arange(n), y_true] = 1.0

    squared_errors = (y_proba - one_hot) ** 2
    return float(np.mean(np.sum(squared_errors, axis=1)))


def compute_ece(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    n_bins: int = 10,
) -> tuple[float, float, float, float]:
    """Calculate Expected Calibration Error (ECE) across 10 bins for classes 0, 1, 2.

    Returns:
        (ece_mean, ece_home, ece_draw, ece_away)
    """
    n = len(y_true)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    class_eces: list[float] = []

    for c in range(3):
        binary_y = (y_true == c).astype(np.float32)
        c_probs = y_proba[:, c]
        c_ece = 0.0

        for lo, hi in zip(bins[:-1], bins[1:]):
            mask = (c_probs > lo) & (c_probs <= hi)
            bin_count = np.sum(mask)
            if bin_count > 0:
                bin_acc = np.mean(binary_y[mask])
                bin_conf = np.mean(c_probs[mask])
                c_ece += (bin_count / n) * abs(bin_acc - bin_conf)

        class_eces.append(float(c_ece))

    ece_mean = float(np.mean(class_eces))
    return ece_mean, class_eces[0], class_eces[1], class_eces[2]


def evaluate_predictions(y_true: np.ndarray, y_proba: np.ndarray) -> CalibrationMetrics:
    """Compute RPS, Brier Score, and 10-bin ECE for a set of predictions."""
    rps = compute_rps(y_true, y_proba)
    brier = compute_brier_score(y_true, y_proba)
    ece_mean, ece_h, ece_d, ece_a = compute_ece(y_true, y_proba, n_bins=10)

    return CalibrationMetrics(
        rps=round(rps, 4),
        brier_score=round(brier, 4),
        ece_mean=round(ece_mean, 4),
        ece_home=round(ece_h, 4),
        ece_draw=round(ece_d, 4),
        ece_away=round(ece_a, 4),
        sample_count=len(y_true),
    )


def generate_calibration_delta_report(
    y_true: np.ndarray,
    baseline_proba: np.ndarray,
    ensemble_proba: np.ndarray,
) -> CalibrationDeltaReport:
    """Compare baseline model vs new stacked ensemble on holdout data and generate delta report."""
    base_m = evaluate_predictions(y_true, baseline_proba)
    ens_m = evaluate_predictions(y_true, ensemble_proba)

    rps_imp = (
        ((base_m.rps - ens_m.rps) / base_m.rps) * 100.0 if base_m.rps > 0 else 0.0
    )
    brier_imp = (
        ((base_m.brier_score - ens_m.brier_score) / base_m.brier_score) * 100.0
        if base_m.brier_score > 0
        else 0.0
    )
    ece_imp = (
        ((base_m.ece_mean - ens_m.ece_mean) / base_m.ece_mean) * 100.0
        if base_m.ece_mean > 0
        else 0.0
    )

    passes_gate = ens_m.ece_mean < 0.05

    report_lines = [
        "=" * 80,
        "CALIBRATION DELTA REPORT: STACKED xG ENSEMBLE vs NON-xG BASELINE",
        "=" * 80,
        f"Evaluation Samples: {ens_m.sample_count} matches",
        "-" * 80,
        f"{'Metric':<22} | {'Baseline (Non-xG)':<18} | {'Stacked xG Ens':<16} | {'Improvement':<12}",
        "-" * 80,
        f"{'Ranked Prob Score':<22} | {base_m.rps:<18.4f} | {ens_m.rps:<16.4f} | {rps_imp:+.2f}%",
        f"{'Brier Score':<22} | {base_m.brier_score:<18.4f} | {ens_m.brier_score:<16.4f} | {brier_imp:+.2f}%",
        f"{'ECE (Mean)':<22} | {base_m.ece_mean:<18.4f} | {ens_m.ece_mean:<16.4f} | {ece_imp:+.2f}%",
        f"{'  ECE Home (1)':<22} | {base_m.ece_home:<18.4f} | {ens_m.ece_home:<16.4f} | ---",
        f"{'  ECE Draw (X)':<22} | {base_m.ece_draw:<18.4f} | {ens_m.ece_draw:<16.4f} | ---",
        f"{'  ECE Away (2)':<22} | {base_m.ece_away:<18.4f} | {ens_m.ece_away:<16.4f} | ---",
        "=" * 80,
        f"CALIBRATION GATE (ECE < 5.0%): {'PASS' if passes_gate else 'FAIL'} (Measured ECE: {ens_m.ece_mean * 100:.2f}%)",
        "=" * 80,
    ]
    report_text = "\n".join(report_lines)
    logger.info("\n%s", report_text)

    return CalibrationDeltaReport(
        baseline_metrics=base_m,
        ensemble_metrics=ens_m,
        rps_improvement_pct=round(rps_imp, 2),
        brier_improvement_pct=round(brier_imp, 2),
        ece_improvement_pct=round(ece_imp, 2),
        passes_ece_gate=passes_gate,
        formatted_report=report_text,
    )


__all__ = [
    "CalibrationMetrics",
    "CalibrationDeltaReport",
    "compute_rps",
    "compute_brier_score",
    "compute_ece",
    "evaluate_predictions",
    "generate_calibration_delta_report",
]
