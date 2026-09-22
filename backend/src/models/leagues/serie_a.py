# backend/src/models/leagues/serie_a.py
"""
Serie A Model - Optimized for tactical rigidity and defensive organization
Key features: Defensive solidity, tactical fouls, lower scoring
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
    _KELLY_CAP = get_league_policy("SERIE_A").kelly_cap
except LeaguePolicyUnavailableError:
    _KELLY_CAP = 0.04  # ponytail: conservative fallback


class SerieAModel:
    """
    Serie A-specific model accounting for:
    - Tactical defenses
    - Lower goal variance
    - Draw frequency
    """

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.scaler = StandardScaler()

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

        self.ensemble_weights = {"rf": 0.30, "xgb": 0.40, "lgbm": 0.20, "gb": 0.10}

        self.is_trained = False

    def extract_serie_a_features(self, match_data: Dict) -> np.ndarray:
        """
        Extract Serie A-specific features
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

        # Padding
        features.extend([0] * (87 - len(features)))

        return np.array(features).reshape(1, -1)

    def train(self, X_train: pd.DataFrame, y_train: pd.Series):
        """Train ensemble with isotonic calibration (BUG-001 fix)"""
        X_scaled = self.scaler.fit_transform(X_train)
        y_values = np.asarray(y_train).ravel()
        sample_weights = compute_sample_weight(class_weight="balanced", y=y_values)

        for name, model in self.models.items():
            print(f"Training {name} for Serie A...")
            model.fit(X_scaled, y_values, sample_weight=sample_weights)

            calibrated = CalibratedClassifierCV(model, method="isotonic", cv=5)
            calibrated.fit(X_scaled, y_values, sample_weight=sample_weights)
            self.models[name] = calibrated

        self.is_trained = True
        print("✅ Serie A model training complete")

    def predict_proba(self, match_data: Dict) -> Dict[str, float]:
        """
        Returns calibrated probabilities for Home/Draw/Away
        """
        if not self.is_trained:
            raise ValueError("Model not trained. Call train() first.")

        X = self.extract_serie_a_features(match_data)
        X_scaled = self.scaler.transform(X)

        probs_home = 0
        probs_draw = 0
        probs_away = 0

        for name, model in self.models.items():
            pred = model.predict_proba(X_scaled)[0]
            weight = self.ensemble_weights[name]

            if len(pred) == 3:
                probs_home += pred[0] * weight
                probs_draw += pred[1] * weight
                probs_away += pred[2] * weight
            else:
                probs_home += pred[1] * weight
                probs_away += pred[0] * weight
                probs_draw += 0.28 * weight  # Serie A draw rate

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
        Kelly Criterion edge calculation
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

                if edge_value > 0.04:
                    edges[outcome] = {
                        "edge_pct": round(edge_value * 100, 2),
                        "kelly_stake_pct": round(max(0, kelly_fraction * 100), 2),
                        "clv_cents": round((fair_prob - implied_prob) * 100, 2),
                        "confidence": predictions["confidence"],
                    }

        return edges

    def cache_prediction(self, match_id: str, prediction: Dict, ttl: int = 300):
        """Cache to Redis"""
        key = f"seriea:pred:{match_id}"
        self.redis.setex(key, ttl, json.dumps(prediction))

    def get_cached_prediction(self, match_id: str) -> Dict:
        """Retrieve cached prediction"""
        key = f"seriea:pred:{match_id}"
        cached = self.redis.get(key)
        return json.loads(cached) if cached else None
