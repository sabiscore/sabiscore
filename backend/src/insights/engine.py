import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
import logging
import json

from ..models.ensemble import SabiScoreEnsemble
from ..models.feature_registry import CANONICAL_FEATURES_68, DEFAULT_FEATURE_VALUES_68
from ..data.aggregator import DataAggregator
from ..data.team_database import get_team_stats, get_matchup_features, get_team_elo

# Avoid importing heavy transformer (sklearn/great_expectations) at module import time
# We'll lazily import FeatureTransformer in __init__ and fall back to a minimal implementation
from ..models.explainer import ModelExplainer
from .calculators import (
    assess_bet_quality,
    calculate_betting_edge,
    calculate_confidence_interval,
    calculate_expected_value,
    calculate_implied_probability,
    calculate_kelly_stake,
    calculate_value_percentage,
)
from ..core.config import settings
from ..core.exceptions import DataUnavailableError
from ..core.league_policy import (
    LeaguePolicyUnavailableError,
    get_league_policy,
)
from ..services.rl_betting_agent import RLBettingAgent
from ..services.uncertainty_service import UncertaintyService

logger = logging.getLogger(__name__)

# Public sizing is Quarter-Kelly, hard-capped by the per-league policy (never the
# global ceiling on its own). Mirrors services/ultra_prediction_service.py.
QUARTER_KELLY = 0.25
MAX_KELLY_CAP = 0.05


def _league_kelly_cap(league: str) -> float:
    """Per-league Kelly ceiling, defaulting to the most conservative cap."""
    try:
        return min(get_league_policy(league).kelly_cap, MAX_KELLY_CAP)
    except LeaguePolicyUnavailableError:
        logger.warning("No league policy for %r; using conservative Kelly cap", league)
        return 0.02


# Legacy defaults are retained below for backward-compatible enrichment logic.
# Canonical fallback now uses the production 68-feature schema (Phase 7-A).
MODEL_EXPECTED_FEATURES = [
    "home_form_5",
    "home_form_10",
    "home_form_20",
    "home_win_rate_5",
    "home_goals_per_match_5",
    "away_form_5",
    "away_form_10",
    "away_form_20",
    "away_win_rate_5",
    "away_goals_per_match_5",
    "home_xg_avg_5",
    "home_xg_conceded_avg_5",
    "home_xg_diff_5",
    "home_xg_overperformance",
    "home_xg_consistency",
    "away_xg_avg_5",
    "away_xg_conceded_avg_5",
    "away_xg_diff_5",
    "away_xg_overperformance",
    "away_xg_consistency",
    "xg_differential",
    "home_days_rest",
    "home_fatigue_index",
    "home_fixtures_14d",
    "home_fixture_congestion",
    "away_days_rest",
    "away_fatigue_index",
    "away_fixtures_14d",
    "away_fixture_congestion",
    "home_advantage_win_rate",
    "home_goals_advantage",
    "away_win_rate_away",
    "home_crowd_boost",
    "home_advantage_coefficient",
    "referee_home_bias",
    "home_momentum_lambda",
    "home_momentum_weighted",
    "home_win_streak",
    "home_unbeaten_streak",
    "away_momentum_lambda",
    "away_momentum_weighted",
    "away_win_streak",
    "away_unbeaten_streak",
    "odds_volatility_1h",
    "market_panic_score",
    "odds_drift_home",
    "bookmaker_margin",
    "home_implied_prob",
    "h2h_home_wins",
    "h2h_draws",
    "h2h_away_wins",
    "h2h_total_matches",
    "h2h_avg_goals",
    "h2h_home_win_rate",
    "home_squad_value",
    "home_missing_value",
    "away_squad_value",
    "away_missing_value",
    "squad_value_diff",
    "temperature",
    "precipitation",
    "wind_speed",
    "weather_impact_score",
    "home_elo",
    "away_elo",
    "elo_difference",
    "home_possession_style",
    "away_possession_style",
    "home_pressing_intensity",
    "away_pressing_intensity",
    "home_first_half_goals_rate",
    "away_first_half_goals_rate",
    "home_defensive_solidity",
    "away_defensive_solidity",
    "home_setpiece_goals_rate",
    "away_setpiece_goals_rate",
    "home_goals_conceded_per_match_5",
    "home_gd_avg_5",
    "home_gd_trend",
    "home_clean_sheets_5",
    "home_scoring_consistency",
    "away_goals_conceded_per_match_5",
    "away_gd_avg_5",
    "away_gd_trend",
    "away_clean_sheets_5",
    "away_scoring_consistency",
]

