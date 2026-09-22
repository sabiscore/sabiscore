#!/usr/bin/env python3
"""
Advanced Feature Engineering Pipeline
120+ engineered features with temporal, contextual, and interaction features
"""

import pandas as pd
import numpy as np
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class AdvancedFeatureEngineer:
    """
    Comprehensive feature engineering pipeline
    Categories: Temporal, Statistical, Contextual, Interactions
    Target: 120+ features for maximum predictive power
    """

    def __init__(self):
        self.scalers = {}
        self.encoders = {}

    def engineer_all_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Master feature engineering pipeline"""
        logger.info("🔧 Engineering advanced features...")

        df = df.copy()

        # 1. Temporal Features
        df = self._add_temporal_features(df)

        # 2. Rolling Statistics (Multiple Windows)
        df = self._add_rolling_stats(df)

        # 3. Momentum & Trends
        df = self._add_momentum_features(df)

        # 4. Head-to-Head History
        df = self._add_h2h_features(df)

        # 5. League-Specific Context
        df = self._add_league_context(df)

        # 6. Weather & Venue Impact
        df = self._add_contextual_features(df)

        # 7. Feature Interactions
        df = self._add_interaction_features(df)

        # 8. Aggregated Team Metrics
        df = self._add_aggregated_metrics(df)

        # 9. Market Expectations (Odds-based)
        df = self._add_market_features(df)

        # 10. Psychological Factors
        df = self._add_psychological_features(df)

        logger.info(
            f"✅ Feature engineering complete! {len(df.columns)} features created"
        )

        return df

    def _add_temporal_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Time-based features"""
        if "date" not in df.columns and "match_date" in df.columns:
            df["date"] = df["match_date"]

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

            # Day of week (weekday vs weekend)
            df["day_of_week"] = df["date"].dt.dayofweek
            df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)

            # Month/Season effects
            df["month"] = df["date"].dt.month
            df["quarter"] = df["date"].dt.quarter

            # Season phase
            df["season_phase"] = pd.cut(
                df["month"], bins=[0, 3, 6, 9, 12], labels=[0, 1, 2, 3]
            ).astype(float)

            # Days since season start (approximation)
            if "season" in df.columns:
                season_start = df.groupby("season")["date"].transform("min")
                df["days_into_season"] = (df["date"] - season_start).dt.days
            else:
                # Use August 1st as season start
                year_start = df["date"].dt.year.map(
                    lambda x: pd.Timestamp(f"{x}-08-01")
                )
                df["days_into_season"] = (df["date"] - year_start).dt.days

        return df

    def _add_rolling_stats(self, df: pd.DataFrame) -> pd.DataFrame:
        """Multi-window rolling statistics"""
        windows = [3, 5, 10]  # Short, medium, long-term
        stats = [
            "goals",
            "goals_conceded",
            "shots",
            "shots_on_target",
            "possession",
            "corners",
            "fouls",
            "yellow_cards",
        ]

        for team_type in ["home", "away"]:
            team_col = f"{team_type}_team"

            if team_col not in df.columns:
                continue

            for stat in stats:
                stat_col = f"{team_type}_{stat}"

                # Use alternative column names if exact match not found
                if stat_col not in df.columns:
                    # Try common alternatives
                    alternatives = [
                        f"{stat}_{team_type}",
                        f"{team_type}_{stat}_avg",
                        stat,
                    ]
                    for alt in alternatives:
                        if alt in df.columns:
                            stat_col = alt
                            break
                    else:
                        continue  # Skip if not found

                for window in windows:
                    # Mean
                    df[f"{team_type}_{stat}_avg_{window}"] = df.groupby(team_col)[
                        stat_col
                    ].transform(lambda x: x.rolling(window, min_periods=1).mean())

                    # Std (consistency)
                    df[f"{team_type}_{stat}_std_{window}"] = df.groupby(team_col)[
                        stat_col
                    ].transform(
                        lambda x: x.rolling(window, min_periods=2).std().fillna(0)
                    )

                    # Max (peak performance)
                    df[f"{team_type}_{stat}_max_{window}"] = df.groupby(team_col)[
                        stat_col
                    ].transform(lambda x: x.rolling(window, min_periods=1).max())

                    # Min (worst performance)
                    df[f"{team_type}_{stat}_min_{window}"] = df.groupby(team_col)[
                        stat_col
                    ].transform(lambda x: x.rolling(window, min_periods=1).min())

        return df

    def _add_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Trend and momentum indicators"""

        def calculate_trend(series, window=5):
            """Linear regression slope"""
            if len(series) < 2:
                return 0
            x = np.arange(len(series))
            if len(x) != len(series):
                return 0
            try:
                coeffs = np.polyfit(x, series, 1)
                return coeffs[0]  # Slope
            except Exception:
                return 0

        for team_type in ["home", "away"]:
            team_col = f"{team_type}_team"

            if team_col not in df.columns:
                continue

            # Points trend (form improvement/decline)
            if "result" in df.columns:
                # Map results to points
                points_map = {"H": 3, "W": 3, "D": 1, "L": 0, "A": 0}
                df["points_temp"] = df["result"].map(points_map).fillna(0)

                df[f"{team_type}_points_trend"] = df.groupby(team_col)[
                    "points_temp"
                ].transform(
                    lambda x: (
                        x.rolling(5, min_periods=2)
                        .apply(calculate_trend, raw=False)
                        .fillna(0)
                    )
                )

                # Form (recent points per game)
                for window in [3, 5, 10]:
                    df[f"{team_type}_form_{window}"] = df.groupby(team_col)[
                        "points_temp"
                    ].transform(lambda x: x.rolling(window, min_periods=1).mean())

                df.drop("points_temp", axis=1, inplace=True)

        return df

    def _add_h2h_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Head-to-head historical performance"""
        h2h_stats = {}

        for idx, row in df.iterrows():
            if "home_team" not in row or "away_team" not in row:
                continue

            home, away = row["home_team"], row["away_team"]
            key = tuple(sorted([home, away]))

            if key not in h2h_stats:
                h2h_stats[key] = {
                    "total": 0,
                    "home_wins": 0,
                    "away_wins": 0,
                    "draws": 0,
                    "home_goals": 0,
                    "away_goals": 0,
                }

            # Assign current stats
            df.at[idx, "h2h_total"] = h2h_stats[key]["total"]
            df.at[idx, "h2h_home_wins"] = h2h_stats[key]["home_wins"]
            df.at[idx, "h2h_away_wins"] = h2h_stats[key]["away_wins"]
            df.at[idx, "h2h_draws"] = h2h_stats[key]["draws"]

            if h2h_stats[key]["total"] > 0:
                df.at[idx, "h2h_avg_goals"] = (
                    h2h_stats[key]["home_goals"] + h2h_stats[key]["away_goals"]
                ) / h2h_stats[key]["total"]
                df.at[idx, "h2h_home_win_pct"] = (
                    h2h_stats[key]["home_wins"] / h2h_stats[key]["total"]
                )
                df.at[idx, "h2h_draw_pct"] = (
                    h2h_stats[key]["draws"] / h2h_stats[key]["total"]
                )
            else:
                df.at[idx, "h2h_avg_goals"] = 0
                df.at[idx, "h2h_home_win_pct"] = 0
                df.at[idx, "h2h_draw_pct"] = 0

            # Update stats for future matches
            if "result" in row and pd.notna(row["result"]):
                h2h_stats[key]["total"] += 1

                if row["result"] in ["H", "W"]:
                    h2h_stats[key]["home_wins"] += 1
                elif row["result"] == "D":
                    h2h_stats[key]["draws"] += 1
                elif row["result"] in ["A", "L"]:
                    h2h_stats[key]["away_wins"] += 1

                if "home_goals" in row:
                    h2h_stats[key]["home_goals"] += row.get("home_goals", 0)
                if "away_goals" in row:
                    h2h_stats[key]["away_goals"] += row.get("away_goals", 0)

        # Fill NaN values
        h2h_cols = [
            "h2h_total",
            "h2h_home_wins",
            "h2h_away_wins",
            "h2h_draws",
            "h2h_avg_goals",
            "h2h_home_win_pct",
            "h2h_draw_pct",
        ]
        for col in h2h_cols:
            if col in df.columns:
                df[col] = df[col].fillna(0)

        return df

    def _add_league_context(self, df: pd.DataFrame) -> pd.DataFrame:
        """League-specific features"""

        # League table position (if available)
        if "home_position" in df.columns and "away_position" in df.columns:
            df["position_diff"] = df["home_position"] - df["away_position"]
            df["top_team_vs_bottom"] = (
                ((df["home_position"] <= 6) & (df["away_position"] >= 15))
                | ((df["away_position"] <= 6) & (df["home_position"] >= 15))
            ).astype(int)

            df["both_top_6"] = (
                (df["home_position"] <= 6) & (df["away_position"] <= 6)
            ).astype(int)
            df["both_bottom_6"] = (
                (df["home_position"] >= 15) & (df["away_position"] >= 15)
            ).astype(int)

        return df

    def _add_contextual_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Venue and environmental factors"""

        # Rest days
        for team_type in ["home", "away"]:
            team_col = f"{team_type}_team"
            if team_col in df.columns and "date" in df.columns:
                df[f"{team_type}_rest_days"] = (
                    df.groupby(team_col)["date"].diff().dt.days.fillna(7)
                )

        if "home_rest_days" in df.columns and "away_rest_days" in df.columns:
            df["rest_advantage"] = df["home_rest_days"] - df["away_rest_days"]

        # Match density (matches in last 7/14/30 days)
        if "date" in df.columns:
            for team_type in ["home", "away"]:
                team_col = f"{team_type}_team"
                if team_col not in df.columns:
                    continue

                for window in [7, 14, 30]:
                    # Count matches in rolling window
                    df[f"{team_type}_matches_last_{window}d"] = (
                        df.groupby(team_col)
                        .apply(
                            lambda x: x["date"].rolling(f"{window}D", on="date").count()
                        )
                        .reset_index(level=0, drop=True)
                        .fillna(0)
                    )

        return df

    def _add_interaction_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Feature interactions capturing complex relationships"""

        # Attack vs Defense matchup
        if (
            "home_goals_avg_5" in df.columns
            and "away_goals_conceded_avg_5" in df.columns
        ):
            df["attack_defense_home"] = df["home_goals_avg_5"] * (
                1 / (df["away_goals_conceded_avg_5"] + 0.1)
            )
            df["attack_defense_away"] = df["away_goals_avg_5"] * (
                1 / (df["home_goals_conceded_avg_5"] + 0.1)
            )

        # Form * Quality interaction
        if "home_form_5" in df.columns and "home_win_ratio" in df.columns:
            df["home_form_quality"] = df["home_form_5"] * df["home_win_ratio"]
            df["away_form_quality"] = df["away_form_5"] * df["away_win_ratio"]

        # Form difference
        if "home_form_5" in df.columns and "away_form_5" in df.columns:
            df["form_diff"] = df["home_form_5"] - df["away_form_5"]

        # Goal differential
        if "home_goals_avg_5" in df.columns and "away_goals_avg_5" in df.columns:
            df["goals_diff"] = df["home_goals_avg_5"] - df["away_goals_avg_5"]

        # Defensive comparison
        if (
            "home_goals_conceded_avg_5" in df.columns
            and "away_goals_conceded_avg_5" in df.columns
        ):
            df["defense_diff"] = (
                df["away_goals_conceded_avg_5"] - df["home_goals_conceded_avg_5"]
            )

        return df

    def _add_aggregated_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """High-level team strength indicators"""

        # Expected Goals (xG) approximation
        if (
            "home_shots_on_target_avg_5" in df.columns
            and "home_shots_avg_5" in df.columns
        ):
            df["home_xg_approx"] = (
                df["home_shots_on_target_avg_5"] * 0.35 + df["home_shots_avg_5"] * 0.1
            )
            df["away_xg_approx"] = (
                df["away_shots_on_target_avg_5"] * 0.35 + df["away_shots_avg_5"] * 0.1
            )

        # Defensive solidity index
        if "home_goals_conceded_avg_5" in df.columns:
            df["home_defensive_index"] = 1 / (df["home_goals_conceded_avg_5"] + 0.5)
            df["away_defensive_index"] = 1 / (df["away_goals_conceded_avg_5"] + 0.5)

        # Overall team strength (composite)
        strength_features = []
        for team_type in ["home", "away"]:
            if f"{team_type}_form_5" in df.columns:
                strength_features.append(f"{team_type}_form_5")
            if f"{team_type}_goals_avg_5" in df.columns:
                strength_features.append(f"{team_type}_goals_avg_5")

            if strength_features:
                df[f"{team_type}_strength"] = df[strength_features].mean(axis=1)
                strength_features = []

        return df

    def _add_market_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Betting market implied probabilities"""

        # Convert odds to probabilities
        if "home_odds" in df.columns:
            df["market_prob_home"] = 1 / df["home_odds"]
            df["market_prob_draw"] = 1 / df.get("draw_odds", 3.5)
            df["market_prob_away"] = 1 / df.get("away_odds", 3.5)

            # Market efficiency (overround)
            df["market_overround"] = (
                df["market_prob_home"] + df["market_prob_draw"] + df["market_prob_away"]
            )

            # Market favorite
            df["market_favorite_home"] = (
                df["market_prob_home"] > df["market_prob_away"]
            ).astype(int)

        return df

    def _add_psychological_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Momentum, pressure, confidence indicators"""

        # Win/loss streak
        def calculate_streak(results):
            """Calculate current streak"""
            if len(results) == 0:
                return 0
            streak = 0
            last_result = None
            for r in reversed(list(results)):
                if r in ["W", "H"]:
                    if last_result is None or last_result in ["W", "H"]:
                        streak += 1
                        last_result = r
                    else:
                        break
                elif r in ["L", "A"]:
                    if last_result is None or last_result in ["L", "A"]:
                        streak -= 1
                        last_result = r
                    else:
                        break
                else:
                    break
            return streak

        if "result" in df.columns:
            for team_type in ["home", "away"]:
                team_col = f"{team_type}_team"
                if team_col in df.columns:
                    df[f"{team_type}_streak"] = df.groupby(team_col)[
                        "result"
                    ].transform(
                        lambda x: (
                            x.rolling(10, min_periods=1)
                            .apply(lambda s: calculate_streak(s), raw=False)
                            .fillna(0)
                        )
                    )

        # Pressure (league position based)
        if "home_position" in df.columns:
            df["home_relegation_pressure"] = (df["home_position"] >= 15).astype(int)
            df["away_relegation_pressure"] = (df["away_position"] >= 15).astype(int)

            df["home_title_pressure"] = (df["home_position"] <= 3).astype(int)
            df["away_title_pressure"] = (df["away_position"] <= 3).astype(int)

        return df

    def get_feature_importance_categories(self) -> Dict[str, List[str]]:
        """Return feature names grouped by category"""
        return {
            "temporal": [
                "day_of_week",
                "is_weekend",
                "month",
                "quarter",
                "season_phase",
                "days_into_season",
            ],
            "rolling_stats": [
                col
                for col in [
                    "home_goals_avg_5",
                    "away_goals_avg_5",
                    "home_goals_conceded_avg_5",
                    "away_goals_conceded_avg_5",
                ]
            ],
            "momentum": [
                col
                for col in [
                    "home_form_5",
                    "away_form_5",
                    "home_points_trend",
                    "away_points_trend",
                ]
            ],
            "h2h": [
                col
                for col in ["h2h_total", "h2h_home_wins", "h2h_draws", "h2h_avg_goals"]
            ],
            "interactions": [
                col for col in ["form_diff", "goals_diff", "defense_diff"]
            ],
            "market": [
                col
                for col in ["market_prob_home", "market_prob_draw", "market_overround"]
            ],
            "psychological": [
                col
                for col in ["home_streak", "away_streak", "home_relegation_pressure"]
            ],
        }
