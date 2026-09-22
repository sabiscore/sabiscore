"""Sequential opponent-adjusted xG ratings."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class XGEloUpdater:
    """Maintain lightweight offense/concession ratings in chronological order.

    Ratings are pre-match state. A match's observed xG is applied only after
    its pre-match features have been emitted. This makes the output directly
    usable for walk-forward training and inference.
    """

    k_factor: float = 0.10
    home_advantage: float = 0.20
    league_xg: float = 1.30
    initial_rating: float = 1.0
    min_rating: float = 0.05
    offense_ratings: dict[object, float] = field(default_factory=dict)
    defense_ratings: dict[object, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.k_factor <= 0:
            raise ValueError("k_factor must be positive")
        if self.league_xg <= 0:
            raise ValueError("league_xg must be positive")
        if self.min_rating <= 0:
            raise ValueError("min_rating must be positive")

    def _get(self, team: object, ratings: dict[object, float]) -> float:
        return float(ratings.get(team, self.initial_rating))

    def _expected_xg(
        self, offense: float, opponent_defense: float, *, home: bool
    ) -> float:
        home_multiplier = (
            1.0 + self.home_advantage if home else 1.0 - self.home_advantage
        )
        return max(0.0, self.league_xg * offense * opponent_defense * home_multiplier)

    def calculate_ratings(
        self,
        df: pd.DataFrame,
        *,
        date_col: str = "date",
        home_team_col: str = "home_team",
        away_team_col: str = "away_team",
        home_xg_col: str = "home_xg",
        away_xg_col: str = "away_xg",
    ) -> pd.DataFrame:
        required = {date_col, home_team_col, away_team_col, home_xg_col, away_xg_col}
        missing = required.difference(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {sorted(missing)}")

        out = df.copy()
        out[date_col] = pd.to_datetime(out[date_col], errors="raise")
        order = out[date_col].argsort(kind="mergesort")
        out = out.iloc[order].reset_index(drop=True)
        if out[date_col].is_monotonic_increasing is False:
            raise AssertionError("xG-Elo input could not be sorted chronologically")

        columns = {
            "pre_match_home_offense": np.empty(len(out), dtype=np.float32),
            "pre_match_away_offense": np.empty(len(out), dtype=np.float32),
            "pre_match_home_defense": np.empty(len(out), dtype=np.float32),
            "pre_match_away_defense": np.empty(len(out), dtype=np.float32),
            "expected_home_xg": np.empty(len(out), dtype=np.float32),
            "expected_away_xg": np.empty(len(out), dtype=np.float32),
        }

        for idx, row in out.iterrows():
            home = row[home_team_col]
            away = row[away_team_col]
            home_off = self._get(home, self.offense_ratings)
            away_off = self._get(away, self.offense_ratings)
            home_def = self._get(home, self.defense_ratings)
            away_def = self._get(away, self.defense_ratings)

            expected_home = self._expected_xg(home_off, away_def, home=True)
            expected_away = self._expected_xg(away_off, home_def, home=False)

            columns["pre_match_home_offense"][idx] = home_off
            columns["pre_match_away_offense"][idx] = away_off
            columns["pre_match_home_defense"][idx] = home_def
            columns["pre_match_away_defense"][idx] = away_def
            columns["expected_home_xg"][idx] = expected_home
            columns["expected_away_xg"][idx] = expected_away

            actual_home = float(row[home_xg_col])
            actual_away = float(row[away_xg_col])
            if not np.isfinite(actual_home) or not np.isfinite(actual_away):
                # A match without observed xG cannot update the state. Its
                # pre-match features remain valid and no fabricated outcome is used.
                continue

            home_residual = actual_home - expected_home
            away_residual = actual_away - expected_away

            self.offense_ratings[home] = max(
                self.min_rating, home_off + self.k_factor * home_residual
            )
            self.offense_ratings[away] = max(
                self.min_rating, away_off + self.k_factor * away_residual
            )
            # Higher defense rating means more xG conceded (weaker defense).
            self.defense_ratings[away] = max(
                self.min_rating, away_def + self.k_factor * home_residual
            )
            self.defense_ratings[home] = max(
                self.min_rating, home_def + self.k_factor * away_residual
            )

        for name, values in columns.items():
            out[name] = values
        return out

    def snapshot(self) -> dict[str, dict[object, float]]:
        """Return a copy of the current state for persistence."""
        return {
            "offense": dict(self.offense_ratings),
            "defense": dict(self.defense_ratings),
        }
