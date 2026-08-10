"""Phase 8 feature expansion validator with SHAP ablation.

Usage
-----
# Standard walk-forward expansion check
python backend/scripts/validate_feature_expansion.py \\
  --baseline backend/models/epl_ensemble_v5_phase7.pkl \\
  --candidate backend/models/epl_ensemble_v6_phase8_20260610.pkl \\
  --data backend/data/processed/epl_training.parquet \\
  --output docs/expansion-report-YYYYMMDD.json \\
  --walk-forward

# SHAP ablation — hold-one-family-out across all Phase 8 feature families
python backend/scripts/validate_feature_expansion.py \\
  --data backend/data/processed/epl_training.parquet \\
  --output docs/shap-ablation-YYYYMMDD.json \\
  --walk-forward --shap-ablation

Phase 8 feature families (for ablation)
  pi_ratings      (6): home/away pi_attack, pi_defense, diffs
  berrar_ratings  (3): home/away berrar_rating, diff
  ewma_form       (6): weighted win_rate, draw_rate, ppg × home/away
  market_drift    (5): odds_drift_{home,draw,away}, max_abs_odds_drift, sharp_money_direction
  match_context   (1): match_importance_score

Ablation output reports per-family:
  mean_shap        — mean absolute SHAP value across all walk-forward val folds
  delta_rps        — RPS change when family is held out (positive = family helps)
  delta_brier      — Brier score change when family is held out
  delta_draw_f1    — draw F1 change when family is held out
  prune_flag       — True if mean_shap < SHAP_PRUNE_THRESHOLD (default 0.002)
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
from sklearn.metrics import brier_score_loss, f1_score
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
    DEFAULT_FEATURE_VALUES_86,
    PHASE7_FEATURES_ALWAYS_DATA_GAP,
    PHASE8_FEATURES_BERRAR,
    PHASE8_FEATURES_CONTEXT,
    PHASE8_FEATURES_FORM,
    PHASE8_FEATURES_MARKET,
    PHASE8_FEATURES_PI,
)
from models.evaluation.temporal_splits import walk_forward_splits  # noqa: E402

# ── optional SHAP ─────────────────────────────────────────────────────────────
_SHAP_AVAILABLE = False
try:
    import shap  # type: ignore[import]
    _SHAP_AVAILABLE = True
except ImportError:
    pass

# ── constants ─────────────────────────────────────────────────────────────────
TARGET_COL = "result"
DATE_COL = "match_date"
LEAGUE_COL = "league"
DROP_COLS = {TARGET_COL, DATE_COL, LEAGUE_COL, "match_id", "home_team", "away_team",
             "home_team_id", "away_team_id"}

SHAP_PRUNE_THRESHOLD: float = float(os.getenv("SHAP_PRUNE_THRESHOLD", "0.002"))

PHASE8_FEATURE_FAMILIES: Dict[str, List[str]] = {
    "pi_ratings": list(PHASE8_FEATURES_PI),
    "berrar_ratings": list(PHASE8_FEATURES_BERRAR),
    "ewma_form": list(PHASE8_FEATURES_FORM),
    "market_drift": list(PHASE8_FEATURES_MARKET),
    "match_context": list(PHASE8_FEATURES_CONTEXT),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("validate_feature_expansion")


# ── data classes ──────────────────────────────────────────────────────────────

@dataclass
class FamilyAblationResult:
    family: str
    features: List[str]
    mean_shap: float
    delta_rps: float
    delta_brier: float
    delta_draw_f1: float
    prune_flag: bool
    n_folds: int
    leagues_below_threshold: int = 0


@dataclass
class ExpansionReport:
    date: str
    data_path: str
    n_rows: int
    feature_set_baseline: str
    feature_set_candidate: str
    baseline_rps: float
    candidate_rps: float
    delta_rps: float
    baseline_brier: float
    candidate_brier: float
    delta_brier: float
    baseline_draw_f1: float
    candidate_draw_f1: float
    delta_draw_f1: float
    improvement: bool
    shap_ablation: Optional[List[Dict]]


# ── metric helpers ────────────────────────────────────────────────────────────

def _compute_rps(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    n_classes = y_proba.shape[1]
    y_onehot = np.eye(n_classes, dtype=float)[y_true.astype(int)]
    cdf_pred = np.cumsum(y_proba, axis=1)[:, :-1]
    cdf_true = np.cumsum(y_onehot, axis=1)[:, :-1]
    return float(round(np.mean(np.sum((cdf_pred - cdf_true) ** 2, axis=1) / (n_classes - 1)), 4))


def _multiclass_brier(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    return float(
        np.mean([brier_score_loss((y_true == c).astype(float), y_proba[:, c])
                 for c in range(y_proba.shape[1])])
    )


def _draw_f1(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(f1_score(y_true, y_pred, labels=[1], average="micro", zero_division=0))


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
        raise ValueError(f"Unmapped target labels: {sorted(set(y[mapped.isna()].astype(str).tolist()))}")
    return mapped.astype(int).to_numpy()


# ── dataset helpers ───────────────────────────────────────────────────────────

def _load_dataset(path: Path) -> pd.DataFrame:
    if path.is_dir():
        files = sorted(path.rglob("*.parquet")) + sorted(path.rglob("*.csv"))
        if not files:
            raise ValueError(f"No parquet/csv files under {path}")
        frames = [pd.read_parquet(f) if f.suffix == ".parquet" else pd.read_csv(f) for f in files]
        return pd.concat(frames, ignore_index=True)
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)


def _prepare(df: pd.DataFrame, feature_cols: List[str]) -> Tuple[pd.DataFrame, np.ndarray]:
    df = df.dropna(subset=[TARGET_COL, DATE_COL]).copy()
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")
    df = df.dropna(subset=[DATE_COL]).reset_index(drop=True)
    for col in feature_cols:
        if col not in df.columns:
            df[col] = DEFAULT_FEATURE_VALUES_86.get(col, 0.0)
    for col in PHASE7_FEATURES_ALWAYS_DATA_GAP:
        if col in df.columns:
            df[col] = DEFAULT_FEATURE_VALUES_86.get(col, 0.0)
    for col in feature_cols:
        if df[col].isna().any():
            df[col] = df[col].fillna(DEFAULT_FEATURE_VALUES_86.get(col, 0.0))
    y = _normalize_target(df[TARGET_COL])
    return df, y


# ── lightweight walk-forward evaluator ───────────────────────────────────────

def _quick_lgbm_eval(
    df: pd.DataFrame,
    feature_cols: List[str],
    y_all: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Walk-forward LGBM eval — returns (stacked_proba, stacked_y_true)."""
    all_preds: List[np.ndarray] = []
    all_true: List[np.ndarray] = []

    for split in walk_forward_splits(
        df[[DATE_COL]].join(df[feature_cols]).join(df[[TARGET_COL]]),
        date_col=DATE_COL,
    ):
        X_train = df.loc[split.train_idx, feature_cols]
        X_val = df.loc[split.val_idx, feature_cols]
        y_train = y_all[split.train_idx]
        y_val = y_all[split.val_idx]

        model = lgb.LGBMClassifier(
            n_estimators=300,
            max_depth=7,
            learning_rate=0.05,
            subsample=0.85,
            class_weight="balanced",
            objective="multiclass",
            num_class=3,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )
        model.fit(X_train, y_train)
        all_preds.append(model.predict_proba(X_val))
        all_true.append(y_val)

    if not all_preds:
        raise ValueError("walk_forward_splits produced no folds — need ≥4 seasons of data")

    return np.vstack(all_preds), np.concatenate(all_true)


