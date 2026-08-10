"""Phase 8 baseline evaluator — RPS, Macro-F1, balanced_accuracy, and draw-F1 gates.

Usage
-----
# Standard evaluation
python backend/scripts/evaluate_baseline_v8.py \\
  --model backend/models/epl_ensemble_v6_phase8_20260610.pkl \\
  --data backend/data/processed \\
  --output docs/baseline-v8-YYYYMMDD.json \\
  --walk-forward

# Compare against a previous baseline report
python backend/scripts/evaluate_baseline_v8.py \\
  --model backend/models/epl_ensemble_v6_phase8_20260610.pkl \\
  --data backend/data/processed \\
  --output docs/baseline-v8-YYYYMMDD.json \\
  --walk-forward \\
  --baseline-report docs/baseline-v8-20260601.json

Gates (all must pass for RELEASE READY verdict)
  aggregate_rps            ≤ 0.210
  draw_f1_delta            ≥ 0.0   (must not degrade vs. baseline report, if provided)
  balanced_accuracy_delta  ≥ 0.0   (must not degrade vs. baseline, if provided)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
)

# ── path bootstrap ────────────────────────────────────────────────────────────
SCRIPT_PATH = Path(__file__).resolve()
BACKEND_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = SCRIPT_PATH.parents[2]
SRC_ROOT = BACKEND_ROOT / "src"
for _p in (str(SRC_ROOT), str(BACKEND_ROOT), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from models.evaluation.metrics import expected_calibration_error  # noqa: E402
from models.evaluation.temporal_splits import walk_forward_splits  # noqa: E402
from models.feature_registry import (  # noqa: E402
    DEFAULT_FEATURE_VALUES_86,
    PHASE7_FEATURES_ALWAYS_DATA_GAP,
)

# ── constants ─────────────────────────────────────────────────────────────────
TARGET_COL = "result"
DATE_COL = "match_date"
LEAGUE_COL = "league"
DROP_COLS = {TARGET_COL, DATE_COL, LEAGUE_COL, "match_id", "home_team", "away_team",
             "home_team_id", "away_team_id"}

RPS_GATE = 0.210

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("evaluate_baseline_v8")


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


# ── data helpers ──────────────────────────────────────────────────────────────

def _load_dataset(path: Path) -> pd.DataFrame:
    if path.is_file():
        return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    if not path.is_dir():
        raise ValueError(f"Data path does not exist: {path}")
    files = sorted(path.rglob("*.parquet")) + sorted(path.rglob("*.csv"))
    if not files:
        raise ValueError(f"No parquet/csv files under {path}")
    frames = [pd.read_parquet(f) if f.suffix == ".parquet" else pd.read_csv(f) for f in files]
    return pd.concat(frames, ignore_index=True)


def _normalize_target(y: pd.Series) -> Tuple[np.ndarray, int]:
    if y.dtype.kind in {"i", "u", "f"}:
        y_int = y.astype(int).to_numpy()
        classes = sorted(set(y_int.tolist()))
        draw_class = 1 if 1 in classes else classes[len(classes) // 2]
        return y_int, int(draw_class)
    mapping = {
        "home_win": 0, "h": 0, "0": 0,
        "draw": 1, "d": 1, "1": 1,
        "away_win": 2, "a": 2, "2": 2,
    }
    mapped = y.astype(str).str.strip().str.lower().map(mapping)
    if mapped.isna().any():
        unknown = sorted(set(y[mapped.isna()].astype(str).tolist()))
        raise ValueError(f"Unmapped target labels: {unknown}")
    return mapped.astype(int).to_numpy(), 1


def _select_features(df: pd.DataFrame, model: object) -> pd.DataFrame:
    feature_cols: Optional[List[str]] = None
    if hasattr(model, "feature_columns"):
        feature_cols = list(model.feature_columns)
    elif hasattr(model, "feature_names_in_"):
        feature_cols = list(model.feature_names_in_)

    if feature_cols:
        missing = [c for c in feature_cols if c not in df.columns]
        for c in missing:
            df[c] = DEFAULT_FEATURE_VALUES_86.get(c, 0.0)
        for c in PHASE7_FEATURES_ALWAYS_DATA_GAP:
            if c in df.columns:
                df[c] = DEFAULT_FEATURE_VALUES_86.get(c, 0.0)
        return df[feature_cols]

    cols = [c for c in df.columns if c not in DROP_COLS]
    X = df[cols].copy()
    numeric = X.select_dtypes(include=[np.number]).columns
    if len(numeric) == 0:
        raise ValueError("No numeric feature columns found")
    return X[numeric]


# ── per-league summary ────────────────────────────────────────────────────────

def _league_breakdown(
    leagues: Iterable[str],
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_proba: np.ndarray,
) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    arr = np.asarray(list(leagues))
    for league in sorted(set(arr.tolist())):
        mask = arr == league
        if mask.sum() == 0:
            continue
        yt = y_true[mask]
        yp = y_pred[mask]
        ypr = y_proba[mask]
        draw_prec = float(precision_score(yt, yp, labels=[1], average="micro", zero_division=0))
        draw_rec = float(recall_score(yt, yp, labels=[1], average="micro", zero_division=0))
        draw_f1 = (
            2 * draw_prec * draw_rec / (draw_prec + draw_rec)
            if (draw_prec + draw_rec) > 0 else 0.0
        )
        out[str(league)] = {
            "matches": int(mask.sum()),
            "accuracy": float((yp == yt).mean()),
            "log_loss": float(log_loss(yt, ypr)),
            "rps": _compute_rps(yt, ypr),
            "brier": _multiclass_brier(yt, ypr),
            "macro_f1": float(f1_score(yt, yp, average="macro", zero_division=0)),
            "balanced_accuracy": float(balanced_accuracy_score(yt, yp)),
            "draw_precision": draw_prec,
            "draw_recall": draw_rec,
            "draw_f1": round(draw_f1, 4),
        }
    return out


# ── gate validation ───────────────────────────────────────────────────────────

def _validate_report(
    results: dict,
    baseline_report: Optional[dict],
) -> Tuple[bool, List[str]]:
    """Check all release gates. Returns (passed, list_of_failures)."""
    failures: List[str] = []

    # Gate 1: aggregate RPS
    agg_rps = results.get("rps", 1.0)
    if agg_rps > RPS_GATE:
        failures.append(f"rps={agg_rps:.4f} exceeds gate {RPS_GATE:.3f}")

    if baseline_report:
        baseline_rps = baseline_report.get("rps", 0.0)
        if agg_rps > baseline_rps:
            failures.append(
                f"rps regression: current={agg_rps:.4f} > baseline={baseline_rps:.4f}"
            )

        # Gate 2: draw_f1 must not degrade
        baseline_draw_f1 = baseline_report.get("draw_f1", 0.0)
        current_draw_f1 = results.get("draw_f1", 0.0)
        if current_draw_f1 < baseline_draw_f1:
            failures.append(
                f"draw_f1 regression: current={current_draw_f1:.4f} < baseline={baseline_draw_f1:.4f}"
            )

        # Gate 3: balanced_accuracy must not degrade
        baseline_bal = baseline_report.get("balanced_accuracy", 0.0)
        current_bal = results.get("balanced_accuracy", 0.0)
        if current_bal < baseline_bal:
            failures.append(
                f"balanced_accuracy regression: current={current_bal:.4f} < baseline={baseline_bal:.4f}"
            )

    return len(failures) == 0, failures


# ── per-league delta report ───────────────────────────────────────────────────

def _build_delta_report(
    current_per_league: Dict[str, dict],
    baseline_per_league: Optional[Dict[str, dict]],
) -> Dict[str, dict]:
    if not baseline_per_league:
        return {}
    deltas: Dict[str, dict] = {}
    for league, curr in current_per_league.items():
        base = baseline_per_league.get(league)
        if base is None:
            continue
        deltas[league] = {
            k: round(curr.get(k, 0.0) - base.get(k, 0.0), 4)
            for k in ("accuracy", "log_loss", "rps", "brier", "macro_f1",
                      "balanced_accuracy", "draw_f1")
        }
    return deltas


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 8 baseline evaluator")
    parser.add_argument("--model", required=True, help="Model pickle path")
    parser.add_argument("--data", required=True, help="Training data path or directory")
    parser.add_argument("--output", required=True, help="Output JSON report path")
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        required=True,
        help="Mandatory — confirms temporal walk-forward evaluation (no random k-fold)",
    )
    parser.add_argument(
        "--baseline-report",
        type=Path,
        default=None,
        help="Path to a prior baseline JSON report for regression gating",
    )
    parser.add_argument(
        "--phase",
        default="8",
        help="Phase label to embed in the output report (default: 8)",
    )
    args = parser.parse_args()

    model_path = Path(args.model)
    data_path = Path(args.data)
    output_path = Path(args.output)

    if not model_path.exists():
        raise ValueError(f"Model file not found: {model_path}")

    df = _load_dataset(data_path)
    if TARGET_COL not in df.columns or DATE_COL not in df.columns:
        raise ValueError(f"Dataset must include '{TARGET_COL}' and '{DATE_COL}'")

    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")
    df = df.dropna(subset=[TARGET_COL, DATE_COL]).reset_index(drop=True)

    model = joblib.load(model_path)
    X = _select_features(df, model)
    y_all, draw_class = _normalize_target(df[TARGET_COL])

    all_preds: List[np.ndarray] = []
    all_true: List[np.ndarray] = []
    all_leagues: List[str] = []
    per_season: Dict[str, dict] = {}

    for split in walk_forward_splits(
        df[[DATE_COL]].join(X).join(df[[TARGET_COL]]),
        date_col=DATE_COL,
    ):
        X_val = X.loc[split.val_idx]
        y_val = y_all[split.val_idx]

        proba = model.predict_proba(X_val)
        pred = np.argmax(proba, axis=1)

        rps_fold = _compute_rps(y_val, proba)
        macro_f1_fold = float(f1_score(y_val, pred, average="macro", zero_division=0))

        all_preds.append(proba)
        all_true.append(y_val)
        if LEAGUE_COL in df.columns:
            all_leagues.extend(df.loc[split.val_idx, LEAGUE_COL].astype(str).tolist())

        per_season[split.season_label] = {
            "matches": int(len(y_val)),
            "accuracy": float((pred == y_val).mean()),
            "log_loss": float(log_loss(y_val, proba)),
            "rps": rps_fold,
            "macro_f1": macro_f1_fold,
        }

    if not all_preds:
        raise ValueError("No walk-forward folds produced — need ≥4 seasons of data")

    p_all = np.vstack(all_preds)
    y_eval = np.concatenate(all_true)
    y_pred = np.argmax(p_all, axis=1)

    rps = _compute_rps(y_eval, p_all)
    brier = _multiclass_brier(y_eval, p_all)
    ece = expected_calibration_error(y_eval, p_all)
    macro_f1 = float(f1_score(y_eval, y_pred, average="macro", zero_division=0))
    bal_acc = float(balanced_accuracy_score(y_eval, y_pred))
    draw_prec = float(precision_score(y_eval, y_pred, labels=[draw_class], average="micro", zero_division=0))
    draw_rec = float(recall_score(y_eval, y_pred, labels=[draw_class], average="micro", zero_division=0))
    draw_f1 = (
        round(2 * draw_prec * draw_rec / (draw_prec + draw_rec), 4)
        if (draw_prec + draw_rec) > 0 else 0.0
    )

    results: dict = {
        "phase": args.phase,
        "model": str(model_path),
        "data": str(data_path),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "n_val_samples": int(len(y_eval)),
        "accuracy_overall": float((y_pred == y_eval).mean()),
        "log_loss": float(log_loss(y_eval, p_all)),
        "brier_score": brier,
        "ece": ece,
        "rps": rps,
        "macro_f1": macro_f1,
        "balanced_accuracy": bal_acc,
        "draw_precision": draw_prec,
        "draw_recall": draw_rec,
        "draw_f1": draw_f1,
        "per_season": per_season,
    }

    if all_leagues:
        results["per_league"] = _league_breakdown(all_leagues, y_eval, y_pred, p_all)

    # ── baseline comparison + delta report ────────────────────────────────
    baseline_report: Optional[dict] = None
    if args.baseline_report and args.baseline_report.exists():
        baseline_report = json.loads(args.baseline_report.read_text(encoding="utf-8"))
        results["baseline_report"] = str(args.baseline_report)
        if "per_league" in results and "per_league" in (baseline_report or {}):
            results["per_league_delta"] = _build_delta_report(
                results["per_league"],
                baseline_report.get("per_league"),
            )

    gate_passed, gate_failures = _validate_report(results, baseline_report)
    results["gates"] = {
        "rps_gate": RPS_GATE,
        "passed": gate_passed,
        "failures": gate_failures,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(
        "[baseline_v8] "
        f"accuracy={results['accuracy_overall']:.4f} "
        f"ll={results['log_loss']:.4f} "
        f"brier={brier:.4f} "
        f"rps={rps:.4f} "
        f"macro_f1={macro_f1:.4f} "
        f"bal_acc={bal_acc:.4f} "
        f"draw_f1={draw_f1:.4f} "
        f"ece={ece['mean']:.4f}"
    )
    print(f"[baseline_v8] gates={'PASS' if gate_passed else 'FAIL — ' + '; '.join(gate_failures)}")
    print("[baseline_v8] NOTE: evaluation used walk-forward temporal splits only — no random k-fold CV")
    print(f"[baseline_v8] report written to {output_path}")

    if not gate_passed:
        sys.exit(2)


if __name__ == "__main__":
    main()