# Default values for features when real data is unavailable
# Based on EPL league averages from training data
FEATURE_DEFAULTS = {
    # Form features (0-1 scale where possible, averages otherwise)
    "home_form_5": 0.55,
    "home_form_10": 0.54,
    "home_form_20": 0.53,  # Slight home advantage
    "home_win_rate_5": 0.50,
    "home_goals_per_match_5": 1.55,
    "away_form_5": 0.45,
    "away_form_10": 0.44,
    "away_form_20": 0.43,
    "away_win_rate_5": 0.40,
    "away_goals_per_match_5": 1.25,
    # xG features (expected goals ~1.3-1.6 per team per match in EPL)
    "home_xg_avg_5": 1.55,
    "home_xg_conceded_avg_5": 1.30,
    "home_xg_diff_5": 0.25,
    "home_xg_overperformance": 0.05,
    "home_xg_consistency": 0.75,
    "away_xg_avg_5": 1.35,
    "away_xg_conceded_avg_5": 1.50,
    "away_xg_diff_5": -0.15,
    "away_xg_overperformance": -0.05,
    "away_xg_consistency": 0.70,
    "xg_differential": 0.20,
    # Rest & fatigue
    "home_days_rest": 7.0,
    "home_fatigue_index": 0.30,
    "home_fixtures_14d": 2.0,
    "home_fixture_congestion": 0.35,
    "away_days_rest": 7.0,
    "away_fatigue_index": 0.35,
    "away_fixtures_14d": 2.0,
    "away_fixture_congestion": 0.35,
    # Home advantage factors
    "home_advantage_win_rate": 0.55,
    "home_goals_advantage": 0.30,
    "away_win_rate_away": 0.35,
    "home_crowd_boost": 0.10,
    "home_advantage_coefficient": 1.15,
    "referee_home_bias": 0.52,
    # Momentum features
    "home_momentum_lambda": 0.55,
    "home_momentum_weighted": 0.55,
    "home_win_streak": 1.5,
    "home_unbeaten_streak": 3.0,
    "away_momentum_lambda": 0.45,
    "away_momentum_weighted": 0.45,
    "away_win_streak": 1.0,
    "away_unbeaten_streak": 2.5,
    # Odds/market features
    "odds_volatility_1h": 0.02,
    "market_panic_score": 0.15,
    "odds_drift_home": 0.0,
    "bookmaker_margin": 0.05,
    "home_implied_prob": 0.45,
    # Head-to-head (assumes ~10 previous meetings)
    "h2h_home_wins": 4.0,
    "h2h_draws": 3.0,
    "h2h_away_wins": 3.0,
    "h2h_total_matches": 10.0,
    "h2h_avg_goals": 2.5,
    "h2h_home_win_rate": 0.40,
    # Squad values (in millions)
    "home_squad_value": 400.0,
    "home_missing_value": 20.0,
    "away_squad_value": 350.0,
    "away_missing_value": 15.0,
    "squad_value_diff": 50.0,
    # Weather
    "temperature": 15.0,
    "precipitation": 2.0,
    "wind_speed": 12.0,
    "weather_impact_score": 0.1,
    # Elo ratings (average ~1500)
    "home_elo": 1550.0,
    "away_elo": 1500.0,
    "elo_difference": 50.0,
    # Tactical/style features
    "home_possession_style": 0.52,
    "away_possession_style": 0.48,
    "home_pressing_intensity": 0.55,
    "away_pressing_intensity": 0.50,
    "home_first_half_goals_rate": 0.45,
    "away_first_half_goals_rate": 0.42,
    "home_defensive_solidity": 0.65,
    "away_defensive_solidity": 0.60,
    "home_setpiece_goals_rate": 0.25,
    "away_setpiece_goals_rate": 0.22,
    # Goals/GD features
    "home_goals_conceded_per_match_5": 1.20,
    "home_gd_avg_5": 0.35,
    "home_gd_trend": 0.05,
    "home_clean_sheets_5": 0.30,
    "home_scoring_consistency": 0.70,
    "away_goals_conceded_per_match_5": 1.40,
    "away_gd_avg_5": -0.15,
    "away_gd_trend": -0.02,
    "away_clean_sheets_5": 0.25,
    "away_scoring_consistency": 0.65,
}

# Enforce canonical production fallback when model feature metadata is unavailable.
FEATURE_DEFAULTS.update(DEFAULT_FEATURE_VALUES_68)
MODEL_EXPECTED_FEATURES = list(CANONICAL_FEATURES_68)