# ── SHAP helpers ──────────────────────────────────────────────────────────────

def _compute_shap_values(
    model: lgb.LGBMClassifier,
    X_val: pd.DataFrame,
) -> np.ndarray:
    """Return mean absolute SHAP values per feature (shape: n_features)."""
    if not _SHAP_AVAILABLE:
        return np.zeros(X_val.shape[1])
    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X_val)
    # shap_vals is list[class] of (n_samples, n_features)
    if isinstance(shap_vals, list):
        stacked = np.stack([np.abs(sv).mean(axis=0) for sv in shap_vals], axis=0)
        return stacked.mean(axis=0)
    return np.abs(shap_vals).mean(axis=0)


def _compute_shap_per_sample(
    model: lgb.LGBMClassifier,
    X_val: pd.DataFrame,
) -> np.ndarray:
    """Return per-sample mean absolute SHAP values (shape: n_samples × n_features)."""
    if not _SHAP_AVAILABLE:
        return np.zeros((len(X_val), X_val.shape[1]))
    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X_val)
    if isinstance(shap_vals, list):
        # (n_classes, n_samples, n_features) — mean over classes
        stacked = np.stack([np.abs(sv) for sv in shap_vals], axis=0)
        return stacked.mean(axis=0)
    return np.abs(shap_vals)


