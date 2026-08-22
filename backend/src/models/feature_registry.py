"""Canonical feature registry for inference-safe SabiScore models."""

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Canonical production feature schema (58) from sabiscore_production_v2 metadata.
CANONICAL_FEATURES_58: List[str] = [
    "home_form_last5_home",
    "home_wins_last5_home",
    "home_draws_last5_home",
    "home_losses_last5_home",
    "away_form_last5_away",
    "away_wins_last5_away",
    "away_draws_last5_away",
    "away_losses_last5_away",
    "home_goals_for_avg",
    "home_goals_against_avg",
    "away_goals_for_avg",
    "away_goals_against_avg",
    "total_goals_expected",
    "home_gd_recent",
    "away_gd_recent",
    "combined_attack",
    "combined_defense_weakness",
    "market_prob_home",
    "market_prob_draw",
    "market_prob_away",
    "market_edge_home",
    "market_favorite",
    "odds_ratio",
    "log_odds_home",
    "log_odds_draw",
    "log_odds_away",
    "draw_probability",
    "market_confidence",
    "ev_home",
    "ev_draw",
    "ev_away",
    "h2h_home_wins",
    "h2h_away_wins",
    "h2h_draws",
    "h2h_matches",
    "h2h_dominance",
    "home_venue_win_rate",
    "home_venue_draw_rate",
    "home_venue_loss_rate",
    "home_advantage_strength",
    "day_of_week",
    "is_weekend",
    "month",
    "season_phase",
    "league_home_rate",
    "league_avg_goals",
    "league_draw_rate",
    "form_market_agreement_home",
    "form_market_disagreement",
    "home_attack_vs_away_defense",
    "away_attack_vs_home_defense",
    "venue_market_combo",
    "h2h_market_agreement",
    "league_Bundesliga",
    "league_EPL",
    "league_La_Liga",
    "league_Ligue_1",
    "league_Serie_A",
]

# Phase 7-A expansion - 2026-05-31.
# The 58-feature schema remains intact for backward compatibility with pre-Phase-7 models.
#
# ATE resolution — Phase 8 Sprint 1 gate (2026-06-10):
#   CONFIRMED (causal report): elo_difference (ATE=0.335), home_pressing_intensity (ATE=0.146)
#   ASSUMPTION-PASS (proxy ATE ≥ 0.02): elo_home_trend_5, elo_away_trend_5,
#     elo_momentum_cross, progressive_carry_diff, shot_quality_diff
#
#   REMOVED from canonical Phase 7 set — pending_count now 0:
#     elo_league_adjusted     — proxy collinear with elo_difference; ATE not independently
#                               estimable from current data. Removed to prevent leakage-adjacent
#                               signal confusion. Eligible for re-introduction only after
#                               StatsBomb league-adjusted ratings are available (Phase 8.5+).
#     key_passes_under_pressure_diff — proxy ATE=0.005, well below 0.02 threshold. Negligible
#                               causal signal; retaining it inflates feature count without benefit.
#     set_piece_xg_diff       — mixed signal across leagues; validation returned inconclusive
#                               directionality. Remove until per-league ATE can be confirmed.
#
# CANONICAL_FEATURES_68 is the artifact-compatible set (58 base + 10 phase7).
# PENDING FEATURE COUNT: 0 — gate cleared for Phase 8 training path.
# Column order is the trained artifact's own `feature_columns`, verified identical
# across all six v5_phase7 .pkl files. It is NOT free to reorder: inference indexes
# positionally.
#
# ⚠️ elo_league_adjusted / key_passes_under_pressure_diff / set_piece_xg_diff were
# deleted from this list on 2026-06-10 as carrying no independent ATE signal. Removing
# the *slots* rather than just the computation broke every artifact: they expect 68
# columns, the registry then emitted 65, and PredictionEngine correctly refuses to
# zero-pad a short vector (that refusal is the anti-fabrication guard, working as
# designed). The result was model_version="fallback" on every single inference —
# the certified model never ran in production once between that change and
# 2026-08-08, on any league.
#
# They are restored here as slots only. Every one of them is in
# PHASE7_FEATURES_ALWAYS_DATA_GAP below, so the value is always the registry default
# and is never computed from live data — exactly the existing treatment of
# shot_quality_diff, which has always sat in both lists. The substantive B13
# invariant ("never compute a live value for an unvalidated feature") is unchanged;
# only "absent from the vector" changed, because that part was incompatible with
# the artifacts actually being served.
PHASE7_FEATURES_10: List[str] = [
    "elo_difference",
    "elo_home_trend_5",
    "elo_away_trend_5",
    "elo_league_adjusted",
    "elo_momentum_cross",
    "home_pressing_intensity",
    "progressive_carry_diff",
    "shot_quality_diff",
    "key_passes_under_pressure_diff",
    "set_piece_xg_diff",
]

# Deprecated alias — holds 10, not 7. Retained because production code imports it by
# name (upcoming_match_feature_service.py); same object, not a copy.
PHASE7_FEATURES_7 = PHASE7_FEATURES_10

# Removed Phase 7 features — kept for audit trail and future re-evaluation.
# DO NOT include these in any training vector without re-running ATE validation.
PHASE7_FEATURES_REMOVED: List[str] = [
    "elo_league_adjusted",           # collinear proxy, no independent ATE signal
    "key_passes_under_pressure_diff",  # proxy ATE=0.005 < threshold
    "set_piece_xg_diff",             # mixed/inconclusive directional signal
]

# Features that remain in CANONICAL_FEATURES_68 for backward compatibility with v5_phase7
# model artifacts (removing them would cause dimension mismatch on loaded .pkl files) but
# MUST always be returned as DATA_GAP at inference time. The vector slot is present; the
# value is always the registry default. Do not compute live values for these features.
#
# Phase 8 Sprint 4 decision (2026-06-10):
#   shot_quality_diff — proxy ATE unreliable without real StatsBomb shot-map data.
#   Proxy derived from xg_avg_5 difference collapses to q75=0 on synthetic training data,
#   making ATE estimates non-discriminative. Permanent DATA_GAP until real StatsBomb
#   event-level shots corpus confirms ATE >= 0.02 (see guardrail 12 in Sprint 4 brief).
PHASE7_FEATURES_ALWAYS_DATA_GAP: List[str] = [
    "shot_quality_diff",
    # Restored as slots for artifact compatibility (see PHASE7_FEATURES_10) and
    # listed here so they are never computed live — the vector position exists,
    # the value is always the registry default.
    *PHASE7_FEATURES_REMOVED,
]

