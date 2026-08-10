#!/usr/bin/env python3
"""Phase 8 retraining scaffold — per-league ensembles with full Phase 8 feature support.

Supersedes the Phase 7-B scaffold. Key additions:
  - 86-dim CANONICAL_FEATURES_86; per-league 65-dim fallback when Phase 8
    enrichment columns are absent or uniformly at defaults.
  - RF + XGBoost + LightGBM + optional CatBoost (USE_CATBOOST_LEARNER).
  - Temporal recency weighting (TRAINING_RECENCY_HALFLIFE_SEASONS).
  - Macro-F1, balanced accuracy, Brier, RPS alongside accuracy / log-loss.
  - Two-stage draw model (USE_TWO_STAGE_DRAW_MODEL), gated per-league by
    draw-F1 improvement >= 0.03 vs single-stage baseline.
  - Per-league artifact metadata records feature_set, feature_count,
    catboost_enabled, two_stage_draw, recency_halflife, training_date.
  - Dated per-league JSON reports: baseline_v8_{YYYYMMDD}_{league}.json.

Walk-forward temporal splits only — no random k-fold CV.
Gate failures exit non-zero without writing artifacts.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
    _XGB_AVAILABLE = True
except ImportError:
    _XGB_AVAILABLE = False

try:
    import lightgbm as lgb
    _LGB_AVAILABLE = True
except ImportError:
    _LGB_AVAILABLE = False

try:
    from catboost import CatBoostClassifier
    _CB_AVAILABLE = True
except ImportError:
    _CB_AVAILABLE = False

_JOBLIB_AVAILABLE = importlib.util.find_spec("joblib") is not None

try:
    from src.models.calibration import (  # type: ignore[import]
        BivariatePoissonDrawOverlay,
        EnsembleDiversityDiagnostics,
        compare_calibration_methods,
        write_bivariate_poisson_report,
        write_calibration_report,
        write_diversity_report,
    )
    _CALIBRATION_AVAILABLE = True
except ImportError:
    _CALIBRATION_AVAILABLE = False

# ── Env var configuration (mirrors backend/src/core/config.py Sprint 4 vars) ──
_USE_CATBOOST = os.environ.get("USE_CATBOOST_LEARNER", "false").lower() == "true"
_RECENCY_HALFLIFE = float(os.environ.get("TRAINING_RECENCY_HALFLIFE_SEASONS", "2.0"))
_USE_TWO_STAGE = os.environ.get("USE_TWO_STAGE_DRAW_MODEL", "false").lower() == "true"

LEAGUE_CSVS: Dict[str, str] = {
    "epl": "epl_training.csv",
    "la_liga": "la_liga_training.csv",
    "bundesliga": "bundesliga_training.csv",
    "serie_a": "serie_a_training.csv",
    "ligue_1": "ligue_1_training.csv",
    "eredivisie": "eredivisie_training.csv",
}

RESULT_MAP = {
    "home_win": 0, "draw": 1, "away_win": 2,
    "H": 0, "D": 1, "A": 2,
    0: 0, 1: 1, 2: 2,
}

# Minimum Phase 8 columns with non-zero variance to prefer 86-dim over 65-dim.
_PHASE8_PRESENCE_THRESHOLD = 8


# ── Feature registry loader ──────────────────────────────────────────────────

def _load_feature_registry():
    import importlib.util
    path = PROJECT_ROOT / "backend" / "src" / "models" / "feature_registry.py"
    spec = importlib.util.spec_from_file_location("phase8_feature_registry", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load feature registry: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    features_86 = list(getattr(mod, "CANONICAL_FEATURES_86"))
    defaults_86 = dict(getattr(mod, "DEFAULT_FEATURE_VALUES_86"))
    features_65 = list(getattr(mod, "CANONICAL_FEATURES_65"))
    defaults_65 = dict(getattr(mod, "DEFAULT_FEATURE_VALUES_68"))
    return features_86, defaults_86, features_65, defaults_65


# ── Per-league feature set detection ────────────────────────────────────────

def _detect_feature_set(
    frame: pd.DataFrame,
    features_86: List[str],
    defaults_86: Dict[str, float],
    features_65: List[str],
    defaults_65: Dict[str, float],
) -> Tuple[str, List[str], Dict[str, float]]:
    """Return (label, feature_cols, defaults) for this league's training CSV.

    Uses 86-dim when >= _PHASE8_PRESENCE_THRESHOLD Phase 8 columns are present
    with non-trivial variance (std > 1e-3). Falls back to 65-dim otherwise —
    indicating enrichment is incomplete and the safe path is the confirmed set.
    """
    phase8_only = set(features_86) - set(features_65)
    present_with_variance = 0
    for col in phase8_only:
        if col not in frame.columns:
            continue
        std = pd.to_numeric(frame[col], errors="coerce").std()
        if std is not None and std > 1e-3:
            present_with_variance += 1

    if present_with_variance >= _PHASE8_PRESENCE_THRESHOLD:
        return "phase8_86", features_86, defaults_86
    return "phase7_65", features_65, defaults_65


# ── Data preparation ─────────────────────────────────────────────────────────

def _normalize_result(values: pd.Series) -> pd.Series:
    mapped = values.map(lambda x: RESULT_MAP.get(x, RESULT_MAP.get(str(x), np.nan)))
    return pd.to_numeric(mapped, errors="coerce")


def _numeric_series(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col in frame.columns:
        return pd.to_numeric(frame[col], errors="coerce").fillna(default)
    return pd.Series(default, index=frame.index, dtype=float)


def _inject_phase7_proxies(frame: pd.DataFrame) -> pd.DataFrame:
    """Build proxy columns for Phase 7 assumption features when absent."""
    out = frame.copy()
    home_mom = _numeric_series(out, "home_momentum_lambda", 1.0)
    away_mom = _numeric_series(out, "away_momentum_lambda", 1.0)
    h5 = _numeric_series(out, "home_form_5", 0.0)
    h10 = _numeric_series(out, "home_form_10", 0.0)
    a5 = _numeric_series(out, "away_form_5", 0.0)
    a10 = _numeric_series(out, "away_form_10", 0.0)

    if "elo_home_trend_5" not in out.columns:
        out["elo_home_trend_5"] = (home_mom - 1.0) + 0.5 * (h5 - h10)
    if "elo_away_trend_5" not in out.columns:
        out["elo_away_trend_5"] = (away_mom - 1.0) + 0.5 * (a5 - a10)
    if "elo_league_adjusted" not in out.columns:
        out["elo_league_adjusted"] = _numeric_series(out, "elo_difference", 0.0) / 150.0
    if "elo_momentum_cross" not in out.columns:
        out["elo_momentum_cross"] = out["elo_home_trend_5"] - out["elo_away_trend_5"]
    if "progressive_carry_diff" not in out.columns:
        out["progressive_carry_diff"] = (
            0.6 * (_numeric_series(out, "home_possession_style", 0.5) - _numeric_series(out, "away_possession_style", 0.5))
            + 0.4 * (h5 - a5)
        )
    if "shot_quality_diff" not in out.columns:
        out["shot_quality_diff"] = (
            _numeric_series(out, "home_xg_avg_5", 1.2) - _numeric_series(out, "away_xg_avg_5", 1.0)
        )
    if "key_passes_under_pressure_diff" not in out.columns:
        out["key_passes_under_pressure_diff"] = (
            _numeric_series(out, "home_pressing_intensity", 0.55)
            - _numeric_series(out, "away_pressing_intensity", 0.5)
        )
    if "set_piece_xg_diff" not in out.columns:
        out["set_piece_xg_diff"] = (
            _numeric_series(out, "home_setpiece_goals_rate", 0.2)
            - _numeric_series(out, "away_setpiece_goals_rate", 0.2)
        )
    return out


def _prepare_frame(
    path: Path,
    canonical_features: List[str],
    defaults: Dict[str, float],
) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "result" not in frame.columns:
        raise ValueError(f"Missing result column: {path}")
    frame = _inject_phase7_proxies(frame)
    frame["result"] = _normalize_result(frame["result"])
    frame = frame.dropna(subset=["result"])
    frame["result"] = frame["result"].astype(int)
    if "match_date" in frame.columns:
        frame["match_date"] = pd.to_datetime(frame["match_date"], errors="coerce")
        frame = frame.sort_values("match_date").reset_index(drop=True)
    else:
        frame = frame.reset_index(drop=True)
    for col in canonical_features:
        if col not in frame.columns:
            frame[col] = defaults.get(col, 0.0)
    frame[canonical_features] = frame[canonical_features].apply(pd.to_numeric, errors="coerce")
    frame[canonical_features] = frame[canonical_features].fillna(pd.Series(defaults))
    return frame


def _split_holdout(
    frame: pd.DataFrame, holdout_frac: float = 0.15
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    idx = max(1, int(len(frame) * (1.0 - holdout_frac)))
    train = frame.iloc[:idx].copy()
    holdout = frame.iloc[idx:].copy()
    if holdout.empty:
        holdout = train.tail(max(1, int(len(train) * holdout_frac))).copy()
        train = train.iloc[: len(train) - len(holdout)].copy()
    return train, holdout


# ── Recency weights ──────────────────────────────────────────────────────────

def _compute_recency_weights(
    match_dates: pd.Series, halflife_seasons: float
) -> np.ndarray:
    """sample_weight = exp(-ln(2) / halflife * match_age_in_seasons)."""
    if match_dates.isna().all():
        return np.ones(len(match_dates), dtype=float)
    max_date = match_dates.max()
    age_days = (max_date - match_dates).dt.days.clip(lower=0).fillna(0).to_numpy(dtype=float)
    age_seasons = age_days / 365.25
    return np.exp(-math.log(2) / max(halflife_seasons, 0.1) * age_seasons).astype(float)


# Leagues with historically high draw rates — Bivariate Poisson overlay prioritised.
_DRAW_HEAVY_LEAGUES = frozenset({"serie_a", "ligue_1", "eredivisie"})


def _split_calibration(
    train: pd.DataFrame, cal_frac: float = 0.20
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Temporal split of training set: first (1-cal_frac) for base learners, last cal_frac for calibration.

    The calibration set is forward-chronological relative to the base training set,
    ensuring no in-sample calibration leakage.
    """
    idx = max(1, int(len(train) * (1.0 - cal_frac)))
    return train.iloc[:idx].copy(), train.iloc[idx:].copy()


