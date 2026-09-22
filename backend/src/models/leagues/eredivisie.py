# backend/src/models/leagues/eredivisie.py
"""
Eredivisie Model - Optimized for attacking football and Ajax dominance
Key features: High-scoring matches (3.0 GPG), youth development, Ajax superiority
Target: 71.2% accuracy, +₦52 CLV, 0.194 Brier score

NAIRA METRICS (₦1,580/USD):
- Base Bankroll: ₦10,000
- Kelly Fraction: 1/8 (0.125)
- Min Edge: ₦66 (4.2%)
- Target CLV: +₦52 vs Pinnacle closing
- Expected ROI: +17.2% (high-scoring matches = more variance)
"""

import numpy as np
import pandas as pd
from typing import Dict
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight
import redis


class EredivisieModel:
    """
    Eredivisie-specific model accounting for:
    - High-scoring matches (3.0 goals per game)
    - Ajax/PSV/Feyenoord dominance (60% of titles)
    - Youth talent breakouts
    - Technical, attacking football
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.scaler = StandardScaler()

        self.models = {
            "rf": RandomForestClassifier(
                n_estimators=250,
                max_depth=15,
                min_samples_split=10,
                min_samples_leaf=4,
                random_state=42,
            ),
            "xgb": XGBClassifier(
                n_estimators=220,
                max_depth=6,
                learning_rate=0.045,
                subsample=0.87,
                colsample_bytree=0.83,
                gamma=0.24,
                random_state=42,
            ),
            "lgbm": LGBMClassifier(
                n_estimators=200,
                max_depth=7,
                learning_rate=0.05,
                num_leaves=38,
                subsample=0.85,
                colsample_bytree=0.80,
                random_state=42,
            ),
            "gb": GradientBoostingClassifier(
                n_estimators=180,
                max_depth=5,
                learning_rate=0.055,
                subsample=0.84,
                random_state=42,
            ),
        }

        # Eredivisie weights
        self.ensemble_weights = {"rf": 0.32, "xgb": 0.37, "lgbm": 0.23, "gb": 0.08}

        self.is_trained = False

    def extract_eredivisie_features(self, match_data: Dict) -> np.ndarray:
        """Extract 82 Eredivisie-specific features"""
        features = []

        # === BIG 3 DOMINANCE (10 features) ===
        features.extend(
            [
                match_data.get("home_big_3", 0),  # 1 if Ajax/PSV/Feyenoord
                match_data.get("away_big_3", 0),
                match_data.get("home_european_coefficient", 0) / 100,
                match_data.get("away_european_coefficient", 0) / 100,
                match_data.get("home_title_wins_history", 0) / 35,
                match_data.get("away_title_wins_history", 0) / 35,
                match_data.get("big_3_vs_rest", 0),  # 1 if big3 vs small club
                match_data.get(
                    "home_european_fatigue", 0
                ),  # Played in Europe this week
                match_data.get("away_european_fatigue", 0),
                match_data.get("squad_value_gap", 1.0),  # Ratio
            ]
        )

        # === ATTACKING PHILOSOPHY (16 features) ===
        features.extend(
            [
                match_data.get("home_goals_scored_l5", 0),
                match_data.get("away_goals_scored_l5", 0),
                match_data.get("home_xg_l5", 0),
                match_data.get("away_xg_l5", 0),
                match_data.get("home_goals_per_game", 1.8),
                match_data.get("away_goals_per_game", 1.8),
                match_data.get("home_shots_per_90", 0),
                match_data.get("away_shots_per_90", 0),
                match_data.get("home_attacking_third_entries", 0),
                match_data.get("away_attacking_third_entries", 0),
                match_data.get("home_progressive_passes", 0),
                match_data.get("away_progressive_passes", 0),
                match_data.get("home_key_passes", 0),
                match_data.get("away_key_passes", 0),
                match_data.get("home_over_2_5_rate", 0.58),
                match_data.get("away_over_2_5_rate", 0.58),
            ]
        )

        # === YOUTH DEVELOPMENT (12 features) ===
        features.extend(
            [
                match_data.get("home_academy_players", 0) / 7,
                match_data.get("away_academy_players", 0) / 7,
                match_data.get("home_avg_age", 24.8) / 35,
                match_data.get("away_avg_age", 24.8) / 35,
                match_data.get("home_u21_minutes_pct", 0.38),
                match_data.get("away_u21_minutes_pct", 0.38),
                match_data.get("home_breakthrough_talent", 0),  # Star youngster flag
                match_data.get("away_breakthrough_talent", 0),
                match_data.get("home_talent_export_value", 0) / 50,  # €M sold
                match_data.get("away_talent_export_value", 0) / 50,
                match_data.get("home_youth_promotion_rate", 0.42),
                match_data.get("away_youth_promotion_rate", 0.42),
            ]
        )

        # === TECHNICAL QUALITY (14 features) ===
        features.extend(
            [
                match_data.get("home_pass_completion", 78) / 100,
                match_data.get("away_pass_completion", 78) / 100,
                match_data.get("home_possession_avg", 52) / 100,
                match_data.get("away_possession_avg", 52) / 100,
                match_data.get("home_dribble_success", 0.56),
                match_data.get("away_dribble_success", 0.56),
                match_data.get("home_through_balls", 0),
                match_data.get("away_through_balls", 0),
                match_data.get("home_shot_creating_actions", 0),
                match_data.get("away_shot_creating_actions", 0),
                match_data.get("home_build_up_play_speed", 5.8),  # Seconds
                match_data.get("away_build_up_play_speed", 5.8),
                match_data.get("home_creative_midfielders", 0) / 4,
                match_data.get("away_creative_midfielders", 0) / 4,
            ]
        )

        # === DEFENSIVE VULNERABILITY (10 features) ===
        features.extend(
            [
                match_data.get("home_goals_conceded_l5", 0),
                match_data.get("away_goals_conceded_l5", 0),
                match_data.get("home_xga_l5", 0),
                match_data.get("away_xga_l5", 0),
                match_data.get("home_clean_sheets_l5", 0) / 5,
                match_data.get("away_clean_sheets_l5", 0) / 5,
                match_data.get("home_defensive_actions", 0),
                match_data.get("away_defensive_actions", 0),
                match_data.get("home_goals_conceded_per_90", 1.5),
                match_data.get("away_goals_conceded_per_90", 1.5),
            ]
        )

        # === HOME ADVANTAGE (8 features) ===
        features.extend(
            [
                match_data.get("home_win_rate_home", 0.56),
                match_data.get("away_win_rate_away", 0.34),
                match_data.get("home_goals_per_game_home", 2.1),
                match_data.get("away_goals_per_game_away", 1.4),
                match_data.get("home_attendance_support", 0.72),
                match_data.get("home_fortress_rating", 0.64),
                match_data.get("home_unbeaten_home", 0) / 12,
                match_data.get("artificial_pitch", 0),  # Some clubs use artificial turf
            ]
        )

        # === FORM & MOMENTUM (12 features) ===
        features.extend(
            [
                match_data.get("home_points_l5", 0) / 15,
                match_data.get("away_points_l5", 0) / 15,
                match_data.get("home_winning_streak", 0) / 8,
                match_data.get("away_winning_streak", 0) / 8,
                match_data.get("home_unbeaten_run", 0) / 12,
                match_data.get("away_unbeaten_run", 0) / 12,
                match_data.get("home_goals_last_3", 0) / 12,
                match_data.get("away_goals_last_3", 0) / 12,
                match_data.get("h2h_home_wins_l5", 0) / 5,
                match_data.get("h2h_goals_per_game", 3.0),
                match_data.get("h2h_btts_rate", 0.68),  # Both teams to score
                match_data.get("recent_form_differential", 0),
            ]
        )

        return np.array(features).reshape(1, -1)

    def train(self, X_train: pd.DataFrame, y_train: pd.Series):
        """Train with isotonic calibration and balanced sample weights (C11 / BUG-007)."""
        X_scaled = self.scaler.fit_transform(X_train)
        sample_weights = compute_sample_weight(class_weight="balanced", y=y_train)

        for name, model in self.models.items():
            print(f"Training {name} for Eredivisie...")
            model.fit(X_scaled, y_train, sample_weight=sample_weights)

            calibrated = CalibratedClassifierCV(model, method="isotonic", cv=5)
            calibrated.fit(X_scaled, y_train, sample_weight=sample_weights)
            self.models[name] = calibrated

        self.is_trained = True
        print("✅ Eredivisie model training complete")

    def predict_proba(self, match_data: Dict) -> Dict[str, float]:
        """Predictions with Eredivisie high-scoring adjustments"""
        if not self.is_trained:
            raise ValueError("Model not trained")

        X = self.extract_eredivisie_features(match_data)
        X_scaled = self.scaler.transform(X)

        probs_home = probs_draw = probs_away = 0

        for name, model in self.models.items():
            pred = model.predict_proba(X_scaled)[0]
            weight = self.ensemble_weights[name]

            if len(pred) == 3:
                probs_home += pred[0] * weight
                probs_draw += pred[1] * weight
                probs_away += pred[2] * weight

        # Eredivisie adjustments
        if match_data.get("big_3_vs_rest", 0) == 1:
            if match_data.get("home_big_3", 0) == 1:
                probs_home *= 1.14  # Big 3 home advantage
                probs_draw *= 0.90

        if match_data.get("h2h_goals_per_game", 3.0) > 3.5:
            probs_draw *= 0.85  # High-scoring matches reduce draws

        # Normalize
        total = probs_home + probs_draw + probs_away

        return {
            "home_win": round(probs_home / total, 4),
            "draw": round(probs_draw / total, 4),
            "away_win": round(probs_away / total, 4),
            "confidence": round(max(probs_home, probs_draw, probs_away) / total, 4),
        }