# Apex candidate schema. The active v5 contract above remains byte-for-byte
# compatible; candidate training replaces its redundant market block under a
# distinct manifest rather than silently changing positional semantics.
APEX_MARKET_FEATURES_14: List[str] = [
    "market_prob_home",
    "market_prob_draw",
    "market_prob_away",
    "market_overround",
    "market_favorite_home",
    "market_favorite_draw",
    "market_favorite_away",
    "log_odds_home",
    "log_odds_draw",
    "log_odds_away",
    "market_probability_margin",
    "market_normalized_entropy",
    "market_home_away_probability_diff",
    "odds_ratio",
]

APEX_FEATURES_58: List[str] = [
    *CANONICAL_FEATURES_58[:17],
    *APEX_MARKET_FEATURES_14,
    *CANONICAL_FEATURES_58[31:],
]

CANONICAL_FEATURES_68: List[str] = [
    *CANONICAL_FEATURES_58,
    *PHASE7_FEATURES_10,
]

APEX_FEATURES_68: List[str] = [*APEX_FEATURES_58, *PHASE7_FEATURES_10]

# Deprecated alias — holds 68, not 65. The 2026-06-10 rename to _65 described a
# vector the serving artifacts could not accept; see PHASE7_FEATURES_10. Retained
# because tests and older code import it by name; same object, not a copy.
CANONICAL_FEATURES_65 = CANONICAL_FEATURES_68

DEFAULT_FEATURE_VALUES_58: Dict[str, float] = {
    "home_form_last5_home": 1.5,
    "home_wins_last5_home": 2.0,
    "home_draws_last5_home": 1.0,
    "home_losses_last5_home": 2.0,
    "away_form_last5_away": 1.3,
    "away_wins_last5_away": 1.0,
    "away_draws_last5_away": 1.0,
    "away_losses_last5_away": 3.0,
    "home_goals_for_avg": 1.55,
    "home_goals_against_avg": 1.20,
    "away_goals_for_avg": 1.25,
    "away_goals_against_avg": 1.40,
    "total_goals_expected": 2.80,
    "home_gd_recent": 0.35,
    "away_gd_recent": -0.15,
    "combined_attack": 2.80,
    "combined_defense_weakness": 2.60,
    "market_prob_home": 0.42,
    "market_prob_draw": 0.26,
    "market_prob_away": 0.32,
    "market_edge_home": 0.10,
    "market_favorite": 0.0,
    "odds_ratio": 1.0,
    "log_odds_home": 0.0,
    "log_odds_draw": 0.0,
    "log_odds_away": 0.0,
    "draw_probability": 0.26,
    "market_confidence": 0.42,
    "ev_home": 0.0,
    "ev_draw": 0.0,
    "ev_away": 0.0,
    "h2h_home_wins": 2.0,
    "h2h_away_wins": 2.0,
    "h2h_draws": 1.0,
    "h2h_matches": 5.0,
    "h2h_dominance": 0.0,
    "home_venue_win_rate": 0.50,
    "home_venue_draw_rate": 0.26,
    "home_venue_loss_rate": 0.24,
    "home_advantage_strength": 0.26,
    "day_of_week": 5.0,
    "is_weekend": 1.0,
    "month": 8.0,
    "season_phase": 0.5,
    "league_home_rate": 0.42,
    "league_avg_goals": 2.75,
    "league_draw_rate": 0.246,
    "form_market_agreement_home": 0.21,
    "form_market_disagreement": 0.08,
    "home_attack_vs_away_defense": 0.15,
    "away_attack_vs_home_defense": 0.05,
    "venue_market_combo": 0.21,
    "h2h_market_agreement": 0.0,
    "league_Bundesliga": 0.0,
    "league_EPL": 1.0,
    "league_La_Liga": 0.0,
    "league_Ligue_1": 0.0,
    "league_Serie_A": 0.0,
}

DEFAULT_FEATURE_VALUES_68: Dict[str, float] = {
    **DEFAULT_FEATURE_VALUES_58,
    "elo_difference": 0.0,
    "elo_home_trend_5": 0.0,
    "elo_away_trend_5": 0.0,
    "elo_momentum_cross": 0.0,
    "home_pressing_intensity": 0.55,
    "progressive_carry_diff": 0.0,
    "shot_quality_diff": 0.0,
    # Restored 2026-08-08 for artifact compatibility. These three are permanently
    # in PHASE7_FEATURES_ALWAYS_DATA_GAP, so this default is the ONLY value they
    # ever take — nothing computes them from live data. Neutral (0.0), matching
    # their Phase 7 siblings above.
    "elo_league_adjusted": 0.0,
    "key_passes_under_pressure_diff": 0.0,
    "set_piece_xg_diff": 0.0,
}


# ── Phase 8 feature expansion ─────────────────────────────────────────────────
# Phase 8 feature expansion — built on top of the artifact-compatible 68-feature set.
# CANONICAL_FEATURES_68 is the base; new features are accumulated here.
# Do not append to the Phase 7 list — v5_phase7 models were trained on a 68-column
# vector (pre-removal) and will continue to load correctly at inference time via
# backward-compatible defaults. New v6_phase8 models will train on CANONICAL_FEATURES_89.
#
# Phase 8 feature groups (21 new features, ATE validation required):
#   Pi-ratings (6):  home/away attack+defense, diffs      [5a]
#   Berrar ratings (3): home/away rating, diff             [5a.5]
#   EWMA form (6):   weighted win/draw rate + PPG × 2     [5b]
#   Market (5):      odds drifts + direction               [5d]
#   Match context (1): importance score                    [5e]

PHASE8_FEATURES_PI: List[str] = [
    "home_pi_attack",
    "home_pi_defense",
    "away_pi_attack",
    "away_pi_defense",
    "pi_attack_diff",
    "pi_defense_diff",
]

PHASE8_FEATURES_BERRAR: List[str] = [
    "home_berrar_rating",
    "away_berrar_rating",
    "berrar_rating_diff",
]

