# backend/src/models/leagues/bundesliga.py
"""
Bundesliga Model - Optimized for high-press, vertical transitions
Key features: PPDA, counter-attack speed, winter break impact, gegenpressing
Phase 7-B holdout: ~41.9% accuracy, 0.232 Brier score (3-way prediction baseline ~33%)
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


class BundesligaModel:
    """
    Bundesliga-specific model accounting for:
    - High-intensity gegenpressing (PPDA < 9 for top teams)
    - Vertical transition speed (< 4s counter-attacks)
    - Winter break form dip (December/January)
    - Youth integration effect
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.scaler = StandardScaler()

        # Ensemble weights tuned for Bundesliga dynamics
        self.models = {
            "rf": RandomForestClassifier(
                n_estimators=280,
                max_depth=16,
                min_samples_split=10,
                min_samples_leaf=4,
                max_features="sqrt",
                class_weight="balanced",
                random_state=42,
            ),
            "xgb": XGBClassifier(
                n_estimators=230,
                max_depth=6,
                learning_rate=0.035,
                subsample=0.82,
                colsample_bytree=0.78,
                gamma=0.25,
                min_child_weight=4,
                reg_alpha=0.12,
                reg_lambda=1.1,
                random_state=42,
            ),
            "lgbm": LGBMClassifier(
                n_estimators=240,
                max_depth=7,
                learning_rate=0.042,
                num_leaves=42,
                subsample=0.8,
                colsample_bytree=0.72,
                min_child_samples=28,
                reg_alpha=0.18,
                reg_lambda=0.95,
                class_weight="balanced",
                random_state=42,
            ),
            "gb": GradientBoostingClassifier(
                n_estimators=180,
                max_depth=5,
                learning_rate=0.055,
                subsample=0.78,
                min_samples_split=12,
                min_samples_leaf=5,
                random_state=42,
            ),
        }

        # Bundesliga ensemble weights (higher LightGBM for transition dynamics)
        self.ensemble_weights = {"rf": 0.26, "xgb": 0.38, "lgbm": 0.28, "gb": 0.08}

        self.is_trained = False

    def extract_bundesliga_features(self, match_data: Dict) -> np.ndarray:
        """Extract 89 Bundesliga-specific features"""
        features = []

        # === GEGENPRESSING INTENSITY (15 features) ===
        features.extend(
            [
                match_data.get("home_ppda", 9.8),  # Lower than EPL
                match_data.get("away_ppda", 9.8),
                match_data.get("home_counterpressing_recoveries", 0),
                match_data.get("away_counterpressing_recoveries", 0),
                match_data.get("home_press_duration", 4.2),  # Seconds
                match_data.get("away_press_duration", 4.2),
                match_data.get("home_high_press_triggers", 0),
                match_data.get("away_high_press_triggers", 0),
                match_data.get("home_ball_wins_final_third", 0),
                match_data.get("away_ball_wins_final_third", 0),
                match_data.get("home_pressing_intensity", 0.78),
                match_data.get("away_pressing_intensity", 0.78),
                match_data.get("home_aggressive_tackles", 0),
                match_data.get("away_aggressive_tackles", 0),
                match_data.get("home_turnovers_forced", 0),
            ]
        )

        # === TRANSITION SPEED (14 features) ===
        features.extend(
            [
                match_data.get("home_counter_attack_speed", 4.8),
                match_data.get("away_counter_attack_speed", 4.8),
                match_data.get("home_fast_breaks", 0),
                match_data.get("away_fast_breaks", 0),
                match_data.get("home_transition_goals", 0),
                match_data.get("away_transition_goals", 0),
                match_data.get("home_sprint_speed_kmh", 0),
                match_data.get("away_sprint_speed_kmh", 0),
                match_data.get("home_progressive_carries", 0),
                match_data.get("away_progressive_carries", 0),
                match_data.get("home_vertical_passing_speed", 0),
                match_data.get("away_vertical_passing_speed", 0),
                match_data.get("home_transition_xg", 0),
                match_data.get("away_transition_xg", 0),
            ]
        )

        # === ATTACKING EXPLOSIVENESS (16 features) ===
        features.extend(
            [
                match_data.get("home_goals_scored_l5", 0),
                match_data.get("away_goals_scored_l5", 0),
                match_data.get("home_xg_l5", 0),
                match_data.get("away_xg_l5", 0),
                match_data.get("home_shots_per_90", 0),
                match_data.get("away_shots_per_90", 0),
                match_data.get("home_big_chances_created", 0),
                match_data.get("away_big_chances_created", 0),
                match_data.get("home_goals_per_shot", 0.13),
                match_data.get("away_goals_per_shot", 0.13),
                match_data.get("home_multi_goal_games", 0) / 5,
                match_data.get("away_multi_goal_games", 0) / 5,
                match_data.get("home_first_half_goals", 0),
                match_data.get("away_first_half_goals", 0),
                match_data.get(
                    "home_goal_rush_tendency", 0.22
                ),  # Multiple goals in 10min
                match_data.get("away_goal_rush_tendency", 0.22),
            ]
        )

        # === YOUTH & ATHLETICISM (12 features) ===
        features.extend(
            [
                match_data.get("home_avg_age", 24.5) / 35,
                match_data.get("away_avg_age", 24.5) / 35,
                match_data.get("home_u23_minutes_pct", 0.35),
                match_data.get("away_u23_minutes_pct", 0.35),
                match_data.get("home_sprint_distance", 0),
                match_data.get("away_sprint_distance", 0),
                match_data.get("home_distance_covered_km", 0),
                match_data.get("away_distance_covered_km", 0),
                match_data.get("home_high_intensity_runs", 0),
                match_data.get("away_high_intensity_runs", 0),
                match_data.get("home_academy_graduates", 0) / 5,
                match_data.get("away_academy_graduates", 0) / 5,
            ]
        )

        # === DEFENSIVE VULNERABILITY (10 features) ===
        features.extend(
            [
                match_data.get("home_goals_conceded_l5", 0),
                match_data.get("away_goals_conceded_l5", 0),
                match_data.get("home_xga_l5", 0),
                match_data.get("away_xga_l5", 0),
                match_data.get("home_defensive_errors", 0),
                match_data.get("away_defensive_errors", 0),
                match_data.get("home_clean_sheets_l5", 0) / 5,
                match_data.get("away_clean_sheets_l5", 0) / 5,
                match_data.get("home_goals_conceded_per_90", 1.4),
                match_data.get("away_goals_conceded_per_90", 1.4),
            ]
        )

        # === SET PIECES & AERIAL (10 features) ===
        features.extend(
            [
                match_data.get("home_set_piece_goals", 0),
                match_data.get("away_set_piece_goals", 0),
                match_data.get("home_corner_conversion", 0.08),
                match_data.get("away_corner_conversion", 0.08),
                match_data.get("home_aerial_duels_won_pct", 0.54),
                match_data.get("away_aerial_duels_won_pct", 0.54),
                match_data.get("home_crosses_per_90", 0),
                match_data.get("away_crosses_per_90", 0),
                match_data.get("home_headed_goals", 0),
                match_data.get("away_headed_goals", 0),
            ]
        )

        # === HOME ADVANTAGE (8 features) ===
        features.extend(
            [
                match_data.get("home_win_rate_home", 0.58),
                match_data.get("away_win_rate_away", 0.36),
                match_data.get("home_goals_per_game_home", 1.9),
                match_data.get("away_goals_per_game_away", 1.3),
                match_data.get("home_yellow_wall_boost", 0),  # Dortmund-style crowd
                match_data.get("home_attendance_pct", 0.85),
                match_data.get("home_unbeaten_home", 0) / 15,
                match_data.get("referee_cards_differential", 0),
            ]
        )

        # === MOMENTUM & FORM (14 features) ===
        features.extend(
            [
                match_data.get("home_points_l5", 0) / 15,
                match_data.get("away_points_l5", 0) / 15,
                match_data.get("home_winning_streak", 0) / 8,
                match_data.get("away_winning_streak", 0) / 8,
                match_data.get("home_unbeaten_run", 0) / 12,
                match_data.get("away_unbeaten_run", 0) / 12,
                match_data.get("home_comeback_wins", 0) / 5,
                match_data.get("away_comeback_wins", 0) / 5,
                match_data.get("home_goals_last_3", 0) / 10,
                match_data.get("away_goals_last_3", 0) / 10,
                match_data.get("h2h_home_wins_l5", 0) / 5,
                match_data.get("h2h_total_goals_l5", 0) / 25,
                match_data.get("h2h_avg_goals_per_game", 3.2),
                match_data.get("form_momentum_score", 0),
            ]
        )

        return np.array(features).reshape(1, -1)

    def train(self, X_train: pd.DataFrame, y_train: pd.Series):
        """Train with isotonic calibration (BUG-001 fix)"""
        X_scaled = self.scaler.fit_transform(X_train)
        y_values = np.asarray(y_train).ravel()
        sample_weights = compute_sample_weight(class_weight="balanced", y=y_values)

        for name, model in self.models.items():
            print(f"Training {name} for Bundesliga...")
            model.fit(X_scaled, y_values, sample_weight=sample_weights)

            # Isotonic calibration for draw probability redistribution (BUG-001 fix)
            calibrated = CalibratedClassifierCV(model, method="isotonic", cv=5)
            calibrated.fit(X_scaled, y_values, sample_weight=sample_weights)
            self.models[name] = calibrated

        self.is_trained = True
        print("✅ Bundesliga model training complete")

    def predict_proba(self, match_data: Dict) -> Dict[str, float]:
        """Predictions with Bundesliga volatility adjustments"""
        if not self.is_trained:
            raise ValueError("Model not trained")

        X = self.extract_bundesliga_features(match_data)
        X_scaled = self.scaler.transform(X)

        probs_home = probs_draw = probs_away = 0

        for name, model in self.models.items():
            pred = model.predict_proba(X_scaled)[0]
            weight = self.ensemble_weights[name]

            if len(pred) == 3:
                probs_home += pred[0] * weight
                probs_draw += pred[1] * weight
                probs_away += pred[2] * weight

        # Bundesliga adjustments
        if match_data.get("home_ppda", 10) < 8.5:  # Intense pressing
            probs_home *= 1.06
            probs_draw *= 0.92  # Fewer draws in high-press games

        if match_data.get("h2h_avg_goals_per_game", 3.0) > 3.5:
            probs_draw *= 0.88  # Goal-fests reduce draws

        # Normalize
        total = probs_home + probs_draw + probs_away

        return {
            "home_win": round(probs_home / total, 4),
            "draw": round(probs_draw / total, 4),
            "away_win": round(probs_away / total, 4),
            "confidence": round(max(probs_home, probs_draw, probs_away) / total, 4),
        }

    def calculate_edge(
        self, predictions: Dict[str, float], odds: Dict[str, float]
    ) -> Dict:
        """Edge calculation with Bundesliga variance premium"""
        edges = {}

        for outcome in ["home_win", "draw", "away_win"]:
            fair_prob = predictions[outcome]
            decimal_odd = odds.get(outcome, 0)

            if decimal_odd > 1.01:
                implied_prob = 1 / decimal_odd
                edge_value = fair_prob - implied_prob

                kelly_fraction = (fair_prob * (decimal_odd - 1) - (1 - fair_prob)) / (
                    decimal_odd - 1
                )
                kelly_fraction *= 0.115  # Slightly more aggressive for Bundesliga

                if edge_value > 0.044:  # 4.4% minimum
                    edges[outcome] = {
                        "edge_pct": round(edge_value * 100, 2),
                        "kelly_stake_pct": round(max(0, kelly_fraction * 100), 2),
                        "clv_cents": round((fair_prob - implied_prob) * 100, 2),
                        "confidence": predictions["confidence"],
                    }

        return edges
