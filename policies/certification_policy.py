"""
Certification Policy Module v1.2.0 for SabiScore.

Enforces gate criteria for production eligibility, specifically verifying error association
monotonically holds within aleatoric strata using residualized epistemic uncertainty.
"""

from typing import Dict, Any, List, Tuple
import numpy as np
from scipy.stats import spearmanr

CERTIFICATION_POLICY_VERSION = "1.2.0"


def compute_rps(y_true: np.ndarray, y_prob: np.ndarray) -> np.ndarray:
    """
    Calculates Ranked Probability Score (RPS) for 3-class ordered outcomes.
    """
    n_samples, n_classes = y_prob.shape
    y_true_onehot = np.zeros((n_samples, n_classes))
    y_true_onehot[np.arange(n_samples), y_true.astype(int)] = 1.0

    cum_true = np.cumsum(y_true_onehot, axis=1)
    cum_pred = np.cumsum(y_prob, axis=1)

    # 1 / (K - 1) * sum((cum_pred - cum_true)^2)
    rps = np.mean((cum_pred[:, :-1] - cum_true[:, :-1]) ** 2, axis=1)
    return rps


def verify_error_association_gate(
    u_alea: np.ndarray,
    u_epi_residualized: np.ndarray,
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_strata: int = 3,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Evaluates error_association gate condition:
    corr(u_epi_residualized, RPS | u_alea stratum_k) > 0 for all k.

    Returns
    -------
    Tuple[bool, Dict[str, Any]]
        - passed: True if all strata exhibit positive Spearman correlation
        - diagnostic_info: Summary dict containing per-stratum correlations and overall status
    """
    if len(u_alea) < 15:
        return False, {
            "passed": False,
            "reason": f"Insufficient sample size: {len(u_alea)} < 15",
        }

    rps = compute_rps(y_true, y_prob)

    # Calculate quantile thresholds for aleatoric stratification
    quantiles = np.linspace(0.0, 1.0, n_strata + 1)[1:-1]
    strata_bounds = np.quantile(u_alea, quantiles)

    strata_masks: List[np.ndarray] = []
    # Lower stratum
    strata_masks.append(u_alea <= strata_bounds[0])
    # Middle strata
    for i in range(len(strata_bounds) - 1):
        strata_masks.append(
            (u_alea > strata_bounds[i]) & (u_alea <= strata_bounds[i + 1])
        )
    # Upper stratum
    strata_masks.append(u_alea > strata_bounds[-1])

    strata_correlations: List[float] = []
    strata_counts: List[int] = []

    all_passed = True
    for idx, mask in enumerate(strata_masks):
        count = int(np.sum(mask))
        strata_counts.append(count)

        if count < 5:
            all_passed = False
            strata_correlations.append(0.0)
            continue

        corr, _ = spearmanr(u_epi_residualized[mask], rps[mask])
        if np.isnan(corr) or corr <= 0.0:
            all_passed = False

        strata_correlations.append(float(corr) if not np.isnan(corr) else 0.0)

    # Overall cross-strata metric
    overall_corr, _ = spearmanr(u_epi_residualized, rps)

    diagnostic_info = {
        "policy_version": CERTIFICATION_POLICY_VERSION,
        "gate_name": "error_association",
        "passed": all_passed,
        "overall_corr": float(overall_corr) if not np.isnan(overall_corr) else 0.0,
        "strata_correlations": strata_correlations,
        "strata_sample_counts": strata_counts,
        "n_strata": n_strata,
    }

    return all_passed, diagnostic_info