PHASE8_FEATURES_FORM: List[str] = [
    "home_weighted_win_rate",
    "home_weighted_draw_rate",
    "home_weighted_ppg",
    "away_weighted_win_rate",
    "away_weighted_draw_rate",
    "away_weighted_ppg",
]

PHASE8_FEATURES_MARKET: List[str] = [
    "odds_drift_home",
    "odds_drift_draw",
    "odds_drift_away",
    "max_abs_odds_drift",
    "sharp_money_direction",
]

PHASE8_FEATURES_CONTEXT: List[str] = [
    "match_importance_score",
]

# All Phase 8 input features: 6 Pi + 3 Berrar + 6 EWMA form + 5 market + 1 context = 21.
# The name says what it holds. The historical `_18` name (below) predates the FORM group
# growing from 3 to 6 entries and undercounted from then on — a variable whose name
# disagrees with its own len() is the same drift class as a stale docstring.
PHASE8_FEATURES_21: List[str] = [
    *PHASE8_FEATURES_PI,
    *PHASE8_FEATURES_BERRAR,
    *PHASE8_FEATURES_FORM,
    *PHASE8_FEATURES_MARKET,
    *PHASE8_FEATURES_CONTEXT,
]

# 68 Phase 7 (artifact-compatible) + 21 Phase 8 = 89.
# Was 86 while the Phase 7 base was 65; restoring the three artifact slots moved it.
# Phase 8 is shadow-only and disabled in production (PHASE9_SHADOW_ONLY / phase8_enabled),
# so nothing is served from this set today — but a v6_phase8 retrain must train on 89.
CANONICAL_FEATURES_89: List[str] = [
    *CANONICAL_FEATURES_68,
    *PHASE8_FEATURES_21,
]

# The Apex-ordered equivalent, mirroring APEX_FEATURES_68's relationship to
# CANONICAL_FEATURES_68 (the Apex market block replaces the legacy one in place).
# train_on_real_matches.py builds its X matrix from the Apex ordering, so a
# Phase 8 training run needs this list rather than CANONICAL_FEATURES_89.
APEX_FEATURES_89: List[str] = [*APEX_FEATURES_68, *PHASE8_FEATURES_21]

# Deprecated aliases — the counts in these names are wrong (they hold 21, 89 and 89
# respectively). Retained, not deleted: all are imported across production code
# (`api/endpoints/phase8_features.py`) and tests, so removing them is a breaking
# change under INV-17. Prefer the accurate names above in new code; these are the
# same objects, not copies.
PHASE8_FEATURES_18 = PHASE8_FEATURES_21
CANONICAL_FEATURES_86 = CANONICAL_FEATURES_89
CANONICAL_FEATURES_83 = CANONICAL_FEATURES_89

# Default values for Phase 8 features — used when live data is unavailable.
# Pi/Berrar defaults are 0.0 (neutral) because only diffs matter to the model.
# Market defaults assume no observable drift. Context defaults to 0.3 (moderate).
DEFAULT_FEATURE_VALUES_89: Dict[str, float] = {
    **DEFAULT_FEATURE_VALUES_68,
    # Pi-ratings
    "home_pi_attack": 0.0,
    "home_pi_defense": 0.0,
    "away_pi_attack": 0.0,
    "away_pi_defense": 0.0,
    "pi_attack_diff": 0.0,
    "pi_defense_diff": 0.0,
    # Berrar ratings — initialised at 1500 in-system; diff=0 for defaults
    "home_berrar_rating": 1500.0,
    "away_berrar_rating": 1500.0,
    "berrar_rating_diff": 0.0,
    # EWMA form — priors for an average team
    "home_weighted_win_rate": 0.40,
    "home_weighted_draw_rate": 0.28,
    "home_weighted_ppg": 1.48,
    "away_weighted_win_rate": 0.32,
    "away_weighted_draw_rate": 0.26,
    "away_weighted_ppg": 1.22,
    # Market movement — no drift observed
    "odds_drift_home": 0.0,
    "odds_drift_draw": 0.0,
    "odds_drift_away": 0.0,
    "max_abs_odds_drift": 0.0,
    "sharp_money_direction": 0.0,
    # Match context — low importance by default
    "match_importance_score": 0.2,
}

# Deprecated alias, same object — imported by name in tests and older code.
DEFAULT_FEATURE_VALUES_86 = DEFAULT_FEATURE_VALUES_89


# ── Declared feature-schema contracts ────────────────────────────────────────
# `active_generation.json` names the contract its artifacts were trained against
# in `feature_schema_version`. Until this map existed that string resolved to
# nothing: the manifest hash-protects every artifact's bytes while the contract
# describing their shape was unvalidated free text. Six public consumers
# (`/health`, `/api/v1/models/status`, `legacy_endpoints`, and every prediction's
# provenance block) republish it as fact, and `prediction.py` answers a width
# mismatch with `_fallback_result()` rather than raising — so relabelling a
# 68-column generation as 89 would silently degrade every prediction to fallback
# while the API kept reporting the false schema. Keys are the only strings a
# manifest may declare; add one here before shipping an artifact that claims it.
FEATURE_SCHEMA_VERSIONS: Dict[str, List[str]] = {
    "phase7_68": CANONICAL_FEATURES_68,
    "apex_v1_68": APEX_FEATURES_68,
    "phase8_89": CANONICAL_FEATURES_89,
    "apex_v1_89": APEX_FEATURES_89,
}


class UnknownFeatureSchemaError(ValueError):
    """A declared feature_schema_version matches no registered contract."""


def resolve_feature_schema(version: object) -> List[str]:
    """Return the ordered feature contract a declared schema version names.

    Raises rather than returning a permissive default: an unrecognised schema
    string is exactly the case where the caller's belief about vector shape is
    least trustworthy, and a fallback would launder that into a confident answer.
    """

    if not isinstance(version, str) or not version.strip():
        raise UnknownFeatureSchemaError("feature_schema_version is missing or empty")
    key = version.strip()
    try:
        return FEATURE_SCHEMA_VERSIONS[key]
    except KeyError as exc:
        raise UnknownFeatureSchemaError(
            f"Unknown feature_schema_version {key!r}; expected one of "
            f"{sorted(FEATURE_SCHEMA_VERSIONS)}"
        ) from exc


