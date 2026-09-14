"""Point-in-time target encoding without one-hot expansion or leakage."""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

import numpy as np
import pandas as pd


class PointInTimeTargetEncoder:
    """Expanding target mean using only events strictly before each row's date.

    Rows sharing a date are evaluated against the state at the start of that
    date, so one match cannot leak another match from the same matchday.
    """

    def __init__(self, smoothing: float = 0.0) -> None:
        if smoothing < 0:
            raise ValueError("smoothing must be non-negative")
        self.smoothing = float(smoothing)
        self.global_sum = 0.0
        self.global_count = 0
        self.category_stats: dict[tuple[str, object], list[float]] = {}
        self.fitted = False

    @staticmethod
    def _validate(df: pd.DataFrame, category_col: str, target_col: str, date_col: str) -> None:
        missing = {category_col, target_col, date_col}.difference(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {sorted(missing)}")

    def fit_transform(
        self,
        df: pd.DataFrame,
        category_col: str,
        target_col: str,
        *,
        date_col: str = "date",
        output_col: str | None = None,
    ) -> pd.DataFrame:
        self._validate(df, category_col, target_col, date_col)
        out = df.copy()
        dates = pd.to_datetime(out[date_col], errors="raise")
        target = pd.to_numeric(out[target_col], errors="coerce")
        if target.isna().any():
            raise ValueError(f"Target column {target_col!r} contains non-numeric values")

        order = dates.argsort(kind="mergesort")
        encoded = np.empty(len(out), dtype=np.float32)
        encoded.fill(np.nan)
        self.global_sum = 0.0
        self.global_count = 0
        self.category_stats.clear()

        # Work by date to make "point in time" strict even for same-day matches.
        for _, positions in dates.iloc[order].groupby(dates.iloc[order]).groups.items():
            positions = np.asarray(positions, dtype=np.int64)
            for position in positions:
                category = out.iloc[position][category_col]
                key = (category_col, category)
                stats = self.category_stats.get(key, [0.0, 0.0])
                if stats[1] > 0:
                    numerator = stats[0]
                    denominator = stats[1]
                    if self.smoothing:
                        prior_global = self.global_sum / self.global_count if self.global_count else 0.0
                        value = (numerator + self.smoothing * prior_global) / (denominator + self.smoothing)
                    else:
                        value = numerator / denominator
                elif self.global_count:
                    value = self.global_sum / self.global_count
                else:
                    value = np.nan
                encoded[position] = np.float32(value) if np.isfinite(value) else np.nan

            # Update state only after every row on this date has been encoded.
            for position in positions:
                category = out.iloc[position][category_col]
                key = (category_col, category)
                stats = self.category_stats.setdefault(key, [0.0, 0.0])
                value = float(target.iloc[position])
                stats[0] += value
                stats[1] += 1.0
                self.global_sum += value
                self.global_count += 1

        self.fitted = True
        out[output_col or f"{category_col}_{target_col}_encoded"] = encoded
        return out

    def transform(
        self,
        df: pd.DataFrame,
        category_col: str,
        *,
        output_col: str,
        prior_global_mean: float | None = None,
    ) -> pd.DataFrame:
        """Encode prediction rows from a previously learned historical state.

        No target values from the prediction frame are accepted or consumed.
        """
        if not self.fitted:
            raise RuntimeError("Encoder must be fit before transform")
        if category_col not in df.columns:
            raise ValueError(f"Missing column: {category_col}")
        fallback = prior_global_mean
        if fallback is None:
            fallback = self.global_sum / self.global_count if self.global_count else np.nan
        values = np.empty(len(df), dtype=np.float32)
        for i, category in enumerate(df[category_col].tolist()):
            stats = self.category_stats.get((category_col, category))
            if stats and stats[1] > 0:
                value = stats[0] / stats[1]
            else:
                value = fallback
            values[i] = np.float32(value) if np.isfinite(value) else np.nan
        out = df.copy()
        out[output_col] = values
        return out


def ram_optimized_target_encoding(
    df: pd.DataFrame,
    category_col: str,
    target_col: str,
    *,
    date_col: str = "date",
) -> pd.DataFrame:
    """Compatibility helper for a single leakage-safe encoding column."""
    return PointInTimeTargetEncoder().fit_transform(
        df, category_col, target_col, date_col=date_col
    )
