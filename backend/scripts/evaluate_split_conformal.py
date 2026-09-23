"""Directive §21 — non-adaptive split conformal coverage evaluation (MAPIE).

§21 permits conformal prediction to be *investigated*, and is explicit about
what may be claimed:

    VALID:   "The system's prediction sets achieve measured marginal coverage
              under the evaluation assumptions."
    INVALID: "The system now knows which predictions will be wrong."

This script measures the first. It does not support the second.

Scope and why it is leakage-free
--------------------------------
Each artifact records its own ``holdout_season`` (and ``calibration_season``)
in its hash-verified metadata. That season was excluded from training AND from
calibrator fitting, so it is the only slice on which a coverage claim about the
*real* served model can be honest. It is read per artifact, never hardcoded: a
hardcoded season silently becomes leakage when a new generation moves the
split (the ``v5_phase7-20260922`` generation fits its calibrator on 2425, the
season an earlier revision of this script hardcoded as "holdout"). The holdout
is split **temporally** in two: the earlier half conformalizes, the later half
is scored, so calibration strictly precedes test.

The wrapped estimator is the served path itself. ``ServedEnsemble`` calls
``PredictionEngine``'s own methods on a batch — stacked meta-model (averaging
only as its fallback), then the artifact's ``FittedCalibrator``, then the
Bivariate Poisson overlay when active — and ``served_path_identity`` in the
report proves it row-for-row against ``PredictionEngine._run_inference``.
Features come from ``build_dataset`` in the schema the artifacts record, which
after docs/DEBT.md item 141 is also the schema serving builds.

**LAC is the headline.** ``conformity_score="lac"`` is the Least Ambiguous
set-valued Classifier score (s = 1 - p_true). ``aps`` is also computed, as the
Phase D/E directive §17 asks, but evaluation-only: §21 prohibits adopting
adaptive conformal "until an appropriate difficulty signal has been
demonstrated". On the current generation ``error_association`` passes but
``informative_within_confidence_band`` does not (docs/DEBT.md items 50, 129), so
the uncertainty contract is still unmet. ``raps`` is not computed (see
``evaluate_league``).

**Coverage alone is not sufficient** (§21). This script therefore also reports
set size, the set-size distribution, failure concentration by true class, and
stability across temporal sub-windows.

⚠️ Evaluation only. No feature contract, model artifact, promotion gate,
calibration layer or serving path is touched.

Usage
-----
    .venv/Scripts/python.exe backend/scripts/evaluate_split_conformal.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

_SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = _SCRIPTS.parents[1]
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from train_on_real_matches import (  # noqa: E402
    build_dataset,
    load_matches,
    ranked_probability_score as _rps,
)

OUT_JSON = REPO_ROOT / "reports" / "research" / "split-conformal-report.json"
MODELS_DIR = REPO_ROOT / "backend" / "models"
CACHE = REPO_ROOT / "backend" / "data" / "cache"

CONFIDENCE_LEVELS = [0.80, 0.90, 0.95]
IDENTITY_CHECK_ROWS = 25
# _run_inference rounds each probability to 4 dp; that is the finest agreement
# a batch reproduction can be held to.
IDENTITY_TOLERANCE = 1e-4
CLASS_NAMES = ["home_win", "draw", "away_win"]


class ServedEnsemble:
    """sklearn-compatible view of exactly what production serves.

    MAPIE needs ``predict_proba``, ``predict`` and ``classes_``. The artifact is
    wrapped through ``PredictionEngine._wrap_artifact`` — the loader serving
    uses, including its calibrator preflight — and every probability comes from
    ``PredictionEngine``'s own methods, not a transcription of them, so this
    cannot drift from serving. ``src.models.prediction`` imports offline: its
    chain does not reach ``core/database.py`` (an earlier revision of this
    script claimed otherwise and transcribed the methods instead).

    ``predict_proba`` is ``_run_inference``'s success path on a batch. The two
    places the batch form must differ are both mechanical: ``_run_inference``
    scores one fixture per call (its averaging helper rejects any shape but
    ``(1, 3)``), and it rounds its outputs to 4 dp. ``identity_check`` holds the
    batch form to ``_run_inference`` itself, row by row, within that rounding.
    """

    _estimator_type = "classifier"

    def __init__(self, raw: dict[str, Any], league: str, path: Path) -> None:
        from src.models.prediction import PredictionEngine

        self._engine = PredictionEngine
        self._league = league
        self._bundle = PredictionEngine._wrap_artifact(raw, league, path)
        if self._bundle is None or self._bundle.models_dict is None:
            raise RuntimeError(f"{league}: artifact is not a dict-form served bundle")
        self.feature_columns: list[str] = list(raw["feature_columns"])
        self.classes_ = np.asarray([0, 1, 2])
        self.metadata: dict[str, Any] = raw.get("model_metadata", {})

    def _averaged(self, X: np.ndarray) -> np.ndarray:
        # _ensemble_predict_dict's equal-weight mean, minus its single-row gate.
        return np.mean(
            [
                np.asarray(m.predict_proba(X), dtype=np.float64)
                for m in self._bundle.models_dict.values()
            ],
            axis=0,
        )

    def head(self, X: Any) -> np.ndarray:
        """The served head alone: stacked meta-model, averaging only as fallback."""
        bundle = self._bundle
        # _run_inference casts features to float32 before any model sees them.
        arr = np.asarray(X, dtype=np.float32)
        if bundle.meta_model is not None:
            try:
                return self._engine._stacked_predict(
                    bundle.models_dict, bundle.meta_model, arr
                )
            except Exception:  # noqa: BLE001 - mirrors serving's own fallback
                pass
        return self._averaged(arr)

    def predict_proba(self, X: Any) -> np.ndarray:
        from src.models.calibration import apply_calibrator

        bundle = self._bundle
        proba = self.head(X)
        if bundle.calibrator is not None:
            proba = apply_calibrator(
                bundle.calibrator.method, bundle.calibrator.calibrators, proba
            )
        overlay = bundle.overlay
        if overlay is not None and getattr(overlay, "alpha", 0.0) > 0.0:
            proba = overlay.apply(proba)
        return np.asarray(proba, dtype=np.float64)

    def predict(self, X: Any) -> np.ndarray:
        return self.classes_[self.predict_proba(X).argmax(axis=1)]

    def identity_check(self, X: np.ndarray) -> dict[str, Any]:
        """Hold the batch form to ``PredictionEngine._run_inference``, row by row."""

        rows = X[:IDENTITY_CHECK_ROWS]
        batch = self.predict_proba(rows)
        engine = self._engine()
        served = np.asarray(
            [
                [r.home_win, r.draw, r.away_win]
                for r in (
                    engine._run_inference(self._bundle, row, self._league.upper())
                    for row in rows
                )
            ]
        )
        max_diff = float(np.abs(batch - served).max())
        return {
            "rows_checked": int(len(rows)),
            "max_abs_diff_vs_run_inference": round(max_diff, 6),
            "tolerance": IDENTITY_TOLERANCE,
            "identical_within_rounding": max_diff <= IDENTITY_TOLERANCE,
        }

    def __sklearn_is_fitted__(self) -> bool:
        return True


def load_artifact(league: str) -> ServedEnsemble | None:
    import joblib

    path = MODELS_DIR / f"{league}_ensemble_v5_phase7.pkl"
    if not path.exists():
        return None
    return ServedEnsemble(joblib.load(path), league, path)


def evaluate_league(
    league: str,
    model: ServedEnsemble,
    X: np.ndarray,
    y: np.ndarray,
    dates: list[Any],
) -> dict[str, Any] | None:
    """Split conformal on one league's holdout season."""
    from mapie.classification import SplitConformalClassifier

    order = np.argsort(np.asarray(dates))
    X, y = X[order], y[order]
    sorted_dates = [dates[i] for i in order]

    split = len(y) // 2
    if split < 20 or len(y) - split < 20:
        return None

    X_cal, y_cal = X[:split], y[:split]
    X_test, y_test = X[split:], y[split:]

    # ponytail: no RAPS. MAPIE carves its regularisation set out of the
    # calibration half with a *random* StratifiedShuffleSplit (breaks the
    # chronological rule) and, at ~150 calibration rows, gets 15 — below the 20
    # a 95% level needs, so it raised on every league (docs/DEBT.md item 142).
    methods = ["lac", "aps"]
    method_results = {}

    proba = model.predict_proba(X_test)
    point_pred = proba.argmax(axis=1)

    for method in methods:
        conformal = SplitConformalClassifier(
            estimator=model,
            confidence_level=CONFIDENCE_LEVELS,
            conformity_score=method,
            prefit=True,
        )
        conformal.conformalize(X_cal, y_cal)
        _, y_sets = conformal.predict_set(X_test)

        per_level: dict[str, Any] = {}
        for i, level in enumerate(CONFIDENCE_LEVELS):
            sets = y_sets[:, :, i]
            covered = sets[np.arange(len(y_test)), y_test]
            sizes = sets.sum(axis=1)
            empirical = float(covered.mean())

            missed = ~covered.astype(bool)
            by_class = {
                CLASS_NAMES[c]: {
                    "n": int((y_test == c).sum()),
                    "missed": int((missed & (y_test == c)).sum()),
                    "miss_rate": float(
                        (missed & (y_test == c)).sum() / max((y_test == c).sum(), 1)
                    ),
                }
                for c in range(3)
            }

            per_level[f"{level:.2f}"] = {
                "nominal_coverage": level,
                "empirical_coverage": empirical,
                "coverage_gap": empirical - level,
                "mean_set_size": float(sizes.mean()),
                "set_size_distribution": {
                    str(k): int((sizes == k).sum()) for k in range(0, 4)
                },
                "singleton_rate": float((sizes == 1).mean()),
                "full_set_rate": float((sizes == 3).mean()),
                "empty_set_rate": float((sizes == 0).mean()),
                "failure_concentration_by_true_class": by_class,
            }

        stability: dict[str, Any] = {}
        mid = len(y_test) // 2
        for label, sl in (
            ("test_first_half", slice(0, mid)),
            ("test_second_half", slice(mid, None)),
        ):
            window: dict[str, Any] = {}
            for i, level in enumerate(CONFIDENCE_LEVELS):
                sets = y_sets[sl, :, i]
                yy = y_test[sl]
                window[f"{level:.2f}"] = float(sets[np.arange(len(yy)), yy].mean())
            stability[label] = {"n": int(len(y_test[sl])), "empirical_coverage": window}

        method_results[method] = {
            "levels": per_level,
            "temporal_stability": stability,
        }

    return {
        "league": league,
        "n_conformalize": int(len(y_cal)),
        "n_test": int(len(y_test)),
        "conformalize_date_range": [str(sorted_dates[0]), str(sorted_dates[split - 1])],
        "test_date_range": [str(sorted_dates[split]), str(sorted_dates[-1])],
        "point_accuracy_on_test": float((point_pred == y_test).mean()),
        "artifact_reported_accuracy": model.metadata.get("accuracy"),
        "methods": method_results,
    }