def active_canonical_features(use_phase7: bool, use_phase8: bool = False) -> List[str]:
    if use_phase8:
        return list(CANONICAL_FEATURES_89)
    return list(CANONICAL_FEATURES_68 if use_phase7 else CANONICAL_FEATURES_58)


def active_default_feature_values(
    use_phase7: bool, use_phase8: bool = False
) -> Dict[str, float]:
    if use_phase8:
        return dict(DEFAULT_FEATURE_VALUES_89)
    return dict(DEFAULT_FEATURE_VALUES_68 if use_phase7 else DEFAULT_FEATURE_VALUES_58)


def canonical_feature_count() -> int:
    return len(CANONICAL_FEATURES_58)


def canonical_feature_count_phase7() -> int:
    """Returns the Phase 7 serving feature count (68 — matches the v5_phase7 artifacts)."""
    return len(CANONICAL_FEATURES_68)


def canonical_feature_count_phase8() -> int:
    """Returns the Phase 8 feature count (89 = 68 phase7 + 21 phase8)."""
    return len(CANONICAL_FEATURES_89)


def derive_last5_form_features(
    form_5: float,
    win_rate_5: float,
    *,
    is_home: bool,
    wins_5: Optional[float] = None,
    draws_5: Optional[float] = None,
    losses_5: Optional[float] = None,
) -> Dict[str, float]:
    """WP-18/WP-10.3: pure remap from rate-based team-form stats (the
    home_form_5/home_win_rate_5-style keys UpcomingMatchFeatureProjector and
    ScrapedTeamForm.to_projection_stats() both produce) onto the 4 canonical
    last-5 fields CANONICAL_FEATURES_58 declares per side
    (``{side}_form_last5_{side}`` etc.). This is the same formula
    FeatureTransformer._project_to_canonical_features() has always used:
    form_last5 = form_5 * 3.0; wins_last5 = round(win_rate_5 * 5.0), with
    draws/losses split from a fixed 2-loss baseline — an algebraic estimate,
    not a real count.

    When wins_5/draws_5/losses_5 (real last-5 integer counts) are all
    supplied, they're used verbatim instead of the estimate — strictly more
    accurate whenever the caller has them. All-or-nothing: a partial trio
    (e.g. only wins_5) falls back to the full estimate rather than mixing
    real and derived values.
    """
    side = "home" if is_home else "away"
    if wins_5 is not None and draws_5 is not None and losses_5 is not None:
        wins, draws, losses = float(wins_5), float(draws_5), float(losses_5)
    else:
        wins = float(round(win_rate_5 * 5.0))
        draws = max(0.0, 5.0 - wins - 2.0)
        losses = max(0.0, 5.0 - wins - draws)
    return {
        f"{side}_form_last5_{side}": form_5 * 3.0,
        f"{side}_wins_last5_{side}": wins,
        f"{side}_draws_last5_{side}": draws,
        f"{side}_losses_last5_{side}": losses,
    }


# Per-league priors: (home_win_rate, avg_total_goals, draw_rate). Constants, not
# measurements — identical at training and serving time, which is the only
# property that matters for train/serve consistency. Mirrors the table in
# FeatureTransformer._project_to_canonical_features().
LEAGUE_RATE_PRIORS: Dict[str, Tuple[float, float, float]] = {
    "epl": (0.42, 2.85, 0.246),
    "la_liga": (0.44, 2.60, 0.255),
    "bundesliga": (0.45, 3.05, 0.228),
    "serie_a": (0.43, 2.58, 0.272),
    "ligue_1": (0.41, 2.66, 0.259),
}
_LEAGUE_RATE_FALLBACK = (0.42, 2.75, 0.246)

# Canonical league key -> the one-hot column that must be 1.0 for it. The
# 58-feature schema carries no Eredivisie/UCL column, so those leagues
# legitimately produce an all-zero one-hot block rather than a fabricated flag.
_LEAGUE_ONEHOT_ALIASES: Dict[str, str] = {
    "epl": "league_EPL",
    "premier_league": "league_EPL",
    "la_liga": "league_La_Liga",
    "laliga": "league_La_Liga",
    "bundesliga": "league_Bundesliga",
    "serie_a": "league_Serie_A",
    "seriea": "league_Serie_A",
    "ligue_1": "league_Ligue_1",
    "ligue1": "league_Ligue_1",
}
LEAGUE_ONEHOT_FEATURES = (
    "league_Bundesliga", "league_EPL", "league_La_Liga",
    "league_Ligue_1", "league_Serie_A",
)
TEMPORAL_FEATURES = ("day_of_week", "is_weekend", "month", "season_phase")
LEAGUE_RATE_FEATURES = ("league_home_rate", "league_avg_goals", "league_draw_rate")
COMBINATION_FEATURES = (
    "combined_attack", "combined_defense_weakness",
    "home_attack_vs_away_defense", "away_attack_vs_home_defense",
)


def _league_key(league: str) -> str:
    return str(league or "").strip().lower().replace(" ", "_")


def derive_temporal_features(match_date: datetime) -> Dict[str, float]:
    """Kickoff-derived schedule features. Pure — no I/O, no clock read.

    Same definitions as FeatureTransformer._project_to_canonical_features() so
    both pipelines feed the artifact identical semantics.
    """
    return {
        "day_of_week": float(match_date.weekday()),
        "is_weekend": 1.0 if match_date.weekday() >= 5 else 0.0,
        "month": float(match_date.month),
        "season_phase": float(min(max((match_date.month - 1) / 11.0, 0.0), 1.0)),
    }


def has_league_rate_priors(league: str) -> bool:
    """Does this league have measured priors, or will it take the fallback?

    Public because a stricter caller may want to refuse rather than accept the
    fallback: FeatureTransformer raises DataUnavailableError for an unsupported
    league, while UpcomingMatchFeatureProjector must keep serving Eredivisie
    and UCL, which legitimately have no one-hot column. derive_league_features
    itself stays permissive so both callers can share it; the strictness lives
    with the caller that wants it.
    """
    return _league_key(league) in LEAGUE_RATE_PRIORS


