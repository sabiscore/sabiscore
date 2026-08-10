"""Utilities for model-backed uncertainty decomposition and confidence intervals."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from math import log
from math import sqrt
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..core.config import settings

try:
    import torch
except Exception:  # pragma: no cover
    torch = None

from ..models.bnn_ensemble import BNNEnsembleMember


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UncertaintyBreakdown:
    epistemic_unc: float
    aleatoric_unc: float
    concentration: float
    credible_interval: Tuple[float, float]
    confidence_tier: str = "OK"  # "LOW_EVIDENCE" | "OK" — C12


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class UncertaintyService:
    """Uncertainty provider with BNN-first, proxy-fallback behavior."""

    def __init__(self) -> None:
        self._bnn_model: Optional[BNNEnsembleMember] = None
        self._bnn_feature_cols: Optional[List[str]] = None
        self._bnn_enabled = bool(settings.use_bnn_member)
        self._bnn_load_error: Optional[str] = None
        self._load_bnn_model()

    def _load_bnn_model(self) -> None:
        if not self._bnn_enabled:
            return
        if torch is None:
            self._bnn_load_error = "torch unavailable"
            logger.warning("BNN uncertainty disabled: torch unavailable")
            return

        model_path = Path(settings.bnn_model_path)
        if not model_path.exists():
            self._bnn_load_error = f"model not found: {model_path}"
            logger.warning("BNN uncertainty disabled: model file not found at %s", model_path)
            return

        try:
            state = torch.load(model_path, map_location="cpu")
            if isinstance(state, dict) and "state_dict" in state:
                in_features = int(state.get("in_features", 58))
                hidden = int(state.get("hidden", 256))
                feature_cols: Optional[List[str]] = state.get("feature_cols")
                model = BNNEnsembleMember(in_features=in_features, hidden=hidden)
                model.load_state_dict(state["state_dict"], strict=False)
            else:
                # Legacy checkpoint without metadata
                in_features = 58
                hidden = 256
                feature_cols = None
                model = BNNEnsembleMember(in_features=in_features, hidden=hidden)
                model.load_state_dict(state, strict=False)
            model.eval()
            self._bnn_model = model
            self._bnn_feature_cols = feature_cols
            self._bnn_load_error = None
            logger.info(
                "BNN uncertainty model loaded from %s (in_features=%d, hidden=%d, feature_cols=%s)",
                model_path, in_features, hidden,
                f"{len(feature_cols)} cols" if feature_cols else "legacy/none",
            )
        except Exception as exc:
            self._bnn_load_error = str(exc)
            self._bnn_model = None
            logger.warning("Failed to load BNN uncertainty model: %s", exc)

    def _build_input_tensor(
        self,
        feature_frame: pd.DataFrame,
        *,
        strict: bool = False,
    ) -> "torch.Tensor":
        """Build BNN input tensor aligned to the training feature_cols.

        Strict mode rejects missing or non-finite inputs. It is required for
        public measured uncertainty so zero-filled features cannot masquerade
        as model evidence.
        """
        if self._bnn_feature_cols is not None:
            missing = [column for column in self._bnn_feature_cols if column not in feature_frame.columns]
            if strict and missing:
                raise ValueError(f"BNN feature schema incomplete ({len(missing)} missing columns)")
            rows = []
            for _, row in feature_frame.iterrows():
                vec = np.array(
                    [float(row[c]) if c in row.index else 0.0 for c in self._bnn_feature_cols],
                    dtype=np.float32,
                )
                rows.append(vec)
            X = np.stack(rows, axis=0)
        else:
            X = feature_frame.select_dtypes(include="number").to_numpy(dtype=np.float32)
        if strict and not np.isfinite(X).all():
            raise ValueError("BNN feature tensor contains non-finite values")
        X = np.where(np.isfinite(X), X, 0.0)
        return torch.tensor(X, dtype=torch.float32)

    def decompose_measured(
        self,
        feature_frame: pd.DataFrame,
    ) -> Optional[UncertaintyBreakdown]:
        """Return BNN-backed uncertainty only when every required input exists."""

        if self._bnn_model is None or torch is None:
            return None
        if feature_frame is None or feature_frame.empty:
            return None
        try:
            x_tensor = self._build_input_tensor(feature_frame, strict=True)
            outputs = self._bnn_model.predict_uncertainty(
                x_tensor,
                epistemic_threshold=float(settings.epistemic_threshold),
                ci_samples=max(50, int(settings.bnn_mc_samples)),
            )
            if not outputs:
                return None
            out = outputs[0]
            probs = [out.home_prob, out.draw_prob, out.away_prob]
            top_idx = max(range(3), key=lambda idx: probs[idx])
            values = (
                float(out.epistemic),
                float(out.aleatoric),
                float(out.concentration),
                float(out.ci_lower[top_idx]),
                float(out.ci_upper[top_idx]),
            )
            if not np.isfinite(values).all():
                return None
            return UncertaintyBreakdown(
                epistemic_unc=max(0.0, values[0]),
                aleatoric_unc=max(0.0, values[1]),
                concentration=max(0.0, values[2]),
                credible_interval=(
                    _clamp(values[3], 0.0, 1.0),
                    _clamp(values[4], 0.0, 1.0),
                ),
                confidence_tier="LOW_EVIDENCE" if out.low_evidence else "OK",
            )
        except Exception as exc:
            logger.warning("Measured BNN uncertainty unavailable: %s", type(exc).__name__)
            return None

    def decompose(
        self,
        feature_frame: pd.DataFrame,
        probabilities: Dict[str, float],
        confidence: float,
    ) -> UncertaintyBreakdown:
        """Use BNN model-derived uncertainty when available, else proxy fallback."""
        if self._bnn_model is None or torch is None:
            return self.decompose_from_probabilities(probabilities, confidence)

        if feature_frame is None or feature_frame.empty:
            return self.decompose_from_probabilities(probabilities, confidence)

        try:
            x_tensor = self._build_input_tensor(feature_frame)
            outputs = self._bnn_model.predict_uncertainty(
                x_tensor,
                epistemic_threshold=float(settings.epistemic_threshold),
                ci_samples=max(50, int(settings.bnn_mc_samples)),
            )
            if not outputs:
                return self.decompose_from_probabilities(probabilities, confidence)

            out = outputs[0]
            probs = [out.home_prob, out.draw_prob, out.away_prob]
            top_idx = max(range(3), key=lambda idx: probs[idx])
            lower = _clamp(float(out.ci_lower[top_idx]), 0.0, 1.0)
            upper = _clamp(float(out.ci_upper[top_idx]), 0.0, 1.0)

            ep = max(0.0, float(out.epistemic))
            return UncertaintyBreakdown(
                epistemic_unc=ep,
                aleatoric_unc=max(0.0, float(out.aleatoric)),
                concentration=max(0.0, float(out.concentration)),
                credible_interval=(lower, upper),
                confidence_tier="LOW_EVIDENCE" if out.low_evidence else "OK",
            )
        except Exception as exc:
            logger.warning("BNN uncertainty decomposition failed; using proxy fallback: %s", exc)
            return self.decompose_from_probabilities(probabilities, confidence)

    def decompose_from_probabilities(
        self,
        probabilities: Dict[str, float],
        confidence: float,
        z_score: float = 1.96,
    ) -> UncertaintyBreakdown:
        home = float(probabilities.get("home_win", 0.0))
        draw = float(probabilities.get("draw", 0.0))
        away = float(probabilities.get("away_win", 0.0))

        probs = [max(home, 0.0), max(draw, 0.0), max(away, 0.0)]
        total = sum(probs) or 1.0
        probs = [p / total for p in probs]

        entropy = 0.0
        for prob in probs:
            if prob > 0:
                entropy -= prob * log(prob)

        normalized_entropy = entropy / 1.0986122886681098
        aleatoric_unc = _clamp(normalized_entropy, 0.0, 1.0)
        epistemic_unc = _clamp(1.0 - float(confidence), 0.0, 1.0)
        concentration = max(1.0001, 1.0 + (1.0 - aleatoric_unc) * 9.0)

        std_err = sqrt(max(1e-6, confidence * (1.0 - confidence) / 100.0))
        lower = _clamp(confidence - z_score * std_err, 0.0, 1.0)
        upper = _clamp(confidence + z_score * std_err, 0.0, 1.0)

        return UncertaintyBreakdown(
            epistemic_unc=epistemic_unc,
            aleatoric_unc=aleatoric_unc,
            concentration=concentration,
            credible_interval=(lower, upper),
            confidence_tier="LOW_EVIDENCE" if epistemic_unc > float(settings.epistemic_threshold) else "OK",
        )

    def compute_from_defaults(
        self,
        home_win_prob: float = 0.42,
        draw_prob: float = 0.26,
        away_win_prob: float = 0.32,
    ) -> UncertaintyBreakdown:
        """Convenience wrapper used when only market probabilities are available."""
        probs = {"home_win": home_win_prob, "draw": draw_prob, "away_win": away_win_prob}
        confidence = max(home_win_prob, draw_prob, away_win_prob)
        return self.decompose_from_probabilities(probs, confidence)

    def to_dict(self, breakdown: UncertaintyBreakdown) -> Dict[str, object]:
        return {
            "epistemic_unc": breakdown.epistemic_unc,
            "aleatoric_unc": breakdown.aleatoric_unc,
            "concentration": breakdown.concentration,
            "credible_interval": {
                "lower": breakdown.credible_interval[0],
                "upper": breakdown.credible_interval[1],
            },
            "confidence_tier": breakdown.confidence_tier,
        }