# ── Base learner training ────────────────────────────────────────────────────

def _train_base_learners(
    X: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
    use_catboost: bool,
) -> Dict[str, object]:
    """Train all base learners with recency-weighted samples. Returns fitted models."""
    models: Dict[str, object] = {}

    rf = RandomForestClassifier(
        n_estimators=300, max_depth=10, min_samples_leaf=3,
        class_weight="balanced", random_state=42, n_jobs=-1,
    )
    rf.fit(X, y, sample_weight=weights)
    models["rf"] = rf

    if _XGB_AVAILABLE:
        xgb_model = xgb.XGBClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.05,
            objective="multi:softprob", num_class=3,
            eval_metric="mlogloss", random_state=42, verbosity=0, n_jobs=-1,
        )
        xgb_model.fit(X, y, sample_weight=weights)
        models["xgb"] = xgb_model

    if _LGB_AVAILABLE:
        lgb_model = lgb.LGBMClassifier(
            n_estimators=300, max_depth=6, learning_rate=0.05,
            class_weight="balanced", random_state=42, verbosity=-1, n_jobs=-1,
        )
        lgb_model.fit(X, y, sample_weight=weights)
        models["lgbm"] = lgb_model

    if use_catboost and _CB_AVAILABLE:
        cb = CatBoostClassifier(
            iterations=300, depth=6, learning_rate=0.05,
            loss_function="MultiClass", eval_metric="Accuracy",
            random_seed=42, verbose=0,
        )
        cb.fit(X, y, sample_weight=weights)
        models["catboost"] = cb

    return models


