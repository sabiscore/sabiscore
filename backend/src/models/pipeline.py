"""Memory-bounded, chronological feature-engineering orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from ..data.imputation import LeagueTransitionDiscount
from ..features.target_encoding import PointInTimeTargetEncoder
from ..features.xg_elo import XGEloUpdater

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TargetEncodingSpec:
    category_col: str
    target_col: str
    output_col: str | None = None


class ChronologicalFeaturePipeline:
    """Build leakage-safe features in a single chronological pass where possible."""

    def __init__(
        self,
        *,
        target_encodings: Sequence[TargetEncodingSpec] = (),
        xg_elo: XGEloUpdater | None = None,
        transition_discount: LeagueTransitionDiscount | None = None,
    ) -> None:
        self.target_encodings = tuple(target_encodings)
        self.xg_elo = xg_elo or XGEloUpdater()
        self.transition_discount = transition_discount or LeagueTransitionDiscount()

    @staticmethod
    def _chronological(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
        if date_col not in df.columns:
            raise ValueError(f"Missing date column: {date_col}")
        out = df.copy()
        out[date_col] = pd.to_datetime(out[date_col], errors="raise")
        return out.sort_values(date_col, kind="mergesort").reset_index(drop=True)

    @staticmethod
    def _downcast_numeric(df: pd.DataFrame) -> None:
        """Downcast numeric feature columns in-place without changing integers used as IDs."""
        for column in df.columns:
            series = df[column]
            if pd.api.types.is_float_dtype(series):
                df[column] = pd.to_numeric(series, downcast="float")
            elif pd.api.types.is_integer_dtype(series) and series.dtype.itemsize > 4:
                # Keep identifier semantics but avoid unnecessary 64-bit feature storage.
                df[column] = pd.to_numeric(series, downcast="integer")

    def _apply_transition_priors(self, df: pd.DataFrame) -> None:
        """Add promoted-team priors season-by-season using only earlier seasons."""
        required = {"season", "home_team", "away_team", "home_xg", "away_xg"}
        missing = required.difference(df.columns)
        if missing:
            logger.info("Skipping transition priors; missing columns: %s", sorted(missing))
            return

        df["home_xg_cold_start"] = np.full(len(df), np.nan, dtype=np.float32)
        df["away_xg_cold_start"] = np.full(len(df), np.nan, dtype=np.float32)
        seasons = sorted(df["season"].dropna().unique())
        for season in seasons:
            # The helper computes the league prior from season < target season.
            try:
                season_frame, promoted = self.transition_discount.apply(df, season)
            except ValueError as exc:
                if "Prior-season xG history is required" in str(exc):
                    continue
                raise
            if not promoted:
                continue
            mask = df["season"].eq(season)
            df.loc[mask, "home_xg_cold_start"] = season_frame.loc[mask, "home_xg_cold_start"].to_numpy(dtype=np.float32)
            df.loc[mask, "away_xg_cold_start"] = season_frame.loc[mask, "away_xg_cold_start"].to_numpy(dtype=np.float32)

    def transform(self, df: pd.DataFrame, *, date_col: str = "date") -> pd.DataFrame:
        """Return training-ready engineered features with strict temporal ordering."""
        out = self._chronological(df, date_col)
        self._apply_transition_priors(out)

        # XG-Elo emits pre-match state before applying each match's observed xG.
        out = self.xg_elo.calculate_ratings(out, date_col=date_col)

        for spec in self.target_encodings:
            encoder = PointInTimeTargetEncoder()
            out = encoder.fit_transform(
                out,
                spec.category_col,
                spec.target_col,
                date_col=date_col,
                output_col=spec.output_col,
            )

        self._downcast_numeric(out)
        return out


def build_training_features(
    df: pd.DataFrame,
    *,
    target_encodings: Sequence[TargetEncodingSpec] = (),
    date_col: str = "date",
) -> pd.DataFrame:
    """Convenience entry point used by training jobs and validation tests."""
    pipeline = ChronologicalFeaturePipeline(target_encodings=target_encodings)
    return pipeline.transform(df, date_col=date_col)
