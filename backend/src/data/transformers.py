import logging
import math
from typing import Any, Dict, Callable, List, Optional

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from ..core.exceptions import DataUnavailableError, OddsUnavailableError
from ..models.feature_registry import (
    CANONICAL_FEATURES_68,
    DEFAULT_FEATURE_VALUES_68,
    PHASE7_FEATURES_ALWAYS_DATA_GAP,
    UnknownFeatureSchemaError,
    derive_apex_market_features,
    derive_combination_features,
    derive_goals_gd_features,
    derive_last5_form_features,
    derive_league_features,
    derive_market_features,
    derive_temporal_features,
    has_league_rate_priors,
    is_apex_schema,
    resolve_feature_schema,
)

# Default serving schema when nothing declares otherwise — today's exact
# CANONICAL_FEATURES_68 behavior, preserved as a literal string so a future
# schema-resolution failure always falls back to this, never a guess.
_DEFAULT_FEATURE_SCHEMA_VERSION = "phase7_68"


logger = logging.getLogger(__name__)

# Slots that exist only for model-artifact dimensional compatibility and are never
# computed from live data. Exempt from the fail-closed required-evidence check.
_ALWAYS_DATA_GAP_FEATURES = frozenset(PHASE7_FEATURES_ALWAYS_DATA_GAP)


# Legacy defaults below are retained for backward-compatible intermediate calculations.
# Final inference projection is always aligned to the canonical 68-feature schema (Phase 7-A).
MODEL_EXPECTED_FEATURES = [
    'home_form_5', 'home_form_10', 'home_form_20', 'home_win_rate_5', 'home_goals_per_match_5',
    'away_form_5', 'away_form_10', 'away_form_20', 'away_win_rate_5', 'away_goals_per_match_5',
    'home_xg_avg_5', 'home_xg_conceded_avg_5', 'home_xg_diff_5', 'home_xg_overperformance', 'home_xg_consistency',
    'away_xg_avg_5', 'away_xg_conceded_avg_5', 'away_xg_diff_5', 'away_xg_overperformance', 'away_xg_consistency',
    'xg_differential',
    'home_days_rest', 'home_fatigue_index', 'home_fixtures_14d', 'home_fixture_congestion',
    'away_days_rest', 'away_fatigue_index', 'away_fixtures_14d', 'away_fixture_congestion',
    'home_advantage_win_rate', 'home_goals_advantage', 'away_win_rate_away', 'home_crowd_boost',
    'home_advantage_coefficient', 'referee_home_bias',
    'home_momentum_lambda', 'home_momentum_weighted', 'home_win_streak', 'home_unbeaten_streak',
    'away_momentum_lambda', 'away_momentum_weighted', 'away_win_streak', 'away_unbeaten_streak',
    'odds_volatility_1h', 'market_panic_score', 'odds_drift_home', 'bookmaker_margin', 'home_implied_prob',
    'h2h_home_wins', 'h2h_draws', 'h2h_away_wins', 'h2h_total_matches', 'h2h_avg_goals', 'h2h_home_win_rate',
    'home_squad_value', 'home_missing_value', 'away_squad_value', 'away_missing_value', 'squad_value_diff',
    'temperature', 'precipitation', 'wind_speed', 'weather_impact_score',
    'home_elo', 'away_elo', 'elo_difference',
    'home_possession_style', 'away_possession_style', 'home_pressing_intensity', 'away_pressing_intensity',
    'home_first_half_goals_rate', 'away_first_half_goals_rate',
    'home_defensive_solidity', 'away_defensive_solidity',
    'home_setpiece_goals_rate', 'away_setpiece_goals_rate',
    'home_goals_conceded_per_match_5', 'home_gd_avg_5', 'home_gd_trend', 'home_clean_sheets_5', 'home_scoring_consistency',
    'away_goals_conceded_per_match_5', 'away_gd_avg_5', 'away_gd_trend', 'away_clean_sheets_5', 'away_scoring_consistency',
]

# Default values for features when real data is unavailable
# Based on EPL league averages from training data
FEATURE_DEFAULTS = {
    # Form features
    'home_form_5': 0.55, 'home_form_10': 0.54, 'home_form_20': 0.53,
    'home_win_rate_5': 0.50, 'home_goals_per_match_5': 1.55,
    'away_form_5': 0.45, 'away_form_10': 0.44, 'away_form_20': 0.43,
    'away_win_rate_5': 0.40, 'away_goals_per_match_5': 1.25,
    # xG features
    'home_xg_avg_5': 1.55, 'home_xg_conceded_avg_5': 1.30, 'home_xg_diff_5': 0.25,
    'home_xg_overperformance': 0.05, 'home_xg_consistency': 0.75,
    'away_xg_avg_5': 1.35, 'away_xg_conceded_avg_5': 1.50, 'away_xg_diff_5': -0.15,
    'away_xg_overperformance': -0.05, 'away_xg_consistency': 0.70,
    'xg_differential': 0.20,
    # Rest & fatigue
    'home_days_rest': 7.0, 'home_fatigue_index': 0.30, 'home_fixtures_14d': 2.0, 'home_fixture_congestion': 0.35,
    'away_days_rest': 7.0, 'away_fatigue_index': 0.35, 'away_fixtures_14d': 2.0, 'away_fixture_congestion': 0.35,
    # Home advantage
    'home_advantage_win_rate': 0.55, 'home_goals_advantage': 0.30, 'away_win_rate_away': 0.35,
    'home_crowd_boost': 0.10, 'home_advantage_coefficient': 1.15, 'referee_home_bias': 0.52,
    # Momentum
    'home_momentum_lambda': 0.55, 'home_momentum_weighted': 0.55, 'home_win_streak': 1.5, 'home_unbeaten_streak': 3.0,
    'away_momentum_lambda': 0.45, 'away_momentum_weighted': 0.45, 'away_win_streak': 1.0, 'away_unbeaten_streak': 2.5,
    # Odds/market
    'odds_volatility_1h': 0.02, 'market_panic_score': 0.15, 'odds_drift_home': 0.0,
    'bookmaker_margin': 0.05, 'home_implied_prob': 0.45,
    # H2H
    'h2h_home_wins': 4.0, 'h2h_draws': 3.0, 'h2h_away_wins': 3.0,
    'h2h_total_matches': 10.0, 'h2h_avg_goals': 2.5, 'h2h_home_win_rate': 0.40,
    # Squad
    'home_squad_value': 400.0, 'home_missing_value': 20.0,
    'away_squad_value': 350.0, 'away_missing_value': 15.0,
    'squad_value_diff': 50.0,
    # Weather
    'temperature': 15.0, 'precipitation': 2.0, 'wind_speed': 12.0, 'weather_impact_score': 0.1,
    # Elo
    'home_elo': 1550.0, 'away_elo': 1500.0, 'elo_difference': 50.0,
    # Tactical
    'home_possession_style': 0.52, 'away_possession_style': 0.48,
    'home_pressing_intensity': 0.55, 'away_pressing_intensity': 0.50,
    'home_first_half_goals_rate': 0.45, 'away_first_half_goals_rate': 0.42,
    'home_defensive_solidity': 0.65, 'away_defensive_solidity': 0.60,
    'home_setpiece_goals_rate': 0.25, 'away_setpiece_goals_rate': 0.22,
    # Goals/GD
    'home_goals_conceded_per_match_5': 1.20, 'home_gd_avg_5': 0.35, 'home_gd_trend': 0.05,
    'home_clean_sheets_5': 0.30, 'home_scoring_consistency': 0.70,
    'away_goals_conceded_per_match_5': 1.40, 'away_gd_avg_5': -0.15, 'away_gd_trend': -0.02,
    'away_clean_sheets_5': 0.25, 'away_scoring_consistency': 0.65,
}

