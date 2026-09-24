#!/usr/bin/env python3
"""docs/DEBT.md item 142 -- clean season-2425 selection evidence by cross-fitting.

The question
------------
Generation ``v5_phase7-20260922`` serves: base learners -> stacked meta head
(``TemperatureScaledMetaModel``; Ligue 1 ``VectorScaledMetaModel``) -> a sigmoid
``FittedCalibrator`` that was fitted on the BASE-LEARNER AVERAGE, not on that
head. Item 142 is an open operator decision about which composition to serve,
and its own note says the selection evidence must come from 2425. But 2425 is
in-sample for both post-hoc layers (scale layer and sigmoid calibrator were
fitted on it), and 2526 was already consulted by ``_select_calibrator``'s
persistence check. Neither season is clean as-is.

This script makes 2425 clean by construction: both post-hoc layers are REFIT
out-of-fold on 5 contiguous chronological blocks of 2425, so every candidate is
scored only on rows its post-hoc layers never saw. Base learners and the inner
``SoftmaxMetaModel`` were fitted on seasons <= 2324, so they are already clean
on 2425.

Measurement only. No artifact is modified and no composition is recommended.
No 2526 label is read: the ``fd_*_2526.csv`` files are never copied into the
loader's input directory, so no 2526 row is ever parsed.

Candidates (pre-registered)
---------------------------
C1 avg                  mean of the three base learners' predict_proba
C2 avg+sigmoid(cf)      C1 -> sigmoid calibrator refit out-of-fold
C3 stacked_raw          inner SoftmaxMetaModel, before temperature/vector scaling
C4 stacked+scale(cf)    C3 -> scaling layer (temperature; Ligue 1 vector) refit out-of-fold
C5 served(cf)           C4 -> sigmoid refit out-of-fold on the base-learner average
                        (the served design, including its fit/apply mismatch)
REF (IN-SAMPLE)         shipped layers applied to 2425 -- reference for the bias only

Usage (from backend/):
    PYTHONPATH=. ../.venv/Scripts/python.exe scripts/research_item142_crossfit_selection.py
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
REPO = _SCRIPTS.parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(BACKEND))

import joblib  # noqa: E402

from train_on_real_matches import (  # noqa: E402
    _LEAGUE_TO_SLUG,
    _fit_temperature,
    _fit_served_base_calibrator,
    _fit_vector_scaling,
    _schema_features,
    build_dataset,
    load_matches,
)
from src.core.meta_model import (  # noqa: E402
    SoftmaxMetaModel,
    TemperatureScaledMetaModel,
    VectorScaledMetaModel,
)
from src.models.calibration import (  # noqa: E402
    _compute_brier_multiclass,
    apply_calibrator,
    compute_ece,
    fit_calibrator,
)
from src.models.evaluation.metrics import (  # noqa: E402
    block_bootstrap_ci,
    expected_calibration_error,
    log_loss_multiclass,
    ranked_probability_score_rowwise,
)
from src.models.prediction import PredictionEngine  # noqa: E402

SEASON = "2425"
EXCLUDED_SEASON = "2526"
SCHEMA = "apex_v1_68"
N_BLOCKS = 5
N_BOOTSTRAP = 2000
SEED = 42
PARITY_ROWS = 20
PARITY_TOL = 1e-6
# block_bootstrap_ci rounds its bounds to 4 dp; paired RPS deltas are ~1e-3, so the
# statistic is scaled by 1e6 going in and unscaled coming out (1e-10 resolution).
CI_SCALE = 1e6

MODELS = BACKEND / "models"
CACHE = BACKEND / "data" / "cache"
OUT_JSON = BACKEND / "reports" / "research" / "item142-crossfit-selection-2425.json"
OUT_MD = OUT_JSON.with_suffix(".md")

C1, C2, C3, C4, C5 = (
    "C1_avg",
    "C2_avg+sigmoid(cf)",
    "C3_stacked_raw",
    "C4_stacked+scale(cf)",
    "C5_served(cf)",
)
R_SERVED = "REF_served(as-shipped)_IN-SAMPLE"
R_SCALE = "REF_stacked+scale(as-shipped)_IN-SAMPLE"
CHALLENGERS = (C1, C2, C3, C4)
ALL_COLUMNS = (C1, C2, C3, C4, C5, R_SERVED, R_SCALE)
LEAGUE_OF = {slug: league for league, slug in _LEAGUE_TO_SLUG.items()}
SHIPPED_RATIONALE = "DEBT-83: Platt/sigmoid fitted on base-learner equal-weight average"


def where(fn: Any) -> str:
    path = Path(inspect.getsourcefile(fn)).resolve().relative_to(REPO)
    return f"{path.as_posix()}:{inspect.getsourcelines(fn)[1]}"


def load_pre_holdout_matches() -> tuple[list[dict], dict]:
    """``load_matches`` over every fd_*.csv except season 2526, which is never copied."""
    files = sorted(CACHE.glob("fd_*.csv"))
    used = [p for p in files if p.stem.split("_")[2] != EXCLUDED_SEASON]
    with tempfile.TemporaryDirectory() as tmp:
        for p in used:
            shutil.copy2(p, Path(tmp) / p.name)
        matches = load_matches(Path(tmp))
    seasons = sorted({m["season"] for m in matches})
    if EXCLUDED_SEASON in seasons:
        raise SystemExit("a 2526 row reached the loader -- refusing to continue")
    return matches, {
        "method": "fd_*_2526.csv files are not copied into load_matches' input dir",
        "files_used": [p.name for p in used],
        "files_never_opened": sorted({p.name for p in files} - {p.name for p in used}),
        "seasons_loaded": seasons,
        "latest_kickoff_loaded": max(m["date"] for m in matches).date().isoformat(),
    }


def season_rows(dataset: dict, slug: str, pooled: bool):
    """The artifact's 2425 rows, in the trainer's own row order."""
    # train_pooled concatenates every league in dataset order; a dedicated
    # artifact sees only its own league.
    parts = list(dataset.values()) if pooled else [dataset[LEAGUE_OF[slug]]]
    X, y, dates = [], [], []
    for d in parts:
        for xr, yr, s, dt in zip(d["X"], d["y"], d["seasons"], d["dates"]):
            if s == SEASON:
                X.append(xr)
                y.append(yr)
                dates.append(dt)
    # train_league casts to float32; so does _run_inference.
    return np.asarray(X, dtype=np.float32), np.asarray(y, dtype=np.int64), dates


def score(y: np.ndarray, p: np.ndarray) -> dict:
    return {
        "n": int(len(y)),
        "rps": float(ranked_probability_score_rowwise(y, p).mean()),
        "log_loss": log_loss_multiclass(y, p),
        "brier": _compute_brier_multiclass(y, p),
        "ece": expected_calibration_error(y, p)["mean"],
    }


def paired_week_ci(y, p_cand, p_ref, dates) -> dict:
    """Paired RPS delta (cand - ref) with a calendar-week (ISO week) block bootstrap.

    Weeks are the resampling unit: block_bootstrap_ci runs with block_size=1 over
    per-week (sum of deltas, row count) pairs, and the statistic is the ratio of
    resampled sums -- the mean delta over the resampled rows.
    """
    d = ranked_probability_score_rowwise(y, p_cand) - ranked_probability_score_rowwise(
        y, p_ref
    )
    weeks = [dt.isocalendar()[:2] for dt in dates]
    keys = sorted(set(weeks))
    index = {k: j for j, k in enumerate(keys)}
    wk = np.asarray([index[w] for w in weeks])
    per_week = np.column_stack(
        [
            np.bincount(wk, weights=d, minlength=len(keys)) * CI_SCALE,
            np.bincount(wk, minlength=len(keys)).astype(np.float64),
        ]
    )
    ci = block_bootstrap_ci(
        np.arange(len(keys)),
        per_week,
        lambda _weeks, a: a[:, 0].sum() / a[:, 1].sum(),
        n_bootstrap=N_BOOTSTRAP,
        block_size=1,
        rng_seed=SEED,
    )
    lo, hi = ci["ci_lower"], ci["ci_upper"]
    lo = None if lo is None else lo / CI_SCALE
    hi = None if hi is None else hi / CI_SCALE
    return {
        "delta_rps": float(d.mean()),
        "ci95": [lo, hi],
        "n_rows": int(len(d)),
        "n_weeks": len(keys),
        "n_bootstrap": ci["n_bootstrap"],
        "beats_served_cf": hi is not None and hi < 0,
        "worse_than_served_cf": lo is not None and lo > 0,
    }


def crossfit(y, avg, mf, inner, fit_layer, blocks, scheme: str) -> dict:
    """Out-of-fold C2/C4/C5 for one scheme. Returns positions + probabilities."""
    n = len(y)
    c2, c4, c5 = (np.full((n, 3), np.nan) for _ in range(3))
    folds = (
        [(np.concatenate(blocks[:b] + blocks[b + 1 :]), blocks[b]) for b in range(N_BLOCKS)]
        if scheme == "kfold5"
        else [(np.concatenate(blocks[:b]), blocks[b]) for b in range(1, N_BLOCKS)]
    )
    fitted = []
    for train, test in folds:
        # Same routine that produced the shipped calibrators: fit_calibrator on the
        # float32 base-learner average (see functions_used.shipped_calibrator_fitter).
        cal = fit_calibrator("sigmoid", y[train], avg[train].astype(np.float32))
        layer = fit_layer(inner, mf[train], y[train])
        c2[test] = apply_calibrator("sigmoid", cal, avg[test])
        c4[test] = layer.predict_proba(mf[test])
        c5[test] = apply_calibrator("sigmoid", cal, c4[test])
        fitted.append(
            {
                "n_train": int(len(train)),
                "n_test": int(len(test)),
                "layer": getattr(layer, "temperature", None)
                if isinstance(layer, TemperatureScaledMetaModel)
                else {"scale": layer.scale.tolist(), "bias": layer.bias.tolist()},
                "sigmoid": [
                    [float(c.coef_.ravel()[0]), float(c.intercept_.ravel()[0])]
                    for c in cal
                ],
            }
        )
    rows = np.sort(np.concatenate([test for _, test in folds]))
    return {"rows": rows, C2: c2, C4: c4, C5: c5, "folds": fitted}


def evaluate_artifact(slug: str, entry: dict, dataset: dict) -> dict:
    path = MODELS / entry["artifact"]
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    raw = joblib.load(path)
    md = raw["model_metadata"]
    pooled = bool(md.get("pooled_fallback_for"))
    X, y, dates = season_rows(dataset, slug, pooled)
    out: dict[str, Any] = {
        "artifact": entry["artifact"],
        "artifact_sha256_matches_manifest": sha == entry["artifact_sha256"],
        "pooled_model": pooled,
        "population": (
            "pooled artifact: every league's 2425 rows in train_pooled's order "
            "(Eredivisie has no pre-2526 season, so 0 of these rows are Eredivisie)"
            if pooled
            else f"{LEAGUE_OF[slug]} 2425 rows"
        ),
    }

    rebuilt_window = {
        "start": min(dates).date().isoformat(),
        "end": max(dates).date().isoformat(),
    }
    out["row_count_check"] = {
        "rebuilt_2425_rows": int(len(y)),
        "pickle_calibration_samples": md.get("calibration_samples"),
        "pickle_calibration_season": md.get("calibration_season"),
        "rebuilt_window": rebuilt_window,
        "pickle_calibration_window": md.get("calibration_window"),
        "match": int(len(y)) == md.get("calibration_samples")
        and rebuilt_window == md.get("calibration_window")
        and md.get("calibration_season") == SEASON,
    }
    out["column_order_check"] = {
        "builder_equals_pickle_feature_columns": list(_schema_features(SCHEMA))
        == list(raw["feature_columns"]),
        "n_columns": len(raw["feature_columns"]),
        "pickle_feature_schema_version": md.get("feature_schema_version"),
    }
    if not (out["row_count_check"]["match"] and out["column_order_check"]["builder_equals_pickle_feature_columns"]):
        out["skipped"] = "2425 rebuild does not reproduce the artifact's calibration rows/columns"
        return out

    bundle = PredictionEngine._wrap_artifact(raw, slug, path)
    cal = bundle.calibrator
    meta = bundle.meta_model
    if cal is None or meta is None or bundle.overlay is not None:
        out["skipped"] = "served bundle is not stacked head + calibrator (no overlay)"
        return out
    if not isinstance(meta, (TemperatureScaledMetaModel, VectorScaledMetaModel)) or not isinstance(
        meta.base_model, SoftmaxMetaModel
    ):
        out["skipped"] = f"inner meta model not accessible ({type(meta).__name__}); C3/C4 impossible"
        return out
    inner = meta.base_model
    fit_layer = _fit_vector_scaling if isinstance(meta, VectorScaledMetaModel) else _fit_temperature
    out["served_composition"] = {
        "base_learners": list(bundle.models_dict),
        "meta_head": f"{type(meta).__name__}({type(inner).__name__})",
        "post_hoc_calibrator": f"FittedCalibrator(method={cal.method}, n_training_rows={cal.n_training_rows})",
        "calibrator_rationale_matches_shipped_fitter": str(cal.selection_rationale).startswith(
            SHIPPED_RATIONALE
        ),
    }

    models = bundle.models_dict
    avg = np.mean(  # PredictionEngine._ensemble_predict_dict's equal-weight mean
        [np.asarray(m.predict_proba(X), dtype=np.float64) for m in models.values()], axis=0
    )
    mf = PredictionEngine._build_meta_features(models, X)
    stacked_raw = inner.predict_proba(mf)
    shipped_scaled = meta.predict_proba(mf)
    shipped_served = apply_calibrator(cal.method, cal.calibrators, shipped_scaled)

    # Refitting each shipped layer on ALL 2425 rows (trainer row order) must give
    # back the shipped parameters -- proof these are the rows the layers saw.
    refit_layer = fit_layer(inner, mf, y)
    if isinstance(meta, TemperatureScaledMetaModel):
        layer_delta = abs(refit_layer.temperature - meta.temperature)
        layer_desc = {"shipped_temperature": meta.temperature, "refit_temperature": refit_layer.temperature}
    else:
        layer_delta = float(
            max(np.abs(refit_layer.scale - meta.scale).max(), np.abs(refit_layer.bias - meta.bias).max())
        )
        layer_desc = {
            "shipped_scale": meta.scale.tolist(),
            "refit_scale": refit_layer.scale.tolist(),
            "shipped_bias": meta.bias.tolist(),
            "refit_bias": refit_layer.bias.tolist(),
        }
    avg32 = avg.astype(np.float32)
    refit_cal = fit_calibrator("sigmoid", y, avg32)
    sig_delta = max(
        max(abs(float(a.coef_.ravel()[0]) - float(b.coef_.ravel()[0])), abs(float(a.intercept_.ravel()[0]) - float(b.intercept_.ravel()[0])))
        for a, b in zip(refit_cal, cal.calibrators)
    )
    out["shipped_layer_reproduction"] = {
        "scale_layer_max_abs_param_delta": layer_delta,
        **layer_desc,
        "sigmoid_max_abs_coef_or_intercept_delta": sig_delta,
        "calibrator_insample_ece_before": {"pickle": cal.ece_before.get("mean"), "rebuilt": compute_ece(y, avg32)["mean"]},
        "calibrator_insample_brier_before": {
            "pickle": cal.brier_before,
            "rebuilt": round(_compute_brier_multiclass(y, avg32), 4),
        },
    }

    # Parity: the batch reconstruction of the served composition against
    # _run_inference itself (rounds to 4 dp) and against its unrounded success path.
    rng = np.random.default_rng(SEED)
    picks = np.sort(rng.choice(len(y), size=min(PARITY_ROWS, len(y)), replace=False))
    engine = PredictionEngine()
    d_round, d_raw, labels = [], [], set()
    for i in picks:
        r = engine._run_inference(bundle, X[i], LEAGUE_OF[slug])
        served = np.array([r.home_win, r.draw, r.away_win])
        labels.add((r.calibration_method, r.model_version, r.calibration_applied))
        unrounded = apply_calibrator(
            cal.method, cal.calibrators, PredictionEngine._stacked_predict(models, meta, X[i : i + 1])
        )[0]
        d_round.append(max(abs(round(float(v), 4) - s) for v, s in zip(shipped_served[i], served)))
        d_raw.append(float(np.abs(shipped_served[i] - unrounded).max()))
    out["parity"] = {
        "rows_checked": int(len(picks)),
        "row_positions": picks.tolist(),
        "tolerance": PARITY_TOL,
        "max_abs_diff_vs_run_inference_after_same_4dp_rounding": max(d_round),
        "max_abs_diff_vs_unrounded_served_call": max(d_raw),
        "run_inference_labels": sorted(map(list, labels)),
        # A fallback or an unapplied calibrator would make the diffs meaningless.
        "passed": bool(
            max(d_round) <= PARITY_TOL
            and max(d_raw) <= PARITY_TOL
            and all(m == "sigmoid" and v != "fallback" and ok for m, v, ok in labels)
        ),
    }
    out["_arrays"] = {
        "y": y,
        "dates": dates,
        "avg": avg,
        "mf": mf,
        "inner": inner,
        "fit_layer": fit_layer,
        C1: avg,
        C3: stacked_raw,
        R_SERVED: shipped_served,
        R_SCALE: shipped_scaled,
    }
    return out


def run_schemes(out: dict) -> dict:
    a = out["_arrays"]
    y, dates = a["y"], a["dates"]
    order = sorted(range(len(y)), key=lambda i: dates[i])  # stable: ties keep trainer order
    blocks = [np.asarray(b) for b in np.array_split(np.asarray(order), N_BLOCKS)]
    out["blocks"] = [
        {
            "block": k,
            "n": int(len(b)),
            "first_kickoff": dates[b[0]].date().isoformat(),
            "last_kickoff": dates[b[-1]].date().isoformat(),
        }
        for k, b in enumerate(blocks)
    ]
    evaluated: dict[str, Any] = {}
    for scheme in ("kfold5", "forward"):
        try:
            cf = crossfit(y, a["avg"], a["mf"], a["inner"], a["fit_layer"], blocks, scheme)
        except Exception as exc:  # noqa: BLE001 - report the failed part, keep the rest
            out[scheme] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        rows = cf["rows"]
        probs = {k: (cf[k] if k in (C2, C4, C5) else a[k])[rows] for k in ALL_COLUMNS}
        yy, dd = y[rows], [dates[i] for i in rows]
        out[scheme] = {
            "rows_scored": int(len(rows)),
            "metrics": {k: score(yy, p) for k, p in probs.items()},
            "paired_rps_vs_served_cf": {
                k: paired_week_ci(yy, probs[k], probs[C5], dd) for k in CHALLENGERS
            },
            "in_sample_gap_rps": {
                "served(as-shipped) - served(cf)": score(yy, probs[R_SERVED])["rps"]
                - score(yy, probs[C5])["rps"],
                "stacked+scale(as-shipped) - stacked+scale(cf)": score(yy, probs[R_SCALE])["rps"]
                - score(yy, probs[C4])["rps"],
            },
            "folds": cf["folds"],
        }
        evaluated[scheme] = (yy, dd, probs)
    out["_scored"] = evaluated
    return out


def pooled_block(results: dict) -> dict:
    """The five dedicated artifacts, each on its own 2425 rows (Eredivisie excluded:
    its pooled model scores those same rows again)."""
    pooled: dict[str, Any] = {}
    for scheme in ("kfold5", "forward"):
        parts = [
            (slug, r["_scored"][scheme])
            for slug, r in results.items()
            if not r.get("pooled_model") and scheme in r.get("_scored", {})
        ]
        if not parts:
            continue
        yy = np.concatenate([p[0] for _, p in parts])
        dd = [dt for _, p in parts for dt in p[1]]
        probs = {k: np.vstack([p[2][k] for _, p in parts]) for k in ALL_COLUMNS}
        pooled[scheme] = {
            "artifacts": [slug for slug, _ in parts],
            "rows_scored": int(len(yy)),
            "metrics": {k: score(yy, p) for k, p in probs.items()},
            "paired_rps_vs_served_cf": {
                k: paired_week_ci(yy, probs[k], probs[C5], dd) for k in CHALLENGERS
            },
            "in_sample_gap_rps": {
                "served(as-shipped) - served(cf)": score(yy, probs[R_SERVED])["rps"]
                - score(yy, probs[C5])["rps"],
                "stacked+scale(as-shipped) - stacked+scale(cf)": score(yy, probs[R_SCALE])["rps"]
                - score(yy, probs[C4])["rps"],
            },
        }
    return pooled


def summarize(results: dict, pooled: dict) -> dict:
    summary: dict[str, Any] = {}
    for scheme in ("kfold5", "forward"):
        per = {}
        for cand in CHALLENGERS:
            beats = [s for s, r in results.items() if r.get(scheme, {}).get("paired_rps_vs_served_cf", {}).get(cand, {}).get("beats_served_cf")]
            worse = [s for s, r in results.items() if r.get(scheme, {}).get("paired_rps_vs_served_cf", {}).get(cand, {}).get("worse_than_served_cf")]
            scored = [s for s, r in results.items() if "paired_rps_vs_served_cf" in r.get(scheme, {})]
            pc = pooled.get(scheme, {}).get("paired_rps_vs_served_cf", {}).get(cand, {})
            per[cand] = {
                "beats_served_cf_ci_excludes_zero": beats,
                "worse_than_served_cf_ci_excludes_zero": worse,
                "artifacts_scored": len(scored),
                "pooled_5_dedicated_beats": pc.get("beats_served_cf"),
                "pooled_5_dedicated_worse": pc.get("worse_than_served_cf"),
            }
        summary[scheme] = per
    return summary


def write_markdown(report: dict) -> None:
    res, pooled = report["per_artifact"], report["pooled_5_dedicated"]
    rows = list(res.items()) + [("POOLED (5 dedicated)", pooled)]

    def f(x, nd=4):
        return "—" if x is None else f"{x:.{nd}f}"

    def ci_cell(c):
        if not c:
            return "—"
        lo, hi = c["ci95"]
        mark = " (beats)" if c["beats_served_cf"] else " (worse)" if c["worse_than_served_cf"] else ""
        return f"{c['delta_rps']:+.4f} [{f(lo)}, {f(hi)}]{mark}"

    lines = [
        "# Item 142 — cross-fitted season-2425 selection evidence",
        "",
        f"Generated {report['generated_at']} at `{report['git_head'][:10]}`; generation "
        f"`{report['generation']}`, schema `{SCHEMA}`. Season 2425 only; no 2526 file was opened "
        f"({', '.join(report['no_2526_labels_read']['files_never_opened'])}).",
        "",
        "Measurement only. Nothing here recommends a composition; that decision belongs to the operator.",
        "Post-hoc layers were refit out-of-fold on 5 contiguous chronological blocks of 2425; base learners "
        "and the inner SoftmaxMetaModel were fitted on seasons ≤ 2324 and are used as shipped.",
        "",
        "## Checks",
        "",
        "| artifact | 2425 rows rebuilt / pickle | columns | refit Δ scale layer | refit Δ sigmoid | parity (rounded / unrounded) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for slug, r in res.items():
        rc, rep, par = r["row_count_check"], r.get("shipped_layer_reproduction", {}), r.get("parity", {})
        lines.append(
            f"| {slug} | {rc['rebuilt_2425_rows']} / {rc['pickle_calibration_samples']} "
            f"({'match' if rc['match'] else 'MISMATCH'}) | "
            f"{'match' if r['column_order_check']['builder_equals_pickle_feature_columns'] else 'MISMATCH'} | "
            f"{rep.get('scale_layer_max_abs_param_delta', float('nan')):.1e} | "
            f"{rep.get('sigmoid_max_abs_coef_or_intercept_delta', float('nan')):.1e} | "
            f"{'pass' if par.get('passed') else 'FAIL'} "
            f"({par.get('max_abs_diff_vs_run_inference_after_same_4dp_rounding', float('nan')):.1e} / "
            f"{par.get('max_abs_diff_vs_unrounded_served_call', float('nan')):.1e}) |"
        )
    for scheme, title in (
        ("kfold5", "5-block chronological cross-fit (all 2425 rows)"),
        ("forward", "Robustness: forward expanding window (blocks 2–5 scored; block 1 only trains)"),
    ):
        lines += [
            "",
            f"## Mean RPS — {title}",
            "",
            "Lower is better. REF columns are IN-SAMPLE (shipped layers were fitted on these rows).",
            "",
            "| artifact | n | C1 avg | C2 avg+sigmoid(cf) | C3 stacked_raw | C4 stacked+scale(cf) | C5 served(cf) | REF served (in-sample) | REF stacked+scale (in-sample) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for name, r in rows:
            s = r.get(scheme, {})
            if "metrics" not in s:
                lines.append(f"| {name} | — | {s.get('error', 'not scored')} |")
                continue
            m = s["metrics"]
            lines.append(
                f"| {name} | {s['rows_scored']} | "
                + " | ".join(f(m[k]["rps"]) for k in ALL_COLUMNS)
                + " |"
            )
        lines += [
            "",
            f"ΔRPS vs C5 served(cf), candidate − C5; 95% CI from a paired calendar-week (ISO) block bootstrap, "
            f"{N_BOOTSTRAP} replicates, seed {SEED}. \"beats\" = CI entirely below zero.",
            "",
            "| artifact | C1 avg | C2 avg+sigmoid(cf) | C3 stacked_raw | C4 stacked+scale(cf) |",
            "| --- | --- | --- | --- | --- |",
        ]
        for name, r in rows:
            p = r.get(scheme, {}).get("paired_rps_vs_served_cf", {})
            lines.append(f"| {name} | " + " | ".join(ci_cell(p.get(k)) for k in CHALLENGERS) + " |")
        lines += ["", "In-sample vs cross-fitted gap (RPS, positive = in-sample looks worse):", ""]
        for name, r in rows:
            g = r.get(scheme, {}).get("in_sample_gap_rps")
            if g:
                lines.append(
                    f"- {name}: served {g['served(as-shipped) - served(cf)']:+.4f}; "
                    f"stacked+scale {g['stacked+scale(as-shipped) - stacked+scale(cf)']:+.4f}"
                )
        lines += ["", "Candidates whose CI vs served(cf) excludes zero:", ""]
        for cand, v in report["summary"][scheme].items():
            lines.append(
                f"- {cand}: beats in {len(v['beats_served_cf_ci_excludes_zero'])}/{v['artifacts_scored']} "
                f"({', '.join(v['beats_served_cf_ci_excludes_zero']) or 'none'}); worse in "
                f"{len(v['worse_than_served_cf_ci_excludes_zero'])}/{v['artifacts_scored']} "
                f"({', '.join(v['worse_than_served_cf_ci_excludes_zero']) or 'none'}); pooled beats: "
                f"{v['pooled_5_dedicated_beats']}, pooled worse: {v['pooled_5_dedicated_worse']}"
            )
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in report["caveats"]]
    lines += ["", "Full numbers (log loss, Brier, ECE, per-fold parameters): `item142-crossfit-selection-2425.json`.", ""]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    manifest = json.loads((MODELS / "active_generation.json").read_text(encoding="utf-8"))
    if manifest["feature_schema_version"] != SCHEMA:
        raise SystemExit(f"manifest serves {manifest['feature_schema_version']!r}, not {SCHEMA!r}")
    matches, provenance = load_pre_holdout_matches()
    dataset = build_dataset(matches, schema=SCHEMA)
    del matches

    results: dict[str, dict] = {}
    for slug, entry in sorted(manifest["artifacts"].items()):
        print(f"[{slug}] rebuilding 2425 and checking parity ...", flush=True)
        results[slug] = evaluate_artifact(slug, entry, dataset)

    parity_ok = all(r.get("parity", {}).get("passed") for r in results.values() if "skipped" not in r)
    if parity_ok:
        for slug, r in results.items():
            if "skipped" not in r:
                print(f"[{slug}] cross-fitting ...", flush=True)
                run_schemes(r)
    pooled = pooled_block(results) if parity_ok else {}

    git = lambda *a: subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout.strip()  # noqa: E731
    report = {
        "study": "docs/DEBT.md item 142 — cross-fitted post-hoc layers, season 2425",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_head": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "git_dirty_paths_at_run": git("status", "--porcelain").splitlines(),
        "generation": manifest["generation"],
        "feature_schema_version": SCHEMA,
        "season_evaluated": SEASON,
        "no_2526_labels_read": provenance,
        "environment": {
            "python": sys.version.split()[0],
            **{lib: importlib.metadata.version(lib) for lib in ("numpy", "scikit-learn", "xgboost", "lightgbm", "scipy")},
        },
        "design": {
            "blocks": f"{N_BLOCKS} contiguous chronological blocks per artifact (np.array_split of the kickoff-sorted rows)",
            "kfold5": "each block predicted by post-hoc layers fitted on the other 4",
            "forward": "block b (b=2..5) predicted by layers fitted on blocks < b; block 1 is never scored",
            "clean_without_refit": [C1, C3],
            "refit_out_of_fold": [C2, C4, C5],
            "C5_calibrator": "sigmoid fitted on the training blocks' base-learner average (float32), applied to C4 — the served design",
            "bootstrap": f"paired, ISO calendar-week blocks, {N_BOOTSTRAP} replicates, seed {SEED}; statistic = mean RPS delta over resampled rows",
            "parity": f"{PARITY_ROWS} random rows (seed {SEED}) per artifact vs PredictionEngine._run_inference (4 dp) and its unrounded success path; tolerance {PARITY_TOL}",
        },
        "functions_used": {
            "dataset_builder": where(build_dataset),
            "loader": where(load_matches),
            "base_average_as_served": where(PredictionEngine._ensemble_predict_dict),
            "meta_features": where(PredictionEngine._build_meta_features),
            "served_stacked_call": where(PredictionEngine._stacked_predict),
            "served_inference": where(PredictionEngine._run_inference),
            "artifact_wrapper": where(PredictionEngine._wrap_artifact),
            "inner_meta_model": where(SoftmaxMetaModel.predict_proba),
            "temperature_layer_fit": where(_fit_temperature),
            "vector_layer_fit": where(_fit_vector_scaling),
            "sigmoid_fit": where(fit_calibrator),
            "sigmoid_apply": where(apply_calibrator),
            "shipped_calibrator_fitter": (
                "backend/scripts/train_on_real_matches.py@f1be78f^:1008 _fit_served_base_calibrator "
                "(sigmoid forced; its selection_rationale string is the one every shipped calibrator "
                "carries) -> calibration.fit_calibrator('sigmoid', y, base_average.astype(float32)). "
                f"HEAD's version ({where(_fit_served_base_calibrator)}) calls compare_calibration_methods, "
                "which selects on the holdout season, so it is not used here."
            ),
            "rps": where(ranked_probability_score_rowwise),
            "log_loss": where(log_loss_multiclass),
            "brier_mean_aggregation": where(_compute_brier_multiclass),
            "ece": where(expected_calibration_error),
            "bootstrap": where(block_bootstrap_ci),
        },
        "parity_gate_passed": parity_ok,
        "per_artifact": {
            slug: {k: v for k, v in r.items() if not k.startswith("_")} for slug, r in results.items()
        },
        "pooled_5_dedicated": pooled,
        "summary": summarize(results, pooled) if parity_ok else {},
        "caveats": [
            "The scale-layer TYPE per league (temperature; vector for Ligue 1) was chosen by "
            "_select_calibrator, which consulted 2526. It is held fixed as shipped; only its "
            "parameters are refit out-of-fold here.",
            "The Eredivisie artifact is the pooled model. Its 2425 population is the five other "
            "leagues' rows (Eredivisie has no pre-2526 season), so it is reported separately and "
            "excluded from the pooled row, which would otherwise score those rows twice.",
            "Each out-of-fold layer is fitted on 4/5 of one season (forward: as little as 1/5), "
            "while the shipped layers used all of it; cross-fitted scores carry that small-sample cost.",
            "Local runtime is Python 3.14 / scikit-learn 1.8; production is 3.11 / 1.3.2. The sigmoid "
            "calibrator is applied from coefficients (calibration._platt_probability), so the served "
            "numbers do not depend on the scikit-learn version.",
            "No recommendation is made. Item 142's options remain an operator decision.",
        ],
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    if parity_ok:
        write_markdown(report)
        print(f"wrote {OUT_JSON.relative_to(REPO)} and {OUT_MD.relative_to(REPO)}")
        return 0
    print(f"PARITY FAILED — wrote checks only to {OUT_JSON.relative_to(REPO)}; nothing downstream is valid")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