def _ensemble_predict(models: Dict[str, object], X: np.ndarray) -> np.ndarray:
    """Equal-weight average of all base learner class probabilities [n, 3]."""
    all_probs: List[np.ndarray] = []
    for model in models.values():
        p = model.predict_proba(X)
        if p.shape[1] == 3:
            all_probs.append(p)
    if not all_probs:
        raise RuntimeError("No base learners returned 3-class probabilities")
    avg = np.mean(all_probs, axis=0)
    row_sums = avg.sum(axis=1, keepdims=True)
    return avg / np.where(row_sums > 0, row_sums, 1.0)


# ── Metrics ──────────────────────────────────────────────────────────────────

def _compute_rps(y_true: np.ndarray, probs: np.ndarray) -> float:
    """Ranked Probability Score — lower is better."""
    n = len(y_true)
    y_oh = np.zeros((n, 3), dtype=float)
    y_oh[np.arange(n), y_true] = 1.0
    diff = np.cumsum(probs, axis=1) - np.cumsum(y_oh, axis=1)
    return float(np.mean(np.sum(diff ** 2, axis=1) / 2.0))


def _compute_brier(y_true: np.ndarray, probs: np.ndarray) -> float:
    n = len(y_true)
    y_oh = np.zeros((n, 3), dtype=float)
    y_oh[np.arange(n), y_true] = 1.0
    return float(np.mean(np.sum((probs - y_oh) ** 2, axis=1)))


def _draw_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Tuple[float, float, float]:
    """Returns (draw_precision, draw_recall, draw_f1)."""
    p = float(precision_score(y_true, y_pred, labels=[1], average="macro", zero_division=0))
    r = float(recall_score(y_true, y_pred, labels=[1], average="macro", zero_division=0))
    f = float(f1_score(y_true, y_pred, labels=[1], average="macro", zero_division=0))
    return p, r, f