# Enforce canonical production schema for all inference-time projections.
FEATURE_DEFAULTS.update(DEFAULT_FEATURE_VALUES_68)
MODEL_EXPECTED_FEATURES = list(CANONICAL_FEATURES_68)


def _safe_float(value: Any) -> Optional[float]:
    """Coerce to float, treating NaN/inf as absent.

    NaN must be None: callers use "is not None" to decide whether evidence is
    present, so returning NaN would short-circuit their fallback chain and slip a
    NaN past the fail-closed raise instead of reporting the missing source.
    """
    try:
        if value is None:
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


class FeatureTransformer:
    """Feature engineering pipeline with validation and leakage controls.
    
    Produces canonical feature vectors aligned with production model metadata.
    """

    def __init__(
        self, *, allow_legacy_defaults: bool = False, schema_version: str | None = None
    ) -> None:
        self.scaler = StandardScaler()
        self.allow_legacy_defaults = allow_legacy_defaults
        self.schema_version = schema_version or self._resolve_active_schema_version()
        try:
            self.expected_columns = list(resolve_feature_schema(self.schema_version))
        except UnknownFeatureSchemaError:
            self.schema_version = _DEFAULT_FEATURE_SCHEMA_VERSION
            self.expected_columns = list(CANONICAL_FEATURES_68)
        self.feature_completeness: float = 1.0

    @staticmethod
    def _resolve_active_schema_version() -> str:
        """The active generation's declared schema, or today's default on any hiccup.

        docs/DEBT.md item 37's serving wire-up: every existing caller
        (``FeatureTransformer()`` with no args) must keep resolving to
        exactly ``CANONICAL_FEATURES_68`` — the only generation active today
        — so any failure here (missing manifest, import cycle) falls back to
        the literal default rather than raising out of a constructor no
        caller expects to fail.
        """
        try:
            from ..models.active_generation import active_feature_schema_version

            return active_feature_schema_version()
        except Exception:
            return _DEFAULT_FEATURE_SCHEMA_VERSION

    def _fail_closed_enabled(self) -> bool:
        if self.allow_legacy_defaults:
            return False
        try:
            from ..core.config import settings  # local import avoids circular at module load

            return bool(getattr(settings, "provider_fail_closed", True))
        except Exception:
            return True

    def _legacy_default(self, feature: str) -> float:
        if self._fail_closed_enabled():
            raise DataUnavailableError(
                f"Required feature '{feature}' is unavailable; refusing to use legacy defaults",
                provider="internal",
                evidence_type=f"feature:{feature}",
            )
        value = FEATURE_DEFAULTS.get(feature)
        if value is None:
            raise DataUnavailableError(
                f"Required feature '{feature}' has no legacy default",
                provider="internal",
                evidence_type=f"feature:{feature}",
            )
        return float(value)

    def _value_or_legacy(self, mapping: Dict[str, Any], key: str, feature: str) -> Any:
        if key in mapping and mapping.get(key) is not None:
            return mapping[key]
        return self._legacy_default(feature)

    @staticmethod
    def _is_non_empty_frame(value: Any) -> bool:
        return isinstance(value, pd.DataFrame) and not value.empty

    @staticmethod
    def _has_numeric(mapping: Dict[str, Any], key: str) -> bool:
        return _safe_float(mapping.get(key)) is not None

    def _validate_required_evidence(self, match_data: Dict[str, Any]) -> None:
        """Fail closed before any feature prior can enter production inference."""
        missing: List[str] = []

        odds = match_data.get("odds") or {}
        if not all(self._has_numeric(odds, key) and float(odds[key]) > 1.0 for key in ("home_win", "draw", "away_win")):
            missing.append("odds.1x2")

        schedule = match_data.get("schedule") or {}
        if not schedule.get("league"):
            missing.append("schedule.league")
        kickoff = schedule.get("date")
        if not kickoff:
            missing.append("schedule.date")
        else:
            try:
                pd.to_datetime(kickoff)
            except Exception:
                missing.append("schedule.date")

        historical_stats = match_data.get("historical_stats")
        if not self._is_non_empty_frame(historical_stats):
            missing.append("historical_stats")
        elif not {"home_score", "away_score"}.issubset(set(historical_stats.columns)):
            missing.append("historical_stats.home_score_away_score")

        head_to_head = match_data.get("head_to_head")
        if not self._is_non_empty_frame(head_to_head):
            missing.append("head_to_head")
        elif not {"home_score", "away_score"}.issubset(set(head_to_head.columns)):
            missing.append("head_to_head.home_score_away_score")

        current_form = match_data.get("current_form") or {}
        for side in ("home", "away"):
            form = current_form.get(side) or {}
            if not form.get("last_5_games"):
                missing.append(f"current_form.{side}.last_5_games")

        team_stats = match_data.get("team_stats") or {}
        required_team_fields = (
            "squad_value",
            "missing_value",
            "elo",
            "xg_avg_5",
            "xg_conceded_avg_5",
            "xg_diff_5",
            "xg_overperformance",
            "xg_consistency",
            "possession_style",
            "pressing_intensity",
            "first_half_goals_rate",
            "defensive_solidity",
            "setpiece_goals_rate",
            "gd_trend",
            "scoring_consistency",
        )
        for side in ("home", "away"):
            stats = team_stats.get(side) or {}
            for field in required_team_fields:
                if not self._has_numeric(stats, field):
                    missing.append(f"team_stats.{side}.{field}")

        if missing:
            raise DataUnavailableError(
                "Required feature evidence unavailable: " + ", ".join(sorted(set(missing))),
                provider="internal",
                evidence_type="feature_evidence",
            )

    def engineer_features(self, match_data: Dict[str, Any]) -> pd.DataFrame:
        if self._fail_closed_enabled():
            self._validate_required_evidence(match_data)

        # Measure real evidence before defaults fill the gaps
        _hs = match_data.get("historical_stats")
        _h2h = match_data.get("head_to_head")
        _present = sum([
            bool(match_data.get("current_form")),
            bool(match_data.get("team_stats")),
            isinstance(_hs, pd.DataFrame) and not _hs.empty,
            isinstance(_h2h, pd.DataFrame) and not _h2h.empty,
        ])
        self.feature_completeness = _present / 4.0

        # Handle None values by converting to empty DataFrame/dict
        historical_stats = match_data.get("historical_stats")
        if historical_stats is None or (isinstance(historical_stats, pd.DataFrame) and historical_stats.empty):
            historical_stats = pd.DataFrame()

        current_form = match_data.get("current_form") or {}

        odds = match_data.get("odds") or {}
        
        injuries = match_data.get("injuries")
        if injuries is None or (isinstance(injuries, pd.DataFrame) and injuries.empty):
            injuries = pd.DataFrame()
            
        head_to_head = match_data.get("head_to_head")
        if head_to_head is None or (isinstance(head_to_head, pd.DataFrame) and head_to_head.empty):
            head_to_head = pd.DataFrame()
            
        team_stats = match_data.get("team_stats") or {}

        base = self._create_base_features(historical_stats)
        base = self._add_form_features(base, current_form)
        base = self._add_odds_features(base, odds)
        base = self._add_injury_features(base, injuries)
        base = self._add_h2h_features(base, head_to_head)
        base = self._add_team_stats_features(base, team_stats)
        base = self._add_advanced_team_features(base, team_stats)
        base = self._add_form_trends(base, current_form)
        base = self._add_schedule_features(base, match_data)
        base = self._apply_enhanced_features(base, match_data)
        base = self._project_to_canonical_features(base, match_data)

        base = self._ensure_minimum_row(base)

        base = self._handle_missing_values(base)
        base = self._validate_features(base)

        return self._scale_features(base)

    def _project_to_canonical_features(self, features: pd.DataFrame, match_data: Dict[str, Any]) -> pd.DataFrame:
        """Project engineered features into the canonical 68-feature inference schema."""
        schedule = match_data.get("schedule") or {}
        odds = match_data.get("odds") or {}

        row = features.iloc[0].to_dict() if not features.empty else {}
        canonical = (
            dict(DEFAULT_FEATURE_VALUES_68)
            if not self._fail_closed_enabled()
            else {name: float("nan") for name in self.expected_columns}
        )

        def get_num(name: str, default: float) -> float:
            value = _safe_float(row.get(name))
            if value is None:
                if self._fail_closed_enabled():
                    raise DataUnavailableError(
                        f"Required feature '{name}' is unavailable; refusing to use projection defaults",
                        provider="internal",
                        evidence_type=f"feature:{name}",
                    )
                return default
            return value

        home_odds = odds.get("home_win", 2.5)
        draw_odds = odds.get("draw", 3.3)
        away_odds = odds.get("away_win", 2.8)
        derive_market = (
            derive_apex_market_features if is_apex_schema(self.schema_version)
            else derive_market_features
        )
        try:
            market_features = derive_market(home_odds, draw_odds, away_odds)
        except ValueError as exc:
            raise DataUnavailableError(
                "Malformed 1X2 market; refusing to repair invalid prices",
                provider="market",
                evidence_type="odds:1x2",
            ) from exc

        home_form_5 = get_num("home_form_5", 0.5)
        away_form_5 = get_num("away_form_5", 0.45)

        # WP-18: delegate to the shared pure formula in feature_registry.py —
        # was duplicated inline here and never reused by
        # upcoming_match_feature_service.py's own pipeline (now wired too).
        # Numerically identical to the prior inline formula; no wins_5/draws_5/
        # losses_5 available from an already-engineered features row, so this
        # always takes the round()/estimate path, same as before.
        canonical.update(derive_last5_form_features(
            home_form_5, get_num("home_win_rate_5", 0.5), is_home=True,
        ))
        canonical.update(derive_last5_form_features(
            away_form_5, get_num("away_win_rate_5", 0.4), is_home=False,
        ))

        # docs/DEBT.md item 36(a): shared with the projector and the training
        # builder. get_num keeps this call site fail-closed — an absent value
        # still raises DataUnavailableError rather than taking the default.
        canonical.update(derive_goals_gd_features(get_num, is_home=True))
        canonical.update(derive_goals_gd_features(get_num, is_home=False))

        canonical["total_goals_expected"] = get_num("xg_differential", 0.20) + 2.60

        canonical.update(market_features)
        market_prob_home = market_features["market_prob_home"]

        canonical["h2h_home_wins"] = get_num("h2h_home_wins", 2.0)
        canonical["h2h_away_wins"] = get_num("h2h_away_wins", 2.0)
        canonical["h2h_draws"] = get_num("h2h_draws", 1.0)
        canonical["h2h_matches"] = max(1.0, get_num("h2h_total_matches", 5.0))
        canonical["h2h_dominance"] = (canonical["h2h_home_wins"] - canonical["h2h_away_wins"]) / canonical["h2h_matches"]

        home_win_rate = get_num("home_advantage_win_rate", 0.5)
        away_win_rate = get_num("away_win_rate_away", 0.3)
        home_draw_rate = max(0.0, 1.0 - home_win_rate - away_win_rate)

        canonical["home_venue_win_rate"] = home_win_rate
        canonical["home_venue_draw_rate"] = home_draw_rate
        canonical["home_venue_loss_rate"] = away_win_rate
        canonical["home_advantage_strength"] = home_win_rate - away_win_rate

        kickoff = schedule.get("date")
        kickoff_dt = None
        if kickoff:
            try:
                kickoff_dt = pd.to_datetime(kickoff)
            except Exception:
                kickoff_dt = None
        if kickoff_dt is None:
            if self._fail_closed_enabled():
                raise DataUnavailableError(
                    "Kickoff timestamp is required for schedule features",
                    provider="internal",
                    evidence_type="feature:schedule.date",
                )
            kickoff_dt = pd.Timestamp.utcnow()

        # §7.2 (docs/DEBT.md item 36): delegate to the shared registry helpers
        # UpcomingMatchFeatureProjector and train_on_real_matches.py already
        # call, rather than keeping a third inline copy of the same arithmetic.
        # The tables were verified byte-identical before this change (the
        # league priors dict, the fallback triple, the one-hot alias logic over
        # all 12 league keys including unsupported ones, the temporal formulas
        # across five kickoffs, and the four combination formulas) — this is a
        # unification of provably equal implementations, not a behaviour change.
        # pandas' .dayofweek and datetime.weekday() share the Monday=0
        # convention, so converting the Timestamp here is exact.
        canonical.update(derive_temporal_features(kickoff_dt.to_pydatetime()))

        league_name = str(schedule.get("league", "EPL"))
        # ⚠️ The fail-closed guard stays HERE, not in derive_league_features().
        # That helper deliberately falls back to _LEAGUE_RATE_FALLBACK for an
        # unsupported league (Eredivisie and UCL have no one-hot column and
        # legitimately produce an all-zero block). FeatureTransformer is the
        # stricter caller and refuses instead — moving the check into the
        # shared helper would impose this strictness on the projector, which
        # must keep serving those two competitions.
        if not has_league_rate_priors(league_name) and self._fail_closed_enabled():
            raise DataUnavailableError(
                f"League policy defaults unavailable for '{league_name}'",
                provider="internal",
                evidence_type="feature:league",
            )
        canonical.update(derive_league_features(league_name))

        canonical["form_market_agreement_home"] = (canonical["home_form_last5_home"] / 3.0) * market_prob_home
        canonical["form_market_disagreement"] = abs((canonical["home_form_last5_home"] / 3.0) - market_prob_home)
        canonical.update(derive_combination_features(
            home_goals_for_avg=canonical["home_goals_for_avg"],
            home_goals_against_avg=canonical["home_goals_against_avg"],
            away_goals_for_avg=canonical["away_goals_for_avg"],
            away_goals_against_avg=canonical["away_goals_against_avg"],
        ))
        canonical["venue_market_combo"] = canonical["home_venue_win_rate"] * market_prob_home
        canonical["h2h_market_agreement"] = canonical["h2h_dominance"] * market_prob_home

        # Phase 7-A additions (Elo + StatsBomb tactical layer).
        # Only compute columns required by the loaded model artifact. This preserves
        # 58-feature model compatibility without requiring absent enhanced sources.
        team_stats = match_data.get("team_stats") or {}
        home_stats = team_stats.get("home", {}) if isinstance(team_stats, dict) else {}
        away_stats = team_stats.get("away", {}) if isinstance(team_stats, dict) else {}
        enhanced = match_data.get("enhanced_features") or {}
        expected = set(self.expected_columns)

        def _source_num(name: str, *sources: Any, default: float = 0.0) -> float:
            value = _safe_float(row.get(name))
            if value is not None:
                return value
            for source in sources:
                source_value = _safe_float(source)
                if source_value is not None:
                    return source_value
            if self._fail_closed_enabled():
                raise DataUnavailableError(
                    f"Required feature '{name}' is unavailable; refusing to use projection defaults",
                    provider="internal",
                    evidence_type=f"feature:{name}",
                )
            return default

        elo_diff: Optional[float] = None
        if "elo_difference" in expected or "elo_momentum_cross" in expected:
            home_elo = _source_num("home_elo", home_stats.get("elo"))
            away_elo = _source_num("away_elo", away_stats.get("elo"))
            elo_diff = _source_num("elo_difference", home_elo - away_elo)

        elo_home_trend_5: Optional[float] = None
        if "elo_home_trend_5" in expected or "elo_momentum_cross" in expected:
            elo_home_trend_5 = _source_num("elo_home_trend_5", row.get("home_elo_trend_5"), home_stats.get("elo_trend_5"))

        elo_away_trend_5: Optional[float] = None
        if "elo_away_trend_5" in expected or "elo_momentum_cross" in expected:
            elo_away_trend_5 = _source_num("elo_away_trend_5", row.get("away_elo_trend_5"), away_stats.get("elo_trend_5"))

        if "elo_difference" in expected and elo_diff is not None:
            canonical["elo_difference"] = elo_diff
        if "elo_home_trend_5" in expected and elo_home_trend_5 is not None:
            canonical["elo_home_trend_5"] = elo_home_trend_5
        if "elo_away_trend_5" in expected and elo_away_trend_5 is not None:
            canonical["elo_away_trend_5"] = elo_away_trend_5
        if "elo_momentum_cross" in expected and elo_home_trend_5 is not None and elo_away_trend_5 is not None:
            canonical["elo_momentum_cross"] = elo_home_trend_5 - elo_away_trend_5

        def _enhanced_num(*keys: str, default: float = 0.0) -> float:
            for item in keys:
                raw = enhanced.get(item)
                value = _safe_float(raw)
                if value is not None:
                    return value
            if self._fail_closed_enabled():
                raise DataUnavailableError(
                    f"Required enhanced feature evidence unavailable: {'/'.join(keys)}",
                    provider="internal",
                    evidence_type=f"feature:{keys[0] if keys else 'enhanced'}",
                )
            return default

        if "home_pressing_intensity" in expected:
            canonical["home_pressing_intensity"] = _source_num(
                "home_pressing_intensity",
                home_stats.get("pressing_intensity"),
                enhanced.get("home_pressing_intensity"),
                enhanced.get("sb_home_pressing_intensity"),
                default=0.55,
            )
        if "progressive_carry_diff" in expected:
            canonical["progressive_carry_diff"] = _enhanced_num(
                "progressive_carry_diff",
                "sb_progressive_carry_diff",
                default=0.0,
            )
        if "shot_quality_diff" in expected:
            canonical["shot_quality_diff"] = _enhanced_num(
                "shot_quality_diff",
                "sb_shot_quality_diff",
                default=0.0,
            )
        if "key_passes_under_pressure_diff" in expected:
            canonical["key_passes_under_pressure_diff"] = _enhanced_num(
                "key_passes_under_pressure_diff",
                "sb_key_passes_under_pressure_diff",
                default=0.0,
            )
        if "set_piece_xg_diff" in expected:
            canonical["set_piece_xg_diff"] = _enhanced_num(
                "set_piece_xg_diff",
                "sb_set_piece_xg_diff",
                default=0.0,
            )

        return pd.DataFrame([canonical], columns=self.expected_columns)

    # ------------------------------------------------------------------
    def _create_base_features(self, historical_stats: pd.DataFrame) -> pd.DataFrame:
        features = pd.DataFrame([{k: float("nan") for k in FEATURE_DEFAULTS}])
        if not self._fail_closed_enabled():
            for col, val in FEATURE_DEFAULTS.items():
                if col in features.columns:
                    features[col] = val

        if historical_stats is None or (isinstance(historical_stats, pd.DataFrame) and historical_stats.empty):
            return features

        # Update with calculated values where possible
        try:
            # Assuming historical_stats contains recent matches relevant to the teams
            # We'll use the last 5 matches for the "_5" features
            last_5 = historical_stats.tail(5)
            
            if not last_5.empty:
                features["home_goals_per_match_5"] = last_5["home_score"].mean()
                features["away_goals_per_match_5"] = last_5["away_score"].mean()
                features["home_goals_conceded_per_match_5"] = last_5["away_score"].mean()
                features["away_goals_conceded_per_match_5"] = last_5["home_score"].mean()
                
                # Simple win rate calculation based on score comparison
                home_wins = (last_5["home_score"] > last_5["away_score"]).mean()
                away_wins = (last_5["away_score"] > last_5["home_score"]).mean()
                features["home_win_rate_5"] = home_wins
                features["away_win_rate_5"] = away_wins
                
                # GD stats
                features["home_gd_avg_5"] = (last_5["home_score"] - last_5["away_score"]).mean()
                features["away_gd_avg_5"] = (last_5["away_score"] - last_5["home_score"]).mean()
                
                # Clean sheets
                features["home_clean_sheets_5"] = (last_5["away_score"] == 0).mean()
                features["away_clean_sheets_5"] = (last_5["home_score"] == 0).mean()

        except Exception as e:
            logger.warning(f"Error calculating base features: {e}")
            
        return features

    def _add_form_features(self, features: pd.DataFrame, current_form: Dict[str, Any]) -> pd.DataFrame:
        for side in ("home", "away"):
            form = current_form.get(side, {})
            # Form points from last 5 games (W=3, D=1, L=0)
            results = form.get("last_5_games", [])
            points = sum(3 if r == "W" else 1 if r == "D" else 0 for r in results)
            
            # Normalize form to 0-1 range (max 15 points)
            features[f"{side}_form_5"] = points / 15.0 if results else self._legacy_default(f"{side}_form_5")
            
            # For 10 and 20 game form, we might not have data, so use defaults or estimate
            # If we have 'form_10' in input, use it, otherwise estimate from form_5
            features[f"{side}_form_10"] = form.get("form_10", features[f"{side}_form_5"])
            features[f"{side}_form_20"] = form.get("form_20", features[f"{side}_form_10"])
            
            # Streaks
            features[f"{side}_win_streak"] = self._value_or_legacy(form, "win_streak", f"{side}_win_streak")
            features[f"{side}_unbeaten_streak"] = self._value_or_legacy(form, "unbeaten_streak", f"{side}_unbeaten_streak")
            
        return features

    def _add_odds_features(self, features: pd.DataFrame, odds: Dict[str, float]) -> pd.DataFrame:
        from ..core.config import settings  # local import avoids circular at module load

        has_1x2 = bool(odds.get("home_win") and odds.get("draw") and odds.get("away_win"))
        if not has_1x2:
            if self._fail_closed_enabled() and getattr(settings, "provider_fail_closed", True):
                # ponytail: fail-closed in production — no fabricated market signals
                raise OddsUnavailableError()
            # Development / mock mode: fall through with league-average placeholder odds.
            # These values must never reach a verdict in a production deployment.
            logger.warning(
                "Odds unavailable; using placeholder values. "
                "Set PROVIDER_FAIL_CLOSED=false only in non-production environments."
            )

        home = max(float(odds.get("home_win") or 2.5), 1.01)
        draw = max(float(odds.get("draw") or 3.2), 1.01)
        away = max(float(odds.get("away_win") or 2.8), 1.01)

        ip_home = 1 / home
        ip_draw = 1 / draw
        ip_away = 1 / away
        margin = ip_home + ip_draw + ip_away - 1
        prob_sum = ip_home + ip_draw + ip_away
        features["home_implied_prob"] = ip_home / prob_sum
        features["bookmaker_margin"] = margin

        # Optional market signals — use defaults when absent but do not raise.
        features["odds_volatility_1h"] = self._value_or_legacy(odds, "volatility_1h", "odds_volatility_1h")
        features["market_panic_score"] = self._value_or_legacy(odds, "panic_score", "market_panic_score")
        features["odds_drift_home"] = self._value_or_legacy(odds, "drift_home", "odds_drift_home")

        return features

    def _add_injury_features(self, features: pd.DataFrame, injuries: pd.DataFrame) -> pd.DataFrame:
        # Not in expected features list explicitly, but might be used for 'missing_value' calculation
        # We'll keep it simple and just return features as is for now, 
        # assuming missing_value is handled in team_stats
        return features

    def _add_h2h_features(self, features: pd.DataFrame, head_to_head: pd.DataFrame) -> pd.DataFrame:
        if head_to_head.empty:
            # Use defaults
            features["h2h_home_wins"] = self._legacy_default("h2h_home_wins")
            features["h2h_away_wins"] = self._legacy_default("h2h_away_wins")
            features["h2h_draws"] = self._legacy_default("h2h_draws")
            features["h2h_total_matches"] = self._legacy_default("h2h_total_matches")
            features["h2h_avg_goals"] = self._legacy_default("h2h_avg_goals")
            features["h2h_home_win_rate"] = self._legacy_default("h2h_home_win_rate")
            return features

        total = len(head_to_head)
        home_wins = (head_to_head["home_score"] > head_to_head["away_score"]).sum()
        away_wins = (head_to_head["away_score"] > head_to_head["home_score"]).sum()
        draws = (head_to_head["home_score"] == head_to_head["away_score"]).sum()
        
        features["h2h_home_wins"] = home_wins
        features["h2h_away_wins"] = away_wins
        features["h2h_draws"] = draws
        features["h2h_total_matches"] = total
        features["h2h_avg_goals"] = (head_to_head["home_score"] + head_to_head["away_score"]).mean()
        features["h2h_home_win_rate"] = home_wins / total if total > 0 else 0.0
        
        return features

    def _add_team_stats_features(self, features: pd.DataFrame, team_stats: Dict[str, Any]) -> pd.DataFrame:
        home_stats = team_stats.get("home", {})
        away_stats = team_stats.get("away", {})
        
        # Squad value features
        features["home_squad_value"] = self._value_or_legacy(home_stats, "squad_value", "home_squad_value")
        features["away_squad_value"] = self._value_or_legacy(away_stats, "squad_value", "away_squad_value")
        features["home_missing_value"] = self._value_or_legacy(home_stats, "missing_value", "home_missing_value")
        features["away_missing_value"] = self._value_or_legacy(away_stats, "missing_value", "away_missing_value")
        features["squad_value_diff"] = features["home_squad_value"] - features["away_squad_value"]
        
        # Elo features
        features["home_elo"] = self._value_or_legacy(home_stats, "elo", "home_elo")
        features["away_elo"] = self._value_or_legacy(away_stats, "elo", "away_elo")
        features["elo_difference"] = features["home_elo"] - features["away_elo"]
        
        return features

    def _add_advanced_team_features(self, features: pd.DataFrame, team_stats: Dict[str, Any]) -> pd.DataFrame:
        home_stats = team_stats.get("home", {})
        away_stats = team_stats.get("away", {})

        # xG features
        for side, stats in [("home", home_stats), ("away", away_stats)]:
            features[f"{side}_xg_avg_5"] = self._value_or_legacy(stats, "xg_avg_5", f"{side}_xg_avg_5")
            features[f"{side}_xg_conceded_avg_5"] = self._value_or_legacy(stats, "xg_conceded_avg_5", f"{side}_xg_conceded_avg_5")
            features[f"{side}_xg_diff_5"] = self._value_or_legacy(stats, "xg_diff_5", f"{side}_xg_diff_5")
            features[f"{side}_xg_overperformance"] = self._value_or_legacy(stats, "xg_overperformance", f"{side}_xg_overperformance")
            features[f"{side}_xg_consistency"] = self._value_or_legacy(stats, "xg_consistency", f"{side}_xg_consistency")
            
        features["xg_differential"] = features["home_xg_diff_5"] - features["away_xg_diff_5"]

        # Tactical features
        for side, stats in [("home", home_stats), ("away", away_stats)]:
            features[f"{side}_possession_style"] = self._value_or_legacy(stats, "possession_style", f"{side}_possession_style")
            features[f"{side}_pressing_intensity"] = self._value_or_legacy(stats, "pressing_intensity", f"{side}_pressing_intensity")
            features[f"{side}_first_half_goals_rate"] = self._value_or_legacy(stats, "first_half_goals_rate", f"{side}_first_half_goals_rate")
            features[f"{side}_defensive_solidity"] = self._value_or_legacy(stats, "defensive_solidity", f"{side}_defensive_solidity")
            features[f"{side}_setpiece_goals_rate"] = self._value_or_legacy(stats, "setpiece_goals_rate", f"{side}_setpiece_goals_rate")
            
            # GD trends
            features[f"{side}_gd_trend"] = self._value_or_legacy(stats, "gd_trend", f"{side}_gd_trend")
            features[f"{side}_scoring_consistency"] = self._value_or_legacy(stats, "scoring_consistency", f"{side}_scoring_consistency")

        return features

    def _add_form_trends(self, features: pd.DataFrame, current_form: Dict[str, Any]) -> pd.DataFrame:
        home_form = current_form.get("home", {})
        away_form = current_form.get("away", {})

        # Momentum features
        features["home_momentum_lambda"] = self._value_or_legacy(home_form, "momentum_lambda", "home_momentum_lambda")
        features["home_momentum_weighted"] = self._value_or_legacy(home_form, "momentum_weighted", "home_momentum_weighted")
        features["away_momentum_lambda"] = self._value_or_legacy(away_form, "momentum_lambda", "away_momentum_lambda")
        features["away_momentum_weighted"] = self._value_or_legacy(away_form, "momentum_weighted", "away_momentum_weighted")

        # Fatigue features
        features["home_days_rest"] = self._value_or_legacy(home_form, "days_rest", "home_days_rest")
        features["home_fatigue_index"] = self._value_or_legacy(home_form, "fatigue_index", "home_fatigue_index")
        features["home_fixtures_14d"] = self._value_or_legacy(home_form, "fixtures_14d", "home_fixtures_14d")
        features["home_fixture_congestion"] = self._value_or_legacy(home_form, "fixture_congestion", "home_fixture_congestion")
        
        features["away_days_rest"] = self._value_or_legacy(away_form, "days_rest", "away_days_rest")
        features["away_fatigue_index"] = self._value_or_legacy(away_form, "fatigue_index", "away_fatigue_index")
        features["away_fixtures_14d"] = self._value_or_legacy(away_form, "fixtures_14d", "away_fixtures_14d")
        features["away_fixture_congestion"] = self._value_or_legacy(away_form, "fixture_congestion", "away_fixture_congestion")

        return features

    def _add_schedule_features(self, features: pd.DataFrame, match_data: Dict[str, Any]) -> pd.DataFrame:
        schedule = match_data.get("schedule", {})
        
        # Weather features
        weather = schedule.get("weather", {})
        features["temperature"] = self._value_or_legacy(weather, "temperature", "temperature")
        features["precipitation"] = self._value_or_legacy(weather, "precipitation", "precipitation")
        features["wind_speed"] = self._value_or_legacy(weather, "wind_speed", "wind_speed")
        features["weather_impact_score"] = self._value_or_legacy(weather, "impact_score", "weather_impact_score")
        
        # Home advantage features
        features["home_advantage_win_rate"] = self._value_or_legacy(schedule, "home_advantage_win_rate", "home_advantage_win_rate")
        features["home_goals_advantage"] = self._value_or_legacy(schedule, "home_goals_advantage", "home_goals_advantage")
        features["away_win_rate_away"] = self._value_or_legacy(schedule, "away_win_rate_away", "away_win_rate_away")
        features["home_crowd_boost"] = self._value_or_legacy(schedule, "home_crowd_boost", "home_crowd_boost")
        features["home_advantage_coefficient"] = self._value_or_legacy(schedule, "home_advantage_coefficient", "home_advantage_coefficient")
        features["referee_home_bias"] = self._value_or_legacy(schedule, "referee_home_bias", "referee_home_bias")
        
        return features

    def _apply_enhanced_features(self, features: pd.DataFrame, match_data: Dict[str, Any]) -> pd.DataFrame:
        if features.empty:
            return features

        enhanced = match_data.get("enhanced_features") if isinstance(match_data, dict) else None
        if not enhanced:
            return features

        overrides: tuple[tuple[str, str, Optional[Callable[[float, Dict[str, Any]], Optional[float]]]], ...] = (
            ("ws_home_win_rate_5", "home_win_rate_5", lambda v, _: _clamp(v, 0.0, 1.0)),
            ("ws_away_win_rate_5", "away_win_rate_5", lambda v, _: _clamp(v, 0.0, 1.0)),
            ("ws_home_avg_possession", "home_possession_style", lambda v, _: _clamp(v / 100.0 if v > 1 else v, 0.0, 1.0)),
            ("ws_away_avg_possession", "away_possession_style", lambda v, _: _clamp(v / 100.0 if v > 1 else v, 0.0, 1.0)),
            ("us_home_xg_pg", "home_xg_avg_5", None),
            ("us_away_xg_pg", "away_xg_avg_5", None),
            ("us_home_xga_pg", "home_xg_conceded_avg_5", None),
            ("us_away_xga_pg", "away_xg_conceded_avg_5", None),
            ("us_home_xg_diff", "home_xg_diff_5", None),
            ("us_away_xg_diff", "away_xg_diff_5", None),
            ("tm_value_diff_m", "squad_value_diff", None),
            ("bf_market_margin_pct", "bookmaker_margin", lambda v, _: v / 100.0 if v > 1 else v),
        )

        row_index: Any = features.index[0] if len(features.index) > 0 else 0
        for source, target, transform in overrides:
            raw_value = enhanced.get(source)
            if raw_value is None:
                continue

            value = _safe_float(raw_value)
            if value is None:
                continue

            if transform is not None:
                try:
                    transformed = transform(value, enhanced)
                except Exception as exc:
                    logger.debug("Enhanced feature transform failed for %s -> %s: %s", source, target, exc)
                    continue
                if transformed is None:
                    continue
                value = transformed

            if value is None:
                continue

            safe_val: Any = float(value)
            col_dtype = features.dtypes.get(target)
            if col_dtype is not None and pd.api.types.is_integer_dtype(col_dtype):
                safe_val = int(round(float(value)))
            features.loc[row_index, target] = safe_val

        self._apply_enhanced_xg_consistency(features, enhanced, row_index)
        self._apply_enhanced_odds(features, enhanced, row_index)
        return features

    def _apply_enhanced_xg_consistency(
        self,
        features: pd.DataFrame,
        enhanced: Dict[str, Any],
        index: Any,
    ) -> None:
        home_recent = _safe_float(enhanced.get("us_home_recent_xg"))
        home_avg = _safe_float(enhanced.get("us_home_xg_pg"))
        away_recent = _safe_float(enhanced.get("us_away_recent_xg"))
        away_avg = _safe_float(enhanced.get("us_away_xg_pg"))

        def _consistency(recent: Optional[float], avg: Optional[float]) -> Optional[float]:
            if recent is None or avg is None or avg == 0:
                return None
            variance = abs(recent - avg) / max(abs(avg), 1e-3)
            return round(_clamp(1.0 - min(variance, 1.0) * 0.5, 0.0, 1.0), 3)

        home_consistency = _consistency(home_recent, home_avg)
        if home_consistency is not None:
            features.loc[index, "home_xg_consistency"] = home_consistency

        away_consistency = _consistency(away_recent, away_avg)
        if away_consistency is not None:
            features.loc[index, "away_xg_consistency"] = away_consistency

        # Recompute differential after overrides
        try:
            home_diff = _safe_float(features.loc[index, "home_xg_diff_5"])
            away_diff = _safe_float(features.loc[index, "away_xg_diff_5"])
            if home_diff is not None and away_diff is not None:
                features.loc[index, "xg_differential"] = home_diff - away_diff
        except (KeyError, ValueError, TypeError):
            pass

    def _apply_enhanced_odds(
        self,
        features: pd.DataFrame,
        enhanced: Dict[str, Any],
        index: Any,
    ) -> None:
        home_back = _safe_float(enhanced.get("bf_home_back"))
        draw_back = _safe_float(enhanced.get("bf_draw_back"))
        away_back = _safe_float(enhanced.get("bf_away_back"))

        if not all(val and val > 1.0 for val in (home_back, draw_back, away_back)):
            return

        assert home_back is not None and draw_back is not None and away_back is not None

        implied_home = 1.0 / home_back
        implied_draw = 1.0 / draw_back
        implied_away = 1.0 / away_back
        total = implied_home + implied_draw + implied_away
        if total <= 0:
            return

        features.loc[index, "home_implied_prob"] = implied_home / total
        margin = (implied_home + implied_draw + implied_away) - 1.0
        if margin > 0:
            features.loc[index, "bookmaker_margin"] = _clamp(margin, 0.0, 0.3)

    def _handle_missing_values(self, features: pd.DataFrame) -> pd.DataFrame:
        if features.empty:
            return features
        if self._fail_closed_enabled() and features.isnull().any().any():
            # PHASE7_FEATURES_ALWAYS_DATA_GAP occupy a vector slot purely for
            # artifact dimensional compatibility and are *defined* never to carry a
            # live value (feature_registry). Treating them as required evidence
            # would make this fail-closed guard reject every request on features
            # that can never, by design, be populated — turning a correct guard
            # into a permanent outage. They fall through to the default fill below.
            missing = [
                str(col)
                for col in features.columns
                if features[col].isnull().any()
                and str(col) not in _ALWAYS_DATA_GAP_FEATURES
            ]
            if missing:
                raise DataUnavailableError(
                    "Required feature values unavailable: " + ", ".join(missing),
                    provider="internal",
                    evidence_type="feature_values",
                )
        # Fill NaN values with column means, but if mean is NaN, use 0
        for col in features.columns:
            if features[col].isnull().any():
                mean_val = features[col].mean()
                if pd.isna(mean_val):
                    features[col] = features[col].fillna(0.0)
                else:
                    features[col] = features[col].fillna(mean_val)
        return features

    def _scale_features(self, features: pd.DataFrame) -> pd.DataFrame:
        """Scale features for model input.
        
        IMPORTANT: StandardScaler.fit_transform on a single row will output zeros
        because (value - mean) / std = 0/0 for single values.
        
        For single-row predictions, we skip scaling since:
        1. The model was trained on raw features
        2. Or if scaling was used during training, we'd need the stored scaler
        
        In production, the ensemble model handles its own preprocessing if needed.
        """
        if features.empty:
            return features
        
        # Skip scaling for single rows - it would zero everything out
        if len(features) <= 1:
            return features
            
        num_cols = features.select_dtypes(include=[np.number]).columns
        if len(num_cols) > 0:
            features[num_cols] = self.scaler.fit_transform(features[num_cols])
        return features

    def _validate_features(self, features: pd.DataFrame) -> pd.DataFrame:
        fill_value = 0.0 if not self._fail_closed_enabled() else float("nan")
        ordered = features.reindex(columns=self.expected_columns, fill_value=fill_value).copy()

        if len(ordered) != 1:
            logger.warning("Expected a single feature row, got %s rows", len(ordered))
            if len(ordered) > 0:
                ordered = ordered.iloc[[0]].copy()
            else:
                if self._fail_closed_enabled():
                    raise DataUnavailableError(
                        "No feature row produced for production inference",
                        provider="internal",
                        evidence_type="feature_row",
                    )
                ordered = pd.DataFrame([{c: 0.0 for c in self.expected_columns}])

        if ordered.isnull().any().any():
            if self._fail_closed_enabled():
                missing = [str(col) for col in ordered.columns if ordered[col].isnull().any()]
                raise DataUnavailableError(
                    "Required canonical features unavailable: " + ", ".join(missing),
                    provider="internal",
                    evidence_type="canonical_features",
                )
            ordered = ordered.fillna(0.0)

        return pd.DataFrame(ordered)

    def _ensure_minimum_row(self, features: pd.DataFrame) -> pd.DataFrame:
        if not features.empty:
            return features
        if self._fail_closed_enabled():
            raise DataUnavailableError(
                "No engineered features available for production inference",
                provider="internal",
                evidence_type="feature_row",
            )
        defaults = {column: 0.0 for column in self.expected_columns}
        return pd.DataFrame([defaults])
