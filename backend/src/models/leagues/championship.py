# backend/src/models/leagues/championship.py
"""
Championship (EFL) Model - Optimized for unpredictability and parity
Key features: Wage budget disparity, 46-game marathon, playoff pressure
Target: 69.8% accuracy, +₦51 CLV, 0.198 Brier score

NAIRA METRICS (₦1,580/USD):
- Base Bankroll: ₦10,000
- Kelly Fraction: 1/8 (0.125)
- Min Edge: ₦66 (4.2%)
- Target CLV: +₦51 vs Pinnacle closing
- Expected ROI: +16.8% (Championship high variance)
"""

import numpy as np
import pandas as pd
from typing import Dict
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight
import redis


class ChampionshipModel:
    """
    Championship-specific model accounting for:
    - High variance (any team can beat any team)
    - Fixture congestion (midweek matches)
    - Financial disparity (parachute payments)
    - Physical football (most fouls in England)
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.scaler = StandardScaler()

        self.models = {
            "rf": RandomForestClassifier(
                n_estimators=240,
                max_depth=14,
                min_samples_split=12,
                min_samples_leaf=5,
                max_features="sqrt",
                class_weight="balanced",
                random_state=42,
            ),
            "xgb": XGBClassifier(
                n_estimators=210,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.88,
                colsample_bytree=0.85,
                gamma=0.28,
                min_child_weight=6,
                reg_alpha=0.18,
                reg_lambda=1.3,
                random_state=42,
            ),
            "lgbm": LGBMClassifier(
                n_estimators=190,
                max_depth=6,
                learning_rate=0.055,
                num_leaves=32,
                subsample=0.86,
                colsample_bytree=0.82,
                min_child_samples=35,
                reg_alpha=0.16,
                reg_lambda=1.1,
                class_weight="balanced",
                random_state=42,
            ),
            "extra": ExtraTreesClassifier(
                n_estimators=200,
                max_depth=13,
                min_samples_split=14,
                class_weight="balanced",
                random_state=42,
            ),
        }

        # Championship weights (balanced for unpredictability)
        self.ensemble_weights = {"rf": 0.30, "xgb": 0.35, "lgbm": 0.25, "extra": 0.10}

        self.is_trained = False

    def extract_championship_features(self, match_data: Dict) -> np.ndarray:
        """Extract 85 Championship-specific features"""
        features = []

        # === FINANCIAL DISPARITY (10 features) ===
        features.extend(
            [
                match_data.get("home_wage_bill_m", 20) / 50,
                match_data.get("away_wage_bill_m", 20) / 50,
                match_data.get("home_parachute_payment", 0),  # 1 if relegated from PL
                match_data.get("away_parachute_payment", 0),
                match_data.get("home_transfer_spend_m", 0) / 30,
                match_data.get("away_transfer_spend_m", 0) / 30,
                match_data.get("wage_bill_ratio", 1.0),  # home/away
                match_data.get("home_financial_power_index", 0.5),
                match_data.get("away_financial_power_index", 0.5),
                match_data.get("promoted_vs_relegated_match", 0),
            ]
        )

        # === FIXTURE CONGESTION (12 features) ===
        features.extend(
            [
                match_data.get("home_games_in_14_days", 3) / 6,
                match_data.get("away_games_in_14_days", 3) / 6,
                match_data.get("home_travel_distance_l3", 0) / 1000,  # Miles
                match_data.get("away_travel_distance_l3", 0) / 1000,
                match_data.get("home_squad_rotation_rate", 0.35),
                match_data.get("away_squad_rotation_rate", 0.35),
                match_data.get("home_injury_count", 0) / 8,
                match_data.get("away_injury_count", 0) / 8,
                match_data.get("home_minutes_played_l7d", 0) / 1200,
                match_data.get("away_minutes_played_l7d", 0) / 1200,
                match_data.get("home_fa_cup_active", 0),
                match_data.get("away_fa_cup_active", 0),
            ]
        )

        # === PHYSICAL INTENSITY (14 features) ===
        features.extend(
            [
                match_data.get("home_fouls_per_90", 0),
                match_data.get("away_fouls_per_90", 0),
                match_data.get("home_yellow_cards_l5", 0),
                match_data.get("away_yellow_cards_l5", 0),
                match_data.get("home_red_cards_season", 0),
                match_data.get("away_red_cards_season", 0),
                match_data.get("home_tackles_per_90", 0),
                match_data.get("away_tackles_per_90", 0),
                match_data.get("home_aerial_duels_won", 0.52),
                match_data.get("away_aerial_duels_won", 0.52),
                match_data.get("home_physical_play_index", 0.68),
                match_data.get("away_physical_play_index", 0.68),
                match_data.get("referee_cards_avg", 4.2),
                match_data.get("derby_intensity_factor", 0),
            ]
        )

        # === FORM & MOMENTUM (16 features) ===
        features.extend(
            [
                match_data.get("home_points_l5", 0) / 15,
                match_data.get("away_points_l5", 0) / 15,
                match_data.get("home_points_l10", 0) / 30,
                match_data.get("away_points_l10", 0) / 30,
                match_data.get("home_goals_scored_l5", 0),
                match_data.get("away_goals_scored_l5", 0),
                match_data.get("home_goals_conceded_l5", 0),
                match_data.get("away_goals_conceded_l5", 0),
                match_data.get("home_winning_streak", 0) / 7,
                match_data.get("away_winning_streak", 0) / 7,
                match_data.get("home_unbeaten_run", 0) / 12,
                match_data.get("away_unbeaten_run", 0) / 12,
                match_data.get("home_form_momentum", 0),  # Weighted recent form
                match_data.get("away_form_momentum", 0),
                match_data.get("home_goals_trend", 0),  # Scoring improving/declining
                match_data.get("away_goals_trend", 0),
            ]
        )

        # === ATTACKING METRICS (12 features) ===
        features.extend(
            [
                match_data.get("home_xg_l5", 0),
                match_data.get("away_xg_l5", 0),
                match_data.get("home_shots_per_90", 0),
                match_data.get("away_shots_per_90", 0),
                match_data.get("home_shot_accuracy", 0.34),
                match_data.get("away_shot_accuracy", 0.34),
                match_data.get("home_conversion_rate", 0.10),
                match_data.get("away_conversion_rate", 0.10),
                match_data.get("home_big_chances", 0),
                match_data.get("away_big_chances", 0),
                match_data.get("home_goals_per_game", 1.3),
                match_data.get("away_goals_per_game", 1.3),
            ]
        )

        # === DEFENSIVE SOLIDITY (10 features) ===
        features.extend(
            [
                match_data.get("home_xga_l5", 0),
                match_data.get("away_xga_l5", 0),
                match_data.get("home_clean_sheets_l5", 0) / 5,
                match_data.get("away_clean_sheets_l5", 0) / 5,
                match_data.get("home_goals_conceded_per_90", 1.3),
                match_data.get("away_goals_conceded_per_90", 1.3),
                match_data.get("home_save_percentage", 0.68),
                match_data.get("away_save_percentage", 0.68),
                match_data.get("home_defensive_errors", 0),
                match_data.get("away_defensive_errors", 0),
            ]
        )

        # === HOME ADVANTAGE (8 features) ===
        features.extend(
            [
                match_data.get("home_win_rate_home", 0.48),
                match_data.get("away_win_rate_away", 0.32),
                match_data.get("home_goals_per_game_home", 1.5),
                match_data.get("away_goals_per_game_away", 1.1),
                match_data.get("home_attendance_avg", 18000) / 35000,
                match_data.get("home_fortress_rating", 0.58),
                match_data.get("home_unbeaten_home", 0) / 10,
                match_data.get("away_travel_difficulty", 0),
            ]
        )

        # === PLAYOFF PRESSURE (13 features) ===
        features.extend(
            [
                match_data.get("home_table_position", 12) / 24,
                match_data.get("away_table_position", 12) / 24,
                match_data.get("home_playoff_contention", 0),  # 1 if in top 6 race
                match_data.get("away_playoff_contention", 0),
                match_data.get("home_relegation_threat", 0),  # 1 if bottom 3 risk
                match_data.get("away_relegation_threat", 0),
                match_data.get("home_points_from_playoffs", 0) / 20,
                match_data.get("away_points_from_playoffs", 0) / 20,
                match_data.get("home_points_from_relegation", 10) / 20,
                match_data.get("away_points_from_relegation", 10) / 20,
                match_data.get("must_win_scenario", 0),  # Critical match flag
                match_data.get("home_manager_pressure", 0.3),
                match_data.get("away_manager_pressure", 0.3),
            ]
        )

        return np.array(features).reshape(1, -1)

    def train(self, X_train: pd.DataFrame, y_train: pd.Series):
        """Train with isotonic calibration (BUG-001 fix)"""
        X_scaled = self.scaler.fit_transform(X_train)
        y_values = np.asarray(y_train).ravel()
        sample_weights = compute_sample_weight(class_weight="balanced", y=y_values)

        for name, model in self.models.items():
            print(f"Training {name} for Championship...")
            model.fit(X_scaled, y_values, sample_weight=sample_weights)

            calibrated = CalibratedClassifierCV(model, method="isotonic", cv=5)
            calibrated.fit(X_scaled, y_values, sample_weight=sample_weights)
            self.models[name] = calibrated

        self.is_trained = True
        print("✅ Championship model training complete")

    def predict_proba(self, match_data: Dict) -> Dict[str, float]:
        """Predictions with Championship variance adjustment"""
        if not self.is_trained:
            raise ValueError("Model not trained")

        X = self.extract_championship_features(match_data)
        X_scaled = self.scaler.transform(X)

        probs_home = probs_draw = probs_away = 0

        for name, model in self.models.items():
            pred = model.predict_proba(X_scaled)[0]
            weight = self.ensemble_weights[name]

            if len(pred) == 3:
                probs_home += pred[0] * weight
                probs_draw += pred[1] * weight
                probs_away += pred[2] * weight

        # Championship adjustments
        if match_data.get("home_parachute_payment", 0) == 1:
            probs_home *= 1.08  # Relegated PL teams have advantage

        if match_data.get("must_win_scenario", 0) == 1:
            probs_draw *= 0.88  # Desperate teams push for win

        # Normalize
        total = probs_home + probs_draw + probs_away

        return {
            "home_win": round(probs_home / total, 4),
            "draw": round(probs_draw / total, 4),
            "away_win": round(probs_away / total, 4),
            "confidence": round(max(probs_home, probs_draw, probs_away) / total, 4),
        }
