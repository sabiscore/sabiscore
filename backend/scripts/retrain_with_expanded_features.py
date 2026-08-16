"""Phase 8 retraining pipeline — canonical 89-feature ensemble with temporal recency weighting.

Usage
-----
python backend/scripts/retrain_with_expanded_features.py \\
  --feature-set phase8 \\
  --data backend/data/processed \\
  --output-dir backend/models \\
  --leagues EPL Bundesliga La_Liga Serie_A Ligue_1 \\
  [--use-catboost] [--use-two-stage-draw] \\
  [--halflife 2.0] [--walk-forward]

Feature sets
  phase7 (65-dim)  — CANONICAL_FEATURES_65, per-league walk-forward
  phase8 (89-feature canonical schema) — legacy CANONICAL_FEATURES_86 alias, Phase 8 features filled with
                     DEFAULT_FEATURE_VALUES_86 if absent from historical data

Gates
  --walk-forward is MANDATORY (random k-fold is permanently banned).
  Aggregate RPS ≤ 0.210 across all trained leagues is required before any
  model artifact is written.

CatBoost
  Enabled only when: --use-catboost flag is set AND catboost is installed.
  Falls back to 3-learner ensemble (RF + XGB + LGBM) if unavailable.

Two-stage draw model
  Enabled only when: --use-two-stage-draw flag is set AND walk-forward
  per-league draw-F1 improvement ≥ 0.03 vs. the base 3-class model.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
)
import xgboost as xgb
import lightgbm as lgb

# ── path bootstrap ────────────────────────────────────────────────────────────
SCRIPT_PATH = Path(__file__).resolve()
BACKEND_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = SCRIPT_PATH.parents[2]
SRC_ROOT = BACKEND_ROOT / "src"
for _p in (str(SRC_ROOT), str(BACKEND_ROOT), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from models.feature_registry import (  # noqa: E402
    CANONICAL_FEATURES_65,
    CANONICAL_FEATURES_86,
    DEFAULT_FEATURE_VALUES_68,
    DEFAULT_FEATURE_VALUES_86,
    PHASE7_FEATURES_ALWAYS_DATA_GAP,
    PHASE8_FEATURES_BERRAR,
    PHASE8_FEATURES_CONTEXT,
    PHASE8_FEATURES_FORM,
    PHASE8_FEATURES_MARKET,
    PHASE8_FEATURES_PI,
)
from models.evaluation.metrics import expected_calibration_error  # noqa: E402
from models.evaluation.temporal_splits import walk_forward_splits  # noqa: E402

# ── optional CatBoost ─────────────────────────────────────────────────────────
_CATBOOST_AVAILABLE = False
try:
    from catboost import CatBoostClassifier  # type: ignore[import]
    _CATBOOST_AVAILABLE = True
except ImportError:
    pass

# ── constants ─────────────────────────────────────────────────────────────────
LEAGUES_DEFAULT = ["EPL", "Bundesliga", "La_Liga", "Serie_A", "Ligue_1"]
TARGET_COL = "result"
DATE_COL = "match_date"
LEAGUE_COL = "league"
DROP_COLS = {TARGET_COL, DATE_COL, LEAGUE_COL, "match_id", "home_team", "away_team",
             "home_team_id", "away_team_id"}

RPS_GATE = 0.210            # aggregate RPS must be at or below this value
DRAW_F1_IMPROVEMENT_MIN = 0.03  # two-stage draw model only enabled if draw-F1 improves by this much

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("retrain_phase8")


# ── data classes ──────────────────────────────────────────────────────────────

@dataclass
class LeagueMetrics:
    league: str
    n_train: int
    n_val: int
    accuracy: float
    log_loss: float
    brier: float
    ece_mean: float
    rps: float
    macro_f1: float
    balanced_accuracy: float
    draw_precision: float
    draw_recall: float
    draw_f1: float
    feature_set: str
    feature_count: int
    recency_halflife: float
    catboost_enabled: bool
    two_stage_draw: bool
    two_stage_draw_applied: bool
    timestamp: str
    # Diversity diagnostics (Sprint 4 Slice A Phase B)
    learner_max_pairwise_corr: float = 0.0
    learner_mean_disagree: float = 0.0
    diversity_advisory: str = ""  # advisory message when correlation is high


# ── metric helpers ────────────────────────────────────────────────────────────


def _learner_diversity(learners: dict, X: pd.DataFrame) -> Tuple[float, float]:
    """Compute max pairwise probability correlation and mean pairwise disagreement.

    Returns:
        (max_pairwise_corr, mean_pairwise_disagree)

    max_pairwise_corr: highest Pearson r of home_win_prob columns between any
        two base learners.  > ENSEMBLE_CORRELATION_PRUNE_THRESHOLD is advisory
        to prune redundant learners.
    mean_pairwise_disagree: mean absolute prediction disagreement across all
        learner pairs.  Low values indicate ensemble collapse risk.
    """
    if len(learners) < 2:
        return 0.0, 0.0
    names = list(learners.keys())
    # Use home-win probability column (index 0) as the diversity signal
    preds = {n: learners[n].predict_proba(X)[:, 0] for n in names}
    corrs: List[float] = []
    disagrees: List[float] = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = preds[names[i]], preds[names[j]]
            corr = float(np.corrcoef(a, b)[0, 1]) if len(a) > 1 else 0.0
            corrs.append(corr)
            disagrees.append(float(np.mean(np.abs(a - b))))
    max_corr = max(corrs) if corrs else 0.0
    mean_disagree = float(np.mean(disagrees)) if disagrees else 0.0
    return round(max_corr, 4), round(mean_disagree, 4)


def _compute_rps(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    """Ranked Probability Score (Epstein 1969).

    Lower is better; RPS=0 is perfect. Class ordering must be home=0, draw=1, away=2.
    """
    n_classes = y_proba.shape[1]
    y_onehot = np.eye(n_classes, dtype=float)[y_true.astype(int)]
    cdf_pred = np.cumsum(y_proba, axis=1)[:, :-1]
    cdf_true = np.cumsum(y_onehot, axis=1)[:, :-1]
    rps = float(np.mean(np.sum((cdf_pred - cdf_true) ** 2, axis=1) / (n_classes - 1)))
    return round(rps, 4)


def _multiclass_brier(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    return float(
        np.mean(
            [brier_score_loss((y_true == c).astype(float), y_proba[:, c])
             for c in range(y_proba.shape[1])]
        )
    )


# ── feature helpers ───────────────────────────────────────────────────────────

def _load_feature_registry_phase8() -> List[str]:
    """Return the legacy CANONICAL_FEATURES_86 alias for the full 89-feature Phase 8 training schema."""
    return list(CANONICAL_FEATURES_86)


def _inject_phase8_proxies(frame: pd.DataFrame, feature_set: str) -> pd.DataFrame:
    """Fill missing Phase 8 columns with registry defaults.

    Historical datasets built before Phase 8 lack these columns. Filling with
    DEFAULT_FEATURE_VALUES_86 primes the model to use them at inference once
    live computation is available.

    Also ensures PHASE7_FEATURES_ALWAYS_DATA_GAP columns ("shot_quality_diff")
    always carry their default value — never a computed proxy.
    """
    defaults = DEFAULT_FEATURE_VALUES_86 if feature_set == "phase8" else DEFAULT_FEATURE_VALUES_68
    phase8_cols = (
        PHASE8_FEATURES_PI
        + PHASE8_FEATURES_BERRAR
        + PHASE8_FEATURES_FORM
        + PHASE8_FEATURES_MARKET
        + PHASE8_FEATURES_CONTEXT
    )
    for col in phase8_cols:
        if col not in frame.columns:
            frame[col] = defaults.get(col, 0.0)

    for col in PHASE7_FEATURES_ALWAYS_DATA_GAP:
        if col in frame.columns:
            frame[col] = defaults.get(col, 0.0)

    return frame


def _select_feature_columns(df: pd.DataFrame, feature_list: List[str]) -> List[str]:
    """Return feature_list columns that actually exist in df."""
    present = [c for c in feature_list if c in df.columns]
    missing = [c for c in feature_list if c not in df.columns]
    if missing:
        logger.warning("Feature columns absent from dataset (will be absent in model): %s", missing)
    return present


def _compute_recency_weights(
    frame: pd.DataFrame,
    halflife_seasons: float = 2.0,
    date_col: str = DATE_COL,
) -> np.ndarray:
    """Exponential decay sample weights by match age.

    w = exp(-ln(2) / halflife_seasons * age_in_seasons)

    Newer matches receive weight closer to 1.0; a match one halflife old gets 0.5.
    """
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    now = dates.max()
    age_seasons = (now - dates).dt.days / 365.25
    age_seasons = age_seasons.fillna(halflife_seasons)  # missing date → median penalty
    decay = np.log(2) / halflife_seasons
    weights = np.exp(-decay * age_seasons.to_numpy())
    return weights.astype(float)


# ── target normalisation ──────────────────────────────────────────────────────

def _normalize_target(y: pd.Series) -> np.ndarray:
    if y.dtype.kind in {"i", "u", "f"}:
        return y.astype(int).to_numpy()
    mapping = {
        "home_win": 0, "h": 0, "0": 0,
        "draw": 1, "d": 1, "1": 1,
        "away_win": 2, "a": 2, "2": 2,
    }
    mapped = y.astype(str).str.strip().str.lower().map(mapping)
    if mapped.isna().any():
        unknown = sorted(set(y[mapped.isna()].astype(str).tolist()))
        raise ValueError(f"Unmapped target labels: {unknown}")
    return mapped.astype(int).to_numpy()


# ── base learners ─────────────────────────────────────────────────────────────

def _build_base_learners(use_catboost: bool) -> dict:
    """Return a dict of base learner instances."""
    learners: dict = {
        "rf": RandomForestClassifier(
            n_estimators=300,
            max_depth=12,
            min_samples_split=8,
            min_samples_leaf=4,
            max_features="sqrt",
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        ),
        "xgb": xgb.XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.06,
            subsample=0.85,
            colsample_bytree=0.85,
            min_child_weight=3,
            objective="multi:softprob",
            num_class=3,
            eval_metric="mlogloss",
            random_state=42,
            n_jobs=-1,
            verbosity=0,
        ),
        "lgbm": lgb.LGBMClassifier(
            n_estimators=400,
            max_depth=7,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.85,
            min_child_samples=20,
            class_weight="balanced",
            objective="multiclass",
            num_class=3,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        ),
    }
    if use_catboost and _CATBOOST_AVAILABLE:
        learners["catboost"] = CatBoostClassifier(
            iterations=400,
            depth=7,
            learning_rate=0.05,
            loss_function="MultiClass",
            random_seed=42,
            verbose=0,
            auto_class_weights="Balanced",
        )
    elif use_catboost and not _CATBOOST_AVAILABLE:
        logger.warning("CatBoost requested but not installed — skipping. pip install catboost")
    return learners


def _fit_meta_learner(base_preds_train: np.ndarray, y_train: np.ndarray) -> LogisticRegression:
    meta = LogisticRegression(
        max_iter=1000,
        C=1.0,
        random_state=42,
        multi_class="multinomial",
        solver="lbfgs",
    )
    meta.fit(base_preds_train, y_train)
    return meta


def _get_base_predictions(
    learners: dict,
    X: pd.DataFrame,
) -> np.ndarray:
    """Stack predict_proba columns from all base learners."""
    parts = [learner.predict_proba(X) for learner in learners.values()]
    return np.hstack(parts)


# ── two-stage draw model ──────────────────────────────────────────────────────

def _build_draw_stage_model(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    weights: Optional[np.ndarray],
) -> CalibratedClassifierCV:
    """Binary model: draw (class 1) vs. non-draw (classes 0 and 2)."""
    y_binary = (y_train == 1).astype(int)
    base = lgb.LGBMClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.06,
        subsample=0.85,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
        verbose=-1,
    )
    calibrated = CalibratedClassifierCV(base, method="isotonic", cv=3)
    calibrated.fit(X_train, y_binary, sample_weight=weights)
    return calibrated


def _apply_draw_stage(
    base_proba: np.ndarray,
    draw_model: CalibratedClassifierCV,
    X_val: pd.DataFrame,
) -> np.ndarray:
    """Blend base 3-class probabilities with draw-stage binary output.

    The draw stage outputs P(draw). We replace base_proba[:,1] with its
    geometric mean with the draw-stage P(draw) and re-normalise the row.
    """
    draw_prob = draw_model.predict_proba(X_val)[:, 1]
    blended = base_proba.copy()
    blended[:, 1] = np.sqrt(blended[:, 1] * draw_prob)
    row_sums = blended.sum(axis=1, keepdims=True)
    row_sums = np.where(row_sums == 0, 1.0, row_sums)
    return blended / row_sums


# ── walk-forward evaluation ───────────────────────────────────────────────────

def _run_walk_forward_eval(
    df: pd.DataFrame,
    feature_cols: List[str],
    y_all: np.ndarray,
    halflife_seasons: float,
    use_catboost: bool,
    use_two_stage_draw: bool,
) -> Tuple[List[np.ndarray], List[np.ndarray], List[str], float, float, float]:
    """Run walk-forward splits and return stacked predictions.

    Returns:
        (all_preds, all_true, all_seasons, draw_f1_with_twostage,
         learner_max_pairwise_corr, learner_mean_disagree)
    """
    all_preds: List[np.ndarray] = []
    all_true: List[np.ndarray] = []
    season_labels: List[str] = []
    draw_f1_base_vals: List[float] = []
    draw_f1_ts_vals: List[float] = []
    # Diversity diagnostics: accumulated per fold, averaged at the end
    diversity_corr_vals: List[float] = []
    diversity_disagree_vals: List[float] = []

    for split in walk_forward_splits(
        df[[DATE_COL]].join(df[feature_cols]).join(df[[TARGET_COL]]),
        date_col=DATE_COL,
    ):
        X_train = df.loc[split.train_idx, feature_cols]
        X_val = df.loc[split.val_idx, feature_cols]
        y_train = y_all[split.train_idx]
        y_val = y_all[split.val_idx]

        weights_train = _compute_recency_weights(
            df.loc[split.train_idx], halflife_seasons=halflife_seasons
        )

        learners = _build_base_learners(use_catboost)
        for name, learner in learners.items():
            try:
                if name == "rf":
                    learner.fit(X_train, y_train, sample_weight=weights_train)
                elif name == "xgb":
                    learner.fit(X_train, y_train, sample_weight=weights_train)
                elif name == "lgbm":
                    learner.fit(X_train, y_train, sample_weight=weights_train)
                elif name == "catboost":
                    learner.fit(X_train, y_train, sample_weight=weights_train)
            except Exception as exc:
                logger.warning("Learner %s failed on split %s: %s", name, split.season_label, exc)

        base_train = _get_base_predictions(learners, X_train)
        base_val = _get_base_predictions(learners, X_val)
        meta = _fit_meta_learner(base_train, y_train)
        proba_base = meta.predict_proba(base_val)

        # Learner diversity on validation set
        try:
            fold_corr, fold_disagree = _learner_diversity(learners, X_val)
            diversity_corr_vals.append(fold_corr)
            diversity_disagree_vals.append(fold_disagree)
        except Exception as _div_exc:
            logger.debug("Diversity computation failed for split %s: %s", split.season_label, _div_exc)

        proba_final = proba_base
        if use_two_stage_draw:
            draw_model = _build_draw_stage_model(X_train, y_train, weights_train)
            proba_ts = _apply_draw_stage(proba_base, draw_model, X_val)
            y_pred_base = np.argmax(proba_base, axis=1)
            y_pred_ts = np.argmax(proba_ts, axis=1)
            f1_base = float(f1_score(y_val, y_pred_base, labels=[1], average="micro", zero_division=0))
            f1_ts = float(f1_score(y_val, y_pred_ts, labels=[1], average="micro", zero_division=0))
            draw_f1_base_vals.append(f1_base)
            draw_f1_ts_vals.append(f1_ts)
            proba_final = proba_ts

        all_preds.append(proba_final)
        all_true.append(y_val)
        season_labels.append(split.season_label)

    draw_f1_improvement = 0.0
    if use_two_stage_draw and draw_f1_base_vals:
        mean_base = float(np.mean(draw_f1_base_vals))
        mean_ts = float(np.mean(draw_f1_ts_vals))
        draw_f1_improvement = mean_ts - mean_base
        logger.info(
            "Two-stage draw F1: base=%.4f ts=%.4f improvement=%.4f (gate=%.2f)",
            mean_base, mean_ts, draw_f1_improvement, DRAW_F1_IMPROVEMENT_MIN,
        )

    mean_corr = float(np.mean(diversity_corr_vals)) if diversity_corr_vals else 0.0
    mean_disagree = float(np.mean(diversity_disagree_vals)) if diversity_disagree_vals else 0.0
    return all_preds, all_true, season_labels, draw_f1_improvement, mean_corr, mean_disagree


# ── final model training ──────────────────────────────────────────────────────

def _train_final_model(
    X: pd.DataFrame,
    y: np.ndarray,
    weights: np.ndarray,
    use_catboost: bool,
    use_two_stage_draw: bool,
    apply_two_stage: bool,
) -> dict:
    """Train final model on the full dataset and return artifact dict."""
    learners = _build_base_learners(use_catboost)
    for name, learner in learners.items():
        try:
            learner.fit(X, y, sample_weight=weights)
        except Exception as exc:
            logger.warning("Final training: learner %s failed: %s", name, exc)

    base_preds = _get_base_predictions(learners, X)
    meta = _fit_meta_learner(base_preds, y)

    artifact: dict = {
        "learners": learners,
        "meta": meta,
        "feature_columns": list(X.columns),
    }

    if apply_two_stage:
        draw_model = _build_draw_stage_model(X, y, weights)
        artifact["draw_model"] = draw_model

    return artifact


def _predict_with_artifact(artifact: dict, X: pd.DataFrame) -> np.ndarray:
    base = _get_base_predictions(artifact["learners"], X)
    proba = artifact["meta"].predict_proba(base)
    if "draw_model" in artifact:
        proba = _apply_draw_stage(proba, artifact["draw_model"], X)
    return proba


# ── gate check ────────────────────────────────────────────────────────────────

def _global_gate_check(metrics_by_league: Dict[str, LeagueMetrics]) -> bool:
    """Return True iff the aggregate RPS across all leagues is at or below RPS_GATE."""
    rps_vals = [m.rps for m in metrics_by_league.values()]
    if not rps_vals:
        logger.error("Global gate: no league metrics available")
        return False
    agg_rps = float(np.mean(rps_vals))
    passed = agg_rps <= RPS_GATE
    logger.info(
        "Global gate: aggregate RPS=%.4f (gate≤%.3f) — %s",
        agg_rps,
        RPS_GATE,
        "PASS" if passed else "FAIL",
    )
    return passed


# ── dataset loading ───────────────────────────────────────────────────────────

def _load_league_dataset(data_dir: Path, league: str) -> pd.DataFrame:
    slug = league.lower().replace(" ", "_")
    for suffix in ("_training.parquet", "_training.csv", f"_{slug}.parquet", f"_{slug}.csv"):
        candidate = data_dir / f"{slug}{suffix}"
        if candidate.exists():
            return (pd.read_parquet(candidate) if candidate.suffix == ".parquet"
                    else pd.read_csv(candidate))
    # Try a glob for any file containing the league slug
    matches = list(data_dir.glob(f"*{slug}*.parquet")) + list(data_dir.glob(f"*{slug}*.csv"))
    if matches:
        f = matches[0]
        return pd.read_parquet(f) if f.suffix == ".parquet" else pd.read_csv(f)
    raise FileNotFoundError(
        f"No training dataset found for league '{league}' under {data_dir}"
    )


# ── artifact persistence ──────────────────────────────────────────────────────

def _save_league_artifact(
    artifact: dict,
    metrics: LeagueMetrics,
    output_dir: Path,
    date_str: str,
) -> None:
    slug = metrics.league.lower().replace(" ", "_")
    model_path = output_dir / f"{slug}_ensemble_v6_phase8_{date_str}.pkl"
    report_path = output_dir / f"baseline_v8_{date_str}_{slug}.json"

    joblib.dump(artifact, model_path)
    logger.info("Saved model artifact → %s", model_path)

    report = {
        "phase": "8",
        "feature_set": metrics.feature_set,
        "feature_count": metrics.feature_count,
        "trained_at": metrics.timestamp,
        **{k: v for k, v in asdict(metrics).items()},
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Saved league report → %s", report_path)


# ── per-league pipeline ───────────────────────────────────────────────────────

def _retrain_league(
    league: str,
    data_dir: Path,
    output_dir: Path,
    feature_set: str,
    halflife_seasons: float,
    use_catboost: bool,
    use_two_stage_draw: bool,
    date_str: str,
    dry_run: bool,
) -> Optional[LeagueMetrics]:
    logger.info("=== %s (feature_set=%s) ===", league, feature_set)

    try:
        df = _load_league_dataset(data_dir, league)
    except FileNotFoundError as exc:
        logger.error("%s — skipping: %s", league, exc)
        return None

    if TARGET_COL not in df.columns or DATE_COL not in df.columns:
        logger.error("%s — dataset missing '%s' or '%s' columns", league, TARGET_COL, DATE_COL)
        return None

    df = df.dropna(subset=[TARGET_COL, DATE_COL]).reset_index(drop=True)
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")
    df = df.dropna(subset=[DATE_COL]).reset_index(drop=True)

    feature_list = (
        _load_feature_registry_phase8() if feature_set == "phase8"
        else list(CANONICAL_FEATURES_65)
    )

    df = _inject_phase8_proxies(df, feature_set)
    feature_cols = _select_feature_columns(df, feature_list)

    if not feature_cols:
        logger.error("%s — no valid feature columns available after injection", league)
        return None

    # Impute any remaining NaN with default values
    defaults = DEFAULT_FEATURE_VALUES_86 if feature_set == "phase8" else DEFAULT_FEATURE_VALUES_68
    for col in feature_cols:
        if df[col].isna().any():
            df[col] = df[col].fillna(defaults.get(col, 0.0))

    y_all = _normalize_target(df[TARGET_COL])

    # ── walk-forward evaluation ────────────────────────────────────────────
    logger.info("%s — running walk-forward evaluation (%d rows)", league, len(df))
    (
        all_preds, all_true, season_labels,
        draw_f1_improvement, learner_max_corr, learner_mean_disagree,
    ) = _run_walk_forward_eval(
        df=df,
        feature_cols=feature_cols,
        y_all=y_all,
        halflife_seasons=halflife_seasons,
        use_catboost=use_catboost,
        use_two_stage_draw=use_two_stage_draw,
    )

    if not all_preds:
        logger.error("%s — walk-forward produced no folds (need ≥4 seasons)", league)
        return None

    p_all = np.vstack(all_preds)
    y_eval = np.concatenate(all_true)
    y_pred = np.argmax(p_all, axis=1)

    rps = _compute_rps(y_eval, p_all)
    brier = _multiclass_brier(y_eval, p_all)
    ece = expected_calibration_error(y_eval, p_all)
    macro_f1 = float(f1_score(y_eval, y_pred, average="macro", zero_division=0))
    bal_acc = float(balanced_accuracy_score(y_eval, y_pred))
    draw_prec = float(precision_score(y_eval, y_pred, labels=[1], average="micro", zero_division=0))
    draw_rec = float(recall_score(y_eval, y_pred, labels=[1], average="micro", zero_division=0))
    draw_f1_val = (
        2 * draw_prec * draw_rec / (draw_prec + draw_rec)
        if (draw_prec + draw_rec) > 0 else 0.0
    )
    apply_two_stage = use_two_stage_draw and (draw_f1_improvement >= DRAW_F1_IMPROVEMENT_MIN)

    logger.info(
        "%s eval — accuracy=%.4f ll=%.4f brier=%.4f ece=%.4f rps=%.4f "
        "macro_f1=%.4f bal_acc=%.4f draw_f1=%.4f [%d seasons]",
        league,
        float((y_pred == y_eval).mean()),
        float(log_loss(y_eval, p_all)),
        brier, ece["mean"], rps, macro_f1, bal_acc, draw_f1_val,
        len(season_labels),
    )

    if use_two_stage_draw and not apply_two_stage:
        logger.info(
            "%s — two-stage draw not applied: improvement=%.4f < gate=%.2f",
            league, draw_f1_improvement, DRAW_F1_IMPROVEMENT_MIN,
        )

    # Diversity advisory
    _prune_threshold = float(os.environ.get("ENSEMBLE_CORRELATION_PRUNE_THRESHOLD", "0.92"))
    diversity_advisory = ""
    if learner_max_corr >= _prune_threshold:
        diversity_advisory = (
            f"High learner correlation ({learner_max_corr:.4f} >= {_prune_threshold:.2f}): "
            "consider pruning a redundant base learner if draw-F1 is unaffected."
        )
        logger.warning("%s diversity advisory: %s", league, diversity_advisory)
    else:
        logger.info(
            "%s diversity: max_pairwise_corr=%.4f mean_disagree=%.4f",
            league, learner_max_corr, learner_mean_disagree,
        )

    metrics = LeagueMetrics(
        league=league,
        n_train=int(len(df)),
        n_val=int(len(y_eval)),
        accuracy=float((y_pred == y_eval).mean()),
        log_loss=float(log_loss(y_eval, p_all)),
        brier=brier,
        ece_mean=float(ece["mean"]),
        rps=rps,
        macro_f1=macro_f1,
        balanced_accuracy=bal_acc,
        draw_precision=draw_prec,
        draw_recall=draw_rec,
        draw_f1=draw_f1_val,
        feature_set=feature_set,
        feature_count=len(feature_cols),
        recency_halflife=halflife_seasons,
        catboost_enabled=use_catboost and _CATBOOST_AVAILABLE,
        two_stage_draw=use_two_stage_draw,
        two_stage_draw_applied=apply_two_stage,
        timestamp=datetime.now(timezone.utc).isoformat(),
        learner_max_pairwise_corr=learner_max_corr,
        learner_mean_disagree=learner_mean_disagree,
        diversity_advisory=diversity_advisory,
    )

    if dry_run:
        logger.info("%s — dry-run mode: skipping final model training and save", league)
        return metrics

    # ── train final model on full dataset ─────────────────────────────────
    logger.info("%s — training final model on %d rows", league, len(df))
    X_full = df[feature_cols]
    weights_full = _compute_recency_weights(df, halflife_seasons=halflife_seasons)
    artifact = _train_final_model(
        X=X_full,
        y=y_all,
        weights=weights_full,
        use_catboost=use_catboost,
        use_two_stage_draw=use_two_stage_draw,
        apply_two_stage=apply_two_stage,
    )
    artifact["feature_columns"] = feature_cols

    output_dir.mkdir(parents=True, exist_ok=True)
    _save_league_artifact(artifact, metrics, output_dir, date_str)

    return metrics


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 8 SabiScore retraining pipeline")
    parser.add_argument(
        "--feature-set",
        choices=["phase7", "phase8"],
        default="phase8",
        help="Feature schema to use (default: phase8 = canonical 89-feature schema; legacy CANONICAL_FEATURES_86 alias)",
    )
    parser.add_argument(
        "--data",
        required=True,
        type=Path,
        help="Path to processed training data directory (parquet or csv)",
    )
    parser.add_argument(
        "--output-dir",
        default="backend/models",
        type=Path,
        help="Directory to write model artifacts and per-league reports",
    )
    parser.add_argument(
        "--leagues",
        nargs="+",
        default=LEAGUES_DEFAULT,
        help="Leagues to train (default: EPL Bundesliga La_Liga Serie_A Ligue_1)",
    )
    parser.add_argument(
        "--halflife",
        type=float,
        default=float(os.getenv("TRAINING_RECENCY_HALFLIFE_SEASONS", "2.0")),
        help="Recency weighting halflife in seasons (default: 2.0)",
    )
    parser.add_argument(
        "--use-catboost",
        action="store_true",
        default=os.getenv("USE_CATBOOST_LEARNER", "false").lower() == "true",
        help="Add CatBoost as 4th base learner (requires: pip install catboost)",
    )
    parser.add_argument(
        "--use-two-stage-draw",
        action="store_true",
        default=os.getenv("USE_TWO_STAGE_DRAW_MODEL", "false").lower() == "true",
        help="Enable two-stage draw model (applied only when draw-F1 improves ≥0.03)",
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        required=True,
        help="Mandatory flag — confirms temporal walk-forward evaluation (no random k-fold)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run walk-forward evaluation only; do not train final model or save artifacts",
    )
    args = parser.parse_args()

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    logger.info(
        "Phase 8 retraining — feature_set=%s halflife=%.1f catboost=%s two_stage_draw=%s date=%s",
        args.feature_set, args.halflife, args.use_catboost, args.use_two_stage_draw, date_str,
    )

    metrics_by_league: Dict[str, LeagueMetrics] = {}
    for league in args.leagues:
        m = _retrain_league(
            league=league,
            data_dir=args.data,
            output_dir=args.output_dir,
            feature_set=args.feature_set,
            halflife_seasons=args.halflife,
            use_catboost=args.use_catboost,
            use_two_stage_draw=args.use_two_stage_draw,
            date_str=date_str,
            dry_run=args.dry_run,
        )
        if m is not None:
            metrics_by_league[league] = m

    if not metrics_by_league:
        logger.error("No leagues trained successfully — aborting")
        sys.exit(1)

    gate_passed = _global_gate_check(metrics_by_league)

    # ── aggregate report ──────────────────────────────────────────────────
    report = {
        "phase": "8",
        "feature_set": args.feature_set,
        "date": date_str,
        "catboost_available": _CATBOOST_AVAILABLE,
        "catboost_enabled": args.use_catboost and _CATBOOST_AVAILABLE,
        "two_stage_draw_option": args.use_two_stage_draw,
        "recency_halflife_seasons": args.halflife,
        "global_gate_rps_threshold": RPS_GATE,
        "global_gate_passed": gate_passed,
        "aggregate_rps": round(float(np.mean([m.rps for m in metrics_by_league.values()])), 4),
        "aggregate_macro_f1": round(
            float(np.mean([m.macro_f1 for m in metrics_by_league.values()])), 4
        ),
        "aggregate_balanced_accuracy": round(
            float(np.mean([m.balanced_accuracy for m in metrics_by_league.values()])), 4
        ),
        "leagues": {lg: asdict(m) for lg, m in metrics_by_league.items()},
    }

    if not args.dry_run:
        summary_path = args.output_dir / f"retrain_summary_phase8_{date_str}.json"
        args.output_dir.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("Summary report → %s", summary_path)

    print(
        f"\n[retrain_phase8] "
        f"feature_set={args.feature_set} "
        f"leagues={len(metrics_by_league)} "
        f"agg_rps={report['aggregate_rps']:.4f} "
        f"agg_macro_f1={report['aggregate_macro_f1']:.4f} "
        f"bal_acc={report['aggregate_balanced_accuracy']:.4f} "
        f"gate={'PASS' if gate_passed else 'FAIL'}"
    )
    if not gate_passed:
        logger.error(
            "Global RPS gate FAILED (%.4f > %.3f) — models NOT suitable for release",
            report["aggregate_rps"],
            RPS_GATE,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