# ── SHAP ablation ─────────────────────────────────────────────────────────────

def run_shap_ablation(
    df: pd.DataFrame,
    all_phase8_features: List[str],
    y_all: np.ndarray,
    threshold: float = SHAP_PRUNE_THRESHOLD,
) -> List[FamilyAblationResult]:
    """Hold-one-Phase8-family-out walk-forward ablation.

    For each Phase 8 family F:
      1. Build feature set = all_phase8_features minus F
      2. Run walk-forward LGBM evaluation
      3. Compute mean |SHAP| for removed family (requires SHAP)
      4. Report delta_rps, delta_brier, delta_draw_f1 vs. full-family baseline
    """
    logger.info("Running SHAP ablation on %d Phase 8 families", len(PHASE8_FEATURE_FAMILIES))

    # ── full baseline (all Phase 8 features) ──────────────────────────────
    full_cols = [c for c in all_phase8_features if c in df.columns]
    logger.info("Ablation baseline: %d features, running walk-forward...", len(full_cols))
    p_full, y_full = _quick_lgbm_eval(df, full_cols, y_all)
    rps_full = _compute_rps(y_full, p_full)
    brier_full = _multiclass_brier(y_full, p_full)
    draw_f1_full = _draw_f1(y_full, np.argmax(p_full, axis=1))
    logger.info(
        "Baseline: rps=%.4f brier=%.4f draw_f1=%.4f", rps_full, brier_full, draw_f1_full
    )

    # ── always compute splits_list so n_folds is accurate regardless of SHAP ─
    splits_list = list(walk_forward_splits(
        df[[DATE_COL]].join(df[full_cols]).join(df[[TARGET_COL]]),
        date_col=DATE_COL,
    ))

    # ── SHAP values on full model (last fold only — representative) ───────
    shap_mean_by_feature: Dict[str, float] = {}
    shap_per_sample: Optional[np.ndarray] = None   # shape (n_val, n_features)
    shap_val_idx: Optional[np.ndarray] = None
    if _SHAP_AVAILABLE:
        logger.info("Computing SHAP values on final fold...")
        if splits_list:
            last_split = splits_list[-1]
            X_tr = df.loc[last_split.train_idx, full_cols]
            X_vl = df.loc[last_split.val_idx, full_cols]
            y_tr = y_all[last_split.train_idx]
            shap_model = lgb.LGBMClassifier(
                n_estimators=200, max_depth=7, learning_rate=0.05,
                class_weight="balanced", objective="multiclass", num_class=3,
                random_state=42, n_jobs=-1, verbose=-1,
            )
            shap_model.fit(X_tr, y_tr)
            shap_vals_agg = _compute_shap_values(shap_model, X_vl)
            shap_mean_by_feature = dict(zip(full_cols, shap_vals_agg.tolist()))
            shap_per_sample = _compute_shap_per_sample(shap_model, X_vl)
            shap_val_idx = np.asarray(last_split.val_idx)
    else:
        logger.warning("shap not installed — mean_shap will be 0.0. pip install shap")

    # ── per-family ablation ────────────────────────────────────────────────
    results: List[FamilyAblationResult] = []
    for family_name, family_features in PHASE8_FEATURE_FAMILIES.items():
        ablated_cols = [c for c in full_cols if c not in family_features]
        logger.info("Ablating family '%s' (%d features)...", family_name, len(family_features))

        if not ablated_cols:
            logger.warning("No features remaining after ablating '%s' — skipping", family_name)
            continue

        try:
            p_abl, y_abl = _quick_lgbm_eval(df, ablated_cols, y_all)
        except ValueError as exc:
            logger.warning("Ablation of '%s' failed: %s", family_name, exc)
            continue

        rps_abl = _compute_rps(y_abl, p_abl)
        brier_abl = _multiclass_brier(y_abl, p_abl)
        draw_f1_abl = _draw_f1(y_abl, np.argmax(p_abl, axis=1))

        # positive delta = family improves the metric (holding out worsens it)
        delta_rps = round(rps_abl - rps_full, 4)
        delta_brier = round(brier_abl - brier_full, 4)
        delta_draw_f1 = round(draw_f1_full - draw_f1_abl, 4)

        mean_shap = float(
            np.mean([shap_mean_by_feature.get(f, 0.0) for f in family_features])
        )

        # Per-league SHAP: count how many leagues fall below the threshold.
        # When per-sample SHAP is available, use league-stratified means.
        # prune_flag = leagues_below >= 3 (spec §4 Phase C); fallback to global mean.
        leagues_below = 0
        if shap_per_sample is not None and shap_val_idx is not None and LEAGUE_COL in df.columns:
            feat_indices = [full_cols.index(f) for f in family_features if f in full_cols]
            if feat_indices:
                family_sample_shap = shap_per_sample[:, feat_indices].mean(axis=1)
                val_leagues = df.loc[shap_val_idx, LEAGUE_COL].astype(str).to_numpy()
                for lg in sorted(set(val_leagues.tolist())):
                    mask = val_leagues == lg
                    if mask.sum() == 0:
                        continue
                    if float(family_sample_shap[mask].mean()) < threshold:
                        leagues_below += 1

        if shap_per_sample is not None and LEAGUE_COL in df.columns:
            prune = leagues_below >= 3
        else:
            prune = mean_shap < threshold

        logger.info(
            "  family='%s' mean_shap=%.4f delta_rps=%+.4f delta_brier=%+.4f "
            "delta_draw_f1=%+.4f leagues_below=%d prune=%s",
            family_name, mean_shap, delta_rps, delta_brier, delta_draw_f1,
            leagues_below, prune,
        )

        results.append(FamilyAblationResult(
            family=family_name,
            features=family_features,
            mean_shap=round(mean_shap, 6),
            delta_rps=delta_rps,
            delta_brier=delta_brier,
            delta_draw_f1=delta_draw_f1,
            prune_flag=prune,
            n_folds=len(splits_list),
            leagues_below_threshold=leagues_below,
        ))

    return results