def derive_league_features(league: str) -> Dict[str, float]:
    """League one-hots plus the three league-prior rates."""
    key = _league_key(league)
    home_rate, avg_goals, draw_rate = LEAGUE_RATE_PRIORS.get(key, _LEAGUE_RATE_FALLBACK)
    out: Dict[str, float] = {name: 0.0 for name in LEAGUE_ONEHOT_FEATURES}
    onehot = _LEAGUE_ONEHOT_ALIASES.get(key)
    if onehot is not None:
        out[onehot] = 1.0
    out["league_home_rate"] = home_rate
    out["league_avg_goals"] = avg_goals
    out["league_draw_rate"] = draw_rate
    return out


def derive_combination_features(
    home_goals_for_avg: float,
    home_goals_against_avg: float,
    away_goals_for_avg: float,
    away_goals_against_avg: float,
) -> Dict[str, float]:
    """Pure arithmetic over the four per-side goal averages.

    Adds no new information — but the artifact has a slot for each, and leaving
    them at a registry default while their four inputs are genuinely resolved
    discards signal the model can use.
    """
    return {
        "combined_attack": home_goals_for_avg + away_goals_for_avg,
        "combined_defense_weakness": home_goals_against_avg + away_goals_against_avg,
        "home_attack_vs_away_defense": home_goals_for_avg - away_goals_against_avg,
        "away_attack_vs_home_defense": away_goals_for_avg - home_goals_against_avg,
    }


# WP-A: the 14 canonical market fields CANONICAL_FEATURES_58 declares (see
# feature_registry.py:25-38), in that same order.
MARKET_FEATURES_14 = (
    "market_prob_home", "market_prob_draw", "market_prob_away",
    "market_edge_home", "market_favorite", "odds_ratio",
    "log_odds_home", "log_odds_draw", "log_odds_away",
    "draw_probability", "market_confidence",
    "ev_home", "ev_draw", "ev_away",
)


def derive_market_features(
    home_odds: float, draw_odds: float, away_odds: float,
) -> Dict[str, float]:
    """WP-A: pure remap from 1X2 decimal odds onto the 14 canonical market
    fields (MARKET_FEATURES_14). Numerically identical to the inline formula
    FeatureTransformer._project_to_canonical_features() (data/transformers.py
    lines ~324-379) has always used — this is the shared, callable version so
    training (train_on_real_matches.py) and live serving
    (upcoming_match_feature_service.py) compute it from the SAME code, per the
    WP-18 train/serve-consistency precedent set by derive_last5_form_features()
    above. transformers.py's own inline copy is left untouched: it is live,
    tested, and out of scope for this change.

    Invalid prices are rejected. Provider/schema errors must not be repaired
    into plausible-looking evidence.

    ev_home == ev_draw == ev_away always under this formula — algebraically,
    each equals (1/overround) - 1, since market_prob_i * odds_i == 1/overround
    for every outcome once probabilities are de-vigged from the same odds they
    price. This is not a bug; it is what "EV against your own de-vigged
    probabilities" means.

    De-vigs inline ((1/odds_i)/overround per outcome) rather than importing
    providers.the_odds_api.devig_probabilities, which does the identical
    arithmetic — this module is loaded standalone (module name "models",
    outside the real "src" package tree) by tests/test_phase_c_pipeline.py's
    bootstrap to dodge core.database's import-time DB connection, and a
    relative import reaching into a sibling package breaks under that
    isolation. Two lines of duplicated arithmetic is a smaller, more robust
    diff than fixing the bootstrap.
    """
    home_odds, draw_odds, away_odds = _validated_market_prices(
        home_odds, draw_odds, away_odds
    )

    overround = (1 / home_odds) + (1 / draw_odds) + (1 / away_odds)
    market_prob_home = (1 / home_odds) / overround
    market_prob_draw = (1 / draw_odds) / overround
    market_prob_away = (1 / away_odds) / overround
    probs = [market_prob_home, market_prob_draw, market_prob_away]

    return {
        "market_prob_home": market_prob_home,
        "market_prob_draw": market_prob_draw,
        "market_prob_away": market_prob_away,
        "market_edge_home": market_prob_home - market_prob_away,
        "market_favorite": float(probs.index(max(probs))),
        "odds_ratio": home_odds / away_odds,
        "log_odds_home": math.log(home_odds),
        "log_odds_draw": math.log(draw_odds),
        "log_odds_away": math.log(away_odds),
        "draw_probability": market_prob_draw,
        "market_confidence": max(probs),
        "ev_home": market_prob_home * home_odds - 1.0,
        "ev_draw": market_prob_draw * draw_odds - 1.0,
        "ev_away": market_prob_away * away_odds - 1.0,
    }


def _validated_market_prices(
    home_odds: float, draw_odds: float, away_odds: float
) -> Tuple[float, float, float]:
    try:
        prices = (float(home_odds), float(draw_odds), float(away_odds))
    except (TypeError, ValueError) as exc:
        raise ValueError("1X2 prices must be finite decimal numbers") from exc
    if not all(math.isfinite(price) and price > 1.0 for price in prices):
        raise ValueError("1X2 prices must be finite and greater than 1.0")
    return prices


def derive_apex_market_features(
    home_odds: float, draw_odds: float, away_odds: float
) -> Dict[str, float]:
    """Build the non-redundant Apex market block from one coherent snapshot."""

    home_odds, draw_odds, away_odds = _validated_market_prices(
        home_odds, draw_odds, away_odds
    )
    raw = (1.0 / home_odds, 1.0 / draw_odds, 1.0 / away_odds)
    overround = sum(raw)
    if not 1.0 <= overround <= 1.25:
        raise ValueError("1X2 market overround is outside integrity limits")
    probs = tuple(value / overround for value in raw)
    ordered = sorted(probs, reverse=True)
    favorite = max(range(3), key=probs.__getitem__)
    entropy = -sum(prob * math.log(prob) for prob in probs) / math.log(3.0)
    return {
        "market_prob_home": probs[0],
        "market_prob_draw": probs[1],
        "market_prob_away": probs[2],
        "market_overround": overround,
        "market_favorite_home": float(favorite == 0),
        "market_favorite_draw": float(favorite == 1),
        "market_favorite_away": float(favorite == 2),
        "log_odds_home": math.log(home_odds),
        "log_odds_draw": math.log(draw_odds),
        "log_odds_away": math.log(away_odds),
        "market_probability_margin": ordered[0] - ordered[1],
        "market_normalized_entropy": entropy,
        "market_home_away_probability_diff": probs[0] - probs[2],
        "odds_ratio": home_odds / away_odds,
    }


