#!/usr/bin/env python3
"""
Standalone Diagnostic Script: Vector 1 (Mutual Info) & Vector 3 (Residualization)
Analyzes current SabiScore artifacts across scoreable leagues.
"""

from pathlib import Path
import json
import joblib
import numpy as np
import pandas as pd
from scipy.stats import entropy, spearmanr
from sklearn.isotonic import IsotonicRegression
from typing import Dict, Tuple, List, Any


def compute_rps(y_true: np.ndarray, y_prob: np.ndarray) -> np.ndarray:
    """
    Computes Ranked Probability Score (RPS) for 3-class outcomes (Home, Draw, Away).
    y_true: 1D array of class indices [0, 1, 2]
    y_prob: 2D array of predicted probabilities (N, 3)
    """
    n_samples, n_classes = y_prob.shape
    y_true_onehot = np.zeros((n_samples, n_classes))
    y_true_onehot[np.arange(n_samples), y_true] = 1.0

    # Cumulative sums along outcome ordering
    cum_true = np.cumsum(y_true_onehot, axis=1)
    cum_pred = np.cumsum(y_prob, axis=1)

    # RPS formula: (1 / (K - 1)) * sum((cum_pred - cum_true)^2)
    rps = np.mean((cum_pred[:, :-1] - cum_true[:, :-1]) ** 2, axis=1)
    return rps


def extract_vector1_uncertainty(
    tree_probs: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Vector 1: Shannon Mutual Information Decomposition.
    tree_probs: shape (n_trees, n_samples, 3)
    Returns: (u_alea, u_epi, mean_probs)
    """
    # 1. Intra-tree entropy (Aleatoric Uncertainty)
    # Clip probabilities to avoid log(0)
    clipped_probs = np.clip(tree_probs, 1e-12, 1.0)
    tree_entropies = -np.sum(clipped_probs * np.log2(clipped_probs), axis=2)
    u_alea = np.mean(tree_entropies, axis=0)

    # 2. Ensemble average entropy (Total Uncertainty)
    mean_probs = np.mean(tree_probs, axis=0)
    clipped_mean_probs = np.clip(mean_probs, 1e-12, 1.0)
    u_total = -np.sum(clipped_mean_probs * np.log2(clipped_mean_probs), axis=1)

    # 3. Mutual Information (Epistemic Uncertainty)
    u_epi = np.maximum(0.0, u_total - u_alea)

    return u_alea, u_epi, mean_probs


def fit_vector3_residualizer(
    u_alea: np.ndarray, u_epi: np.ndarray
) -> IsotonicRegression:
    """
    Vector 3: Quantile/Monotonic Baseline Residualization.
    Fits f(u_alea) -> E[u_epi | u_alea] using Isotonic Regression for fast, non-parametric mapping.
    """
    iso_reg = IsotonicRegression(out_of_bounds="clip")
    iso_reg.fit(u_alea, u_epi)
    return iso_reg


def compute_residualized_epistemic(
    u_alea: np.ndarray, u_epi: np.ndarray, model: IsotonicRegression
) -> np.ndarray:
    """
    Computes residualized epistemic metric: tilde_u_epi = u_epi - f(u_alea)
    """
    expected_u_epi = model.predict(u_alea)
    return u_epi - expected_u_epi


def evaluate_league_artifact(
    artifact_path: Path, holdout_path: Path
) -> Dict[str, Any]:
    """
    Extracts predictions from a league artifact and evaluates raw vs residualized correlations.
    """
    artifact = joblib.load(artifact_path)
    holdout_df = pd.read_csv(holdout_path)

    # Extract model estimators and feature matrices
    estimators = artifact["model"].estimators_
    X_holdout = holdout_df[artifact["feature_names"]].values
    y_holdout = holdout_df["target"].values

    # Extract raw tree predictions: shape (n_trees, n_samples, 3)
    tree_probs = np.array([est.predict_proba(X_holdout) for est in estimators])

    # Compute Vector 1 metrics
    u_alea, u_epi_raw, mean_probs = extract_vector1_uncertainty(tree_probs)
    rps = compute_rps(y_holdout, mean_probs)

    # Compute raw correlations
    corr_epi_alea_raw, _ = spearmanr(u_epi_raw, u_alea)
    corr_alea_rps, _ = spearmanr(u_alea, rps)

    # Compute Vector 3 residualization
    residualizer = fit_vector3_residualizer(u_alea, u_epi_raw)
    u_epi_tilde = compute_residualized_epistemic(u_alea, u_epi_raw, residualizer)

    corr_epi_alea_tilde, _ = spearmanr(u_epi_tilde, u_alea)

    # Stratified Error Association Check across 3 Aleatoric Quantiles
    terciles = np.quantile(u_alea, [0.333, 0.666])
    strata_masks = [
        u_alea <= terciles[0],
        (u_alea > terciles[0]) & (u_alea <= terciles[1]),
        u_alea > terciles[1],
    ]

    strata_results_raw = []
    strata_results_tilde = []

    for mask in strata_masks:
        if np.sum(mask) > 5:
            r_raw, _ = spearmanr(u_epi_raw[mask], rps[mask])
            r_tilde, _ = spearmanr(u_epi_tilde[mask], rps[mask])
            strata_results_raw.append(r_raw)
            strata_results_tilde.append(r_tilde)

    return {
        "league": artifact_path.stem,
        "n_samples": len(y_holdout),
        "raw_corr_epi_alea": float(corr_epi_alea_raw),
        "tilde_corr_epi_alea": float(corr_epi_alea_tilde),
        "corr_alea_rps": float(corr_alea_rps),
        "strata_corr_raw": [float(x) for x in strata_results_raw],
        "strata_corr_tilde": [float(x) for x in strata_results_tilde],
        "all_strata_passed": all(x > 0 for x in strata_results_tilde),
    }


def main():
    artifacts_dir = Path("artifacts/active")
    holdouts_dir = Path("data/holdouts")

    results = []
    print(
        f"{'League':<20} | {'Raw corr(e,a)':<14} | {'Tilde corr(e,a)':<16} | {'Strata Tilde Corrs':<25} | {'Gate Pass':<10}"
    )
    print("-" * 95)

    for art_path in artifacts_dir.glob("*.joblib"):
        holdout_path = holdouts_dir / f"{art_path.stem}_holdout.csv"
        if not holdout_path.exists():
            continue

        res = evaluate_league_artifact(art_path, holdout_path)
        results.append(res)

        strata_str = ", ".join([f"{x:+.3f}" for x in res["strata_corr_tilde"]])
        print(
            f"{res['league']:<20} | {res['raw_corr_epi_alea']:<14.4f} | {res['tilde_corr_epi_alea']:<16.4f} | {strata_str:<25} | {str(res['all_strata_passed']):<10}"
        )


if __name__ == "__main__":
    main()