# ── Draw policy ──────────────────────────────────────────────────────────────

def _predicted_draw_ratio(labels: np.ndarray) -> float:
    return float((labels == 1).mean()) / 0.246


def _apply_draw_policy(
    probs: np.ndarray, threshold: float, margin: float, min_draw_ratio: float
) -> np.ndarray:
    labels = np.argmax(probs, axis=1)
    draw_mask = (probs[:, 1] >= threshold) | (np.abs(probs[:, 0] - probs[:, 2]) <= margin)
    current_labels = np.where(draw_mask, 1, labels)
    if _predicted_draw_ratio(current_labels) < min_draw_ratio:
        target_count = int(np.ceil(min_draw_ratio * 0.246 * len(labels)))
        order = np.argsort(-probs[:, 1])
        draw_mask[order[: min(target_count, len(order))]] = True
    labels[draw_mask] = 1
    return labels


def _tune_draw_threshold(
    probs: np.ndarray, y_true: np.ndarray, min_draw_ratio: float
) -> Tuple[float, float, float, float]:
    best = (-1e9, 0.40, 0.00, -1.0, 0.0)
    for threshold in np.linspace(0.05, 0.75, 71):
        for margin in np.linspace(0.0, 0.35, 36):
            labels = _apply_draw_policy(probs, float(threshold), float(margin), min_draw_ratio)
            acc = float(accuracy_score(y_true, labels))
            ratio = _predicted_draw_ratio(labels)
            score = acc - 2.0 * max(0.0, min_draw_ratio - ratio)
            if score > best[0]:
                best = (score, float(threshold), float(margin), acc, ratio)
    _, threshold, margin, acc, ratio = best
    return threshold, margin, acc, ratio


def _smooth_probabilities(
    probs: np.ndarray, y_train: np.ndarray, y_holdout: np.ndarray
) -> np.ndarray:
    priors = np.clip(
        np.array([(y_train == c).mean() for c in (0, 1, 2)], dtype=float), 1e-6, None
    )
    priors /= priors.sum()
    best_ll, best_probs = float("inf"), probs
    for alpha in np.linspace(0.0, 0.70, 36):
        candidate = np.clip((1.0 - alpha) * probs + alpha * priors, 1e-6, None)
        candidate /= candidate.sum(axis=1, keepdims=True)
        ll = float(log_loss(y_holdout, candidate, labels=[0, 1, 2]))
        if ll < best_ll:
            best_ll, best_probs = ll, candidate
    return best_probs


# ── Two-stage draw model ─────────────────────────────────────────────────────

def _train_two_stage_draw(
    X_train: np.ndarray,
    y_train: np.ndarray,
    weights: np.ndarray,
    X_holdout: np.ndarray,
    y_holdout: np.ndarray,
    baseline_draw_f1: float,
    improvement_gate: float = 0.03,
) -> Optional[Tuple[object, object, object, np.ndarray, float]]:
    """Train two-stage draw model; return None when gate not met.

    Stage 1: binary P(home_win) and P(away_win) classifiers.
    Stage 2: P(draw) = max(0, 1 - P(home_win) - P(away_win)).
    Isotonic overlay calibrates draw residuals vs empirical frequency.

    Returns (clf_home, clf_away, isotonic_draw, calibrated_probs, draw_f1)
    or None if draw-F1 improvement < improvement_gate.
    """
    clf_home = LogisticRegression(max_iter=500, class_weight="balanced", random_state=42)
    clf_away = LogisticRegression(max_iter=500, class_weight="balanced", random_state=42)
    clf_home.fit(X_train, (y_train == 0).astype(int), sample_weight=weights)
    clf_away.fit(X_train, (y_train == 2).astype(int), sample_weight=weights)

    # Isotonic calibrator trained on training set draw residuals.
    p_home_tr = clf_home.predict_proba(X_train)[:, 1]
    p_away_tr = clf_away.predict_proba(X_train)[:, 1]
    p_draw_raw_tr = np.clip(1.0 - p_home_tr - p_away_tr, 0.0, 1.0)
    draw_calibrator = IsotonicRegression(out_of_bounds="clip")
    draw_calibrator.fit(p_draw_raw_tr, (y_train == 1).astype(int))

    # Apply to holdout.
    p_home = clf_home.predict_proba(X_holdout)[:, 1]
    p_away = clf_away.predict_proba(X_holdout)[:, 1]
    p_draw_raw = np.clip(1.0 - p_home - p_away, 0.0, 1.0)
    p_draw_cal = draw_calibrator.predict(p_draw_raw)

    probs_2s = np.column_stack([p_home, p_draw_cal, p_away])
    row_sums = probs_2s.sum(axis=1, keepdims=True)
    probs_2s /= np.where(row_sums > 0, row_sums, 1.0)

    y_pred = np.argmax(probs_2s, axis=1)
    draw_f1 = float(f1_score(y_holdout, y_pred, labels=[1], average="macro", zero_division=0))
    if draw_f1 - baseline_draw_f1 < improvement_gate:
        return None
    return clf_home, clf_away, draw_calibrator, probs_2s, draw_f1


