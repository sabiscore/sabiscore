"""Draw probability recalibration — post-processing step.

Complements the existing per-league draw threshold tuning in
retrain_with_expanded_features.py (Phase 7-B). This module adds a
multiplicative inflate factor calibrated on a held-out calibration set,
then renormalises to a valid probability triple.

Usage:
  calibrator = DrawRecalibrator.fit(y_cal, y_proba_cal)
  h, d, a = calibrator.recalibrate(home_prob, draw_prob, away_prob)

The inflate factor is stored in the league_calibration_params table
alongside the existing per-league draw threshold.

B13 compliance: no synthetic injection — if calibration set is empty,
factor defaults to 1.0 (no adjustment) and the caller surfaces DATA_GAP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass
class DrawRecalibrator:
    """Holds a per-league draw inflate factor."""

    factor: float = 1.0

    @classmethod
    def fit(
        cls,
        y_cal: "np.ndarray",
        y_proba_cal: "np.ndarray",
    ) -> "DrawRecalibrator":
        """Estimate inflate factor from calibration split.

        Args:
            y_cal:       True labels (0=home, 1=draw, 2=away) — shape (N,).
            y_proba_cal: Model predicted probabilities — shape (N, 3).
                         Column 1 is the draw probability.

        Returns:
            DrawRecalibrator with fitted factor. Typical range EPL ~1.08,
            Bundesliga ~1.12. Factor > 1 means the model under-predicts draws.
        """
        if len(y_cal) == 0:
            return cls(factor=1.0)

        actual_draw_rate = float((y_cal == 1).mean())
        modeled_draw_rate = float(y_proba_cal[:, 1].mean())

        if modeled_draw_rate < 1e-9:
            return cls(factor=1.0)

        factor = round(actual_draw_rate / modeled_draw_rate, 4)
        return cls(factor=factor)

    def recalibrate(
        self,
        home_prob: float,
        draw_prob: float,
        away_prob: float,
    ) -> Tuple[float, float, float]:
        """Apply inflate factor and renormalise to a valid probability triple.

        Draw is capped at 0.60 to prevent degenerate outputs.

        Returns:
            (home, draw, away) renormalised to sum=1.
        """
        adj_draw = min(draw_prob * self.factor, 0.60)
        remaining = home_prob + away_prob
        if remaining < 1e-9:
            scale = 1.0
        else:
            scale = (1.0 - adj_draw) / remaining
        new_home = home_prob * scale
        new_away = away_prob * scale
        total = new_home + adj_draw + new_away
        if total < 1e-9:
            return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
        return (
            round(new_home / total, 6),
            round(adj_draw / total, 6),
            round(new_away / total, 6),
        )