# ── Machine-readable feature contract (docs/DEBT.md item 36) ────────────────
# Three prior artifacts described this contract in three incompatible shapes:
# this module's own name-only lists, backend/models/candidate/
# feature_availability_matrix.json (stale relative to its own producer,
# promotion_evidence.py), and docs/apex_feature_availability.json (no
# producer anywhere in the repo). None of them agreed, and most of the §7.1
# metadata fields (unit, lookahead_risk, availability_time, monitoring_rule,
# ...) do not exist anywhere in real code — inventing plausible values for
# them would be fabrication on the exact surface this contract exists to
# make trustworthy.
#
# build_feature_contract() derives only what real code can answer and marks
# everything else UNDECLARED. It is the single generator going forward:
# scripts/generate_feature_contract.py writes its output to
# backend/models/feature_contract.json, and active_generation.py's build
# gate regenerates it on every load, failing closed if the checked-in copy
# has drifted — the same class of silent staleness that produced this debt
# item in the first place.

UNDECLARED = "UNDECLARED"

_DISPOSITION_DEFER_UNTIL_DATA_EXISTS = "DEFER_UNTIL_DATA_EXISTS"
_DISPOSITION_ALIGNED_OBSERVED = "ALIGNED_OBSERVED"

_DEFAULT_VALUE_SOURCES: Dict[str, Dict[str, float]] = {
    "phase7_68": DEFAULT_FEATURE_VALUES_68,
    "apex_v1_68": DEFAULT_FEATURE_VALUES_68,
    "phase8_89": DEFAULT_FEATURE_VALUES_89,
    "apex_v1_89": DEFAULT_FEATURE_VALUES_89,
}

# Named subgroups to check membership against, most specific first. Every
# entry is a real constant already declared above — this is a lookup over
# structure that exists, not an invented taxonomy.
_NAMED_FEATURE_GROUPS: List[Tuple[str, Sequence[str]]] = [
    ("PHASE8_FEATURES_PI", PHASE8_FEATURES_PI),
    ("PHASE8_FEATURES_BERRAR", PHASE8_FEATURES_BERRAR),
    ("PHASE8_FEATURES_FORM", PHASE8_FEATURES_FORM),
    ("PHASE8_FEATURES_MARKET", PHASE8_FEATURES_MARKET),
    ("PHASE8_FEATURES_CONTEXT", PHASE8_FEATURES_CONTEXT),
    ("PHASE7_FEATURES_10", PHASE7_FEATURES_10),
    ("MARKET_FEATURES_14", MARKET_FEATURES_14),
    ("APEX_MARKET_FEATURES_14", APEX_MARKET_FEATURES_14),
    ("LEAGUE_ONEHOT_FEATURES", LEAGUE_ONEHOT_FEATURES),
    ("TEMPORAL_FEATURES", TEMPORAL_FEATURES),
    ("LEAGUE_RATE_FEATURES", LEAGUE_RATE_FEATURES),
    ("COMBINATION_FEATURES", COMBINATION_FEATURES),
]

# §7.1 metadata fields no code in this repository can answer today. Declaring
# them explicitly UNDECLARED — rather than omitting them or guessing — is the
# honest form of "not yet known": DEBT.md item 36 forbids inventing plausible
# values for these on the exact surface Phase 3 exists to make trustworthy.
#
# `training_source` / `serving_source` / `shadow_source` are NOT in this list —
# see _training_source() / _serving_source() / _shadow_source() below, which
# resolve them per-feature-group where a real, grep-verified derivation
# exists and fall back to UNDECLARED everywhere else. `source` (the generic,
# pipeline-agnostic field) and `offline_backtest_source` stay here: `source`
# would just restate one of the per-pipeline answers under an ambiguous name,
# and `offline_backtest_source` is genuinely unanswerable for every feature —
# walk_forward_validate() (models/model_registry.py) consumes pre-computed
# {date, outcome, probs} records; it has no independent feature-computation
# step to cite as a source. See docs/DEBT.md item 36.
_UNDECLARED_FIELDS: Tuple[str, ...] = (
    "semantic_definition",
    "source",
    "offline_backtest_source",
    "availability_time",
    "lookahead_risk",
    "missingness_policy",
    "normalization",
    "expected_range",
    "monitoring_rule",
    "temporal_validity",
    "unit",
)

# The 8 last-5-form fields (CANONICAL_FEATURES_58[:8]) have no named group in
# _NAMED_FEATURE_GROUPS above, so _feature_group() falls through to the
# generic default for them — listed explicitly here instead, mirroring how
# MARKET_FEATURES_14 is already written out rather than sliced implicitly.
_LAST5_FORM_FIELDS: Tuple[str, ...] = (
    "home_form_last5_home", "home_wins_last5_home",
    "home_draws_last5_home", "home_losses_last5_home",
    "away_form_last5_away", "away_wins_last5_away",
    "away_draws_last5_away", "away_losses_last5_away",
)

# The other half of the WP-18 remap block (the codebase's own
# _HOME_REMAP_FEATURES/_AWAY_REMAP_FEATURES in
# upcoming_match_feature_service.py group these with the 8 above, 7 per side).
# ⚠️ Attributed SEPARATELY on purpose: unlike the last-5 fields, these are not
# produced by a shared function. All three pipelines perform the same direct
# key remap from their own team-stats dict, in three replicated assignments.
# Same values today — verified empirically by
# tests/unit/test_feature_vector_parity.py, not assumed — but three copies of
# an assignment can drift in a way one shared function cannot, so the contract
# says which it is.
_GOALS_GD_FIELDS: Tuple[str, ...] = (
    "home_goals_for_avg", "home_goals_against_avg", "home_gd_recent",
    "away_goals_for_avg", "away_goals_against_avg", "away_gd_recent",
)

