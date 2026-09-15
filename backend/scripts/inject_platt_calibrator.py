"""DEBT-83 — inject a serialized Platt calibrator into served artifacts.

The calibrator is fitted on the EXACT probability vector produced by the
artifact's serving head:

    base learners -> meta_model (when present) -> calibrator -> response

If no meta_model is present, the canonical equal-weight base-learner average
is the served head.  This prevents the previous fit/serve domain mismatch in
which calibration was fitted on the base average while inference first ran a
SoftmaxMetaModel and then calibrated its output.

The script is intentionally fail-closed.  It refuses to inject a calibrator
when the served head cannot be reproduced, returns an invalid simplex, or the
chronological calibration/holdout split is too small.
"""
from __future__ import annotations

import argparse
import csv
import gc
import logging
import shutil
import sys
from datetime import date, datetime, timezone
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


def _valid_probability_matrix(probabilities: np.ndarray) -> bool:
    values = np.asarray(probabilities, dtype=np.float64)
    return bool(
        values.shape[1] == 3
        and np.isfinite(values).all()
        and np.all(values >= 0.0)
        and np.all(values <= 1.0)
        and np.allclose(values.sum(axis=1), 1.0, atol=1e-6, rtol=0.0)
    )


def _build_meta_features(models: Dict[str, Any], X: np.ndarray) -> np.ndarray:
    """Exactly reproduce PredictionEngine._build_meta_features ordering."""
    columns: List[np.ndarray] = []
    for model in models.values():
        probs = np.asarray(model.predict_proba(X), dtype=np.float64)
        if probs.ndim != 2 or probs.shape[1] < 3:
            raise ValueError("base learner returned fewer than three classes")
        columns.extend((probs[:, 0:1], probs[:, 1:2], probs[:, 2:3]))
    if not columns:
        raise ValueError("artifact contains no base learners")
    return np.hstack(columns)


def _served_probabilities(bundle: Dict[str, Any], X: np.ndarray) -> Tuple[np.ndarray, str, str]:
    """Return the exact probability domain used by PredictionEngine.

    Returns ``(probabilities, serving_head, feature_domain)``.  The serving
    head is either ``meta_model`` or ``base_equal_weight``.  The latter is only
    valid when the artifact has no meta-model; it is never used to calibrate an
    artifact that will serve a meta-model output.
    """
    models = bundle.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError("artifact has no models dictionary")

    meta_model = bundle.get("meta_model")
    if meta_model is not None:
        meta_features = _build_meta_features(models, X)
        proba = np.asarray(meta_model.predict_proba(meta_features), dtype=np.float64)
        head = type(meta_model).__name__
        if not _valid_probability_matrix(proba):
            raise ValueError(f"meta_model {head} returned an invalid probability simplex")
        return proba, "meta_model", head

    probabilities = [np.asarray(model.predict_proba(X), dtype=np.float64) for model in models.values()]
    if any(not _valid_probability_matrix(p) for p in probabilities):
        raise ValueError("base learner returned an invalid probability simplex")
    proba = np.mean(probabilities, axis=0)
    if not _valid_probability_matrix(proba):
        raise ValueError("base equal-weight average is not a valid probability simplex")
    return proba, "base_equal_weight", "base_learners"


def _fit_platt(
    bundle: Dict[str, Any],
    X_cal: np.ndarray,
    y_cal: np.ndarray,
    X_hold: np.ndarray,
    y_hold: np.ndarray,
    league: str,
    *,
    calibration_start: date,
    calibration_end: date,
    holdout_start: date,
    holdout_end: date,
) -> Optional[Any]:
    from src.models.calibration import FittedCalibrator, apply_calibrator, compute_ece, fit_calibrator

    try:
        proba_cal, serving_head, serving_domain = _served_probabilities(bundle, X_cal)
        proba_hold, hold_head, _ = _served_probabilities(bundle, X_hold)
        if hold_head != serving_domain and serving_head == "meta_model":
            raise ValueError("serving head changed between calibration and holdout")

        method = "sigmoid"
        calibrators = fit_calibrator(method, y_cal.astype(np.int64), proba_cal)
        proba_cal_after = apply_calibrator(method, calibrators, proba_cal)
        proba_hold_after = apply_calibrator(method, calibrators, proba_hold)

        if not _valid_probability_matrix(proba_cal_after) or not _valid_probability_matrix(proba_hold_after):
            raise ValueError("calibrator returned an invalid probability simplex")

        ece_before = compute_ece(y_cal, proba_cal)
        ece_after = compute_ece(y_cal, proba_cal_after)
        ece_hbefore = compute_ece(y_hold, proba_hold)
        ece_hafter = compute_ece(y_hold, proba_hold_after)

        def _brier(yy: np.ndarray, pp: np.ndarray) -> float:
            oh = np.eye(3)[yy.astype(int)]
            return float(np.mean(np.sum((pp - oh) ** 2, axis=1)))

        bb = _brier(y_cal, proba_cal)
        ba = _brier(y_cal, proba_cal_after)
        logger.info(
            "[DEBT-83] %-12s head=%s method=%s n_cal=%d ece %.4f→%.4f "
            "brier %.4f→%.4f hold_ece %.4f→%.4f",
            league, serving_domain, method, len(y_cal),
            ece_before["mean"], ece_after["mean"], bb, ba,
            ece_hbefore["mean"], ece_hafter["mean"],
        )

        return FittedCalibrator(
            method=method,
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
                "DEBT-83 canonical serve-domain calibration: Platt/sigmoid fitted "
                f"on the exact {serving_head} output ({serving_domain}), then "
                "serialized under artifact['calibrator']. The inference engine "
                "must apply this calibrator to that same probability domain. "
                "Chronological calibration/holdout separation is preserved."
            ),
            method_comparison={
                "selected": "sigmoid",
                "selection_policy": "DEBT-83 production Platt calibration",
                "serving_head": serving_head,
                "serving_domain": serving_domain,
                "class_order": ["home", "draw", "away"],
                "calibration_rows": int(len(y_cal)),
                "holdout_rows": int(len(y_hold)),
                "calibration_period": [calibration_start.isoformat(), calibration_end.isoformat()],
                "holdout_period": [holdout_start.isoformat(), holdout_end.isoformat()],
                "holdout_ece_before": ece_hbefore,
                "holdout_ece_after": ece_hafter,
            },
        )
    except Exception as exc:
        logger.warning("[DEBT-83] %-12s calibrator fit failed: %s", league, exc)
        return None


