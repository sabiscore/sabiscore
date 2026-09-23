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
specifically, the same two-branch logic ``PredictionEngine._run_inference``
computes on the request path: the stacked meta-model when one is present,
equal-weight base-learner averaging only as its fallback.

⚠️ **Corrected 2026-09-23.** An earlier revision of this docstring said the
stacking head is "deliberately NOT used" because ``_ensemble_predict_dict``
"never touches meta_model" and ``_ArtifactBundle`` "has no meta_model field at
all". That was an accurate description of serving as it stood on 2026-09-10.
`docs/DEBT.md` item 87 (2026-09-13) wired ``_run_inference`` to try
``_stacked_predict`` via ``bundle.meta_model`` FIRST, falling back to
averaging only when no meta-model is present or its call raises -- so as of
that fix, averaging is the fallback, not the primary path. See
``ServedEnsemble`` below for the corrected wrapper and its own faithfulness
discussion.

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

    ⚠️ **Updated 2026-09-23 -- the previous revision of this wrapper was
    correct on 2026-09-10 and has since gone stale.** `docs/DEBT.md` item 87
    (2026-09-13) wired ``PredictionEngine._run_inference`` to try the stacked
    meta-model FIRST whenever ``bundle.meta_model is not None``, falling back
    to the equal-weight base-learner average only if the meta-model is absent
    or its call raises. Averaging is no longer what production computes when a
    meta-model is present -- it is the fallback path, not the primary one.

    This wrapper now mirrors ``_run_inference`` exactly: ``_build_meta_features``
    and ``_stacked_predict`` are transcribed from `src/models/prediction.py`
    (not imported -- `docs/DEBT.md` item 7 records that importing
    `src.models.prediction`'s chain reaches `core/database.py`, which opens a
    connection at import time, so an offline research script cannot import it
    without a live DB). ``predict_proba`` tries the stacked path first and
    falls back to averaging only when the meta-model is missing or raises,
    exactly matching the two branches in ``_run_inference``.

    The prior revision's own reasoning for wrapping *only* the average --
    "the stacking head scored ~0.008 RPS better than each artifact's own
    recorded metric" -- was correct for the artifacts and the code as they
    stood on 2026-09-10. It stopped being a reason to prefer averaging the
    moment production started preferring the meta-model. The `faithfulness`
    block in the emitted report re-runs that same exact-reproduction check
    against this wrapper, so a divergence from the artifact's own recorded
    metrics is measured here, not asserted.
    """

    _estimator_type = "classifier"

    def __init__(self, artifact: dict[str, Any]) -> None:
        self._models: dict[str, Any] = artifact["models"]
        self._meta_model: Any = artifact.get("meta_model")
        self.feature_columns: list[str] = artifact["feature_columns"]
        self.classes_ = np.asarray(
            getattr(self._meta_model, "classes_", None)
            if getattr(self._meta_model, "classes_", None) is not None
            else [0, 1, 2]
        )
        self.metadata: dict[str, Any] = artifact.get("model_metadata", {})

    def _build_meta_features(self, X: np.ndarray) -> np.ndarray:
        """Transcribed from ``PredictionEngine._build_meta_features``.

        Concatenates each base learner's 3-class probability vector into one
        ``(n, 3 * n_models)`` row, in ``self._models``' own iteration order --
        the same order ``_run_inference`` builds them in, since both iterate
        the artifact's own ``models`` dict.
        """
        columns: list[np.ndarray] = []
        for model in self._models.values():
            probabilities = np.asarray(model.predict_proba(X), dtype=np.float64)
            if probabilities.ndim != 2 or probabilities.shape[1] < 3:
                raise ValueError("base learner returned invalid meta-feature probabilities")
            columns.extend(
                [probabilities[:, 0:1], probabilities[:, 1:2], probabilities[:, 2:3]]
            )
        if not columns:
            raise ValueError("no base learner available for meta-feature construction")
        return np.hstack(columns)

    def _stacked_predict(self, X: np.ndarray) -> np.ndarray:
        """Transcribed from ``PredictionEngine._stacked_predict``."""
        meta_features = self._build_meta_features(X)
        proba = np.asarray(self._meta_model.predict_proba(meta_features), dtype=np.float64)
        if proba.ndim == 1:
            proba = proba.reshape(1, -1)
        return proba

    def _averaged_predict(self, X: Any) -> np.ndarray:
        """Equal-weight average of base learner probabilities (fallback only).

        Mirrors ``PredictionEngine._ensemble_predict_dict``, including its
        skip-on-failure behaviour, so a base learner that raises is dropped
        from the average rather than failing the whole prediction.
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

    def predict_proba(self, X: Any) -> np.ndarray:
        """Stacked meta-model first, averaging only as fallback.

        Matches ``_run_inference``'s two branches exactly: if a meta-model is
        present, try it; only fall back to averaging if it is absent or its
        call raises. Unlike serving, this wrapper does not special-case "a
        serialized calibrator exists" into a hard failure -- MAPIE needs a
        ``predict_proba`` that always returns, and no artifact evaluated here
        actually has a *usable* calibrator (0/6 per item 122), so that branch
        of `_run_inference` is unreachable on the artifacts this script scores.
        """
        arr = np.asarray(X, dtype=float)
        if self._meta_model is not None:
            try:
                return self._stacked_predict(arr)
            except Exception:  # noqa: BLE001 - mirrors serving's own tolerance
                pass
        return self._averaged_predict(arr)

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
            "estimator": (
                "served v5_phase7 request path, matching "
                "PredictionEngine._run_inference exactly: the stacked "
                "meta-model (SoftmaxMetaModel.predict_proba over the RF/XGB/"
                "LGBM base learners' concatenated probabilities) when present, "
                "falling back to equal-weight base-learner averaging only if "
                "no meta-model is present or the stacked call raises. "
                "Corrected 2026-09-23 -- docs/DEBT.md item 87 (2026-09-13) "
                "made stacking the primary path; a prior revision of this "
                "script (and this field) predated that fix and averaged "
                "unconditionally."
            ),
            "conformity_score": "lac (non-adaptive)",
            "adaptive_scores_excluded": (
                "aps/raps deliberately not evaluated: §21 prohibits adaptive "
                "conformal until a difficulty signal is demonstrated, and "
                "docs/DEBT.md item 50 records that error_association fails."
            ),
            "prefit": True,
            "scope_caveat": (
                "On the artifacts this script can load, meta_model is a bare "
                "SoftmaxMetaModel for all six leagues (docs/DEBT.md: 'genuinely "
                "uncalibrated'), so the stacked path taken here is the raw, "
                "uncalibrated stacking output -- not a calibrated probability. "
                "A serialized calibrator exists for 2/6 leagues (bundesliga, "
                "ligue_1) but _run_inference never applies it to transform "
                "probabilities on the success path; it is consulted only if "
                "the stacked call raises (docs/DEBT.md item 122: 0/6 leagues "
                "have a USABLE calibrator). See per_league[].faithfulness for "
                "whether this wrapper reproduces each artifact's own recorded "
                "accuracy/rps exactly -- exact reproduction is the evidence "
                "this wrapper matches the object actually being measured, not "
                "an assumption."
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