class InsightsEngine:
    """Engine for generating betting insights and analysis"""

    def __init__(
        self,
        model: Optional[SabiScoreEnsemble] = None,
        aggregator: Optional[DataAggregator] = None,
        transformer: Optional[object] = None,
        explainer: Optional[ModelExplainer] = None,
    ):
        self.model = model
        self.uncertainty_service = UncertaintyService()
        self.rl_agent = RLBettingAgent()
        self.data_aggregator = aggregator
        # Lazily resolve transformer to avoid importing optional heavy deps in test envs
        if transformer is not None:
            self.transformer = transformer
        else:
            self.transformer = self._resolve_transformer()
        self.explainer = explainer or ModelExplainer(model)
        self.odds_cache = {}

        # Get expected features from the loaded model, fallback to constant
        self._model_features = None
        if (
            self.model
            and hasattr(self.model, "feature_columns")
            and self.model.feature_columns
        ):
            self._model_features = list(self.model.feature_columns)
            logger.info(f"Model expects {len(self._model_features)} features")
        else:
            self._model_features = MODEL_EXPECTED_FEATURES
            logger.info("Using default MODEL_EXPECTED_FEATURES")

    def _align_features_to_model(
        self, features: pd.DataFrame, match_data: Optional[Dict[str, Any]] = None
    ) -> pd.DataFrame:
        """
        Align generated features to match the exact canonical feature set expected by the trained model.

        This function:
        1. Maps any available features from the input to expected feature names
        2. Fills missing features with sensible defaults based on match_data or league averages
        3. Ensures the output DataFrame has exactly the columns the model expects, in the right order

        Args:
            features: DataFrame with whatever features were generated
            match_data: Optional dict with match context for smarter defaults

        Returns:
            DataFrame with exactly the columns expected by the model
        """
        expected_features = self._model_features or MODEL_EXPECTED_FEATURES

        # Start with defaults
        aligned = {feat: FEATURE_DEFAULTS.get(feat, 0.0) for feat in expected_features}

        # Map from generated features to expected features where possible
        # This mapping handles the mismatch between old feature names and new ones
        feature_mapping = {
            # Old generated -> Expected model features
            "home_attack_strength": ("home_home_strength", lambda x: 1.0 + x * 0.3),
            "away_defense_strength": ("away_away_strength", lambda x: 0.7 + x * 0.3),
            "home_win_rate": ("home_form_5", lambda x: x),
            "away_win_rate": ("away_form_5", lambda x: x),
            "home_goals_per_game": ("home_goals_scored_5", lambda x: x * 5),
            "away_goals_per_game": ("away_goals_scored_5", lambda x: x * 5),
            "home_attacking_strength": ("home_home_strength", lambda x: 1.0 + x * 0.3),
            "away_attacking_strength": ("away_away_strength", lambda x: 0.7 + x * 0.3),
        }

        # Apply mappings from generated features
        if features is not None and len(features) > 0:
            for gen_col, (target_col, transform) in feature_mapping.items():
                if gen_col in features.columns and target_col in expected_features:
                    try:
                        aligned[target_col] = transform(
                            float(features[gen_col].iloc[0])
                        )
                    except Exception:
                        pass  # Keep default

            # Direct copy for any features that already match
            for col in features.columns:
                if col in expected_features:
                    try:
                        aligned[col] = float(features[col].iloc[0])
                    except Exception:
                        pass

        # Enrich with match_data if available (must be a dict, not DataFrame)
        if match_data is not None and isinstance(match_data, dict):
            self._enrich_from_match_data(aligned, match_data)

        # Create DataFrame with features in exact expected order
        result = pd.DataFrame([aligned])[expected_features]

        # ponytail: do NOT silently fill NaN with 0.0 here — NaN means the feature
        # was genuinely unavailable. CatBoost handles NaN natively; sklearn models
        # that cannot should apply their own imputation strategy with explicit logging.
        null_count = int(result.isnull().sum().sum())
        if null_count:
            logger.debug(
                "Aligned features: %d columns are NaN (unavailable evidence)",
                null_count,
            )

        logger.debug(
            "Aligned features: %d columns ready for model", len(result.columns)
        )
        return result

    def _enrich_from_match_data(
        self, aligned: Dict[str, float], match_data: Dict[str, Any]
    ) -> None:
        """Enrich aligned features dict with data from match_data where available.

        Also uses team database to ensure team-specific values are applied.
        """
        if not isinstance(match_data, dict):
            return  # Safety check
        try:
            # Get team names from metadata for team database lookup
            metadata = match_data.get("metadata", {})
            if isinstance(metadata, dict):
                home_team = metadata.get("home_team", "")
                away_team = metadata.get("away_team", "")
            else:
                home_team = ""
                away_team = ""

            # If we have team names, get team-specific features from database
            if home_team and away_team:
                team_features = get_matchup_features(home_team, away_team)
                # Apply team-specific features (these will override defaults)
                for key, value in team_features.items():
                    if key in aligned:
                        aligned[key] = float(value)

            # Extract ELO data if available in match_data (from mock or scraper)
            elo_data = match_data.get("elo", {})
            if isinstance(elo_data, dict) and elo_data:
                if "home" in elo_data:
                    aligned["home_elo"] = float(elo_data["home"])
                if "away" in elo_data:
                    aligned["away_elo"] = float(elo_data["away"])
                if "difference" in elo_data:
                    aligned["elo_difference"] = float(elo_data["difference"])

            # Extract odds if available
            odds = match_data.get("odds", {})
            if isinstance(odds, dict) and odds:
                if "home_win" in odds:
                    aligned["home_win_odds"] = float(odds["home_win"])
                    aligned["home_implied_prob"] = 1.0 / float(odds["home_win"])
                if "draw" in odds:
                    pass  # draw_odds not in model features
                if "away_win" in odds:
                    pass  # away_win_odds not in model features

            # Extract team stats (may override team database values with live data)
            team_stats = match_data.get("team_stats", {})
            if isinstance(team_stats, dict):
                home_stats = team_stats.get("home", {})
                away_stats = team_stats.get("away", {})
            else:
                home_stats = {}
                away_stats = {}

            if isinstance(home_stats, dict) and home_stats:
                if "win_rate" in home_stats:
                    aligned["home_form_5"] = float(home_stats["win_rate"])
                    aligned["home_form_10"] = float(home_stats["win_rate"]) * 0.98
                    aligned["home_form_20"] = float(home_stats["win_rate"]) * 0.96
                    aligned["home_win_rate_5"] = float(home_stats["win_rate"])
                if "goals_per_game" in home_stats:
                    gpg = float(home_stats["goals_per_game"])
                    aligned["home_goals_per_match_5"] = gpg
                    aligned["home_xg_avg_5"] = home_stats.get("xg_avg", gpg * 0.95)
                if "squad_value" in home_stats:
                    aligned["home_squad_value"] = float(home_stats["squad_value"])
                if "xg_avg" in home_stats:
                    aligned["home_xg_avg_5"] = float(home_stats["xg_avg"])

            if isinstance(away_stats, dict) and away_stats:
                if "win_rate" in away_stats:
                    aligned["away_form_5"] = float(away_stats["win_rate"])
                    aligned["away_form_10"] = float(away_stats["win_rate"]) * 0.98
                    aligned["away_form_20"] = float(away_stats["win_rate"]) * 0.96
                    aligned["away_win_rate_5"] = float(away_stats["win_rate"])
                if "goals_per_game" in away_stats:
                    gpg = float(away_stats["goals_per_game"])
                    aligned["away_goals_per_match_5"] = gpg
                    aligned["away_xg_avg_5"] = away_stats.get("xg_avg", gpg * 0.95)
                if "squad_value" in away_stats:
                    aligned["away_squad_value"] = float(away_stats["squad_value"])
                if "xg_avg" in away_stats:
                    aligned["away_xg_avg_5"] = float(away_stats["xg_avg"])

            # H2H data
            h2h = match_data.get("head_to_head", {})
            if isinstance(h2h, dict) and h2h:
                aligned["h2h_home_wins"] = float(h2h.get("home_wins", 4))
                aligned["h2h_away_wins"] = float(h2h.get("away_wins", 3))
                aligned["h2h_draws"] = float(h2h.get("draws", 3))
                aligned["h2h_total_matches"] = float(h2h.get("total_meetings", 10))

        except Exception as e:
            logger.warning(f"Error enriching features from match_data: {e}")

    def generate_match_insights(
        self,
        matchup: str,
        league: str,
        match_data: Optional[Dict[str, Any]] = None,
        realtime_data: Optional[Dict[str, Any]] = None,
        market_odds: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Generate comprehensive match insights"""
        try:
            logger.info(f"Generating insights for {matchup} ({league})")

            # Parse team names with better error handling
            try:
                home_team, away_team = matchup.split(" vs ")
                home_team = home_team.strip()
                away_team = away_team.strip()
            except ValueError:
                logger.warning(f"Invalid matchup format: {matchup}, using fallback")
                return self._create_fallback_insights(matchup, league)

            # Use simplified mock data if aggregator fails
            if not match_data:
                try:
                    # Prefer the injected aggregator (testable); fall back to a fresh one per matchup
                    if self.data_aggregator is not None:
                        match_data = self.data_aggregator.fetch_match_data()
                    else:
                        aggregator = DataAggregator(matchup, league)
                        match_data = aggregator.fetch_match_data()
                except Exception as e:
                    logger.warning(f"Data aggregation failed, using mock data: {e}")
                    match_data = self._create_mock_match_data(
                        home_team, away_team, league
                    )

            metadata = match_data.get(
                "metadata",
                {
                    "matchup": matchup,
                    "league": league,
                    "home_team": home_team,
                    "away_team": away_team,
                },
            )

            # Get features. Missing required evidence must fail closed — substituting
            # FEATURE_DEFAULTS here would let the model infer on pure defaults.
            try:
                features = self._prepare_features(match_data, realtime_data)
            except DataUnavailableError:
                raise
            except Exception as e:
                logger.warning(f"Feature preparation failed, using mock features: {e}")
                features = self._create_mock_features()

            # Generate predictions
            predictions = self._forecast_match_outcome(features)

            # Calculate expected goals
            xg_analysis = self._forecast_xg(match_data)

            # Generate value bets
            odds = market_odds or match_data.get("odds", {})
            value_analysis = self._calculate_value_bets(predictions, odds, league)

            # Run Monte Carlo simulations
            monte_carlo = self._run_monte_carlo(predictions)

            # Generate scenarios with error handling
            try:
                scenarios = self._generate_scenarios(predictions, xg_analysis)
            except Exception as e:
                logger.warning(f"Scenario generation failed: {e}")
                scenarios = []

            # Explain prediction with error handling
            try:
                explanation = self._explain_prediction(features)
            except Exception as e:
                logger.warning(f"Prediction explanation failed: {e}")
                explanation = {"feature_importance": {}, "shap_values": []}

            # Assess risk with error handling
            try:
                risk_assessment = self._assess_risk(
                    predictions, value_analysis, monte_carlo
                )
            except Exception as e:
                logger.warning(f"Risk assessment failed: {e}")
                risk_assessment = {"overall_risk": "medium", "factors": []}

            # Generate narrative with error handling
            try:
                narrative = self._generate_narrative(
                    matchup, predictions, value_analysis, risk_assessment
                )
            except Exception as e:
                logger.warning(f"Narrative generation failed: {e}")
                narrative = f"Analysis for {matchup} completed with basic insights."

            # Build response matching the InsightsResponse schema
            uncertainty = self.uncertainty_service.decompose(
                feature_frame=features,
                probabilities={
                    "home_win": predictions.get("home_win_prob", 0.33),
                    "draw": predictions.get("draw_prob", 0.33),
                    "away_win": predictions.get("away_win_prob", 0.34),
                },
                confidence=float(predictions.get("confidence", 0.5)),
            )
            rl_recommendation = self.rl_agent.recommend(
                probabilities={
                    "home_win": predictions.get("home_win_prob", 0.33),
                    "draw": predictions.get("draw_prob", 0.33),
                    "away_win": predictions.get("away_win_prob", 0.34),
                },
                odds=odds,
                confidence=float(predictions.get("confidence", 0.5)),
                epistemic_unc=uncertainty.epistemic_unc,
            )

            insights = {
                "matchup": matchup,
                "league": league,
                "metadata": {
                    "matchup": matchup,
                    "league": league,
                    "home_team": metadata.get("home_team", home_team),
                    "away_team": metadata.get("away_team", away_team),
                },
                "predictions": {
                    "home_win_prob": predictions.get("home_win_prob", 0.33),
                    "draw_prob": predictions.get("draw_prob", 0.33),
                    "away_win_prob": predictions.get("away_win_prob", 0.34),
                    "prediction": predictions.get("prediction", "draw"),
                    "confidence": predictions.get("confidence", 0.5),
                    # Baseline output is not a model inference; consumers must be able
                    # to tell the two apart rather than infer it from the numbers.
                    "is_baseline": bool(predictions.get("is_baseline", False)),
                },
                "xg_analysis": {
                    "home_xg": xg_analysis.get("home_xg", 1.5),
                    "away_xg": xg_analysis.get("away_xg", 1.3),
                    "total_xg": xg_analysis.get("total_xg", 2.8),
                    "xg_difference": xg_analysis.get("xg_difference", 0.2),
                },
                "value_analysis": value_analysis,
                "monte_carlo": monte_carlo,
                "scenarios": scenarios,
                "explanation": explanation,
                "risk_assessment": risk_assessment,
                "narrative": narrative,
                # Use datetime object so Pydantic encodes consistently
                "generated_at": datetime.now(timezone.utc),
                "confidence_level": self._calculate_overall_confidence(
                    predictions, explanation
                ),
                "uncertainty": self.uncertainty_service.to_dict(uncertainty),
                "causal_summary": self._load_causal_summary(),
                "rl_recommendation": {
                    "stake_fraction": rl_recommendation.stake_fraction,
                    "abstain": rl_recommendation.abstain,
                    "reward_components": rl_recommendation.reward_components,
                    "reason": rl_recommendation.reason,
                },
                "provenance": {
                    "source": {
                        "type": "ml_model",
                        "origin": getattr(self.model, "name", "ensemble"),
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "version": getattr(self.model, "version", None),
                    },
                    "computed_from": [
                        f"league:{league.lower()}",
                        f"matchup:{matchup.lower()}",
                    ],
                    "transformations": [],
                    "real_time_adjusted": bool(realtime_data),
                    "drift_detected": None,
                    "validation_status": "pending",
                },
            }

            logger.info(f"Insights generated successfully for {matchup}")
            return insights

        except DataUnavailableError:
            # _create_fallback_insights still carries probabilities and xG, so it is not a
            # valid response for missing evidence. Let the caller return 422.
            raise
        except Exception as e:
            logger.error(f"Failed to generate insights: {e}")
            # Return a basic fallback response instead of raising
            return self._create_fallback_insights(matchup, league)

    def _prepare_features(
        self, match_data: Dict[str, Any], realtime_data: Optional[Dict[str, Any]]
    ) -> pd.DataFrame:
        """Prepare features for prediction, aligned to match model's expected schema."""
        try:
            # Use transformer to engineer features
            if self.transformer:
                raw_features = self.transformer.engineer_features(match_data)
            else:
                # Create basic features from match data
                team_stats = match_data.get("team_stats", {})
                home_stats = team_stats.get("home", {})
                away_stats = team_stats.get("away", {})

                raw_features = pd.DataFrame(
                    {
                        "home_attack_strength": [
                            home_stats.get("attacking_strength", 0.8)
                        ],
                        "away_defense_strength": [
                            away_stats.get("defensive_strength", 0.7)
                        ],
                        "home_win_rate": [home_stats.get("win_rate", 0.6)],
                        "away_win_rate": [away_stats.get("win_rate", 0.5)],
                        "home_goals_per_game": [home_stats.get("goals_per_game", 1.8)],
                        "away_goals_per_game": [away_stats.get("goals_per_game", 1.5)],
                    }
                )

            # Add realtime features if available
            if realtime_data:
                raw_features = self._add_realtime_features(raw_features, realtime_data)

            # CRITICAL: Align features to match the canonical features expected by the trained model
            # This maps/fills features so the model can make predictions without feature mismatch errors
            features = self._align_features_to_model(raw_features, match_data)

            logger.info(
                f"Features prepared: {features.shape[1]} columns aligned for model"
            )
            return features

        except DataUnavailableError:
            # Required evidence is absent: fail closed rather than aligning to defaults.
            raise
        except Exception as e:
            logger.error(f"Feature preparation failed: {e}")
            # Return aligned mock features
            return self._align_features_to_model(None, match_data)

    def _add_realtime_features(
        self, features: pd.DataFrame, realtime_data: Dict[str, Any]
    ) -> pd.DataFrame:
        """Add realtime features from live data"""
        # Implementation for adding live odds, injuries, etc.
        # Mock implementation
        return features

    def _forecast_match_outcome(self, features: pd.DataFrame) -> Dict[str, Any]:
        """Forecast match outcome probabilities"""
        if not self.model or not self.model.is_trained:
            logger.warning("Model not available, using baseline predictions")
            return self._baseline_predictions()

        try:
            predictions = self.model.predict(features)

            # Convert to dict
            result = {
                "home_win_prob": float(predictions["home_win_prob"].iloc[0]),
                "draw_prob": float(predictions["draw_prob"].iloc[0]),
                "away_win_prob": float(predictions["away_win_prob"].iloc[0]),
                "prediction": predictions["prediction"].iloc[0],
                "confidence": float(predictions["confidence"].iloc[0]),
            }

            return result

        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return self._baseline_predictions()

    def _baseline_predictions(self) -> Dict[str, Any]:
        """Generate baseline predictions using historical averages

        Uses league-wide historical outcomes as baseline instead of arbitrary mock values.
        Baseline rates calculated from training data:
        - Home win: ~46% (historical home advantage)
        - Draw: ~27% (league average)
        - Away win: ~27%
        """
        # Historical baseline probabilities from 5,005 training samples
        baseline_home_win = 0.46
        baseline_draw = 0.27
        baseline_away_win = 0.27

        logger.warning("Model unavailable - using historical baseline predictions")

        return {
            "home_win_prob": baseline_home_win,
            "draw_prob": baseline_draw,
            "away_win_prob": baseline_away_win,
            "prediction": "home_win",  # Home advantage
            "confidence": 0.50,  # Low confidence for baseline
            "is_baseline": True,
        }

    def _create_mock_match_data(
        self, home_team: str, away_team: str, league: str
    ) -> Dict[str, Any]:
        """Create mock match data when aggregation fails.

        Uses team database to get differentiated stats for each team,
        ensuring different matchups produce different predictions.
        """
        # Get team-specific statistics from database
        home_stats = get_team_stats(home_team, is_home=True)
        away_stats = get_team_stats(away_team, is_home=False)

        home_elo = get_team_elo(home_team)
        away_elo = get_team_elo(away_team)
        elo_diff = home_elo - away_elo

        return {
            "metadata": {
                "matchup": f"{home_team} vs {away_team}",
                "league": league,
                "home_team": home_team,
                "away_team": away_team,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "data_source": "team_database_fallback",
            },
            "team_stats": {
                "home": {
                    "attacking_strength": home_stats["attacking_strength"],
                    "defensive_strength": home_stats["defensive_strength"],
                    "win_rate": home_stats["win_rate"],
                    "goals_per_game": home_stats["goals_per_game"],
                    "clean_sheet_rate": home_stats["clean_sheet_rate"],
                    "xg_avg": home_stats["xg_avg"],
                    "squad_value": home_stats["squad_value"],
                },
                "away": {
                    "attacking_strength": away_stats["attacking_strength"],
                    "defensive_strength": away_stats["defensive_strength"],
                    "win_rate": away_stats["win_rate"],
                    "goals_per_game": away_stats["goals_per_game"],
                    "clean_sheet_rate": away_stats["clean_sheet_rate"],
                    "xg_avg": away_stats["xg_avg"],
                    "squad_value": away_stats["squad_value"],
                },
            },
            # No market: this path has no live book, and an ELO-derived price would
            # produce a fabricated edge and stake. Value analysis is skipped instead.
            "odds": {},
            "elo": {"home": home_elo, "away": away_elo, "difference": elo_diff},
            "head_to_head": {},
            "current_form": {},
        }

    def _create_mock_features(self) -> pd.DataFrame:
        """Create mock features aligned to model's expected schema."""
        # Use the alignment function to generate properly structured features
        return self._align_features_to_model(None, None)

    def _resolve_transformer(self):
        """Attempt to import the full FeatureTransformer, otherwise use a minimal fallback.

        The fallback avoids sklearn/great_expectations and produces a simple feature frame
        compatible with the engine's baseline behavior.
        """
        try:
            from ..data.transformers import FeatureTransformer  # type: ignore

            return FeatureTransformer()
        except Exception as e:
            logger.warning("Using MinimalFeatureTransformer due to import error: %s", e)

            class MinimalFeatureTransformer:
                def engineer_features(self, match_data: Dict[str, Any]) -> pd.DataFrame:
                    team_stats = match_data.get("team_stats", {})
                    home = team_stats.get("home", {})
                    away = team_stats.get("away", {})
                    return pd.DataFrame(
                        {
                            "home_attack_strength": [
                                home.get("attacking_strength", 0.8)
                            ],
                            "away_defense_strength": [
                                away.get("defensive_strength", 0.7)
                            ],
                            "home_win_rate": [home.get("win_rate", 0.6)],
                            "away_win_rate": [away.get("win_rate", 0.5)],
                            "home_goals_per_game": [home.get("goals_per_game", 1.8)],
                            "away_goals_per_game": [away.get("goals_per_game", 1.5)],
                        }
                    )

            return MinimalFeatureTransformer()

    def _get_team_metrics(
        self, match_data: Dict[str, Any], team: str
    ) -> Dict[str, Any]:
        """Extract team metrics from match data"""
        team_stats = match_data.get("team_stats", {}).get(team, {})
        return {
            "average_goals_scored": team_stats.get("goals_per_game", 1.5),
            "average_goals_conceded": 2.0 - team_stats.get("goals_per_game", 1.5),
            "win_rate": team_stats.get("win_rate", 0.5),
            "clean_sheet_rate": team_stats.get("clean_sheet_rate", 0.3),
        }

    def _get_h2h_stats(self, match_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract head-to-head statistics"""
        h2h = match_data.get("head_to_head", {})
        return {
            "total_meetings": h2h.get("total_meetings", 10),
            "home_wins": h2h.get("home_wins", 4),
            "away_wins": h2h.get("away_wins", 3),
            "draws": h2h.get("draws", 3),
            "form_edge": h2h.get("form_edge", "neutral"),
        }

    def _create_fallback_insights(self, matchup: str, league: str) -> Dict[str, Any]:
        """Create fallback insights when all else fails"""
        try:
            home_team, away_team = matchup.split(" vs ")
            home_team = home_team.strip()
            away_team = away_team.strip()
        except ValueError:
            home_team, away_team = "Home Team", "Away Team"

        return {
            "matchup": matchup,
            "league": league,
            "metadata": {
                "matchup": matchup,
                "league": league,
                "home_team": home_team,
                "away_team": away_team,
            },
            "predictions": {
                "home_win_prob": 0.40,
                "draw_prob": 0.30,
                "away_win_prob": 0.30,
                "prediction": "home_win",
                "confidence": 0.50,
            },
            "xg_analysis": {
                "home_xg": 1.5,
                "away_xg": 1.2,
                "total_xg": 2.7,
                "xg_difference": 0.3,
            },
            "value_analysis": {
                "bets": [],
                "edges": {},
                "best_bet": None,
                "summary": "No value bets identified",
            },
            "monte_carlo": {
                "simulations": 10000,
                "distribution": {"home_win": 0.40, "draw": 0.30, "away_win": 0.30},
                "confidence_intervals": {
                    "home_win": [0.37, 0.43],
                    "draw": [0.27, 0.33],
                    "away_win": [0.27, 0.33],
                },
            },
            "scenarios": [
                {
                    "name": "Most Likely",
                    "probability": 0.40,
                    "home_score": 2,
                    "away_score": 1,
                    "result": "home_win",
                }
            ],
            "explanation": {"feature_importance": {}, "shap_values": []},
            "risk_assessment": {
                "risk_level": "medium",
                "confidence_score": 0.50,
                "value_available": False,
                "best_bet": None,
                "distribution": {"home_win": 0.40, "draw": 0.30, "away_win": 0.30},
                "recommendation": "Caution",
            },
            "narrative": f"Analysis for {matchup} completed with basic insights. Model confidence is moderate.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "confidence_level": 0.50,
            "uncertainty": {
                "epistemic_unc": 0.5,
                "aleatoric_unc": 0.5,
                "concentration": 1.0001,
                "credible_interval": {"lower": 0.40, "upper": 0.60},
            },
            "causal_summary": self._load_causal_summary(),
            "rl_recommendation": {
                "stake_fraction": 0.0,
                "abstain": True,
                "reward_components": {
                    "R_pnl": 0.0,
                    "R_ic": 0.0,
                    "R_cal": -0.5,
                    "R_risk": 0.0,
                    "R_abs": 0.05,
                },
                "reason": "Fallback insights mode: abstain until full model context is available.",
            },
        }

    def _load_causal_summary(self) -> Dict[str, Any]:
        report_path = settings.data_path / "causal_feature_report.json"
        if not report_path.exists():
            return {
                "top_drivers": [],
                "collider_warnings": [],
                "source": str(report_path),
                "status": "unavailable",
            }

        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "top_drivers": [],
                "collider_warnings": [],
                "source": str(report_path),
                "status": "invalid_report",
            }

        features = payload.get("features", []) if isinstance(payload, dict) else []
        if not isinstance(features, list):
            features = []

        drivers: List[str] = []
        colliders: List[str] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            name = str(feature.get("name", "")).strip()
            classification = str(feature.get("classification", "")).strip()
            if not name:
                continue
            if classification == "CAUSAL_DRIVER":
                drivers.append(name)
            if classification == "COLLIDER_WARNING":
                colliders.append(name)

        return {
            "top_drivers": drivers[:5],
            "collider_warnings": colliders[:5],
            "source": str(report_path),
            "status": "ready",
        }

    def _forecast_xg(self, match_data: Dict[str, Any]) -> Dict[str, Any]:
        """Forecast expected goals"""
        # Mock xG calculation
        team_stats = match_data.get("team_stats", {})

        home_attack = team_stats.get("home", {}).get("attacking_strength", 0.8)
        away_defense = team_stats.get("away", {}).get("defensive_strength", 0.7)
        home_xg = home_attack * away_defense * 2.5  # Base xG calculation

        away_attack = team_stats.get("away", {}).get("attacking_strength", 0.7)
        home_defense = team_stats.get("home", {}).get("defensive_strength", 0.8)
        away_xg = away_attack * home_defense * 1.8

        return {
            "home_xg": round(home_xg, 2),
            "away_xg": round(away_xg, 2),
            "total_xg": round(home_xg + away_xg, 2),
            "xg_difference": round(home_xg - away_xg, 2),
        }

    def _calculate_value_bets(
        self,
        predictions: Dict[str, Any],
        market_odds: Dict[str, float],
        league: str = "",
    ) -> Dict[str, Any]:
        """Calculate value betting opportunities using EV, Kelly, and edges.

        ``kelly_stake`` is a bankroll *fraction* (Quarter-Kelly, capped by the
        league policy), matching the public contract the frontend renders.
        """

        if not market_odds:
            return {
                "bets": [],
                "edges": {},
                "best_bet": None,
                "summary": "Market odds unavailable",
            }

        model_probs = {
            "home_win": predictions.get("home_win_prob", 0.0),
            "draw": predictions.get("draw_prob", 0.0),
            "away_win": predictions.get("away_win_prob", 0.0),
        }

        edges = calculate_betting_edge(model_probs, market_odds)
        bets: List[Dict[str, Any]] = []

        kelly_cap = _league_kelly_cap(league)
        for outcome, prob in model_probs.items():
            odds = market_odds.get(outcome)
            implied = calculate_implied_probability(odds) if odds else None
            if odds is None or implied is None:
                continue

            ev = calculate_expected_value(prob, odds)
            # bankroll=1.0 makes the shared calculator return a fraction, not an amount.
            kelly = min(
                calculate_kelly_stake(
                    prob, odds, bankroll=1.0, kelly_fraction=QUARTER_KELLY
                ),
                kelly_cap,
            )
            value_pct = calculate_value_percentage(prob, implied)
            ci_low, ci_high = calculate_confidence_interval(prob)

            if ev <= 0:
                continue

            quality = assess_bet_quality(ev, predictions.get("confidence", 0.5))
            bets.append(
                {
                    "bet_type": outcome,
                    "market_odds": odds,
                    "model_prob": prob,
                    "market_prob": implied,
                    "expected_value": ev,
                    "value_pct": value_pct,
                    "kelly_stake": kelly,
                    "confidence_interval": [ci_low, ci_high],
                    "edge": edges.get(outcome, 0.0),
                    "recommendation": quality["recommendation"],
                    "quality": quality,
                }
            )

        best_bet = max(
            bets, key=lambda bet: bet["quality"]["quality_score"], default=None
        )
        summary = (
            f"{len(bets)} opportunities with positive EV."
            if bets
            else "No positive-EV opportunities identified."
        )

        return {
            "bets": sorted(bets, key=lambda bet: bet["expected_value"], reverse=True),
            "edges": edges,
            "best_bet": best_bet,
            "summary": summary,
        }

    def _run_monte_carlo(
        self, predictions: Dict[str, Any], n_sims: int = 10000
    ) -> Dict[str, Any]:
        """Run Monte Carlo simulations"""
        np.random.seed(42)

        home_prob = predictions["home_win_prob"]
        draw_prob = predictions["draw_prob"]
        predictions["away_win_prob"]

        results = []
        for _ in range(n_sims):
            rand = np.random.random()
            if rand < home_prob:
                results.append("home_win")
            elif rand < home_prob + draw_prob:
                results.append("draw")
            else:
                results.append("away_win")

        # Calculate statistics
        home_wins = results.count("home_win")
        draws = results.count("draw")
        away_wins = results.count("away_win")

        return {
            "simulations": n_sims,
            "distribution": {
                "home_win": home_wins / n_sims,
                "draw": draws / n_sims,
                "away_win": away_wins / n_sims,
            },
            "confidence_intervals": {
                "home_win": calculate_confidence_interval(home_wins / n_sims, n_sims),
                "draw": calculate_confidence_interval(draws / n_sims, n_sims),
                "away_win": calculate_confidence_interval(away_wins / n_sims, n_sims),
            },
        }

    def _generate_scenarios(
        self, predictions: Dict[str, Any], xg_analysis: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate different match scenarios"""
        scenarios = []

        # Base scenario
        scenarios.append(
            {
                "name": "Most Likely",
                "probability": predictions["home_win_prob"]
                if predictions["prediction"] == "home_win"
                else predictions["draw_prob"]
                if predictions["prediction"] == "draw"
                else predictions["away_win_prob"],
                "home_score": round(xg_analysis["home_xg"]),
                "away_score": round(xg_analysis["away_xg"]),
                "result": predictions["prediction"],
            }
        )

        # Alternative scenarios
        scenarios.extend(
            [
                {
                    "name": "High Scoring",
                    "probability": 0.15,
                    "home_score": max(2, round(xg_analysis["home_xg"] * 1.5)),
                    "away_score": max(1, round(xg_analysis["away_xg"] * 1.3)),
                    "result": "home_win",
                },
                {
                    "name": "Low Scoring",
                    "probability": 0.20,
                    "home_score": max(0, round(xg_analysis["home_xg"] * 0.7)),
                    "away_score": max(0, round(xg_analysis["away_xg"] * 0.8)),
                    "result": "draw",
                },
            ]
        )

        return scenarios

    def _explain_prediction(self, features: pd.DataFrame) -> Dict[str, Any]:
        """Generate prediction explanation"""
        if not self.explainer:
            return {"type": "mock", "description": "Model explanation not available"}

        try:
            explanation = self.explainer.explain_prediction(features)
            return explanation
        except Exception as e:
            logger.error(f"Explanation failed: {e}")
            return {"type": "error", "description": str(e)}

    def _assess_risk(
        self,
        predictions: Dict[str, Any],
        value_analysis: Dict[str, Any],
        monte_carlo: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assess betting risk"""
        confidence = predictions.get("confidence", 0.5)
        distribution = monte_carlo.get("distribution", {})
        top_outcome_prob = max(distribution.values()) if distribution else confidence
        bets = value_analysis.get("bets", [])
        best_bet = value_analysis.get("best_bet")

        if confidence >= 0.75 and top_outcome_prob >= 0.55 and best_bet:
            risk_level = "low"
        elif confidence <= 0.55 or top_outcome_prob <= 0.45 or not bets:
            risk_level = "high"
        else:
            risk_level = "medium"

        recommendation = {
            "low": "Proceed",
            "medium": "Caution",
            "high": "Avoid",
        }[risk_level]

        return {
            "risk_level": risk_level,
            "confidence_score": confidence,
            "value_available": bool(bets),
            "best_bet": best_bet,
            "distribution": distribution,
            "recommendation": recommendation,
        }

    def _generate_narrative(
        self,
        matchup: str,
        predictions: Dict[str, Any],
        value_analysis: Dict[str, Any],
        risk: Dict[str, Any],
    ) -> str:
        """Generate human-readable narrative"""
        home_team, away_team = matchup.split(" vs ")

        pred = predictions["prediction"].replace("_", " ").title()
        conf = int(predictions["confidence"] * 100)

        narrative = f"Our model predicts {pred} with {conf}% confidence for {matchup}. "

        best_bet = value_analysis.get("best_bet") if value_analysis else None
        if best_bet:
            bet_type = best_bet["bet_type"].replace("_", " ").title()
            ev = best_bet["expected_value"] * 100
            narrative += (
                f"Top value opportunity: {bet_type} at {best_bet['market_odds']:.2f} odds "
                f"({ev:.1f}% EV, Kelly stake {best_bet['kelly_stake']:.2f}). "
            )
        elif value_analysis and value_analysis.get("summary"):
            narrative += value_analysis["summary"] + " "

        risk_desc = (
            "low risk"
            if risk["risk_level"] == "low"
            else "moderate risk"
            if risk["risk_level"] == "medium"
            else "high risk"
        )
        narrative += f"This bet carries {risk_desc}. {risk['recommendation']}."

        return narrative

    def _calculate_overall_confidence(
        self, predictions: Dict[str, Any], explanation: Dict[str, Any]
    ) -> float:
        """Calculate overall confidence score"""
        model_conf = predictions.get("confidence", 0.5)
        explanation_conf = (
            0.8 if explanation and explanation.get("feature_importance") else 0.5
        )

        return (model_conf * 0.7) + (explanation_conf * 0.3)