# The 15 Phase 8 fields a real historical replay can compute (Pi + Berrar +
# EWMA form) — see phase8_historical.py's RESOLVED_FEATURES, which this
# mirrors rather than imports: phase8_historical.py already imports THIS
# module (via a path-based spec_from_file_location, to dodge core.database's
# import-time DB connection — see its own module docstring), so importing
# back would be circular. The 6 unresolved fields (market drift, match
# importance) are deliberately absent — their four source fields stay
# UNDECLARED, matching docs/DEBT.md item 29's "structurally underivable"
# finding.
_PHASE8_RESOLVED_FIELDS: Tuple[str, ...] = (
    *PHASE8_FEATURES_PI, *PHASE8_FEATURES_BERRAR, *PHASE8_FEATURES_FORM,
)

_TRAINING_SOURCE_LAST5_FORM = (
    "scripts/train_on_real_matches.py:build_dataset() via "
    "models/feature_registry.py:derive_last5_form_features()"
)
_SERVING_SOURCE_LAST5_FORM = (
    "services/upcoming_match_feature_service.py:UpcomingMatchFeatureProjector "
    "and data/transformers.py:FeatureTransformer, both via "
    "models/feature_registry.py:derive_last5_form_features() — verified by "
    "import + call-site grep in both files, not by either file's own "
    "docstring claim about itself"
)
_TRAINING_SOURCE_GOALS_GD = (
    "scripts/train_on_real_matches.py:build_dataset() — direct key remap from "
    "TeamHistory.stats()'s {side}_goals_per_match_5 / "
    "{side}_goals_conceded_per_match_5 / {side}_gd_avg_5 (replicated "
    "assignment, not a shared function)"
)
_SERVING_SOURCE_GOALS_GD = (
    "services/upcoming_match_feature_service.py:project_match_features() and "
    "data/transformers.py:FeatureTransformer._project_to_canonical_features() "
    "— the same direct key remap from each pipeline's own team-stats dict, "
    "replicated in both (not a shared function). Train/serve equality is "
    "verified empirically by tests/unit/test_feature_vector_parity.py"
)
_SERVING_SOURCE_TEMPORAL = (
    "services/upcoming_match_feature_service.py:project_match_features() and "
    "data/transformers.py:FeatureTransformer._project_to_canonical_features(), "
    "both via models/feature_registry.py:derive_temporal_features()"
)
_SERVING_SOURCE_LEAGUE = (
    "services/upcoming_match_feature_service.py:project_match_features() and "
    "data/transformers.py:FeatureTransformer._project_to_canonical_features(), "
    "both via models/feature_registry.py:derive_league_features(); the latter "
    "additionally refuses a league with no measured priors "
    "(has_league_rate_priors) before delegating"
)
_SERVING_SOURCE_COMBINATION = (
    "services/upcoming_match_feature_service.py:project_match_features() and "
    "data/transformers.py:FeatureTransformer._project_to_canonical_features(), "
    "both via models/feature_registry.py:derive_combination_features()"
)
_TRAINING_SOURCE_TEMPORAL = (
    "scripts/train_on_real_matches.py:build_dataset() via "
    "models/feature_registry.py:derive_temporal_features()"
)
_TRAINING_SOURCE_LEAGUE = (
    "scripts/train_on_real_matches.py:build_dataset() via "
    "models/feature_registry.py:derive_league_features()"
)
_TRAINING_SOURCE_COMBINATION = (
    "scripts/train_on_real_matches.py:build_dataset() via "
    "models/feature_registry.py:derive_combination_features()"
)
_SERVING_SOURCE_MARKET_LEGACY = (
    "services/upcoming_match_feature_service.py:UpcomingMatchFeatureProjector "
    "and data/transformers.py:FeatureTransformer, both via "
    "models/feature_registry.py:derive_market_features()"
)
_TRAINING_SOURCE_MARKET_APEX = (
    "scripts/train_on_real_matches.py:build_dataset()'s X (the script's "
    "current default output) via "
    "models/feature_registry.py:derive_apex_market_features(); NOT verified "
    "against any currently-shipped/certified artifact — see docs/DEBT.md "
    "item 37"
)
_TRAINING_SOURCE_PHASE8_RESOLVED = (
    "src/features/phase8_historical.py:compute_phase8_training_columns() via "
    "the same PiRatingSystem/BerrarRatingSystem/weighted_form_features "
    "classes serving calls"
)
_SHADOW_SOURCE_PHASE8_RESOLVED = (
    "services/upcoming_match_feature_service.py:_inject_phase8_features() via "
    "PiRatingSystem/BerrarRatingSystem/weighted_form_features "
    "(src/features/{pi_ratings,berrar_ratings,form}.py) — the same classes "
    "training's historical replay uses"
)


def _is_apex_schema(schema_version: str) -> bool:
    """Which of the two market blocks a schema carries.

    ⚠️ Decided by schema, NOT by _feature_group(), because seven names —
    market_prob_home/draw/away, log_odds_home/draw/away, odds_ratio — appear
    in BOTH MARKET_FEATURES_14 and APEX_MARKET_FEATURES_14. _feature_group()
    resolves most-specific-first and hits MARKET_FEATURES_14 first, so a
    name-keyed lookup would attribute the legacy derive_market_features() to
    an apex slot it does not produce. The schema is what actually decides:
    APEX_FEATURES_58 splices APEX_MARKET_FEATURES_14 in where
    CANONICAL_FEATURES_58's legacy block sits.
    """
    return schema_version.startswith("apex_")


def _training_source(name: str, group: str, schema_version: str) -> str:
    """Mechanically-derived `training_source` — UNDECLARED where ambiguous.

    Only claims a source where exactly one training code path computes the
    field AND that path was confirmed by reading it (not assumed from a
    comment). See docs/DEBT.md item 36/37 for what's deliberately excluded
    and why: the legacy market block is NOT claimed for phase7_68/phase8_89,
    because build_dataset()'s current default always trains on
    APEX_MARKET_FEATURES_14, while the shipped phase7_68 artifacts' own
    `feature_columns` metadata records the legacy MARKET_FEATURES_14 block —
    a real, found-not-fabricated discrepancy between what the script does
    today and what actually trained the certified generation.
    """
    if name in _LAST5_FORM_FIELDS:
        return _TRAINING_SOURCE_LAST5_FORM
    if name in _GOALS_GD_FIELDS:
        return _TRAINING_SOURCE_GOALS_GD
    if group == "TEMPORAL_FEATURES":
        return _TRAINING_SOURCE_TEMPORAL
    if group in ("LEAGUE_ONEHOT_FEATURES", "LEAGUE_RATE_FEATURES"):
        return _TRAINING_SOURCE_LEAGUE
    if group == "COMBINATION_FEATURES":
        return _TRAINING_SOURCE_COMBINATION
    if group in ("MARKET_FEATURES_14", "APEX_MARKET_FEATURES_14"):
        return (
            _TRAINING_SOURCE_MARKET_APEX if _is_apex_schema(schema_version)
            else UNDECLARED
        )
    if name in _PHASE8_RESOLVED_FIELDS:
        return _TRAINING_SOURCE_PHASE8_RESOLVED
    return UNDECLARED


