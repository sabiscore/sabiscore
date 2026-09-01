"""
Epistemic uncertainty residualization module for SabiScore.

Removes the aleatoric confound from epistemic uncertainty estimates by fitting
a monotonic baseline mapping f(u_alea) -> E[u_epi | u_alea].
"""

from typing import Any, Dict, Optional
import numpy as np
from sklearn.isotonic import IsotonicRegression


class EpistemicResidualizer:
    """
    Orthogonalizes epistemic uncertainty with respect to aleatoric uncertainty
    using Isotonic Regression.
    """

    def __init__(self, out_of_bounds: str = "clip") -> None:
        self.out_of_bounds = out_of_bounds
        self._model: Optional[IsotonicRegression] = None
        self.is_fitted: bool = False

    def fit(
        self, u_alea: np.ndarray, u_epi: np.ndarray
    ) -> "EpistemicResidualizer":
        """
        Fits non-parametric monotonic regression: f(u_alea) -> E[u_epi | u_alea].
        """
        u_alea_flat = np.asarray(u_alea, dtype=np.float64).ravel()
        u_epi_flat = np.asarray(u_epi, dtype=np.float64).ravel()

        if len(u_alea_flat) != len(u_epi_flat):
            raise ValueError(
                f"Length mismatch: u_alea ({len(u_alea_flat)}) vs u_epi ({len(u_epi_flat)})"
            )

        self._model = IsotonicRegression(
            increasing=True, out_of_bounds=self.out_of_bounds
        )
        self._model.fit(u_alea_flat, u_epi_flat)
        self.is_fitted = True
        return self

    def transform(self, u_alea: np.ndarray, u_epi: np.ndarray) -> np.ndarray:
        """
        Computes residualized epistemic metric: u_epi_tilde = u_epi - f(u_alea).
        """
        if not self.is_fitted or self._model is None:
            raise RuntimeError("EpistemicResidualizer must be fitted before transform.")

        u_alea_flat = np.asarray(u_alea, dtype=np.float64).ravel()
        u_epi_flat = np.asarray(u_epi, dtype=np.float64).ravel()

        expected_u_epi = self._model.predict(u_alea_flat)
        u_epi_tilde = u_epi_flat - expected_u_epi
        return u_epi_tilde.astype(np.float64)

    def fit_transform(
        self, u_alea: np.ndarray, u_epi: np.ndarray
    ) -> np.ndarray:
        """
        Fits the residualizer and transforms metrics in a single step.
        """
        return self.fit(u_alea, u_epi).transform(u_alea, u_epi)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes residualizer state for artifact packaging.
        """
        if not self.is_fitted or self._model is None:
            return {"is_fitted": False}

        return {
            "is_fitted": True,
            "out_of_bounds": self.out_of_bounds,
            "f_x_": self._model.f_x_.tolist(),
            "y_thresholds_": self._model.y_thresholds_.tolist(),
            "X_min_": float(self._model.X_min_),
            "X_max_": float(self._model.X_max_),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpistemicResidualizer":
        """
        Reconstructs residualizer from artifact metadata dictionary.
        """
        instance = cls(out_of_bounds=data.get("out_of_bounds", "clip"))
        if not data.get("is_fitted", False):
            return instance

        model = IsotonicRegression(
            increasing=True, out_of_bounds=instance.out_of_bounds
        )
        model.f_x_ = np.array(data["f_x_"], dtype=np.float64)
        model.y_thresholds_ = np.array(data["y_thresholds_"], dtype=np.float64)
        model.X_min_ = data["X_min_"]
        model.X_max_ = data["X_max_"]

        instance._model = model
        instance.is_fitted = True
        return instance