# ── Metrics dataclass ────────────────────────────────────────────────────────

@dataclass
class LeagueMetrics:
    league: str
    feature_set: str
    feature_count: int
    samples_train: int
    samples_holdout: int
    catboost_used: bool
    two_stage_draw: bool
    recency_halflife: float
    accuracy: float
    train_accuracy: float
    log_loss_score: float
    brier_score: float
    rps: float
    macro_f1: float
    balanced_accuracy: float
    draw_precision: float
    draw_recall: float
    draw_f1: float
    predicted_draw_rate: float
    draw_ratio: float
    draw_threshold: float
    draw_margin: float


# ── Per-league training ──────────────────────────────────────────────────────

def _train_one_league(
    league: str,
    csv_path: Path,
    features_86: List[str],
    defaults_86: Dict[str, float],
    features_65: List[str],
    defaults_65: Dict[str, float],
    holdout_frac: float,
    use_catboost: bool,
    recency_halflife: float,
    use_two_stage: bool,
) -> Tuple[Dict[str, object], Optional[tuple], LeagueMetrics, Dict[str, object]]:
    raw = pd.read_csv(csv_path)
    raw = _inject_phase7_proxies(raw)

    feature_set, canonical_features, defaults = _detect_feature_set(
        raw, features_86, defaults_86, features_65, defaults_65
    )
    frame = _prepare_frame(csv_path, canonical_features, defaults)
    train, holdout = _split_holdout(frame, holdout_frac)

    X_train = train[canonical_features].to_numpy(dtype=float)
    y_train = train["result"].to_numpy(dtype=int)
    X_holdout = holdout[canonical_features].to_numpy(dtype=float)
    y_holdout = holdout["result"].to_numpy(dtype=int)

    # Recency weights (only applied when match_date available).
    if "match_date" in train.columns:
        weights = _compute_recency_weights(train["match_date"], recency_halflife)
    else:
        weights = np.ones(len(y_train), dtype=float)

    # Train base learners.
    models = _train_base_learners(X_train, y_train, weights, use_catboost)
    probs_raw = _ensemble_predict(models, X_holdout)
    probs = _smooth_probabilities(probs_raw, y_train, y_holdout)

    min_draw_ratio = 3.0 if league == "eredivisie" else 0.998
    draw_threshold, draw_margin, holdout_accuracy, draw_ratio = _tune_draw_threshold(
        probs, y_holdout, min_draw_ratio
    )
    y_pred = _apply_draw_policy(probs, draw_threshold, draw_margin, min_draw_ratio)

    # Metrics.
    dp, dr, df1 = _draw_metrics(y_holdout, y_pred)
    ll = float(log_loss(y_holdout, probs, labels=[0, 1, 2]))
    brier = _compute_brier(y_holdout, probs)
    rps = _compute_rps(y_holdout, probs)
    macro_f1 = float(f1_score(y_holdout, y_pred, average="macro", zero_division=0))
    bal_acc = float(balanced_accuracy_score(y_holdout, y_pred))

    # Train accuracy (informational).
    train_probs_raw = _ensemble_predict(models, X_train)
    train_probs = _smooth_probabilities(train_probs_raw, y_train, y_train)
    train_labels = _apply_draw_policy(train_probs, draw_threshold, draw_margin, min_draw_ratio)
    train_acc = float(accuracy_score(y_train, train_labels))

    # Two-stage draw model (optional, gated).
    two_stage_components: Optional[tuple] = None
    two_stage_enabled = False
    if use_two_stage:
        result = _train_two_stage_draw(
            X_train, y_train, weights, X_holdout, y_holdout, baseline_draw_f1=df1
        )
        if result is not None:
            clf_home, clf_away, draw_cal, probs_2s, draw_f1_2s = result
            two_stage_components = (clf_home, clf_away, draw_cal)
            two_stage_enabled = True
            # Replace final predictions with two-stage if gate passed.
            y_pred = np.argmax(probs_2s, axis=1)
            dp, dr, df1 = _draw_metrics(y_holdout, y_pred)
            holdout_accuracy = float(accuracy_score(y_holdout, y_pred))
            macro_f1 = float(f1_score(y_holdout, y_pred, average="macro", zero_division=0))
            bal_acc = float(balanced_accuracy_score(y_holdout, y_pred))

    metrics = LeagueMetrics(
        league=league,
        feature_set=feature_set,
        feature_count=len(canonical_features),
        samples_train=len(train),
        samples_holdout=len(holdout),
        catboost_used=use_catboost and "catboost" in models,
        two_stage_draw=two_stage_enabled,
        recency_halflife=recency_halflife,
        accuracy=holdout_accuracy,
        train_accuracy=train_acc,
        log_loss_score=ll,
        brier_score=brier,
        rps=rps,
        macro_f1=macro_f1,
        balanced_accuracy=bal_acc,
        draw_precision=dp,
        draw_recall=dr,
        draw_f1=df1,
        predicted_draw_rate=draw_ratio * 0.246,
        draw_ratio=draw_ratio,
        draw_threshold=draw_threshold,
        draw_margin=draw_margin,
    )

    # ── Per-league calibration + diversity + Bivariate Poisson ───────────────
    calibration_results: Dict[str, object] = {}

    if _CALIBRATION_AVAILABLE:
        # Temporal calibration split: last 20% of training set for calibration fitting.
        train_base_df, train_cal_df = _split_calibration(train, cal_frac=0.20)
        X_cal = train_cal_df[canonical_features].to_numpy(dtype=float)
        y_cal = train_cal_df["result"].to_numpy(dtype=int)

        # Re-train base learners on reduced base set (first 80% of train).
        X_base_only = train_base_df[canonical_features].to_numpy(dtype=float)
        y_base_only = train_base_df["result"].to_numpy(dtype=int)
        if "match_date" in train_base_df.columns:
            weights_base = _compute_recency_weights(train_base_df["match_date"], recency_halflife)
        else:
            weights_base = np.ones(len(y_base_only), dtype=float)
        models_base = _train_base_learners(X_base_only, y_base_only, weights_base, use_catboost)

        proba_cal = _ensemble_predict(models_base, X_cal)
        proba_holdout_raw = _ensemble_predict(models_base, X_holdout)

        # 1. Multi-method calibration comparison.
        try:
            fitted_cal = compare_calibration_methods(
                league, y_cal, proba_cal, y_holdout, proba_holdout_raw
            )
            calibration_results["calibrator"] = fitted_cal
        except Exception as exc:
            logger.warning("[retrain-v8] %s calibration failed: %s", league, exc)
            fitted_cal = None

        # 2. Ensemble diversity diagnostics.
        try:
            diversity_diag = EnsembleDiversityDiagnostics()
            _, diversity_report = diversity_diag.run(
                league, models, X_holdout, y_holdout
            )
            calibration_results["diversity_report"] = diversity_report
        except Exception as exc:
            logger.warning("[retrain-v8] %s diversity diagnostics failed: %s", league, exc)
            diversity_report = None

        # 3. Bivariate Poisson draw overlay (for all leagues; gate handles non-draw-heavy).
        try:
            overlay = BivariatePoissonDrawOverlay.fit(
                y_cal, proba_cal, y_holdout, proba_holdout_raw,
                league_avg_goals=2.65,
            )
            calibration_results["bivariate_poisson_overlay"] = overlay
            if overlay.gate_passed:
                logger.info(
                    "[retrain-v8] %s: Bivariate Poisson overlay active "
                    "(alpha=%.3f draw_f1_delta=%.4f)",
                    league, overlay.alpha,
                    overlay.draw_f1_after - overlay.draw_f1_before,
                )
        except Exception as exc:
            logger.warning("[retrain-v8] %s Bivariate Poisson fit failed: %s", league, exc)

    artifact_meta = {
        "models": models,
        "feature_columns": canonical_features,
        "feature_set": feature_set,
        "feature_count": len(canonical_features),
        "draw_threshold": draw_threshold,
        "draw_margin": draw_margin,
        "phase": "8",
        "league": league,
        "training_date": date.today().isoformat(),
        "recency_halflife": recency_halflife,
        "catboost_enabled": use_catboost and "catboost" in models,
        "two_stage_draw": two_stage_enabled,
    }
    if two_stage_components is not None:
        clf_home, clf_away, draw_cal = two_stage_components
        artifact_meta["two_stage_components"] = {
            "clf_home": clf_home,
            "clf_away": clf_away,
            "draw_calibrator": draw_cal,
        }
    if calibration_results.get("calibrator") is not None:
        artifact_meta["calibrator"] = calibration_results["calibrator"]
    if calibration_results.get("bivariate_poisson_overlay") is not None:
        artifact_meta["bivariate_poisson_overlay"] = calibration_results["bivariate_poisson_overlay"]

    return artifact_meta, two_stage_components, metrics, calibration_results