def inject(artifact_path: Path, cache_dir: Path, holdout_season: str, dry_run: bool = False) -> bool:
    import joblib

    slug = artifact_path.stem.split("_ensemble_")[0]
    league = _SLUG_TO_LEAGUE.get(slug)
    if league is None:
        logger.warning("Unknown slug %r in %s — skipping", slug, artifact_path.name)
        return False

    logger.info("Processing %s (league=%s)", artifact_path.name, league)
    bundle: Any = joblib.load(artifact_path)
    if not isinstance(bundle, dict) or "models" not in bundle:
        logger.warning("%s is not a dict-artifact — skipping", artifact_path.name)
        return False
    if bundle.get("calibrator") is not None:
        logger.info("%s already has calibrator — skipping", artifact_path.name)
        return False

    feature_columns: List[str] = list(bundle.get("feature_columns") or [])
    if not feature_columns:
        logger.warning("%s has no feature_columns — skipping", artifact_path.name)
        return False

    rows = _load_csv_rows(cache_dir, league)
    if len(rows) < 200:
        logger.warning("%s has insufficient CSV rows (%d) — skipping", league, len(rows))
        return False
    X, y, dates = _build_X_y(rows, feature_columns)
    del rows
    gc.collect()
    if len(y) < 100:
        logger.warning("%s has insufficient feature rows (%d) — skipping", league, len(y))
        return False

    cal_mask, hold_mask = _chronological_masks(dates, holdout_season)
    n_cal, n_hold = int(cal_mask.sum()), int(hold_mask.sum())
    if n_cal < 30 or n_hold < 10:
        logger.warning("%s has too few calibration/holdout rows (%d/%d) — skipping", league, n_cal, n_hold)
        return False

    cal_dates = [d for d, flag in zip(dates, cal_mask) if flag]
    hold_dates = [d for d, flag in zip(dates, hold_mask) if flag]
    X_cal, y_cal = X[cal_mask], y[cal_mask]
    X_hold, y_hold = X[hold_mask], y[hold_mask]
    del X
    gc.collect()

    calibrator = _fit_platt(
        bundle,
        X_cal,
        y_cal,
        X_hold,
        y_hold,
        league,
        calibration_start=min(cal_dates),
        calibration_end=max(cal_dates),
        holdout_start=min(hold_dates),
        holdout_end=max(hold_dates),
    )
    del X_cal, X_hold, y_cal, y_hold
    gc.collect()
    if calibrator is None:
        return False

    bundle["calibrator"] = calibrator
    metadata = bundle.setdefault("model_metadata", {})
    metadata.update(
        {
            "calibration_method": "sigmoid",
            "calibration_applied_at_serving": True,
            "calibration_input_domain": calibrator.method_comparison["serving_domain"],
            "calibration_serving_head": calibrator.method_comparison["serving_head"],
            "calibration_class_order": ["home", "draw", "away"],
            "debt83_status": "RESOLVED_PENDING_CERTIFICATION",
            "debt83_resolved_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    if dry_run:
        logger.info("[DRY RUN] would write %s", artifact_path.name)
        return True

    backup = artifact_path.with_suffix(".pkl.pre_debt83_bak")
    if not backup.exists():
        shutil.copy2(artifact_path, backup)
    joblib.dump(bundle, artifact_path, compress=3)
    logger.info("%s: serialized canonical DEBT-83 calibrator", artifact_path.name)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="DEBT-83: inject canonical served-domain Platt calibrators")
    ap.add_argument("--models-dir", type=Path, default=Path("models"))
    ap.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    ap.add_argument("--holdout-season", default="2024-2025")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    models_dir = args.models_dir.resolve()
    cache_dir = args.cache_dir.resolve()
    if not models_dir.exists() or not cache_dir.exists():
        logger.error("models-dir and cache-dir must both exist")
        return 1

    pkls = [
        p for p in sorted(models_dir.glob("*_ensemble_*.pkl"))
        if ".pre_debt83_bak" not in p.name
    ]
    pkls += [
        p for p in sorted(models_dir.glob("*_ensemble_*.joblib"))
        if ".pre_debt83_bak" not in p.name
    ]
    if not pkls:
        logger.error("No ensemble artifacts found under %s", models_dir)
        return 1

    ok = 0
    for path in pkls:
        if inject(path, cache_dir, args.holdout_season, dry_run=args.dry_run):
            ok += 1
        gc.collect()
    logger.info("DEBT-83: %d/%d artifacts processed successfully", ok, len(pkls))
    return 0 if ok == len(pkls) else 1


if __name__ == "__main__":
    sys.exit(main())
