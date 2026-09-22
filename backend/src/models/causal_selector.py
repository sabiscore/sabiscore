"""Phase 6-B causal feature analysis helpers (analysis-only mode).

This module computes lightweight causal-style diagnostics for all canonical
features without modifying the training feature registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .feature_registry import CANONICAL_FEATURES_58


@dataclass(frozen=True)
class CausalFeatureResult:
    name: str
    ate_win: float
    ate_draw: float
    ate_ci: Tuple[float, float]
    p_value: float
    classification: str


class CausalFeatureSelector:
    """Analysis-only causal selector for Phase 6 artifact generation."""

    CLASSIFICATIONS = {
        "CAUSAL_DRIVER",
        "CONFOUNDED",
        "INDEPENDENT",
        "COLLIDER_WARNING",
    }

    def __init__(
        self, alpha_threshold: float = 0.05, practical_ate: float = 0.02
    ) -> None:
        self.alpha_threshold = alpha_threshold
        self.practical_ate = practical_ate

    def analyze(
        self,
        frame: pd.DataFrame,
        outcome_col: str = "match_result",
        feature_cols: Optional[List[str]] = None,
    ) -> List[CausalFeatureResult]:
        """Compute causal-style ATE table for all canonical features.

        Args:
            frame: Input DataFrame containing features and outcome column.
            outcome_col: Name of the outcome column (0=home win, 1=draw, 2=away win).
            feature_cols: Optional explicit list of features to analyse. When None,
                falls back to CANONICAL_FEATURES_58 intersected with frame columns.

        ATE proxy is the difference in outcome means between treatment/control,
        where treatment is feature >= median.
        """
        if outcome_col not in frame.columns:
            raise ValueError(f"Missing outcome column: {outcome_col}")

        prepared = frame.copy()
        prepared = prepared.replace([np.inf, -np.inf], np.nan)

        if outcome_col not in prepared.columns:
            raise ValueError("Outcome column missing after normalization")

        is_home_win = (prepared[outcome_col].astype(str) == "0").astype(float)
        is_draw = (prepared[outcome_col].astype(str) == "1").astype(float)

        candidate_features: List[str]
        if feature_cols is not None:
            candidate_features = [f for f in feature_cols if f in prepared.columns]
        else:
            # Fall back to canonical set; silently skip absent columns
            candidate_features = [
                f for f in CANONICAL_FEATURES_58 if f in prepared.columns
            ]

        results: List[CausalFeatureResult] = []
        for feature in candidate_features:
            if feature not in prepared.columns:
                continue

            series = pd.to_numeric(prepared[feature], errors="coerce")
            clean = pd.DataFrame(
                {"x": series, "home": is_home_win, "draw": is_draw}
            ).dropna()
            if len(clean) < 30:
                continue

            threshold = float(clean["x"].median())
            treated = clean[clean["x"] >= threshold]
            control = clean[clean["x"] < threshold]
            if len(treated) < 10 or len(control) < 10:
                continue

            ate_win = float(treated["home"].mean() - control["home"].mean())
            ate_draw = float(treated["draw"].mean() - control["draw"].mean())

            stderr = float(
                np.sqrt(
                    np.var(treated["home"], ddof=1) / max(len(treated), 1)
                    + np.var(control["home"], ddof=1) / max(len(control), 1)
                )
            )
            ci_low = ate_win - 1.96 * stderr
            ci_high = ate_win + 1.96 * stderr

            z = 0.0 if stderr == 0 else abs(ate_win / stderr)
            p_value = float(np.exp(-0.717 * z - 0.416 * (z**2)))
            p_value = min(1.0, max(0.0, p_value))

            classification = self._classify(ate_win, p_value, feature)

            results.append(
                CausalFeatureResult(
                    name=feature,
                    ate_win=ate_win,
                    ate_draw=ate_draw,
                    ate_ci=(float(ci_low), float(ci_high)),
                    p_value=p_value,
                    classification=classification,
                )
            )

        return results

    def build_graph(
        self,
        frame: pd.DataFrame,
        corr_threshold: float = 0.35,
        feature_cols: Optional[List[str]] = None,
    ) -> Dict[str, object]:
        """Construct a lightweight adjacency graph as a PC-style artifact fallback.

        Args:
            frame: Input DataFrame.
            corr_threshold: Minimum |r| to include an edge.
            feature_cols: Optional explicit feature list. When None, uses
                CANONICAL_FEATURES_58 intersected with frame columns.
        """
        if feature_cols is not None:
            selected = [c for c in feature_cols if c in frame.columns]
        else:
            selected = [c for c in CANONICAL_FEATURES_58 if c in frame.columns]
        numeric = frame[selected].copy()
        numeric = numeric.apply(pd.to_numeric, errors="coerce").dropna(
            axis=1, how="all"
        )
        corr = numeric.corr(method="pearson", min_periods=50)

        edges: List[Dict[str, object]] = []
        for i, src in enumerate(corr.columns):
            for dst in corr.columns[i + 1 :]:
                value = corr.loc[src, dst]
                if pd.isna(value):
                    continue
                if abs(float(value)) < corr_threshold:
                    continue
                edges.append(
                    {
                        "source": src,
                        "target": dst,
                        "confidence": round(abs(float(value)), 6),
                    }
                )

        return {
            "nodes": [{"id": col} for col in corr.columns],
            "edges": edges,
            "method": "correlation-fallback",
            "corr_threshold": corr_threshold,
        }

    def _classify(self, ate_win: float, p_value: float, feature_name: str) -> str:
        if "collider" in feature_name:
            return "COLLIDER_WARNING"
        if abs(ate_win) >= self.practical_ate and p_value <= self.alpha_threshold:
            return "CAUSAL_DRIVER"
        if p_value <= self.alpha_threshold:
            return "CONFOUNDED"
        return "INDEPENDENT"