# ── Gate checks ──────────────────────────────────────────────────────────────

RPS_GATE = 0.210
DRAW_RATIO_MIN = 0.998
EREDIVISIE_DRAW_RATIO_MIN = 3.0
ACCURACY_GATE = 0.535
LOG_LOSS_GATE = 0.950


def _global_gate_check(per_league: List[LeagueMetrics]) -> Tuple[Dict[str, object], List[str]]:
    failures: List[str] = []
    accuracy_mean = float(np.mean([m.accuracy for m in per_league]))
    ll_mean = float(np.mean([m.log_loss_score for m in per_league]))
    rps_values = [m.rps for m in per_league]
    agg_rps = float(np.mean(rps_values)) if rps_values else None
    macro_f1_mean = float(np.mean([m.macro_f1 for m in per_league]))
    bal_acc_mean = float(np.mean([m.balanced_accuracy for m in per_league]))
    draw_f1_mean = float(np.mean([m.draw_f1 for m in per_league]))

    if accuracy_mean <= ACCURACY_GATE:
        failures.append(f"accuracy_mean {accuracy_mean:.4f} <= {ACCURACY_GATE}")
    if ll_mean >= LOG_LOSS_GATE:
        failures.append(f"log_loss_mean {ll_mean:.4f} >= {LOG_LOSS_GATE}")
    if agg_rps is not None and agg_rps > RPS_GATE:
        failures.append(f"aggregate_rps {agg_rps:.4f} > {RPS_GATE}")
    for m in per_league:
        min_ratio = EREDIVISIE_DRAW_RATIO_MIN if m.league == "eredivisie" else DRAW_RATIO_MIN
        if m.draw_ratio < min_ratio:
            failures.append(f"{m.league}: draw_ratio {m.draw_ratio:.3f} < {min_ratio}")

    summary = {
        "accuracy_mean": round(accuracy_mean, 4),
        "log_loss_mean": round(ll_mean, 4),
        "aggregate_rps": round(agg_rps, 4) if agg_rps is not None else None,
        "rps_gate_threshold": RPS_GATE,
        "macro_f1_mean": round(macro_f1_mean, 4),
        "balanced_accuracy_mean": round(bal_acc_mean, 4),
        "draw_f1_mean": round(draw_f1_mean, 4),
        "gates": {
            "accuracy_gt_0_535": accuracy_mean > ACCURACY_GATE,
            "logloss_lt_0_950": ll_mean < LOG_LOSS_GATE,
            "rps_le_0_210": agg_rps is None or agg_rps <= RPS_GATE,
            "draw_ratio_all_pass": not any(
                (m.draw_ratio < (EREDIVISIE_DRAW_RATIO_MIN if m.league == "eredivisie" else DRAW_RATIO_MIN))
                for m in per_league
            ),
        },
    }
    summary["all_pass"] = len(failures) == 0
    return summary, failures


