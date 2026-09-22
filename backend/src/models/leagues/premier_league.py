# backend/src/models/leagues/premier_league.py
"""
Premier League Model - Optimized for high-intensity, high-scoring matches
Key features: Crowd pressure, fatigue from European competitions, tactical flexibility
Phase 7-B holdout: ~44.7% accuracy, 0.230 Brier score (3-way prediction baseline ~33%)
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
import json
from ...core.league_policy import get_league_policy, LeaguePolicyUnavailableError

try:
    _KELLY_CAP = get_league_policy("EPL").kelly_cap
except LeaguePolicyUnavailableError:
    _KELLY_CAP = 0.04  # ponytail: conservative fallback


class PremierLeagueModel:
    """
    EPL-specific model accounting for:
    - High shot volume (14.2 avg per match)
    - Intense pressing (PPDA < 10 for top 6)
    - Weather impact (rain reduces xG by 8%)
    - Midweek European fatigue
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.scaler = StandardScaler()

        # Ensemble weights tuned for EPL volatility
        self.models = {
            "rf": RandomForestClassifier(
                n_estimators=300,
                max_depth=18,
                min_samples_split=8,
                min_samples_leaf=3,
                max_features="sqrt",
                class_weight="balanced",
                random_state=42,
            ),
            "xgb": XGBClassifier(
                n_estimators=250,
                max_depth=7,
                learning_rate=0.03,
                subsample=0.85,
                colsample_bytree=0.8,
                gamma=0.2,
                min_child_weight=3,
                reg_alpha=0.1,
                reg_lambda=1.2,
                random_state=42,
            ),
            "lgbm": LGBMClassifier(
                n_estimators=220,
                max_depth=8,
                learning_rate=0.04,
                num_leaves=45,
                subsample=0.82,
                colsample_bytree=0.75,
                min_child_samples=25,
                reg_alpha=0.15,
                reg_lambda=1.0,
                class_weight="balanced",
                random_state=42,
            ),
            "gb": GradientBoostingClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.8,
                min_samples_split=10,
                min_samples_leaf=4,
                random_state=42,
            ),
        }

        # EPL-specific ensemble weights (higher XGBoost for tactical nuance)
        self.ensemble_weights = {"rf": 0.28, "xgb": 0.42, "lgbm": 0.22, "gb": 0.08}

        self.is_trained = False

    def extract_epl_features(self, match_data: Dict) -> np.ndarray:
        """
        Extract 87 EPL-specific features
        """
        features = []

        # === CORE FORM (15 features) ===
        home_form = match_data.get("home_form_last_5", [])
        away_form = match_data.get("away_form_last_5", [])

        features.extend(
            [
                np.mean(home_form) if home_form else 0,
                np.std(home_form) if len(home_form) > 1 else 0,
                np.mean(away_form) if away_form else 0,
                np.std(away_form) if len(away_form) > 1 else 0,
                match_data.get("home_goals_scored_l5", 0),
                match_data.get("home_goals_conceded_l5", 0),
                match_data.get("away_goals_scored_l5", 0),
                match_data.get("away_goals_conceded_l5", 0),
                match_data.get("home_xg_l5", 0),
                match_data.get("home_xga_l5", 0),
                match_data.get("away_xg_l5", 0),
                match_data.get("away_xga_l5", 0),
                match_data.get("home_shots_l5", 0),
                match_data.get("away_shots_l5", 0),
                match_data.get("home_shots_on_target_l5", 0),
            ]
        )

        # === EPL INTENSITY METRICS (12 features) ===
        features.extend(
            [
                match_data.get("home_ppda", 11.5),  # Passes per defensive action
                match_data.get("away_ppda", 11.5),
                match_data.get("home_high_turnovers", 0),  # Turnovers in final 3rd
                match_data.get("away_high_turnovers", 0),
                match_data.get("home_sprint_distance", 0),  # High-intensity runs
                match_data.get("away_sprint_distance", 0),
                match_data.get("home_aggressive_actions", 0),  # Tackles + interceptions
                match_data.get("away_aggressive_actions", 0),
                match_data.get("home_counter_attacks", 0),
                match_data.get("away_counter_attacks", 0),
                match_data.get("home_box_touches", 0),
                match_data.get("away_box_touches", 0),
            ]
        )

        # === FATIGUE & ROTATION (10 features) ===
        home_last_match = match_data.get("home_days_since_last_match", 7)
        away_last_match = match_data.get("away_days_since_last_match", 7)

        features.extend(
            [
                home_last_match,
                away_last_match,
                1 if home_last_match < 4 else 0,  # Midweek fixture flag
                1 if away_last_match < 4 else 0,
                match_data.get(
                    "home_european_competition", 0
                ),  # Played in Europe this week
                match_data.get("away_european_competition", 0),
                match_data.get("home_minutes_played_l7d", 0) / 990,  # Normalized
                match_data.get("away_minutes_played_l7d", 0) / 990,
                match_data.get("home_rotation_index", 0),  # Lineup changes
                match_data.get("away_rotation_index", 0),
            ]
        )

        # === CROWD & HOME ADVANTAGE (8 features) ===
        features.extend(
            [
                match_data.get("home_attendance", 35000) / 60000,  # Normalized
                match_data.get("home_atmosphere_rating", 3.5) / 5,
                match_data.get("home_win_rate_home", 0.45),
                match_data.get("away_win_rate_away", 0.35),
                match_data.get("home_goals_per_game_home", 1.5),
                match_data.get("away_goals_per_game_away", 1.2),
                match_data.get("referee_home_bias", 0),  # Cards differential
                match_data.get("derby_match", 0),  # Local rivalry flag
            ]
        )

        # === TACTICAL COMPLEXITY (14 features) ===
        features.extend(
            [
                match_data.get("home_possession_avg", 50) / 100,
                match_data.get("away_possession_avg", 50) / 100,
                match_data.get("home_pass_completion", 80) / 100,
                match_data.get("away_pass_completion", 80) / 100,
                match_data.get("home_long_ball_ratio", 0.15),
                match_data.get("away_long_ball_ratio", 0.15),
                match_data.get("home_cross_accuracy", 0.25),
                match_data.get("away_cross_accuracy", 0.25),
                match_data.get("home_dribble_success", 0.55),
                match_data.get("away_dribble_success", 0.55),
                match_data.get("home_build_up_speed", 5.2),  # Seconds per attack
                match_data.get("away_build_up_speed", 5.2),
                match_data.get("home_set_piece_threat", 0.18),
                match_data.get("away_set_piece_threat", 0.18),
            ]
        )

        # === WEATHER & CONDITIONS (6 features) ===
        features.extend(
            [
                match_data.get("temperature", 15) / 30,
                match_data.get("rainfall_mm", 0) / 10,
                match_data.get("wind_speed", 0) / 40,
                1 if match_data.get("rainfall_mm", 0) > 2 else 0,  # Rain flag
                match_data.get("pitch_quality", 8) / 10,
                1 if match_data.get("evening_kickoff", 0) else 0,
            ]
        )

        # === SQUAD VALUE & INJURIES (10 features) ===
        features.extend(
            [
                match_data.get("home_squad_value_m", 400) / 1000,
                match_data.get("away_squad_value_m", 400) / 1000,
                match_data.get("home_injured_value_m", 0) / 100,
                match_data.get("away_injured_value_m", 0) / 100,
                match_data.get("home_key_player_availability", 0.9),
                match_data.get("away_key_player_availability", 0.9),
                match_data.get("home_avg_age", 26) / 35,
                match_data.get("away_avg_age", 26) / 35,
                match_data.get("home_experience_caps", 200) / 500,
                match_data.get("away_experience_caps", 200) / 500,
            ]
        )

        # === MOMENTUM & PSYCHOLOGY (12 features) ===
        features.extend(
            [
                match_data.get("home_goals_last_3", 0) / 9,
                match_data.get("away_goals_last_3", 0) / 9,
                match_data.get("home_clean_sheets_l5", 0) / 5,
                match_data.get("away_clean_sheets_l5", 0) / 5,
                match_data.get("home_come_from_behind_wins", 0) / 5,
                match_data.get("away_come_from_behind_wins", 0) / 5,
                match_data.get("home_late_goals_ratio", 0.22),  # Goals after 75'
                match_data.get("away_late_goals_ratio", 0.22),
                match_data.get("h2h_home_wins_l5", 0) / 5,
                match_data.get("h2h_away_wins_l5", 0) / 5,
                match_data.get("h2h_goals_per_game", 2.8),
                match_data.get("manager_experience_years", 5) / 20,
            ]
        )

        return np.array(features).reshape(1, -1)

    def train(self, X_train: pd.DataFrame, y_train: pd.Series):
        """Train ensemble with isotonic calibration (BUG-001 fix)"""
        X_scaled = self.scaler.fit_transform(X_train)
        y_values = np.asarray(y_train).ravel()
        sample_weights = compute_sample_weight(class_weight="balanced", y=y_values)

        for name, model in self.models.items():
            print(f"Training {name} for EPL...")

            # Train base model
            model.fit(X_scaled, y_values, sample_weight=sample_weights)

            # Apply isotonic calibration for draw probability redistribution (BUG-001 fix)
            calibrated = CalibratedClassifierCV(model, method="isotonic", cv=5)
            calibrated.fit(X_scaled, y_values, sample_weight=sample_weights)
            self.models[name] = calibrated

        self.is_trained = True
        print("✅ EPL model training complete")

    def predict_proba(self, match_data: Dict) -> Dict[str, float]:
        """
        Returns calibrated probabilities for Home/Draw/Away
        """
        if not self.is_trained:
            raise ValueError("Model not trained. Call train() first.")

        X = self.extract_epl_features(match_data)
        X_scaled = self.scaler.transform(X)

        # Ensemble prediction
        probs_home = 0
        probs_draw = 0
        probs_away = 0

        for name, model in self.models.items():
            pred = model.predict_proba(X_scaled)[0]
            weight = self.ensemble_weights[name]

            if len(pred) == 3:  # Home/Draw/Away
                probs_home += pred[0] * weight
                probs_draw += pred[1] * weight
                probs_away += pred[2] * weight
            else:  # Binary (Home Win or Not)
                probs_home += pred[1] * weight
                probs_away += pred[0] * weight
                probs_draw += 0.27 * weight  # EPL draw rate

        # Apply EPL-specific adjustments
        if match_data.get("home_european_competition", 0) == 1:
            probs_home *= 0.92  # 8% fatigue penalty
            probs_draw *= 1.05
            probs_away *= 1.03

        if match_data.get("rainfall_mm", 0) > 3:
            probs_draw *= 1.12  # Rain increases draws by 12%

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
        """
        Kelly Criterion edge calculation with EPL volatility adjustment
        """
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
                kelly_fraction = min(kelly_fraction, _KELLY_CAP)

                if edge_value > 0.042:  # 4.2% minimum edge
                    edges[outcome] = {
                        "edge_pct": round(edge_value * 100, 2),
                        "kelly_stake_pct": round(max(0, kelly_fraction * 100), 2),
                        "clv_cents": round((fair_prob - implied_prob) * 100, 2),
                        "confidence": predictions["confidence"],
                    }

        return edges

    def cache_prediction(self, match_id: str, prediction: Dict, ttl: int = 300):
        """Cache to Redis for 5 minutes"""
        key = f"epl:pred:{match_id}"
        self.redis.setex(key, ttl, json.dumps(prediction))

    def get_cached_prediction(self, match_id: str) -> Dict:
        """Retrieve cached prediction"""
        key = f"epl:pred:{match_id}"
        cached = self.redis.get(key)
        return json.loads(cached) if cached else None
