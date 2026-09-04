"""Canonical feature registry for inference-safe SabiScore models."""

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

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
#
# StatsBomb coverage audit (2026-09-04) — PATH B:
#   scripts/audit_statsbomb_coverage.py measured 23.58% crosswalk intersection between
#   the StatsBomb Open Data match corpus and the 3,440 unique Understat matchups
#   (below the 85% threshold). Full per-league breakdown in
#   reports/evaluation/statsbomb-coverage-audit-2026.json.
#   home_pressing_intensity (ATE=0.146) and progressive_carry_diff — formally relegated
#   to ALWAYS_DATA_GAP. The slots are retained in CANONICAL_FEATURES_68 for artifact
#   compatibility; the values are permanently the registry defaults (0.55 and 0.0).
#   ENABLE_STATSBOMB_ENRICHMENT must remain False; re-evaluate if StatsBomb publishes
#   event data covering ≥85% of the Understat corpus date range.
PHASE7_FEATURES_ALWAYS_DATA_GAP: List[str] = [
    "shot_quality_diff",
    # Formally relegated 2026-09-04 per StatsBomb coverage audit (23.58% < 85%):
    "home_pressing_intensity",
    "progressive_carry_diff",
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

# Gate 7 candidate schema — apex_v4 (2026-09-04).
# StatsBomb coverage audit (PATH B) formally relegated home_pressing_intensity and
# progressive_carry_diff to ALWAYS_DATA_GAP, eliminating them as constant-value
# noise in training. APEX_FEATURES_66 is APEX_FEATURES_68 with those two slots
# dropped entirely, so the model receives 66 real inputs rather than 68 (66 + 2
# constants that carry no information variance).
#
# H2H, venue, and market-interaction families populated in PR #149 are retained in
# full — they constitute 13 of the 58 base features and are DATA_FED in production.
#
# Width: 66 = 68 − 2 event-data gap features.
APEX_FEATURES_66: List[str] = [
    f for f in APEX_FEATURES_68
    if f not in ("home_pressing_intensity", "progressive_carry_diff")
]

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

# ── xG rolling family (candidate — NOT in any *served* schema) ───────────────
# The three features `scripts/measure_xg_feature_ate.py` measured as CAUSAL_DRIVER
# on the real Understat corpus (ATE 0.2464 / 0.2169 / 0.1790, all p=0.0000).
#
# `finishing_efficiency_gap` was measured in the same run and is deliberately
# NOT here: ATE 0.0082, below the 0.02 practical threshold, p=0.3851. Goals
# minus xG is dominated by finishing variance, and admitting it would put an
# unvalidated slot in a candidate whose whole purpose is to carry validated
# ones.
#
# ⚠️ Still absent from every CANONICAL_FEATURES_* and from APEX_FEATURES_68/89.
# Adding a name to an ALREADY-SERVED list changes that list's vector width,
# which is the 2026-06-10 incident this file records at line 95: 65 columns
# emitted against 68-column artifacts, `model_version="fallback"` served on
# every inference for two months. These names reach a model only through
# APEX_FEATURES_71 below — a NEW schema key with its own artifacts, manifest and
# contract hash, which no existing artifact declares and therefore no existing
# artifact can be re-shaped by.
#
# They live here, defined once, because training and serving must compute them
# identically or the `serving_feature_availability` gate is measuring two
# different things. `tests/unit/test_xg_rolling_parity.py` asserts the pandas
# training path and the scalar serving path agree to float tolerance.
PHASE9_FEATURES_XG: List[str] = [
    "xg_differential",
    "xg_attack_diff",
    "xg_defense_diff",
]

# The xG candidate contract: Apex 68 with the three validated xG features
# APPENDED, never interleaved. Append order is load-bearing beyond taste —
# `compare_candidate_vs_incumbent._coherent_price_perturbation` indexes the
# market block through `APEX_FEATURES_68.index(...)` against a candidate row,
# which stays correct only while positions 0..67 are byte-identical to
# APEX_FEATURES_68.
APEX_FEATURES_71: List[str] = [*APEX_FEATURES_68, *PHASE9_FEATURES_XG]

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
    # ⚠️ EVALUATED AND REJECTED (2026-09-03) — see
    # reports/evaluation/apex-v2-71-candidate-evaluation.{json,md}. A candidate
    # trained on this contract fails four promotion gates, most decisively
    # market_baseline (0/5 leagues). On the IDENTICAL holdout the xG block is
    # neutral-to-worse in 4 of 5 leagues (mean RPS -0.00159) despite all three
    # features carrying training_coverage 1.0 and ATE > 0.18 at p < 1e-68.
    #
    # The key stays registered anyway: it is the measurement contract that lets
    # `resolve_feature_schema` answer for a 71-wide artifact at all, so a future
    # xG candidate can be scored without re-deriving the replay, the crosswalk
    # and the gate wiring. It is NOT an endorsement, and
    # `active_generation.json` must not name it — no artifact in models/
    # declares it, and none should until a candidate on this contract clears
    # every gate on its own evidence.
    "apex_v2_71": APEX_FEATURES_71,
    # Same 68-column contract as apex_v1_68 — h2h/venue/market-interaction (13
    # of APEX_FEATURES_68's slots) go from training-constant to
    # training-computed under this key. docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md
    # §2/§5 Phase 2; docs/DEBT.md item 56. The key exists purely so this
    # training run writes its own models/candidate/*_v8_dense68* artifacts
    # rather than overwriting the checked-in apex_v1_68 baseline Phase 3
    # compares against — the CONTRACT is unchanged (same object, not a copy,
    # matching CANONICAL_FEATURES_65's precedent above), only which of its
    # slots training actually varies.
    #
    # ⚠️ Does NOT touch serving_feature_availability's OTHER failure mode: the
    # checked-in models/candidate/feature_availability_matrix.json records
    # serving_schema_misaligned_slots: 11 for apex_v1_68 today, entirely
    # independent of h2h/venue and unaffected by anything registered here —
    # it is the Apex market block (positions 20-30) mismatching the currently
    # active generation's legacy serving contract, fixed only by activating
    # an apex generation. A clean apex_v3_68 result on this axis alone is not
    # this gate clearing; it structurally cannot, from this key alone.
    "apex_v3_68": APEX_FEATURES_68,
    # Gate 7 candidate — StatsBomb coverage audit PATH B (2026-09-04).
    # 66-wide: APEX_FEATURES_68 minus home_pressing_intensity and
    # progressive_carry_diff (both relegated to ALWAYS_DATA_GAP after 23.58%
    # crosswalk coverage against the Understat corpus).  H2H, venue, and
    # market-interaction slots (PR #149, DATA_FED) are fully retained.
    # Only valid for apex_v4_* artifacts; must not be assigned to any existing
    # 68-wide artifact.
    "apex_v4_66": APEX_FEATURES_66,
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


def active_canonical_features(
    use_phase7: bool, use_phase8: bool = False, *, apex: bool = False
) -> List[str]:
    """The serving column order for the active generation.

    ``apex`` is a separate axis from ``use_phase7``/``use_phase8`` (which
    pick the feature *width*, not the market block) — see docs/DEBT.md item
    37. Defaults to False so every pre-existing caller is unaffected.
    """
    if apex:
        if use_phase8:
            return list(APEX_FEATURES_89)
        return list(APEX_FEATURES_68 if use_phase7 else APEX_FEATURES_58)
    if use_phase8:
        return list(CANONICAL_FEATURES_89)
    return list(CANONICAL_FEATURES_68 if use_phase7 else CANONICAL_FEATURES_58)


def active_default_feature_values(
    use_phase7: bool, use_phase8: bool = False, *, apex: bool = False
) -> Dict[str, float]:
    """Neutral fallback values for the active generation's serving schema.

    ``apex=True`` swaps the legacy-only market defaults for the Apex block's
    own, computed from the same neutral 1X2 snapshot
    ``data/transformers.py`` already uses when no live odds are available
    (2.5 / 3.3 / 2.8) — one convention for "no market evidence", expressed in
    whichever market block is actually being served. Computed lazily (not a
    module constant) because MARKET_FEATURES_14/derive_apex_market_features
    are defined later in this file; the diff is 14 names, negligible cost.
    """
    base = (
        dict(DEFAULT_FEATURE_VALUES_89) if use_phase8
        else dict(DEFAULT_FEATURE_VALUES_68 if use_phase7 else DEFAULT_FEATURE_VALUES_58)
    )
    if apex:
        legacy_only = frozenset(MARKET_FEATURES_14) - frozenset(APEX_MARKET_FEATURES_14)
        base = {k: v for k, v in base.items() if k not in legacy_only}
        base.update(derive_apex_market_features(2.5, 3.3, 2.8))
    return base


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


# ── xG rolling family ────────────────────────────────────────────────────────
# The rolling contract, named once so both sides cannot drift apart:
# mean of the last XG_ROLLING_WINDOW matches strictly BEFORE kickoff, and only
# when at least XG_ROLLING_MIN_PERIODS of them exist. Matches the
# `shift(1).rolling(5, min_periods=3)` the ATE measurement used.
XG_ROLLING_WINDOW = 5
XG_ROLLING_MIN_PERIODS = 3


def rolling_xg_mean(values: Sequence[Optional[float]]) -> Optional[float]:
    """Mean of the most-recent ``XG_ROLLING_WINDOW`` observations, or None.

    ``values`` must be ordered most-recent-first and contain only matches that
    kicked off strictly before the target fixture — this function cannot check
    either property, so its callers own the leak boundary.

    Returns None rather than a registry default below the minimum-periods floor.
    A cold-start team has no xG history; answering 0.0 would present unknown as
    zero, which APEX section 26 forbids and which
    `promotion_evidence._column_is_default_only()` would then read as a
    defaulted training slot.
    """
    observed = [float(v) for v in values[:XG_ROLLING_WINDOW] if v is not None]
    if len(observed) < XG_ROLLING_MIN_PERIODS:
        return None
    return sum(observed) / len(observed)


def derive_xg_rolling_features(
    *,
    home_xg_for: Optional[float],
    home_xg_against: Optional[float],
    away_xg_for: Optional[float],
    away_xg_against: Optional[float],
) -> Optional[Dict[str, float]]:
    """The three xG candidate features from four pre-match rolling means.

    Every argument is a `rolling_xg_mean()` output for one side. Returns None if
    any is None: the three features are all cross-team differences, so a single
    cold-start side makes every one of them unanswerable. Partial credit here
    would silently substitute one team's real form for the other's absence.
    """
    if (
        home_xg_for is None
        or home_xg_against is None
        or away_xg_for is None
        or away_xg_against is None
    ):
        return None
    return {
        "xg_differential": (home_xg_for - home_xg_against) - (away_xg_for - away_xg_against),
        "xg_attack_diff": home_xg_for - away_xg_for,
        "xg_defense_diff": away_xg_against - home_xg_against,
    }


# (canonical suffix, team-stats source suffix) for the goals/gd block. Both are
# side-prefixed by the caller, so one table serves home and away.
_GOALS_GD_KEY_MAP: Tuple[Tuple[str, str], ...] = (
    ("goals_for_avg", "goals_per_match_5"),
    ("goals_against_avg", "goals_conceded_per_match_5"),
    ("gd_recent", "gd_avg_5"),
)


def derive_goals_gd_features(
    get: Callable[[str, float], Any],
    *,
    is_home: bool,
) -> Dict[str, float]:
    """docs/DEBT.md item 36(a): the one goals/gd remap, replacing four copies.

    ``get`` is the caller's own ``(key, default) -> value`` lookup, which is
    what lets a single implementation serve three deliberately different
    missing-value policies — the divergence item 36(b) declares as by design:

    * ``FeatureTransformer``'s ``get_num`` raises ``DataUnavailableError``
      under fail-closed rather than substituting a default;
    * the projector passes ``dict.get``, so an absent key takes the default;
    * training passes a strict lookup, so an absent key raises ``KeyError``
      and the row is dropped instead of being silently imputed.

    The *names* were the duplication here, not the arithmetic, so the helper
    owns the key mapping and the registry defaults while leaving the lookup
    policy with the caller. Defaults come from ``DEFAULT_FEATURE_VALUES_68``
    rather than being hand-copied per call site — the projector's copies had
    already drifted (1.5/1.2/0.0, with the home literals reused verbatim for
    the away side), which is exactly the failure mode a shared function
    prevents.
    """
    side = "home" if is_home else "away"
    return {
        f"{side}_{canonical}": float(
            get(f"{side}_{source}", DEFAULT_FEATURE_VALUES_68[f"{side}_{canonical}"])
        )
        for canonical, source in _GOALS_GD_KEY_MAP
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


# ── h2h / home-venue / market-interaction family (docs/DEBT.md item 56,
#    PRODUCTION_EXECUTIVE_DIRECTIVE.md §2/§5 Phase 2) ────────────────────────
# These 13 names are already CANONICAL_FEATURES_58 slots (lines 42-50, 58-63)
# and have been computed at serving time since before this file existed —
# UpcomingMatchFeatureProjector._get_h2h_stats() / _get_home_venue_stats() /
# its post-market interaction block. `train_on_real_matches.build_dataset()`
# has always left them at their registry default, so no tree in any trained
# ensemble has ever split on them: a column that is constant across every
# training row carries zero information gain, the same argument DEBT 56
# Finding 1 makes about the four ALWAYS_DATA_GAP slots. Populating them in
# training is this file's answer to that half of the train/serve parity bar;
# the walk-forward accumulation itself lives in train_on_real_matches.py's
# TeamHistory, mirroring the xG family's split between "formula lives here,
# state lives with the caller" (see PHASE9_FEATURES_XG above).
#
# `data/transformers.py:407-474` is NOT the parity reference for this family
# — read directly, it's a second pipeline that re-derives these fields from
# already-engineered keys through a materially different formula (a clamp on
# h2h_matches, home_venue_loss_rate assigned from the AWAY team's away win
# rate). The functions below are transcribed from the real, live serving
# path — _get_h2h_stats/_get_home_venue_stats/the interaction block in
# upcoming_match_feature_service.py — verified by reading that code directly,
# the same discipline _serving_source()'s docstring already commits to.
#
# `total_goals_expected` is deliberately NOT here. It has zero call sites in
# the serving projector; its only formula anywhere (data/transformers.py:402,
# the wrong pipeline above) is `xg_differential + 2.60`, and xg_differential
# is not a training column under this schema. Computing it in training would
# give training a value serving can never reproduce — a train/serve break in
# the opposite direction from what this section exists to fix. It stays
# defaulted; PRODUCTION_EXECUTIVE_DIRECTIVE.md §5 Phase 2's "16 → 2" is
# corrected here to 16 → 3 (the 2 event-data slots plus this one).
H2H_WINDOW = 10
HOME_VENUE_WINDOW = 20

H2H_FEATURES: Tuple[str, ...] = (
    "h2h_home_wins", "h2h_away_wins", "h2h_draws", "h2h_matches", "h2h_dominance",
)
HOME_VENUE_FEATURES: Tuple[str, ...] = (
    "home_venue_win_rate", "home_venue_draw_rate", "home_venue_loss_rate",
    "home_advantage_strength",
)
MARKET_INTERACTION_FEATURES: Tuple[str, ...] = (
    "form_market_agreement_home", "form_market_disagreement",
    "venue_market_combo", "h2h_market_agreement",
)


def derive_h2h_features(
    meetings: Sequence[Tuple[int, int]]
) -> Optional[Dict[str, float]]:
    """Last-H2H_WINDOW head-to-head meetings, scored from one side's perspective.

    ``meetings`` is (goals_for, goals_against) for the perspective side,
    most-recent-first, already filtered to strictly before kickoff and capped
    at H2H_WINDOW — the caller owns the leak boundary and the perspective
    flip, exactly as _get_h2h_stats() does before its own identical loop.
    None on an empty history: a pair that has never met is a genuine data
    gap, never a fabricated 0.0.
    """
    if not meetings:
        return None
    home_wins = away_wins = draws = 0
    for gf, ga in meetings:
        if gf > ga:
            home_wins += 1
        elif gf < ga:
            away_wins += 1
        else:
            draws += 1
    total = len(meetings)
    return {
        "h2h_home_wins": float(home_wins),
        "h2h_away_wins": float(away_wins),
        "h2h_draws": float(draws),
        "h2h_matches": float(total),
        "h2h_dominance": (home_wins - away_wins) / total,
    }


def derive_home_venue_features(
    results: Sequence[Tuple[int, int]]
) -> Optional[Dict[str, float]]:
    """Home-venue record from the last HOME_VENUE_WINDOW matches a team hosted.

    ``results`` is (home_goals, away_goals) for matches this team hosted,
    most-recent-first, already filtered to strictly before kickoff and capped
    at HOME_VENUE_WINDOW — mirrors _get_home_venue_stats()'s query exactly,
    losses by subtraction as that function does. None on an empty history —
    no prior hosted matches in scope is a data gap, not a neutral 0.50.
    """
    if not results:
        return None
    total = len(results)
    wins = sum(1 for hg, ag in results if hg > ag)
    draws = sum(1 for hg, ag in results if hg == ag)
    losses = total - wins - draws
    return {
        "home_venue_win_rate": wins / total,
        "home_venue_draw_rate": draws / total,
        "home_venue_loss_rate": losses / total,
        "home_advantage_strength": (wins - losses) / total,
    }


def derive_market_interaction_features(
    *,
    market_prob_home: float,
    home_form_last5_home: Optional[float] = None,
    home_venue_win_rate: Optional[float] = None,
    h2h_dominance: Optional[float] = None,
) -> Dict[str, float]:
    """Cross-signal features — transcribed from the post-market interaction
    block in upcoming_match_feature_service.py (~372-388), read directly.

    Each key is independently gated on its own input, mirroring serving
    exactly: h2h_market_agreement needs h2h_dominance, venue_market_combo
    needs home_venue_win_rate, and the two form-interaction keys need
    home_form_last5_home. A caller with only some of the three resolved gets
    only the corresponding subset back — never a value mixing a real signal
    with a registry default.

    ``home_form_last5_home`` is the ALREADY-multiplied value
    (derive_last5_form_features()'s output, home_form_5 * 3.0), not the raw
    rate — matching exactly what serving reads back out of its own
    features_dict rather than recomputing from the source stat.
    """
    out: Dict[str, float] = {}
    if h2h_dominance is not None:
        out["h2h_market_agreement"] = h2h_dominance * market_prob_home
    if home_venue_win_rate is not None:
        out["venue_market_combo"] = home_venue_win_rate * market_prob_home
    if home_form_last5_home is not None:
        form_norm = home_form_last5_home / 3.0
        out["form_market_agreement_home"] = form_norm * market_prob_home
        out["form_market_disagreement"] = abs(form_norm - market_prob_home)
    return out


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
    # Same 68-wide source as apex_v1_68 (the Apex market block has no separate
    # default table; see active_default_feature_values). The three
    # PHASE9_FEATURES_XG names are deliberately ABSENT from it, so
    # build_feature_contract records default_value=None and
    # fallback_policy=UNDECLARED for them.
    #
    # That is the intended disposition, not an oversight this map should paper
    # over. `rolling_xg_mean` returns None below its minimum-periods floor
    # precisely so a cold-start team is not presented as 0.0, and
    # `project_xg_rolling_features` propagates that None as a DATA_GAP. Giving
    # these slots a static default would let a fixture with no observed xG be
    # served a confident neutral value — "present unknown as zero", which APEX
    # section 26 forbids. The schema KEY is wired here so the contract's
    # UNDECLARED is a real statement about the features rather than an artefact
    # of missing wiring, which is exactly the distinction
    # test_default_value_sources_cover_every_registered_schema exists to keep.
    "apex_v2_71": DEFAULT_FEATURE_VALUES_68,
    # Same 68-wide source as apex_v1_68 — required by
    # test_default_value_sources_cover_every_registered_schema. Populating
    # h2h/venue/interaction slots from real training data (see the section
    # below) does not change what a COLD-START row (no prior meetings, no
    # prior home matches) falls back to; the registry default is still the
    # honest answer for those rows, on both the training and serving side.
    "apex_v3_68": DEFAULT_FEATURE_VALUES_68,
    # apex_v4_66 drops home_pressing_intensity and progressive_carry_diff from
    # the input vector. Its defaults are the same 68-wide dict filtered down to
    # 66 entries at use-time by _schema_features(); wiring the same source keeps
    # cold-start behaviour consistent and satisfies
    # test_default_value_sources_cover_every_registered_schema.
    "apex_v4_66": DEFAULT_FEATURE_VALUES_68,
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
# docs/DEBT.md item 36(a): these WERE three replicated assignments (four,
# counting the parity harness's own copy) and are now one shared function,
# derive_goals_gd_features(). The per-pipeline missing-value policies stayed
# deliberately different — item 36(b) declares that divergence by design — so
# the helper takes the caller's own (key, default) lookup rather than owning it.
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

# docs/DEBT.md item 48 follow-up: the 4 canonical Elo slots a real historical
# replay can honestly compute (mirrors src/features/elo_replay.py's
# ELO_TRAINING_COLUMNS rather than importing it — importing back would be
# circular, same reason _PHASE8_RESOLVED_FIELDS mirrors phase8_historical.py
# above). `elo_league_adjusted` is deliberately excluded: it is permanently in
# PHASE7_FEATURES_ALWAYS_DATA_GAP by ATE-review policy (collinear proxy, no
# independent causal signal — see the PHASE7_FEATURES_REMOVED comment above),
# so it stays UNDECLARED regardless of what training can compute.
_ELO_TRAINING_RESOLVED_FIELDS: Tuple[str, ...] = (
    "elo_difference", "elo_home_trend_5", "elo_away_trend_5", "elo_momentum_cross",
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
    "scripts/train_on_real_matches.py:build_dataset() via "
    "models/feature_registry.py:derive_goals_gd_features(), remapping "
    "TeamHistory.stats()'s {side}_goals_per_match_5 / "
    "{side}_goals_conceded_per_match_5 / {side}_gd_avg_5 — passes a strict "
    "lookup, so an absent key drops the row rather than imputing a default"
)
_SERVING_SOURCE_GOALS_GD = (
    "services/upcoming_match_feature_service.py:project_match_features() and "
    "data/transformers.py:FeatureTransformer._project_to_canonical_features(), "
    "both via models/feature_registry.py:derive_goals_gd_features() — verified "
    "by import + call-site grep in both files. The projector passes dict.get "
    "(absent key takes the registry default); FeatureTransformer passes its "
    "fail-closed get_num (absent key raises DataUnavailableError). Train/serve "
    "equality is verified by tests/unit/test_feature_vector_parity.py"
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
_SERVING_SOURCE_MARKET_APEX = (
    "services/upcoming_match_feature_service.py:UpcomingMatchFeatureProjector "
    "and data/transformers.py:FeatureTransformer, both via "
    "models/feature_registry.py:derive_apex_market_features(), dispatched on "
    "the active generation's declared feature_schema_version; reachable only "
    "while an apex_* generation is active — no such generation has yet been "
    "trained, certified, or activated (see docs/DEBT.md item 37)"
)
_TRAINING_SOURCE_PHASE8_RESOLVED = (
    "src/features/phase8_historical.py:compute_phase8_training_columns() via "
    "the same PiRatingSystem/BerrarRatingSystem/weighted_form_features "
    "classes serving calls"
)
_TRAINING_SOURCE_ELO_REPLAY = (
    "src/features/elo_replay.py:compute_elo_training_columns(), wired into "
    "scripts/train_on_real_matches.py:build_dataset() — docs/DEBT.md item 48 "
    "follow-up. Rating math mirrors data/elo_engine.py:EloEngine (cross-verified "
    "by cross_verify_against_elo_engine before being trusted at scale) but is "
    "NOT the production serving authority: serving reads durable, "
    "incrementally-updated PostgreSQL state via services/elo_state_service.py, "
    "while training replays the full historical corpus in one chronological "
    "pass. serving_source stays UNDECLARED here deliberately — FeatureTransformer "
    "receives an already-computed elo_difference from its caller rather than "
    "calling elo_state_service directly itself, so the 'both implementations "
    "confirmed to invoke the identical function' bar this contract requires is "
    "not yet verified for the serving side."
)
_SHADOW_SOURCE_PHASE8_RESOLVED = (
    "services/upcoming_match_feature_service.py:_inject_phase8_features() via "
    "PiRatingSystem/BerrarRatingSystem/weighted_form_features "
    "(src/features/{pi_ratings,berrar_ratings,form}.py) — the same classes "
    "training's historical replay uses"
)


def is_apex_schema(schema_version: str) -> bool:
    """Which of the two market blocks a schema carries.

    ⚠️ Decided by schema, NOT by _feature_group(), because seven names —
    market_prob_home/draw/away, log_odds_home/draw/away, odds_ratio — appear
    in BOTH MARKET_FEATURES_14 and APEX_MARKET_FEATURES_14. _feature_group()
    resolves most-specific-first and hits MARKET_FEATURES_14 first, so a
    name-keyed lookup would attribute the legacy derive_market_features() to
    an apex slot it does not produce. The schema is what actually decides:
    APEX_FEATURES_58 splices APEX_MARKET_FEATURES_14 in where
    CANONICAL_FEATURES_58's legacy block sits.

    Public (no leading underscore): docs/DEBT.md item 37's serving wire-up
    (data/transformers.py, services/upcoming_match_feature_service.py) needs
    this same decision outside this module — one predicate, not a second
    copy of the schema-string convention.
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
            _TRAINING_SOURCE_MARKET_APEX if is_apex_schema(schema_version)
            else UNDECLARED
        )
    if name in _PHASE8_RESOLVED_FIELDS:
        return _TRAINING_SOURCE_PHASE8_RESOLVED
    if name in _ELO_TRAINING_RESOLVED_FIELDS:
        return _TRAINING_SOURCE_ELO_REPLAY
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

    An apex schema's market block is attributed to
    derive_apex_market_features() as of docs/DEBT.md item 37's serving
    wire-up: both serving implementations now dispatch on the active
    generation's feature_schema_version, so under an apex_* generation that
    IS what serves. It was previously UNDECLARED because the function had
    zero callers in backend/src (scripts/ only). Claiming the *legacy*
    function here — which a name-keyed lookup would do, see is_apex_schema —
    would still be exactly the misattribution this contract prevents.
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
            _SERVING_SOURCE_MARKET_APEX if is_apex_schema(schema_version)
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
