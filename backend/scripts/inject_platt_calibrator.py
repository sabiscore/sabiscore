"""DEBT-83 — Inject Platt/sigmoid FittedCalibrator into existing v5_phase7 artifacts.

For each shipped v5_phase7 .pkl file this script:
  1. Loads the artifact.
  2. Loads the per-league CSV training data from data/cache/fd_*.csv.
  3. Replicates the calibration/holdout split (chronological: penultimate = cal,
     last = holdout).
  4. Computes the base-learner equal-weight average on the calibration split
     (identical to what prediction.py's _ensemble_predict_dict serves).
  5. Fits a Platt/sigmoid LogisticRegression calibrator per class.
  6. Re-serializes with compress=3 under the SAME filename (backup .pre_debt83_bak first).

Usage:
    cd backend
    python scripts/inject_platt_calibrator.py [--models-dir models] [--cache-dir data/cache]
                                               [--holdout-season 2024-2025] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import gc
import logging
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("inject_platt")

_SLUG_TO_LEAGUE: Dict[str, str] = {
    "bundesliga": "BUNDESLIGA",
    "epl": "EPL",
    "eredivisie": "EREDIVISIE",
    "la_liga": "LA_LIGA",
    "ligue_1": "LIGUE_1",
    "serie_a": "SERIE_A",
}

_DIV_TO_LEAGUE: Dict[str, str] = {
    "D1": "BUNDESLIGA",
    "E0": "EPL",
    "N1": "EREDIVISIE",
    "SP1": "LA_LIGA",
    "F1": "LIGUE_1",
    "I1": "SERIE_A",
}


def _parse_date(raw: str) -> Optional[date]:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _outcome(hg: int, ag: int) -> int:
    return 0 if hg > ag else (1 if hg == ag else 2)


def _load_csv_rows(cache_dir: Path, league: str) -> List[dict]:
    rows: List[dict] = []
    for path in sorted(cache_dir.glob("fd_*.csv")):
        parts = path.stem.split("_")
        if len(parts) < 3 or _DIV_TO_LEAGUE.get(parts[1]) != league:
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                d = _parse_date(row.get("date") or row.get("Date") or "")
                hg_raw = row.get("home_goals") or row.get("FTHG") or ""
                ag_raw = row.get("away_goals") or row.get("FTAG") or ""
                if not (d and hg_raw != "" and ag_raw != ""):
                    continue
                try:
                    rows.append({"date": d, "hg": int(float(hg_raw)), "ag": int(float(ag_raw)), "_row": row})
                except (ValueError, TypeError):
                    continue
    return sorted(rows, key=lambda r: r["date"])


def _build_X_y(rows: List[dict], feature_columns: List[str]) -> Tuple[np.ndarray, np.ndarray, List[date]]:
    X_rows, y_rows, dates = [], [], []
    for r in rows:
        raw = r["_row"]
        vec = []
        for col in feature_columns:
            val = raw.get(col) or raw.get(col.upper()) or raw.get(col.lower()) or ""
            try:
                vec.append(float(val))
            except (ValueError, TypeError):
                vec.append(0.0)
        X_rows.append(vec)
        y_rows.append(_outcome(r["hg"], r["ag"]))
        dates.append(r["date"])
    if not X_rows:
        return np.empty((0, len(feature_columns)), dtype=np.float32), np.empty(0, dtype=np.int64), []
    return np.array(X_rows, dtype=np.float32), np.array(y_rows, dtype=np.int64), dates


def _season_of(d: date) -> str:
    yr = d.year
    return f"{yr}-{yr+1}" if d.month >= 8 else f"{yr-1}-{yr}"


def _chronological_masks(dates: List[date], holdout_season: str) -> Tuple[np.ndarray, np.ndarray]:
    seasons = np.array([_season_of(d) for d in dates])
    all_seasons = sorted(set(seasons.tolist()))
    if holdout_season not in all_seasons or len(all_seasons) < 2:
        n = len(dates)
        b_hold = int(n * 0.85)
        b_cal = int(n * 0.70)
        cal = np.zeros(n, dtype=bool)
        hold = np.zeros(n, dtype=bool)
        cal[b_cal:b_hold] = True
        hold[b_hold:] = True
        return cal, hold
    prior = all_seasons[all_seasons.index(holdout_season) - 1]
    return seasons == prior, seasons == holdout_season


def _fit_platt(
    models: Dict[str, Any],
    X_cal: np.ndarray,
    y_cal: np.ndarray,
    X_hold: np.ndarray,
    y_hold: np.ndarray,
    league: str,
) -> Optional[Any]:
    from src.models.calibration import FittedCalibrator, fit_calibrator, apply_calibrator, compute_ece

    try:
        proba_cal = np.mean([m.predict_proba(X_cal) for m in models.values()], axis=0).astype(np.float32)
        proba_hold = np.mean([m.predict_proba(X_hold) for m in models.values()], axis=0).astype(np.float32)

        calibrators = fit_calibrator("sigmoid", y_cal, proba_cal)
        proba_cal_after = apply_calibrator("sigmoid", calibrators, proba_cal)
        proba_hold_after = apply_calibrator("sigmoid", calibrators, proba_hold)

        ece_before = compute_ece(y_cal, proba_cal)
        ece_after  = compute_ece(y_cal, proba_cal_after)
        ece_hbefore = compute_ece(y_hold, proba_hold)
        ece_hafter  = compute_ece(y_hold, proba_hold_after)

        def _brier(yy: np.ndarray, pp: np.ndarray) -> float:
            oh = np.eye(3)[yy.astype(int)]
            return float(np.mean(np.sum((pp - oh) ** 2, axis=1)))

        bb = _brier(y_cal, proba_cal)
        ba = _brier(y_cal, proba_cal_after)

        logger.info(
            "  %-12s  n_cal=%4d  ece %.4f→%.4f  brier %.4f→%.4f  hold_ece %.4f→%.4f",
            league, len(y_cal),
            ece_before.get("mean", 0.0), ece_after.get("mean", 0.0),
            bb, ba,
            ece_hbefore.get("mean", 0.0), ece_hafter.get("mean", 0.0),
        )

        return FittedCalibrator(
            method="sigmoid",
            league=league,
            n_training_rows=int(len(y_cal)),
            calibrators=calibrators,
            ece_before=ece_before,
            ece_after=ece_after,
            brier_before=round(bb, 4),
            brier_after=round(ba, 4),
            draw_f1_before=0.0,
            draw_f1_after=0.0,
            selection_rationale=(
                "DEBT-83: Platt/sigmoid fitted on base-learner equal-weight average "
                "(the path prediction.py's _ensemble_predict_dict actually serves). "
                "Isotonic is explicitly forbidden in this certified pipeline."
            ),
        )
    except Exception as exc:
        logger.warning("  %-12s  calibrator fit failed: %s", league, exc)
        return None


def inject(artifact_path: Path, cache_dir: Path, holdout_season: str, dry_run: bool = False) -> bool:
    import joblib

    slug = artifact_path.stem.split("_ensemble_")[0]
    league = _SLUG_TO_LEAGUE.get(slug)
    if league is None:
        logger.warning("Unknown slug %r in %s — skipping", slug, artifact_path.name)
        return False

    logger.info("Processing %s  (league=%s)", artifact_path.name, league)
    bundle: Any = joblib.load(artifact_path)

    if not isinstance(bundle, dict) or "models" not in bundle:
        logger.warning("  %s is not a dict-artifact — skipping", artifact_path.name)
        return False

    if bundle.get("calibrator") is not None:
        logger.info("  %-12s  already has calibrator — skipping", league)
        return False

    feature_columns: List[str] = list(bundle.get("feature_columns") or [])
    if not feature_columns:
        logger.warning("  %-12s  no feature_columns — skipping", league)
        return False

    logger.info("  %-12s  feature_columns=%d  loading CSV …", league, len(feature_columns))
    rows = _load_csv_rows(cache_dir, league)
    if len(rows) < 200:
        logger.warning("  %-12s  insufficient CSV rows (%d) — skipping", league, len(rows))
        return False

    X, y, dates = _build_X_y(rows, feature_columns)
    del rows; gc.collect()

    if len(y) < 100:
        logger.warning("  %-12s  insufficient feature rows (%d) — skipping", league, len(y))
        return False

    cal_mask, hold_mask = _chronological_masks(dates, holdout_season)
    n_cal, n_hold = int(cal_mask.sum()), int(hold_mask.sum())
    logger.info("  %-12s  n_total=%d n_cal=%d n_hold=%d", league, len(y), n_cal, n_hold)

    if n_cal < 30 or n_hold < 10:
        logger.warning("  %-12s  too few cal/holdout rows — skipping", league)
        return False

    X_cal, y_cal = X[cal_mask], y[cal_mask]
    X_hold, y_hold = X[hold_mask], y[hold_mask]
    del X; gc.collect()

    calibrator = _fit_platt(bundle["models"], X_cal, y_cal, X_hold, y_hold, league)
    del X_cal, X_hold, y_cal, y_hold; gc.collect()

    if calibrator is None:
        return False

    bundle["calibrator"] = calibrator
    bundle.setdefault("model_metadata", {})
    bundle["model_metadata"]["calibration_method"] = "sigmoid"
    bundle["model_metadata"]["calibration_applied_at_serving"] = True
    bundle["model_metadata"]["debt83_resolved_at"] = datetime.utcnow().isoformat() + "Z"

    if dry_run:
        logger.info("  %-12s  [DRY RUN] would write → %s", league, artifact_path.name)
        return True

    backup = artifact_path.with_suffix(".pkl.pre_debt83_bak")
    if not backup.exists():
        shutil.copy2(artifact_path, backup)
        logger.info("  %-12s  backup → %s", league, backup.name)

    import joblib as _jl
    _jl.dump(bundle, artifact_path, compress=3)
    logger.info("  %-12s  ✓ calibrator injected → %s (compress=3)", league, artifact_path.name)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="DEBT-83: inject Platt calibrator into v5_phase7 artifacts")
    ap.add_argument("--models-dir", type=Path, default=Path("models"))
    ap.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    ap.add_argument("--holdout-season", default="2024-2025")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    models_dir = Path(args.models_dir).resolve()
    cache_dir = Path(args.cache_dir).resolve()

    if not models_dir.exists():
        logger.error("models-dir not found: %s", models_dir)
        return 1
    if not cache_dir.exists():
        logger.error("cache-dir not found: %s", cache_dir)
        return 1

    pkls = [p for p in sorted(models_dir.glob("*_ensemble_*.pkl")) if ".pre_debt83_bak" not in p.name]
    pkls += [p for p in sorted(models_dir.glob("*_ensemble_*.joblib")) if ".pre_debt83_bak" not in p.name]

    if not pkls:
        logger.error("No artifact files found under %s", models_dir)
        return 1

    logger.info("Found %d artifacts to process", len(pkls))
    ok = 0
    for path in pkls:
        if inject(path, cache_dir, args.holdout_season, dry_run=args.dry_run):
            ok += 1
        gc.collect()

    logger.info("\nDEBT-83: %d/%d artifacts injected successfully.", ok, len(pkls))
    if args.dry_run:
        logger.info("Dry-run mode — no files written.")
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