def _serving_source(name: str, group: str, schema_version: str) -> str:
    """Mechanically-derived `serving_source` — UNDECLARED where ambiguous.

    Serving has two independent implementations (UpcomingMatchFeatureProjector
    and FeatureTransformer). A value is only returned where BOTH were
    confirmed (by import + call-site grep) to invoke the identical function —
    true for last-5-form, the legacy 14-field market block, and — since the
    §7.2 unification — the temporal, league and combination groups, which
    FeatureTransformer previously recomputed with its own inline copies.
    That unification is proven behaviour-preserving by
    tests/unit/test_feature_vector_parity.py, which runs the real
    FeatureTransformer and compares it against these same helpers.

    An apex schema's market block gets UNDECLARED: derive_apex_market_features
    has zero callers anywhere in backend/src (only scripts/), so nothing
    serves it. Claiming the legacy function there — which a name-keyed lookup
    would do, see _is_apex_schema — would be exactly the misattribution this
    contract exists to prevent.
    """
    if name in _LAST5_FORM_FIELDS:
        return _SERVING_SOURCE_LAST5_FORM
    if name in _GOALS_GD_FIELDS:
        return _SERVING_SOURCE_GOALS_GD
    if group == "TEMPORAL_FEATURES":
        return _SERVING_SOURCE_TEMPORAL
    if group in ("LEAGUE_ONEHOT_FEATURES", "LEAGUE_RATE_FEATURES"):
        return _SERVING_SOURCE_LEAGUE
    if group == "COMBINATION_FEATURES":
        return _SERVING_SOURCE_COMBINATION
    if group in ("MARKET_FEATURES_14", "APEX_MARKET_FEATURES_14"):
        return (
            UNDECLARED if _is_apex_schema(schema_version)
            else _SERVING_SOURCE_MARKET_LEGACY
        )
    return UNDECLARED


def _shadow_source(name: str) -> str:
    """Mechanically-derived `shadow_source` — the 15 resolved Phase 8 fields
    only. The 6 unresolved ones (market drift, match importance) are never
    computed by anything; claiming a source for them would misrepresent a
    registry default as an observation.
    """
    if name in _PHASE8_RESOLVED_FIELDS:
        return _SHADOW_SOURCE_PHASE8_RESOLVED
    return UNDECLARED


def _feature_group(name: str) -> str:
    for group_name, members in _NAMED_FEATURE_GROUPS:
        if name in members:
            return group_name
    return "CANONICAL_FEATURES_58"


def _league_scope(name: str) -> str:
    if name in LEAGUE_ONEHOT_FEATURES:
        return name[len("league_"):]
    return "ALL"


def _disposition(name: str, default_value: Optional[float]) -> str:
    if name in PHASE7_FEATURES_ALWAYS_DATA_GAP:
        return _DISPOSITION_DEFER_UNTIL_DATA_EXISTS
    if default_value is not None:
        return _DISPOSITION_ALIGNED_OBSERVED
    return UNDECLARED


def build_feature_contract(schema_version: object) -> Dict[str, Any]:
    """Build the mechanically-derived contract for one declared schema version.

    Raises UnknownFeatureSchemaError for an unrecognised version — the same
    fail-closed behaviour as resolve_feature_schema, no permissive default.
    Every field is either derived from a real constant/function already in
    this module or the literal string UNDECLARED; nothing is invented.
    """
    features = resolve_feature_schema(schema_version)
    defaults = _DEFAULT_VALUE_SOURCES.get(str(schema_version), {})

    records: List[Dict[str, Any]] = []
    for index, name in enumerate(features):
        default_value = defaults.get(name)
        group = _feature_group(name)
        record: Dict[str, Any] = {
            "index": index,
            "feature_name": name,
            "dtype": "float64",
            "default_value": default_value,
            "fallback_policy": (
                "static default (DEFAULT_FEATURE_VALUES_*)"
                if default_value is not None
                else UNDECLARED
            ),
            # Every feature is a fixed vector slot indexed positionally into a
            # trained artifact; there is no "optional" slot in this codebase
            # (PredictionEngine refuses to zero-pad a short vector — see the
            # PHASE7_FEATURES_10 comment above). Mechanically true, not a guess.
            "required_or_optional": "REQUIRED",
            "league_scope": _league_scope(name),
            "feature_group": group,
            "always_data_gap": name in PHASE7_FEATURES_ALWAYS_DATA_GAP,
            "disposition": _disposition(name, default_value),
            # Per-pipeline attribution: a real, grep-verified code path or the
            # literal UNDECLARED. Never a plausible-sounding guess — see each
            # resolver's docstring for exactly what it will and will not claim.
            "training_source": _training_source(name, group, str(schema_version)),
            "serving_source": _serving_source(name, group, str(schema_version)),
            "shadow_source": _shadow_source(name),
            "version": str(schema_version),
        }
        for field in _UNDECLARED_FIELDS:
            record[field] = UNDECLARED
        records.append(record)

    return {
        "schema": "sabiscore_feature_contract_v1",
        "feature_schema_version": str(schema_version),
        "feature_count": len(records),
        "features": records,
        "feature_contract_sha256": contract_sha256(records),
    }


def contract_sha256(records: Sequence[Mapping[str, Any]]) -> str:
    """SHA-256 over the full per-feature record array, not just names.

    Unlike promotion_evidence._contract_hash (which hashes only the ordered
    name list), this hashes every derived field — a real step toward the
    directive's feature_contract_sha256, though not yet the full §7.3
    vector-hash parity mechanism (see docs/DEBT.md for that remaining gap).
    """
    payload = json.dumps(
        list(records), separators=(",", ":"), sort_keys=True, ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
