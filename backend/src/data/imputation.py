"""Leakage-safe imputation and cold-start baselines for football features.

All estimators in this module are point-in-time: a row can only consume
information whose event timestamp is strictly earlier than that row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LeagueTransitionDiscount:
    """Cold-start prior for teams entering a top-flight competition.

    The defaults are deliberately configuration values, not empirical claims.
    They must be calibrated and certified against SabiScore's historical
    holdouts before being used as a performance assertion.
    """

    offensive_discount: float = 0.75
    defensive_penalty: float = 1.30
    minimum_history_seasons: int = 1

    def __post_init__(self) -> None:
        if not 0 < self.offensive_discount <= 1:
            raise ValueError("offensive_discount must be in (0, 1]")
        if self.defensive_penalty < 1:
            raise ValueError("defensive_penalty must be >= 1")
        if self.minimum_history_seasons < 1:
            raise ValueError("minimum_history_seasons must be >= 1")

    @staticmethod
    def _teams_in_season(frame: pd.DataFrame, season: object) -> set[str]:
        subset = frame.loc[frame["season"] == season, ["home_team", "away_team"]]
        if subset.empty:
            return set()
        return set(subset["home_team"].dropna().astype(str)) | set(
            subset["away_team"].dropna().astype(str)
        )

    def promoted_teams(
        self,
        df: pd.DataFrame,
        target_season: object,
        *,
        season_col: str = "season",
        home_team_col: str = "home_team",
        away_team_col: str = "away_team",
    ) -> set[str]:
        """Return teams with insufficient prior top-flight history."""
        required = {season_col, home_team_col, away_team_col}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {sorted(missing)}")

        prior = df.loc[df[season_col] < target_season]
        if prior.empty:
            current = df.loc[df[season_col] == target_season]
            return set(current[home_team_col].dropna().astype(str)) | set(
                current[away_team_col].dropna().astype(str)
            )

        history_counts: dict[str, int] = {}
        for season in sorted(prior[season_col].dropna().unique()):
            for team in self._teams_in_season(prior, season):
                history_counts[team] = history_counts.get(team, 0) + 1

        current_teams = self._teams_in_season(df, target_season)
        return {
            team
            for team in current_teams
            if history_counts.get(team, 0) < self.minimum_history_seasons
        }

    def baselines(
        self,
        df: pd.DataFrame,
        target_season: object,
        *,
        season_col: str = "season",
        home_xg_col: str = "home_xg",
        away_xg_col: str = "away_xg",
    ) -> dict[str, float]:
        """Calculate discounted league-average xG priors from prior seasons."""
        required = {season_col, home_xg_col, away_xg_col}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {sorted(missing)}")

        history = df.loc[df[season_col] < target_season, [home_xg_col, away_xg_col]]
        home_mean = pd.to_numeric(history[home_xg_col], errors="coerce").mean()
        away_mean = pd.to_numeric(history[away_xg_col], errors="coerce").mean()
        if not np.isfinite(home_mean) or not np.isfinite(away_mean):
            raise ValueError("Prior-season xG history is required for cold-start baselines")

        return {
            "home_xg": float(home_mean * self.offensive_discount),
            "away_xg": float(away_mean * self.offensive_discount),
            "home_concession_xg": float(home_mean * self.defensive_penalty),
            "away_concession_xg": float(away_mean * self.defensive_penalty),
        }

    def apply(
        self,
        df: pd.DataFrame,
        target_season: object,
        *,
        home_baseline_col: str = "home_xg_cold_start",
        away_baseline_col: str = "away_xg_cold_start",
    ) -> tuple[pd.DataFrame, set[str]]:
        """Add cold-start baseline columns without filling unrelated missing data."""
        required = {"season", "home_team", "away_team", "home_xg", "away_xg"}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {sorted(missing)}")

        out = df.copy()
        promoted = self.promoted_teams(out, target_season)
        prior = out.loc[out["season"] < target_season]
        if prior.empty or not promoted:
            out[home_baseline_col] = np.nan
            out[away_baseline_col] = np.nan
            return out, promoted

        baseline = self.baselines(out, target_season)
        out[home_baseline_col] = np.nan
        out[away_baseline_col] = np.nan
        target_mask = (out["season"] == target_season) & out["home_team"].isin(promoted)
        out.loc[target_mask, home_baseline_col] = np.float32(baseline["home_xg"])
        target_away_mask = (out["season"] == target_season) & out["away_team"].isin(promoted)
        out.loc[target_away_mask, away_baseline_col] = np.float32(baseline["away_xg"])
        out[home_baseline_col] = out[home_baseline_col].astype(np.float32)
        out[away_baseline_col] = out[away_baseline_col].astype(np.float32)
        return out, promoted


def chronological_numeric_impute(
    df: pd.DataFrame,
    columns: Iterable[str],
    *,
    date_col: str = "date",
) -> pd.DataFrame:
    """Fill numeric gaps with the latest prior observation, never a future value.

    Leading gaps remain NaN because inventing a value would hide unavailable
    evidence. A downstream model may apply a model-specific imputer after the
    chronological feature construction step.
    """
    if date_col not in df.columns:
        raise ValueError(f"Missing date column: {date_col}")
    out = df.copy()
    dates = pd.to_datetime(out[date_col], errors="raise")
    order = dates.argsort(kind="mergesort")
    out = out.iloc[order].copy()
    for column in columns:
        if column not in out.columns:
            raise ValueError(f"Missing column: {column}")
        if not pd.api.types.is_numeric_dtype(out[column]):
            raise TypeError(f"Column {column!r} must be numeric")
        out[column] = out[column].ffill().astype(np.float32)
    return out