def main() -> int:
    manifest = json.loads((MODELS_DIR / "active_generation.json").read_text(encoding="utf-8"))
    schema = manifest["feature_schema_version"]
    print(f"loading corpus and building {schema} vectors (walk-forward) ...")
    matches = load_matches(CACHE)
    dataset = build_dataset(matches, schema=schema)
    print(f"built feature rows for {len(dataset)} leagues")

    results: list[dict[str, Any]] = []
    skipped: dict[str, str] = {}
    holdout_seasons: dict[str, str] = {}

    for league, payload in sorted(dataset.items()):
        model = load_artifact(league)
        if model is None:
            skipped[league] = "no served v5_phase7 artifact"
            continue

        X_all = np.asarray(payload["X"], dtype=float)
        y_all = np.asarray(payload["y"], dtype=int)
        seasons = np.asarray([str(s) for s in payload["seasons"]])
        dates = list(payload["dates"])

        trained_schema = model.metadata.get("feature_schema_version")
        if trained_schema != schema:
            skipped[league] = f"artifact trained on {trained_schema!r}, manifest serves {schema!r}"
            continue
        if X_all.shape[1] != len(model.feature_columns):
            skipped[league] = (
                f"feature width {X_all.shape[1]} != artifact "
                f"{len(model.feature_columns)}"
            )
            continue

        holdout = model.metadata.get("holdout_season")
        if not holdout:
            skipped[league] = "artifact records no holdout_season; refusing to guess one"
            continue
        holdout_seasons[league] = str(holdout)
        mask = seasons == str(holdout)
        if mask.sum() < 40:
            skipped[league] = f"only {int(mask.sum())} rows in holdout season {holdout}"
            continue

        outcome = evaluate_league(
            league,
            model,
            X_all[mask],
            y_all[mask],
            [d for d, m in zip(dates, mask, strict=True) if m],
        )
        if outcome is None:
            skipped[league] = "holdout too small to split"
            continue
        # Faithfulness anchor. The pickle's own model_metadata.rps is the stacked
        # head's RPS on this holdout, WITHOUT the later-injected calibrator (the
        # sidecar metadata JSON records the base-learner average instead).
        # Reproducing it proves these are the artifact's own rows and feature
        # vectors; the served composition is recorded nowhere, so it is scored
        # here (docs/DEBT.md item 142).
        X_hold, y_hold = X_all[mask], y_all[mask]
        served_proba = model.predict_proba(X_hold)
        average_proba = model._averaged(np.asarray(X_hold, dtype=np.float32))
        outcome["faithfulness"] = {
            "n_here": int(mask.sum()),
            "artifact_holdout_samples": model.metadata.get("holdout_samples"),
            "row_counts_match": str(model.metadata.get("holdout_samples"))
            == str(int(mask.sum())),
            "artifact_recorded_rps": model.metadata.get("rps"),
            "rps_stacked_head_uncalibrated": float(_rps(y_hold, model.head(X_hold))),
            "rps_base_learner_average": float(_rps(y_hold, average_proba)),
            "rps_served_path": float(_rps(y_hold, served_proba)),
            "accuracy_served_path": float((served_proba.argmax(axis=1) == y_hold).mean()),
            "artifact_recorded_accuracy": model.metadata.get("accuracy"),
        }
        outcome["served_path_identity"] = model.identity_check(X_hold)
        results.append(outcome)
        lac = outcome["methods"]["lac"]["levels"]
        print(
            f"  {league:<12} holdout={holdout} cal={outcome['n_conformalize']:>3} "
            f"test={outcome['n_test']:>3}  LAC "
            + "  ".join(f"@{lv}: {lac[lv]['empirical_coverage']:.3f}" for lv in lac)
            + f"  identity={outcome['served_path_identity']['identical_within_rounding']}"
        )

    if not results:
        raise SystemExit(f"no league produced a result; skipped: {skipped}")

    # Pooled coverage per conformity score, weighted by test count.
    total = sum(r["n_test"] for r in results)
    pooled: dict[str, Any] = {}
    for method in results[0]["methods"]:
        pooled[method] = {}
        for level in CONFIDENCE_LEVELS:
            key = f"{level:.2f}"
            rows = [r["methods"][method]["levels"][key] for r in results]
            weights = [r["n_test"] for r in results]
            emp = sum(row["empirical_coverage"] * w for row, w in zip(rows, weights)) / total
            size = sum(row["mean_set_size"] * w for row, w in zip(rows, weights)) / total
            pooled[method][key] = {
                "nominal_coverage": level,
                "empirical_coverage": emp,
                "coverage_gap": emp - level,
                "mean_set_size": size,
                "n": total,
            }

    report = {
        "study": "Directive §21 — non-adaptive split conformal (MAPIE)",
        "generated_at": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "claim_scope": (
            "Measures marginal coverage of prediction sets under this evaluation's "
            "assumptions (§21 VALID claim). Does NOT support any claim that the "
            "system knows which individual predictions will be wrong."
        ),
        "method": {
            "library": f"mapie {__import__('mapie').__version__}",
            "generation": manifest["generation"],
            "feature_schema_version": schema,
            "estimator": (
                "PredictionEngine's served path via its own methods: stacked "
                "meta_model (averaging only as fallback), then the artifact's "
                "FittedCalibrator, then the Bivariate Poisson overlay when active. "
                "per_league[].served_path_identity holds it row-for-row to "
                "PredictionEngine._run_inference."
            ),
            "headline_conformity_score": "lac (non-adaptive)",
            "adaptive_scores": (
                "aps is computed evaluation-only, as the Phase D/E directive §17 "
                "requests. Directive §21 prohibits adopting adaptive conformal "
                "until a difficulty signal is demonstrated; on this generation "
                "informative_within_confidence_band still fails, so no claim or "
                "serving use may rest on it. raps is not computed: MAPIE draws its "
                "regularisation set by random split and it is too small at this "
                "calibration size (docs/DEBT.md item 142)."
            ),
            "prefit": True,
            "scope_caveat": (
                "The served path applies a calibrator fitted on the base-learner "
                "average on top of an already temperature/vector-scaled stacking "
                "head (docs/DEBT.md item 142). Coverage here describes what is "
                "served, not an endorsement of that composition."
            ),
            "split": (
                "each artifact's own recorded holdout_season (excluded from "
                "training and calibrator fitting), ordered by date, earlier half "
                "conformalizes, later half tested"
            ),
            "holdout_season_by_league": holdout_seasons,
            "confidence_levels": CONFIDENCE_LEVELS,
        },
        "pooled": pooled,
        "per_league": results,
        "skipped_leagues": skipped,
        "threshold_policy": (
            "No pass/fail gate is asserted. §19 forbids hard-coded universal "
            "thresholds; coverage gaps and set sizes are reported as measurements."
        ),
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"{'score':<6}{'nominal':>9}{'empirical':>12}{'gap':>10}{'set size':>11}{'n':>7}")
    print("-" * 72)
    for method, levels in pooled.items():
        for row in levels.values():
            print(
                f"{method:<6}{row['nominal_coverage']:>9.2f}{row['empirical_coverage']:>12.3f}"
                f"{row['coverage_gap']:>+10.3f}{row['mean_set_size']:>11.2f}{row['n']:>7}"
            )
    print("=" * 72)
    if not all(r["served_path_identity"]["identical_within_rounding"] for r in results):
        raise SystemExit("served-path identity check FAILED — the wrapper is not what serving computes")
    if skipped:
        print(f"skipped: {skipped}")
    print(f"\nwrote {OUT_JSON.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