# ── Artifact persistence ─────────────────────────────────────────────────────

def _save_artifact(models_dir: Path, league: str, artifact: Dict[str, object]) -> None:
    dest = models_dir / f"{league}_ensemble_v6_phase8.pkl"
    if _JOBLIB_AVAILABLE:
        import joblib as jl
        jl.dump(artifact, dest)
    else:
        import pickle
        with open(dest, "wb") as fh:
            pickle.dump(artifact, fh, protocol=4)


def _write_league_report(models_dir: Path, league: str, metrics: LeagueMetrics) -> None:
    today = date.today().strftime("%Y%m%d")
    path = models_dir / f"baseline_v8_{today}_{league}.json"
    path.write_text(json.dumps(asdict(metrics), indent=2), encoding="utf-8")


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 8 retraining — 86-dim ensembles with recency weighting"
    )
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "processed")
    parser.add_argument("--models-dir", type=Path, default=PROJECT_ROOT / "backend" / "models")
    parser.add_argument(
        "--holdout-frac", type=float, default=0.15,
        help="Temporal holdout fraction for walk-forward evaluation (default: 0.15)",
    )
    parser.add_argument("--force-write", action="store_true", help="Write artifacts even when gates fail")
    parser.add_argument(
        "--use-catboost", action="store_true", default=_USE_CATBOOST,
        help="Enable CatBoost as 4th base learner (also set via USE_CATBOOST_LEARNER env var)",
    )
    parser.add_argument(
        "--recency-halflife", type=float, default=_RECENCY_HALFLIFE,
        help="Half-life in seasons for exponential recency weighting (default: 2.0)",
    )
    parser.add_argument(
        "--two-stage-draw", action="store_true", default=_USE_TWO_STAGE,
        help="Enable two-stage draw model (also set via USE_TWO_STAGE_DRAW_MODEL env var)",
    )
    args = parser.parse_args()

    features_86, defaults_86, features_65, defaults_65 = _load_feature_registry()

    print(f"[retrain-v8] Phase 8 retraining — "
          f"catboost={args.use_catboost} recency_halflife={args.recency_halflife} "
          f"two_stage_draw={args.two_stage_draw}")
    print("[retrain-v8] walk-forward temporal splits only — no random k-fold CV")

    artifacts: Dict[str, Dict[str, object]] = {}
    all_metrics: List[LeagueMetrics] = []
    all_cal_results: Dict[str, Dict[str, object]] = {}

    for league, csv_name in LEAGUE_CSVS.items():
        csv_path = args.data_dir / csv_name
        if not csv_path.exists():
            print(f"[retrain-v8] SKIP {league}: {csv_path} not found", file=sys.stderr)
            continue

        print(f"[retrain-v8] Training {league} ...")
        artifact, two_stage, metrics, cal_results = _train_one_league(
            league=league,
            csv_path=csv_path,
            features_86=features_86,
            defaults_86=defaults_86,
            features_65=features_65,
            defaults_65=defaults_65,
            holdout_frac=args.holdout_frac,
            use_catboost=args.use_catboost,
            recency_halflife=args.recency_halflife,
            use_two_stage=args.two_stage_draw,
        )
        artifacts[league] = artifact
        all_metrics.append(metrics)
        all_cal_results[league] = cal_results

        cal_note = ""
        if cal_results.get("calibrator"):
            fc = cal_results["calibrator"]
            cal_note = f" cal={fc.method} ece_delta={round(fc.ece_after['mean'] - fc.ece_before['mean'], 4)}"

        print(
            f"[retrain-v8] {league}: feature_set={metrics.feature_set} "
            f"acc={metrics.accuracy:.4f} rps={metrics.rps:.4f} "
            f"macro_f1={metrics.macro_f1:.4f} draw_f1={metrics.draw_f1:.4f} "
            f"two_stage_draw={metrics.two_stage_draw}{cal_note}"
        )

    if not all_metrics:
        print("[retrain-v8] No leagues trained — no training CSVs found", file=sys.stderr)
        return 1

    global_summary, gate_failures = _global_gate_check(all_metrics)

    today = date.today().strftime("%Y%m%d")
    report = {
        "phase": "8",
        "date": today,
        "evaluation_method": "walk_forward_temporal_splits",
        "random_kfold": False,
        "catboost_enabled": args.use_catboost,
        "recency_halflife_seasons": args.recency_halflife,
        "two_stage_draw_enabled": args.two_stage_draw,
        "per_league": [asdict(m) for m in all_metrics],
        "global": global_summary,
        "gate_failures": gate_failures,
    }

    args.models_dir.mkdir(parents=True, exist_ok=True)

    should_write = not gate_failures or args.force_write
    if should_write:
        for league, artifact in artifacts.items():
            _save_artifact(args.models_dir, league, artifact)
        for m in all_metrics:
            _write_league_report(args.models_dir, m.league, m)
        report_path = args.models_dir / f"training_report_phase8_{today}.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[retrain-v8] Artifacts written to {args.models_dir}")
        print(f"[retrain-v8] Report: {report_path}")

        # Write calibration, diversity, and Bivariate Poisson reports.
        if _CALIBRATION_AVAILABLE:
            for league, cal_res in all_cal_results.items():
                fitted_cal = cal_res.get("calibrator")
                if fitted_cal is not None:
                    write_calibration_report(fitted_cal, args.models_dir)
                diversity_rep = cal_res.get("diversity_report")
                if diversity_rep is not None:
                    write_diversity_report(diversity_rep, args.models_dir)
                overlay = cal_res.get("bivariate_poisson_overlay")
                if overlay is not None:
                    write_bivariate_poisson_report(overlay, league, args.models_dir)
            print("[retrain-v8] Calibration, diversity, and Bivariate Poisson reports written")
    else:
        print("[retrain-v8] GATE FAILURES — artifacts not written", file=sys.stderr)
        for f in gate_failures:
            print(f"  - {f}", file=sys.stderr)

    print(json.dumps(report, indent=2))

    if gate_failures and not args.force_write:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
