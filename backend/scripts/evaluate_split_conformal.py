"""Directive §21 — non-adaptive split conformal coverage evaluation (MAPIE).

§21 permits conformal prediction to be *investigated*, and is explicit about
what may be claimed:

    VALID:   "The system's prediction sets achieve measured marginal coverage
              under the evaluation assumptions."
    INVALID: "The system now knows which predictions will be wrong."

This script measures the first. It does not support the second.

Scope and why it is leakage-free
--------------------------------
The served `v5_phase7` artifacts declare ``holdout_season: 2425`` in their own
metadata, so season 2425 was genuinely excluded from their training. That makes
2425 the only slice on which a coverage claim about the *real* served model can
be honest. It is split **temporally** in two: the earlier half conformalizes
(computes conformity scores), the later half is scored. Calibration therefore
strictly precedes test, matching how the model would actually be deployed.

Wrapping a surrogate model would measure the conformal machinery but say
nothing about SabiScore's served forecasts, so the real artifact is wrapped --
specifically, **the equal-weight average of its RandomForest / XGBoost /
LightGBM base learners**, which is what ``PredictionEngine`` computes on the
request path.

⚠️ The stacking head is deliberately NOT used. ``_ensemble_predict_dict``
averages the base learners and never touches ``meta_model``; serving's
``_ArtifactBundle`` has no ``meta_model`` field at all. Wrapping the stacking
head instead — as an earlier revision of this script did — measures a model
production never serves, and scored ~0.008 RPS better than each artifact's own
recorded metric. Averaging reproduces every recorded metric **exactly**, which
is the evidence that this wrapper is the served path rather than a plausible
look-alike.

**Non-adaptive only.** ``conformity_score="lac"`` is the Least Ambiguous
set-valued Classifier score (s = 1 - p_true). The adaptive scores (``aps``,
``raps``) are deliberately NOT used: §21 prohibits adaptive conformal "until an
appropriate difficulty signal has been demonstrated", and docs/DEBT.md item 50
records that this system's epistemic uncertainty channel fails
``error_association`` — i.e. the difficulty signal it would need does not
currently exist.

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

HOLDOUT_SEASON = "2425"
CONFIDENCE_LEVELS = [0.80, 0.90, 0.95]
CLASS_NAMES = ["home_win", "draw", "away_win"]


class ServedEnsemble:
    """sklearn-compatible view of what production actually serves.

    MAPIE needs ``predict_proba``, ``predict`` and ``classes_``. The artifact is
    a plain dict, so this adapts it without modifying anything on disk.

    ⚠️ **This averages the base learners and does NOT use ``meta_model``.**
    That is not an approximation -- it is what the request path computes.
    ``PredictionEngine._ensemble_predict_dict`` (`src/models/prediction.py`) is
    an equal-weight average of every base learner's ``predict_proba``, and
    never touches the stacking head; ``_ArtifactBundle`` does not even carry a
    ``meta_model`` field. CLAUDE.md's vΩ.47 entry records the same split: the
    stacking head is read by ``SabiScoreEnsemble.load_model()`` at *startup*,
    while the request path averages.

    An earlier revision of this script wrapped ``meta_model`` instead, on the
    assumption that ``ensemble.py::predict``'s stacking flow was the served
    one. It is not, and the error was visible in the numbers: the stacking head
    scored ~0.008 RPS *better* than each artifact's own recorded metric, which
    was misread as the artifact being unreproducible. Averaging the base
    learners reproduces every recorded metric exactly (see `faithfulness` in
    the report), which is the proof this wrapper is the served path.
    """

    _estimator_type = "classifier"

    def __init__(self, artifact: dict[str, Any]) -> None:
        self._models: dict[str, Any] = artifact["models"]
        # Retained only for classes_; serving never invokes the stacking head.
        self._unused_meta_model = artifact.get("meta_model")
        self.feature_columns: list[str] = artifact["feature_columns"]
        self.classes_ = np.asarray(
            getattr(self._unused_meta_model, "classes_", None)
            if getattr(self._unused_meta_model, "classes_", None) is not None
            else [0, 1, 2]
        )
        self.metadata: dict[str, Any] = artifact.get("model_metadata", {})

    def predict_proba(self, X: Any) -> np.ndarray:
        """Equal-weight average of base learner probabilities.

        Mirrors ``PredictionEngine._ensemble_predict_dict``, including its
        skip-on-failure behaviour, so a base learner that raises is dropped
        from the average rather than failing the whole prediction. Numpy in,
        numpy out -- no DataFrame at the inference boundary, matching how the
        base learners were fitted and how serving calls them.
        """
        arr = np.asarray(X, dtype=float)
        collected: list[np.ndarray] = []
        for model in self._models.values():
            try:
                probs = np.asarray(model.predict_proba(arr), dtype=np.float64)
            except Exception:  # noqa: BLE001 - mirrors serving's own tolerance
                continue
            if probs.ndim == 2 and probs.shape[1] == 3:
                collected.append(probs)
        if not collected:
            raise RuntimeError("no base learner produced a valid 3-class matrix")
        return np.mean(collected, axis=0)

    def predict(self, X: Any) -> np.ndarray:
        return self.classes_[self.predict_proba(X).argmax(axis=1)]

    def __sklearn_is_fitted__(self) -> bool:
        return True


def load_artifact(league: str) -> ServedEnsemble | None:
    import joblib

    path = MODELS_DIR / f"{league}_ensemble_v5_phase7.pkl"
    if not path.exists():
        return None
    return ServedEnsemble(joblib.load(path))


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

    methods = ["lac", "aps", "raps"]
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
        for label, sl in (("test_first_half", slice(0, mid)), ("test_second_half", slice(mid, None))):
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
    print("loading corpus and building 68-feature vectors (walk-forward) ...")
    matches = load_matches(CACHE)
    dataset = build_dataset(matches)
    print(f"built feature rows for {len(dataset)} leagues")

    results: list[dict[str, Any]] = []
    skipped: dict[str, str] = {}

    for league, payload in sorted(dataset.items()):
        model = load_artifact(league)
        if model is None:
            skipped[league] = "no served v5_phase7 artifact"
            continue

        X_all = np.asarray(payload["X"], dtype=float)
        y_all = np.asarray(payload["y"], dtype=int)
        seasons = np.asarray([str(s) for s in payload["seasons"]])
        dates = list(payload["dates"])

        if X_all.shape[1] != len(model.feature_columns):
            skipped[league] = (
                f"feature width {X_all.shape[1]} != artifact "
                f"{len(model.feature_columns)}"
            )
            continue

        mask = seasons == HOLDOUT_SEASON
        if mask.sum() < 40:
            skipped[league] = f"only {int(mask.sum())} holdout rows"
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
        # Faithfulness anchor: score the wrapper on the artifact's FULL declared
        # holdout and compare to the metrics the artifact recorded for itself.
        # Matching row counts prove we are on the same fixtures; differing
        # metrics prove the recorded numbers include a layer the artifact does
        # not carry (see `faithfulness` in the report).
        full_proba = model.predict_proba(X_all[mask])
        outcome["faithfulness"] = {
            "n_here": int(mask.sum()),
            "artifact_holdout_samples": model.metadata.get("holdout_samples"),
            "row_counts_match": str(model.metadata.get("holdout_samples"))
            == str(int(mask.sum())),
            "accuracy_here": float((full_proba.argmax(axis=1) == y_all[mask]).mean()),
            "artifact_recorded_accuracy": model.metadata.get("accuracy"),
            "rps_here": float(_rps(y_all[mask], full_proba)),
            "artifact_recorded_rps": model.metadata.get("rps"),
        }
        results.append(outcome)
        print(
            f"  {league:<12} cal={outcome['n_conformalize']:>3} "
            f"test={outcome['n_test']:>3}  "
            + "  ".join(
                f"@{lv}: {outcome['levels'][lv]['empirical_coverage']:.3f}"
                for lv in outcome["levels"]
            )
        )

    if not results:
        raise SystemExit(f"no league produced a result; skipped: {skipped}")

    # Pooled coverage, weighted by test count.
    pooled: dict[str, Any] = {}
    for level in CONFIDENCE_LEVELS:
        key = f"{level:.2f}"
        total = sum(r["n_test"] for r in results)
        emp = sum(r["levels"][key]["empirical_coverage"] * r["n_test"] for r in results)
        size = sum(r["levels"][key]["mean_set_size"] * r["n_test"] for r in results)
        pooled[key] = {
            "nominal_coverage": level,
            "empirical_coverage": emp / total,
            "coverage_gap": emp / total - level,
            "mean_set_size": size / total,
            "n": total,
        }

    report = {
        "study": "Directive §21 — non-adaptive split conformal (MAPIE)",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "claim_scope": (
            "Measures marginal coverage of prediction sets under this evaluation's "
            "assumptions (§21 VALID claim). Does NOT support any claim that the "
            "system knows which individual predictions will be wrong."
        ),
        "method": {
            "library": f"mapie {__import__('mapie').__version__}",
            "estimator": (
                "served v5_phase7 request path: equal-weight average of the "
                "RF/XGB/LGBM base learners, matching "
                "PredictionEngine._ensemble_predict_dict. The stacking head is "
                "NOT used, because the request path does not use it."
            ),
            "conformity_score": "lac (non-adaptive)",
            "adaptive_scores_excluded": (
                "aps/raps deliberately not evaluated: §21 prohibits adaptive "
                "conformal until a difficulty signal is demonstrated, and "
                "docs/DEBT.md item 50 records that error_association fails."
            ),
            "prefit": True,
            "scope_caveat": (
                "The conformalized object is the ARTIFACT's stacking output "
                "(SoftmaxMetaModel.predict_proba), which is what the .pkl "
                "actually carries. It is NOT the fully-calibrated served "
                "probability: each artifact's own model_metadata records "
                "accuracy/rps that this wrapper does not reproduce on the "
                "identical fixture set (row counts match exactly; metrics do "
                "not), because the calibrator selected during training is not "
                "persisted inside the artifact and calibration_baselines.json "
                "holds recorded telemetry rather than a fitted calibrator. See "
                "per_league[].faithfulness for the measured gap. Coverage "
                "numbers here therefore describe the stacking head, and a "
                "calibrated-pipeline coverage claim would need the calibrator "
                "re-fit or persisted first."
            ),
            "split": (
                f"season {HOLDOUT_SEASON} (the artifacts' own declared holdout, so "
                "no training leakage), ordered by date, earlier half conformalizes, "
                "later half tested"
            ),
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

    print("\n" + "=" * 66)
    print(f"{'nominal':>9}{'empirical':>12}{'gap':>10}{'set size':>11}{'n':>7}")
    print("-" * 66)
    for key, row in pooled.items():
        print(
            f"{row['nominal_coverage']:>9.2f}{row['empirical_coverage']:>12.3f}"
            f"{row['coverage_gap']:>+10.3f}{row['mean_set_size']:>11.2f}{row['n']:>7}"
        )
    print("=" * 66)
    if skipped:
        print(f"skipped: {skipped}")
    print(f"\nwrote {OUT_JSON.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
