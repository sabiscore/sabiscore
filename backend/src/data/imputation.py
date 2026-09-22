"""Leakage-safe cold-start imputation for football features."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LeagueTransitionDiscount:
    """Cold-start prior for teams entering a top-flight competition.

    The scalar defaults are configuration values, not certified empirical
    claims. Calibration must be performed on historical holdouts before they
    are used in a production policy decision.
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
        return set(subset["home_team"].dropna().astype(str)) | set(
            subset["away_team"].dropna().astype(str)
        )

    def promoted_teams(self, df: pd.DataFrame, target_season: object) -> set[str]:
        """Identify current-season teams with insufficient top-flight history."""
        required = {"season", "home_team", "away_team"}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {sorted(missing)}")

        prior = df.loc[df["season"] < target_season]
        current_teams = self._teams_in_season(df, target_season)
        history_counts: dict[str, int] = {}
        for season in sorted(prior["season"].dropna().unique()):
            for team in self._teams_in_season(prior, season):
                history_counts[team] = history_counts.get(team, 0) + 1
        return {
            team
            for team in current_teams
            if history_counts.get(team, 0) < self.minimum_history_seasons
        }

    def baselines(self, df: pd.DataFrame, target_season: object) -> dict[str, float]:
        """Compute discounted league-average priors using prior seasons only."""
        required = {"season", "home_xg", "away_xg"}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {sorted(missing)}")

        history = df.loc[df["season"] < target_season, ["home_xg", "away_xg"]]
        home_mean = pd.to_numeric(history["home_xg"], errors="coerce").mean()
        away_mean = pd.to_numeric(history["away_xg"], errors="coerce").mean()
        if not np.isfinite(home_mean) or not np.isfinite(away_mean):
            raise ValueError(
                "Prior-season xG history is required for cold-start baselines"
            )
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
        """Add cold-start priors only to promoted-team rows.

        Existing observations are never overwritten, and unrelated missing
        values remain missing so downstream evidence gates can distinguish
        unavailable data from imputed cold-start priors.
        """
        required = {"season", "home_team", "away_team", "home_xg", "away_xg"}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {sorted(missing)}")

        out = df.copy()
        promoted = self.promoted_teams(out, target_season)
        out[home_baseline_col] = np.full(len(out), np.nan, dtype=np.float32)
        out[away_baseline_col] = np.full(len(out), np.nan, dtype=np.float32)
        if not promoted:
            return out, promoted

        baseline = self.baselines(out, target_season)
        home_mask = (out["season"] == target_season) & out["home_team"].isin(promoted)
        away_mask = (out["season"] == target_season) & out["away_team"].isin(promoted)
        out.loc[home_mask, home_baseline_col] = np.float32(baseline["home_xg"])
        out.loc[away_mask, away_baseline_col] = np.float32(baseline["away_xg"])
        return out, promoted
