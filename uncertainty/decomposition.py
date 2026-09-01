"""
Information-theoretic uncertainty decomposition module for SabiScore.

Decomposes predictive uncertainty from tree ensembles into aleatoric
and epistemic components using Shannon entropy and mutual information.
"""

from typing import Tuple
import numpy as np


def compute_shannon_uncertainty_components(
    tree_probs: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Computes aleatoric, epistemic, and total uncertainty via mutual information.

    Mathematical formulation:
        u_alea(x) = (1 / M) * sum_m H(p_m(x))
        u_total(x) = H( (1 / M) * sum_m p_m(x) )
        u_epi(x) = max(0.0, u_total(x) - u_alea(x))

    Parameters
    ----------
    tree_probs : np.ndarray
        Array of shape (n_trees, n_samples, n_classes) containing predicted
        class probabilities for each tree in the ensemble.

    Returns
    -------
    Tuple[np.ndarray, np.ndarray, np.ndarray]
        - u_alea: Aleatoric uncertainty per sample (n_samples,)
        - u_epi: Epistemic uncertainty (mutual information) per sample (n_samples,)
        - mean_probs: Ensemble averaged probabilities per sample (n_samples, n_classes)
    """
    if tree_probs.ndim != 3:
        raise ValueError(
            f"Expected tree_probs shape (n_trees, n_samples, n_classes), got ndim={tree_probs.ndim}"
        )

    # Clip probabilities to prevent log2(0) numerical instabilities
    clipped_tree_probs = np.clip(tree_probs, 1e-12, 1.0)

    # 1. Intra-tree entropy: H(p_m(x)) for each tree and sample
    # Shape: (n_trees, n_samples)
    tree_entropies = -np.sum(
        clipped_tree_probs * np.log2(clipped_tree_probs), axis=2
    )

    # Aleatoric uncertainty = expected intra-tree entropy
    # Shape: (n_samples,)
    u_alea = np.mean(tree_entropies, axis=0)

    # 2. Ensemble mean probability: p_bar(x)
    # Shape: (n_samples, n_classes)
    mean_probs = np.mean(tree_probs, axis=0)
    clipped_mean_probs = np.clip(mean_probs, 1e-12, 1.0)

    # Total uncertainty = H(p_bar(x))
    # Shape: (n_samples,)
    u_total = -np.sum(clipped_mean_probs * np.log2(clipped_mean_probs), axis=1)

    # 3. Epistemic uncertainty = Mutual Information I(Y; H | x)
    # Non-negative by construction (Jensen's inequality)
    u_epi = np.maximum(0.0, u_total - u_alea)

    return u_alea.astype(np.float64), u_epi.astype(np.float64), mean_probs