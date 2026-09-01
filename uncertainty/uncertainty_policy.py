"""
Uncertainty Policy Module v1.2.0 for SabiScore.

Manages uncertainty extraction, decomposition, residualization, and policy verification.
Backward-compatible with legacy raw-variance metrics while exposing de-confounded outputs.
"""

from typing import Any, Dict, NamedTuple, Optional
import numpy as np

from sabiscore.uncertainty.decomposition import (
    compute_shannon_uncertainty_components,
)
from sabiscore.uncertainty.residualizer import EpistemicResidualizer

POLICY_VERSION = "1.2.0"


class UncertaintyResult(NamedTuple):
    u_alea: np.ndarray
    u_epi_raw: np.ndarray
    u_epi_residualized: np.ndarray
    mean_probs: np.ndarray


class UncertaintyPolicy:
    """
    Executes uncertainty calculations and integrates the residualizer model.
    """

    def __init__(self, residualizer: Optional[EpistemicResidualizer] = None) -> None:
        self.residualizer = residualizer or EpistemicResidualizer()

    def fit_residualizer(
        self, u_alea: np.ndarray, u_epi_raw: np.ndarray
    ) -> None:
        """
        Fits the underlying residualizer on training/holdout calibration distributions.
        """
        self.residualizer.fit(u_alea, u_epi_raw)

    def extract_uncertainty(
        self, tree_probs: np.ndarray
    ) -> UncertaintyResult:
        """
        Extracts aleatoric, raw epistemic, and residualized epistemic metrics.
        """
        u_alea, u_epi_raw, mean_probs = compute_shannon_uncertainty_components(
            tree_probs
        )

        if self.residualizer.is_fitted:
            u_epi_tilde = self.residualizer.transform(u_alea, u_epi_raw)
        else:
            # Fallback if unfitted: return raw epistemic metric
            u_epi_tilde = u_epi_raw.copy()

        return UncertaintyResult(
            u_alea=u_alea,
            u_epi_raw=u_epi_raw,
            u_epi_residualized=u_epi_tilde,
            mean_probs=mean_probs,
        )

    def to_metadata(self) -> Dict[str, Any]:
        """
        Exports policy state and metadata for certification checks.
        """
        return {
            "policy_version": POLICY_VERSION,
            "residualizer": self.residualizer.to_dict(),
        }