# ── model comparison walk-forward ─────────────────────────────────────────────

def _model_walk_forward_metrics(
    model: object,
    df: pd.DataFrame,
    date_col: str = DATE_COL,
) -> Tuple[float, float, float]:
    """Walk-forward evaluate a loaded sklearn-compatible model.

    Returns (rps, brier, draw_f1).
    """
    if hasattr(model, "feature_columns"):
        feature_cols = list(model.feature_columns)
    elif hasattr(model, "feature_names_in_"):
        feature_cols = list(model.feature_names_in_)
    else:
        feature_cols = [c for c in df.columns if c not in DROP_COLS and np.issubdtype(df[c].dtype, np.number)]

    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        for c in missing:
            df[c] = DEFAULT_FEATURE_VALUES_86.get(c, 0.0)
    for c in PHASE7_FEATURES_ALWAYS_DATA_GAP:
        if c in df.columns:
            df[c] = DEFAULT_FEATURE_VALUES_86.get(c, 0.0)

    y_all = _normalize_target(df[TARGET_COL])
    all_preds: List[np.ndarray] = []
    all_true: List[np.ndarray] = []

    for split in walk_forward_splits(
        df[[date_col]].join(df[feature_cols]).join(df[[TARGET_COL]]),
        date_col=date_col,
    ):
        X_val = df.loc[split.val_idx, feature_cols]
        y_val = y_all[split.val_idx]
        proba = model.predict_proba(X_val)
        all_preds.append(proba)
        all_true.append(y_val)

    if not all_preds:
        raise ValueError("No walk-forward folds produced")

    p = np.vstack(all_preds)
    y = np.concatenate(all_true)
    return _compute_rps(y, p), _multiclass_brier(y, p), _draw_f1(y, np.argmax(p, axis=1))


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 8 feature expansion validator")
    parser.add_argument("--baseline", type=Path, default=None,
                        help="Path to baseline model pickle (v5_phase7)")
    parser.add_argument("--candidate", type=Path, default=None,
                        help="Path to candidate model pickle (v6_phase8)")
    parser.add_argument("--data", required=True, type=Path,
                        help="Training dataset path (parquet or csv, or directory)")
    parser.add_argument("--output", required=True, type=Path,
                        help="Output JSON report path")
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        required=True,
        help="Mandatory — confirms temporal walk-forward (no random k-fold)",
    )
    parser.add_argument(
        "--shap-ablation",
        action="store_true",
        help="Run hold-one-family-out SHAP ablation on Phase 8 feature families",
    )
    parser.add_argument(
        "--shap-threshold",
        type=float,
        default=SHAP_PRUNE_THRESHOLD,
        help=f"SHAP pruning threshold (default {SHAP_PRUNE_THRESHOLD})",
    )
    args = parser.parse_args()

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    df = _load_dataset(args.data)
    all_phase8_features = list(CANONICAL_FEATURES_65) + [
        c for family in PHASE8_FEATURE_FAMILIES.values() for c in family
    ]
    df, y_all = _prepare(df, all_phase8_features)
    logger.info("Dataset loaded: %d rows, %d columns", len(df), len(df.columns))

    ablation_results: Optional[List[FamilyAblationResult]] = None
    if args.shap_ablation:
        if not _SHAP_AVAILABLE:
            logger.warning("SHAP not available — ablation will run without shap values (mean_shap=0.0)")
        ablation_results = run_shap_ablation(
            df=df,
            all_phase8_features=all_phase8_features,
            y_all=y_all,
            threshold=args.shap_threshold,
        )
        prune_flagged = [r.family for r in ablation_results if r.prune_flag]
        if prune_flagged:
            logger.warning("Families flagged for pruning (mean_shap < %.4f): %s",
                           args.shap_threshold, prune_flagged)

    # ── model comparison (only if both models provided) ───────────────────
    baseline_rps = baseline_brier = baseline_draw_f1 = 0.0
    candidate_rps = candidate_brier = candidate_draw_f1 = 0.0

    if args.baseline and args.candidate:
        logger.info("Evaluating baseline model: %s", args.baseline)
        baseline_model = joblib.load(args.baseline)
        baseline_rps, baseline_brier, baseline_draw_f1 = _model_walk_forward_metrics(baseline_model, df.copy())

        logger.info("Evaluating candidate model: %s", args.candidate)
        candidate_model = joblib.load(args.candidate)
        candidate_rps, candidate_brier, candidate_draw_f1 = _model_walk_forward_metrics(candidate_model, df.copy())

        logger.info(
            "Baseline: rps=%.4f brier=%.4f draw_f1=%.4f",
            baseline_rps, baseline_brier, baseline_draw_f1,
        )
        logger.info(
            "Candidate: rps=%.4f brier=%.4f draw_f1=%.4f",
            candidate_rps, candidate_brier, candidate_draw_f1,
        )

    improvement = (
        candidate_rps <= baseline_rps
        and candidate_brier <= baseline_brier
        and candidate_draw_f1 >= baseline_draw_f1
    ) if args.baseline and args.candidate else False

    report = ExpansionReport(
        date=date_str,
        data_path=str(args.data),
        n_rows=len(df),
        feature_set_baseline="phase7" if args.baseline else "n/a",
        feature_set_candidate="phase8" if args.candidate else "n/a",
        baseline_rps=round(baseline_rps, 4),
        candidate_rps=round(candidate_rps, 4),
        delta_rps=round(candidate_rps - baseline_rps, 4),
        baseline_brier=round(baseline_brier, 4),
        candidate_brier=round(candidate_brier, 4),
        delta_brier=round(candidate_brier - baseline_brier, 4),
        baseline_draw_f1=round(baseline_draw_f1, 4),
        candidate_draw_f1=round(candidate_draw_f1, 4),
        delta_draw_f1=round(candidate_draw_f1 - baseline_draw_f1, 4),
        improvement=improvement,
        shap_ablation=[asdict(r) for r in ablation_results] if ablation_results else None,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    print(
        f"[validate_expansion] "
        f"baseline_rps={report.baseline_rps:.4f} "
        f"candidate_rps={report.candidate_rps:.4f} "
        f"delta_rps={report.delta_rps:+.4f} "
        f"improvement={report.improvement} "
        f"report={args.output}"
    )
    if ablation_results:
        prune_list = [r.family for r in ablation_results if r.prune_flag]
        print(
            f"[validate_expansion] shap_ablation: {len(ablation_results)} families "
            f"prune_flagged={prune_list or 'none'}"
        )


if __name__ == "__main__":
    main()
