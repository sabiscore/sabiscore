"""
Baseline evaluator using walk-forward temporal splits.

Usage:
  python backend/scripts/evaluate_baseline.py \
    --model backend/models/epl_ensemble_v5_phase7.pkl \
    --data backend/data/processed \
    --output docs/baseline-metrics-YYYYMMDD.json \
    --walk-forward
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Iterable, Tuple
import sys

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

# Ensure script runs from both repo root and backend/ working directories.
SCRIPT_PATH = Path(__file__).resolve()
BACKEND_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = SCRIPT_PATH.parents[2]
SRC_ROOT = BACKEND_ROOT / "src"
for candidate in (str(SRC_ROOT), str(BACKEND_ROOT), str(REPO_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def _load_symbol(module_path: Path, symbol_name: str):
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module spec: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, symbol_name)


expected_calibration_error = _load_symbol(
    BACKEND_ROOT / "src" / "models" / "evaluation" / "metrics.py",
    "expected_calibration_error",
)
walk_forward_splits = _load_symbol(
    BACKEND_ROOT / "src" / "models" / "evaluation" / "temporal_splits.py",
    "walk_forward_splits",
)

TARGET_COL = "result"
DATE_COL = "match_date"
LEAGUE_COL = "league"
DROP_FEATURE_COLS = {
    TARGET_COL,
    DATE_COL,
    LEAGUE_COL,
    "match_id",
    "home_team",
    "away_team",
    "home_team_id",
    "away_team_id",
}


def _load_dataset(path: Path) -> pd.DataFrame:
    if path.is_file():
        if path.suffix == ".parquet":
            return pd.read_parquet(path)
        if path.suffix in {".csv", ".txt"}:
            return pd.read_csv(path)
        raise ValueError(f"Unsupported data file format: {path}")

    if not path.is_dir():
        raise ValueError(f"Data path does not exist: {path}")

    parquet_files = sorted(path.rglob("*.parquet"))
    csv_files = sorted(path.rglob("*.csv"))
    files = parquet_files + csv_files
    if not files:
        raise ValueError(f"No parquet/csv files found under: {path}")

    frames = []
    for file in files:
        if file.suffix == ".parquet":
            frames.append(pd.read_parquet(file))
        else:
            frames.append(pd.read_csv(file))

    return pd.concat(frames, axis=0, ignore_index=True)


def _normalize_target(y: pd.Series) -> Tuple[np.ndarray, int]:
    if y.dtype.kind in {"i", "u", "f"}:
        y_int = y.astype(int).to_numpy()
        classes = sorted(set(y_int.tolist()))
        draw_class = 1 if 1 in classes else classes[len(classes) // 2]
        return y_int, int(draw_class)

    raw = y.astype(str).str.strip().str.lower()
    mapping = {
        "home_win": 0,
        "h": 0,
        "0": 0,
        "draw": 1,
        "d": 1,
        "1": 1,
        "away_win": 2,
        "a": 2,
        "2": 2,
    }
    mapped = raw.map(mapping)
    if mapped.isna().any():
        unknown = sorted(set(raw[mapped.isna()].tolist()))
        raise ValueError(f"Unmapped target labels found: {unknown}")
    return mapped.astype(int).to_numpy(), 1


def _select_features(df: pd.DataFrame, model: object) -> pd.DataFrame:
    feature_columns = None
    if hasattr(model, "feature_columns"):
        feature_columns = list(getattr(model, "feature_columns"))
    elif hasattr(model, "feature_names_in_"):
        feature_columns = list(getattr(model, "feature_names_in_"))

    if feature_columns:
        missing = [c for c in feature_columns if c not in df.columns]
        if missing:
            raise ValueError(f"Dataset missing model feature columns: {missing[:10]}")
        return df[feature_columns]

    cols = [c for c in df.columns if c not in DROP_FEATURE_COLS]
    X = df[cols].copy()
    numeric_cols = X.select_dtypes(include=[np.number]).columns
    if len(numeric_cols) == 0:
        raise ValueError("No numeric feature columns available for evaluation")
    return X[numeric_cols]


def _multiclass_brier(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    return float(
        np.mean(
            [
                brier_score_loss((y_true == c).astype(float), y_proba[:, c])
                for c in range(y_proba.shape[1])
            ]
        )
    )


def _compute_rps(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    """Ranked Probability Score (Epstein 1969). Lower is better.

    Class ordering must be home=0, draw=1, away=2.
    """
    n_classes = y_proba.shape[1]
    y_onehot = np.eye(n_classes, dtype=float)[y_true.astype(int)]
    cdf_pred = np.cumsum(y_proba, axis=1)[:, :-1]
    cdf_true = np.cumsum(y_onehot, axis=1)[:, :-1]
    return float(np.mean(np.sum((cdf_pred - cdf_true) ** 2, axis=1) / (n_classes - 1)))


def _league_breakdown(
    leagues: Iterable[str], y_true: np.ndarray, y_pred: np.ndarray, y_proba: np.ndarray
) -> dict:
    out: dict = {}
    arr_leagues = np.asarray(list(leagues))
    for league in sorted(set(arr_leagues.tolist())):
        mask = arr_leagues == league
        if mask.sum() == 0:
            continue
        out[str(league)] = {
            "matches": int(mask.sum()),
            "accuracy": float((y_pred[mask] == y_true[mask]).mean()),
            "log_loss": float(log_loss(y_true[mask], y_proba[mask])),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        required=True,
        help="Mandatory flag to prevent accidental random CV",
    )
    args = parser.parse_args()

    model_path = Path(args.model)
    data_path = Path(args.data)
    output_path = Path(args.output)

    if not model_path.exists():
        raise ValueError(f"Model file not found: {model_path}")

    df = _load_dataset(data_path)
    if TARGET_COL not in df.columns or DATE_COL not in df.columns:
        raise ValueError(
            f"Dataset must include '{TARGET_COL}' and '{DATE_COL}' columns"
        )

    model = joblib.load(model_path)
    X = _select_features(df, model)
    y_all, draw_class = _normalize_target(df[TARGET_COL])

    all_preds = []
    all_true = []
    all_leagues = []
    per_season = {}

    for split in walk_forward_splits(df[[DATE_COL]].join(X).join(df[[TARGET_COL]]), date_col=DATE_COL):
        X_val = X.loc[split.val_idx]
        y_val = y_all[split.val_idx]

        proba = model.predict_proba(X_val)
        pred = np.argmax(proba, axis=1)

        all_preds.append(proba)
        all_true.append(y_val)
        if LEAGUE_COL in df.columns:
            all_leagues.extend(df.loc[split.val_idx, LEAGUE_COL].astype(str).tolist())

        per_season[split.season_label] = {
            "matches": int(len(y_val)),
            "accuracy": float((pred == y_val).mean()),
            "log_loss": float(log_loss(y_val, proba)),
        }

    if not all_preds:
        raise ValueError("No walk-forward folds were produced for evaluation")

    p_all = np.vstack(all_preds)
    y_eval = np.concatenate(all_true)
    y_pred = np.argmax(p_all, axis=1)

    draw_prec = float(
        precision_score(y_eval, y_pred, labels=[draw_class], average="micro", zero_division=0)
    )
    draw_rec = float(
        recall_score(y_eval, y_pred, labels=[draw_class], average="micro", zero_division=0)
    )
    draw_f1 = (
        2 * draw_prec * draw_rec / (draw_prec + draw_rec)
        if (draw_prec + draw_rec) > 0
        else 0.0
    )
    results = {
        "accuracy_overall": float((y_pred == y_eval).mean()),
        "log_loss": float(log_loss(y_eval, p_all)),
        "brier_score": _multiclass_brier(y_eval, p_all),
        "rps": _compute_rps(y_eval, p_all),
        "macro_f1": float(f1_score(y_eval, y_pred, average="macro", zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y_eval, y_pred)),
        "ece": expected_calibration_error(y_eval, p_all),
        "draw_precision": draw_prec,
        "draw_recall": draw_rec,
        "draw_f1": draw_f1,
        "per_season": per_season,
    }

    if all_leagues:
        results["per_league"] = _league_breakdown(all_leagues, y_eval, y_pred, p_all)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    ece = results["ece"]
    print(
        "[baseline] "
        f"accuracy={results['accuracy_overall']:.4f} "
        f"ll={results['log_loss']:.4f} "
        f"brier={results['brier_score']:.4f} "
        f"rps={results['rps']:.4f} "
        f"macro_f1={results['macro_f1']:.4f} "
        f"bal_acc={results['balanced_accuracy']:.4f} "
        f"ece_mean={ece['mean']:.4f} "
        f"draw_prec={results['draw_precision']:.4f} "
        f"draw_recall={results['draw_recall']:.4f} "
        f"draw_f1={results['draw_f1']:.4f}"
    )
    print("[baseline] NOTE: evaluation used walk-forward temporal splits only — no random k-fold CV")
    print(f"[baseline] report written to {output_path}")


if __name__ == "__main__":
    main()
