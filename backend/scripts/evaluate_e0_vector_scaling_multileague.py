"""Experiment E0 extension — vector scaling on the SERVED ensemble, all leagues.

Directive v5 §9 (no decision on a point estimate), §18 (temporal integrity,
paired evaluation, block bootstrap), §20 (Calibration Workstream B1-B3),
§42 (reopening a closed branch).

WHAT THIS MEASURES, AND WHY IT IS NOT A RE-RUN OF E0
----------------------------------------------------
E0 is CLOSED/PROMOTE. Its cascade (`_select_calibrator` in
`train_on_real_matches.py`) already evaluated vector scaling in all six
leagues -- its registry `multiple_testing_family` is "6 leagues x 4
candidates" -- so "does vector scaling generalise beyond Ligue 1" is already
answered: it wins the calibration split in most leagues and fails the held-out
persistence check in five of six.

Two things about that result are genuinely open, and this script measures them:

1. **E0 decided on point estimates.** Its registry entry records
   `bootstrap_method: UNDECLARED`, `confidence_interval: UNDECLARED`,
   `effect_size: UNDECLARED`. The cascade compares Murphy reliability and
   resolution as bare numbers. §9 forbids resting a decision on a point
   estimate and §18 mandates a paired CI. This supplies the missing
   instrument, including for the one decision that shipped (LIGUE_1).

2. **E0 calibrated the meta-model; production does not serve the meta-model.**
   `PredictionEngine._ensemble_predict_dict` is an equal-weight average of the
   base learners and never touches `meta_model`. This script therefore fits and
   scores the calibrator on the probabilities the request path actually
   produces, per the same principle commit d4e1c0b applied to conformal
   ("conformal evaluation wrapped the stacking head, which production never
   serves").

DELIBERATE DEVIATIONS FROM THE COMMISSIONING SPEC
--------------------------------------------------
* **Split is cal=2425 / test=2526, not 2324 -> 2425.** The served base learners
  were trained on the core split, which is everything *before* the calibration
  season (`train_league`: `core_mask = pretest_mask & ~calibration_mask`), so
  season 2324 is IN the base learners' training set. Fitting a calibrator on
  in-sample probabilities teaches it to correct an over-confidence that does
  not exist out-of-sample, then applying it out-of-sample makes calibration
  look worse than it is. 2425 and 2526 are both out-of-sample for the served
  artifacts, which is what makes the comparison honest.
* **`canonical_league_id`, not a local league map.** A hand-rolled
  normalisation table is the defect class this repo has hit five times
  (`docs/DEBT.md`; `apps/web/src/lib/league-contract.test.ts` exists to police
  it). The corpus is already canonical, so this is a fail-closed assertion.
* **RPS/Brier reused from `train_on_real_matches`, ECE from
  `models.evaluation.metrics`.** Re-implementing them risks silent divergence
  from `backend/reports/evaluation/metric-contract.json`, which pins the
  aggregation conventions, and would make these numbers non-comparable to E0's.
* **Paired block bootstrap, not iid.** `metrics.block_bootstrap_ci` uses
  non-overlapping Künsch blocks precisely because consecutive matches within a
  season are temporally dependent; an iid resample would understate the
  interval and overstate significance. The paired variant here reuses that
  block scheme on the per-fixture loss *difference*.

Writes NO production path and promotes nothing.

Usage
-----
    cd backend && PYTHONPATH=. python scripts/evaluate_e0_vector_scaling_multileague.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import polars as pl
from scipy.optimize import minimize

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from src.core.league_policy import canonical_league_id  # noqa: E402
from src.models.evaluation.metrics import expected_calibration_error  # noqa: E402
from src.models.feature_registry import (  # noqa: E402
    CANONICAL_FEATURES_68,
    resolve_feature_schema,
)
from train_on_real_matches import (  # noqa: E402
    build_dataset,
    load_matches,
    multiclass_brier,
    ranked_probability_score,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

EPSILON = 1e-12
L2_REG = 1e-3
N_BOOTSTRAP = 2000
BLOCK_SIZE = 10
RNG_SEED = 42
# §18 multiple-testing family, declared in the registry before any result
# existed: the 5 scoreable leagues, one candidate.
FAMILY_SIZE = 5
FAMILY_ALPHA = 0.05

CALIBRATION_SEASON = "2425"
TEST_SEASON = "2526"

_CORPUS_DIR = _REPO_ROOT / "data" / "cache"
_MODELS_DIR = _REPO_ROOT / "models"
# The EVALUATION baseline, deliberately distinct from the SERVING manifest.
# active_generation.json still declares v5_phase7-20260808 / phase7_68, which
# memorised the 2526 holdout (docs/DEBT.md item 81); flipping serving to the
# clean apex generation is the item 37/49 schema transition and is separately
# gated (test_default_schema_version_is_unchanged exists to catch exactly that
# flip). Calibration research needs a clean baseline, not a serving change.
_EVAL_BASELINE_DIR = _REPO_ROOT / "models" / "evaluation_baseline"
_PRED_CACHE = (
    _REPO_ROOT / "data" / "processed" / "served_ensemble_predictions_holdout.parquet"
)
_REPORT_PATH = (
    _REPO_ROOT.parent / "reports" / "research" / "e0b_clean_baseline_results.json"
)


# ---------------------------------------------------------------------------
# Stage 1 — served-ensemble probabilities
# ---------------------------------------------------------------------------


def _served_probabilities(models_dict: Dict[str, Any], X: np.ndarray) -> np.ndarray:
    """Equal-weight base-learner average — the request path, not the meta-model.

    Mirrors `PredictionEngine._ensemble_predict_dict`. Reimplemented rather than
    imported because importing `src.models.prediction` pulls the serving import
    chain (and with it a live DB connection) into an offline script; the body is
    four lines and pinned by a parity test.
    """
    all_probs: List[np.ndarray] = []
    for model in models_dict.values():
        proba = np.asarray(model.predict_proba(X), dtype=np.float64)
        if proba.ndim == 2 and proba.shape[1] == 3 and np.all(np.isfinite(proba)):
            all_probs.append(proba)
    if not all_probs:
        raise ValueError("no base learner returned a valid probability simplex")
    return np.mean(all_probs, axis=0)


def build_prediction_table(
    force: bool = False, models_dir: Path | None = None
) -> pl.DataFrame:
    """Run the baseline ensemble over the corpus and cache the result."""
    if _PRED_CACHE.exists() and not force:
        logger.info("Reusing cached baseline predictions: %s", _PRED_CACHE)
        return pl.read_parquet(_PRED_CACHE)

    import joblib

    root = models_dir or _EVAL_BASELINE_DIR
    manifest_path = root / (
        "manifest.json" if root != _MODELS_DIR else "active_generation.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    logger.info(
        "Baseline %s (%s), head %s — from %s",
        manifest["generation"],
        manifest.get("role", "SERVING"),
        manifest.get("served_head"),
        manifest_path.relative_to(_REPO_ROOT),
    )

    # Which 68-block the ACTIVE generation is built on is a manifest fact, not a
    # constant. v5_phase7-20260808 was legacy (CANONICAL_FEATURES_68);
    # v11_clean2526 is apex. Hardcoding either silently scores the artifacts on a
    # vector they were not trained on — the schema-mismatch class
    # PredictionEngine already refuses to zero-pad around.
    schema_version = str(manifest.get("feature_schema_version") or "")
    serving_columns = resolve_feature_schema(schema_version)
    uses_legacy_block = list(serving_columns) == list(CANONICAL_FEATURES_68)
    logger.info(
        "Serving contract: %s (%d features, %s block)",
        schema_version,
        len(serving_columns),
        "legacy" if uses_legacy_block else "apex",
    )

    matches = load_matches(_CORPUS_DIR)
    # `build_dataset` emits the schema vector as `X` and the legacy 68-block as
    # `X_incumbent`; pick whichever the active generation actually declares.
    dataset = build_dataset(
        matches, schema=schema_version if not uses_legacy_block else "apex_v1_68"
    )
    vector_key = "X_incumbent" if uses_legacy_block else "X"

    rows: List[Dict[str, Any]] = []
    for slug, entry in manifest["artifacts"].items():
        league = canonical_league_id(slug)
        data = dataset.get(league)
        if not data or not data[vector_key]:
            logger.warning("No corpus rows for %s — skipping", league)
            continue

        artifact = root / entry["artifact"]
        if not artifact.exists():
            logger.warning("Artifact missing for %s: %s — skipping", league, artifact)
            continue
        raw = joblib.load(artifact)
        if not isinstance(raw, dict) or "models" not in raw:
            logger.warning("%s: artifact is not a base-learner dict — skipping", league)
            continue

        # Fail closed rather than score a vector the artifact was not built on;
        # that is the schema-mismatch class `PredictionEngine` already refuses
        # to zero-pad around.
        columns = list(raw.get("feature_columns") or [])
        if columns != list(serving_columns):
            logger.error(
                "%s: artifact feature_columns (%d) do not match the manifest's "
                "declared %s contract (%d) — refusing to score it",
                league,
                len(columns),
                schema_version,
                len(serving_columns),
            )
            continue

        metadata = json.loads((root / entry["metadata"]).read_text(encoding="utf-8"))
        declared_holdout = str(metadata.get("holdout_season") or "")

        X = np.asarray(data[vector_key], dtype=np.float32)
        y = np.asarray(data["y"], dtype=np.int64)
        seasons = np.asarray(data["seasons"])

        # Score every season, not just the two under test: the per-season curve
        # is what exposes whether a season was in the artifact's training set.
        probs = _served_probabilities(raw["models"], X)
        for prob, label, season in zip(probs, y, seasons):
            rows.append(
                {
                    "league": league,
                    "season": str(season),
                    "declared_holdout_season": declared_holdout,
                    "prob_home": float(prob[0]),
                    "prob_draw": float(prob[1]),
                    "prob_away": float(prob[2]),
                    "y": int(label),
                }
            )
        logger.info(
            "  %s: %d rows scored through the served base-learner average "
            "(artifact declares holdout_season=%s)",
            league,
            len(y),
            declared_holdout or "UNDECLARED",
        )

    df = pl.DataFrame(rows)
    _PRED_CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(_PRED_CACHE)
    logger.info("Served predictions cached: %s (%d rows)", _PRED_CACHE, df.height)
    return df


# ---------------------------------------------------------------------------
# Stage 2 — vector scaling
# ---------------------------------------------------------------------------


class VectorCalibrator:
    """Per-class scale and bias on centred log-odds, fitted by NLL + L2."""

    def __init__(self, l2_reg: float = L2_REG) -> None:
        self.l2_reg = l2_reg
        self.weights = np.ones(3, dtype=np.float64)
        self.bias = np.zeros(3, dtype=np.float64)
        self.converged: bool | None = None

    @staticmethod
    def _logits(probs: np.ndarray) -> np.ndarray:
        log_p = np.log(np.clip(probs, EPSILON, 1.0))
        return log_p - np.mean(log_p, axis=1, keepdims=True)

    @staticmethod
    def _softmax(z: np.ndarray) -> np.ndarray:
        exp_z = np.exp(z - np.max(z, axis=1, keepdims=True))
        return exp_z / np.sum(exp_z, axis=1, keepdims=True)

    def fit(self, probs: np.ndarray, targets: np.ndarray) -> "VectorCalibrator":
        z = self._logits(probs)

        def loss_fn(params: np.ndarray) -> float:
            w, b = params[:3], params[3:]
            p_hat = self._softmax(z * w + b)
            nll = -np.mean(
                np.sum(targets * np.log(np.clip(p_hat, EPSILON, 1.0)), axis=1)
            )
            reg = self.l2_reg * (np.sum((w - 1.0) ** 2) + np.sum(b**2))
            return float(nll + reg)

        res = minimize(
            loss_fn,
            np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0]),
            method="L-BFGS-B",
            bounds=[(1e-3, 10.0)] * 3 + [(-5.0, 5.0)] * 3,
        )
        if not res.success:
            logger.warning("Vector-scaling optimiser did not converge: %s", res.message)
        self.converged = bool(res.success)
        self.weights = res.x[:3]
        self.bias = res.x[3:]
        return self

    def predict(self, probs: np.ndarray) -> np.ndarray:
        return self._softmax(self._logits(probs) * self.weights + self.bias)


def _onehot(y: np.ndarray) -> np.ndarray:
    out = np.zeros((len(y), 3), dtype=np.float64)
    out[np.arange(len(y)), y] = 1.0
    return out


def _rps_per_fixture(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    onehot = _onehot(y)
    return (
        np.sum((np.cumsum(probs, axis=1) - np.cumsum(onehot, axis=1)) ** 2, axis=1)
        / 2.0
    )


def _brier_per_fixture(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.sum((probs - _onehot(y)) ** 2, axis=1)


def paired_block_bootstrap_ci(
    baseline_loss: np.ndarray,
    candidate_loss: np.ndarray,
    *,
    n_bootstrap: int = N_BOOTSTRAP,
    block_size: int = BLOCK_SIZE,
    seed: int = RNG_SEED,
) -> Dict[str, Any]:
    """95% CI for mean(candidate - baseline), resampling Künsch blocks.

    Paired: the same resampled fixture indices score both arms, so fixture
    difficulty cancels. Blocks rather than iid draws, matching
    `metrics.block_bootstrap_ci` -- consecutive matches within a season are
    temporally dependent, and an iid resample would understate the interval.
    """
    diff = candidate_loss - baseline_loss
    n = len(diff)
    point = float(np.mean(diff))
    if n < block_size * 2:
        return {
            "mean_delta": round(point, 6),
            "ci_lower": None,
            "ci_upper": None,
            "n": n,
            "note": "insufficient_samples_for_block_bootstrap",
        }

    rng = np.random.default_rng(seed)
    n_blocks = n // block_size
    starts = np.arange(n_blocks) * block_size
    replicates = np.empty(n_bootstrap, dtype=np.float64)
    for i in range(n_bootstrap):
        chosen = rng.choice(n_blocks, size=n_blocks, replace=True)
        idx = (starts[chosen][:, None] + np.arange(block_size)[None, :]).ravel()[:n]
        replicates[i] = np.mean(diff[idx])

    # §18 requires a pre-declared multiple-testing protocol. The family is the
    # 5 scoreable leagues (declared in the registry's `multiple_testing_family`
    # before any of these results existed), so the nominal 95% interval is
    # accompanied by a Bonferroni family-wise interval at
    # alpha_family / FAMILY_SIZE. Promotion keys off the CORRECTED bound:
    # with 5 tests, one nominally-significant result is roughly what chance
    # alone produces (~12% of the time).
    alpha_corrected = FAMILY_ALPHA / FAMILY_SIZE
    lo_pct, hi_pct = (
        100.0 * alpha_corrected / 2.0,
        100.0 * (1.0 - alpha_corrected / 2.0),
    )
    return {
        "mean_delta": round(point, 6),
        "ci_lower": round(float(np.percentile(replicates, 2.5)), 6),
        "ci_upper": round(float(np.percentile(replicates, 97.5)), 6),
        "ci_level": 0.95,
        "ci_lower_bonferroni": round(float(np.percentile(replicates, lo_pct)), 6),
        "ci_upper_bonferroni": round(float(np.percentile(replicates, hi_pct)), 6),
        "ci_level_bonferroni": round(1.0 - alpha_corrected, 4),
        "family_size": FAMILY_SIZE,
        "n": n,
        "n_bootstrap": n_bootstrap,
        "block_size": block_size,
    }


def assess_temporal_integrity(df: pl.DataFrame, league: str) -> Dict[str, Any]:
    """Is each season out-of-sample for the artifact that scored it?

    An artifact's metadata declares exactly one `holdout_season`; by
    construction every other season in the corpus was available to training.
    That is a claim about provenance, so it is also checkable against
    behaviour: a season the model memorised scores far better than the one
    season it genuinely did not see.

    Reports per-season RPS against the declared holdout's RPS. A season
    scoring materially BETTER than the declared holdout is flagged
    `in_sample_signature` -- it is not a harder-won generalisation, it is
    training data.
    """
    league_df = df.filter(pl.col("league") == league)
    declared = league_df["declared_holdout_season"][0]
    cols = ["prob_home", "prob_draw", "prob_away"]

    per_season: Dict[str, Dict[str, Any]] = {}
    for season in sorted(league_df["season"].unique().to_list()):
        rows = league_df.filter(pl.col("season") == season)
        per_season[season] = {
            "n": rows.height,
            "rps": round(
                ranked_probability_score(
                    rows["y"].to_numpy(), rows.select(cols).to_numpy()
                ),
                6,
            ),
        }

    holdout_rps = per_season.get(declared, {}).get("rps")
    for season, stats in per_season.items():
        if holdout_rps is None or season == declared:
            stats["in_sample_signature"] = False
            continue
        # Margin, not equality: seasons differ in intrinsic predictability, but
        # a full 0.02 RPS better than the only clean season is memorisation,
        # not a easier fixture list. The observed split is ~0.07, far clear of it.
        stats["in_sample_signature"] = bool(stats["rps"] < holdout_rps - 0.02)

    contaminated = sorted(s for s, v in per_season.items() if v["in_sample_signature"])
    clean = sorted(s for s, v in per_season.items() if not v["in_sample_signature"])
    return {
        "declared_holdout_season": declared,
        "per_season": per_season,
        "seasons_with_in_sample_signature": contaminated,
        "seasons_usable_as_out_of_sample": clean,
    }


def evaluate_league(df: pl.DataFrame, league: str) -> Dict[str, Any]:
    integrity = assess_temporal_integrity(df, league)
    league_df = df.filter(pl.col("league") == league)
    train_df = league_df.filter(pl.col("season") == CALIBRATION_SEASON)
    test_df = league_df.filter(pl.col("season") == TEST_SEASON)

    # Fail closed before fitting anything. A calibrator needs BOTH a clean
    # season to fit on and a clean season to be judged on. Fitting on a clean
    # season and scoring on a memorised one measures the gap between the two
    # regimes, not the calibrator -- it would report a large, confident, and
    # entirely spurious degradation.
    contaminated = set(integrity["seasons_with_in_sample_signature"])
    blocking = sorted(contaminated & {CALIBRATION_SEASON, TEST_SEASON})
    if blocking:
        logger.error(
            "%s: seasons %s carry an in-sample signature against declared holdout %s "
            "— refusing to report a calibration delta across a contaminated split",
            league,
            blocking,
            integrity["declared_holdout_season"],
        )
        return {
            "league": league,
            "status": "BLOCKED_CONTAMINATED_SPLIT",
            "blocking_seasons": blocking,
            "temporal_integrity": integrity,
        }

    if train_df.height < 50 or test_df.height < 50:
        logger.warning(
            "%s: insufficient rows (cal=%d test=%d) — skipped",
            league,
            train_df.height,
            test_df.height,
        )
        return {
            "league": league,
            "status": "SKIPPED",
            "n_cal": train_df.height,
            "n_test": test_df.height,
        }

    cols = ["prob_home", "prob_draw", "prob_away"]
    train_probs = train_df.select(cols).to_numpy()
    train_y = train_df["y"].to_numpy()
    test_probs = test_df.select(cols).to_numpy()
    test_y = test_df["y"].to_numpy()

    calibrator = VectorCalibrator().fit(train_probs, _onehot(train_y))
    cal_probs = calibrator.predict(test_probs)

    base_rps = ranked_probability_score(test_y, test_probs)
    cand_rps = ranked_probability_score(test_y, cal_probs)
    base_brier = multiclass_brier(test_y, test_probs)
    cand_brier = multiclass_brier(test_y, cal_probs)

    rps_ci = paired_block_bootstrap_ci(
        _rps_per_fixture(test_probs, test_y), _rps_per_fixture(cal_probs, test_y)
    )
    brier_ci = paired_block_bootstrap_ci(
        _brier_per_fixture(test_probs, test_y), _brier_per_fixture(cal_probs, test_y)
    )

    # §19: statistically detectable after family-wise correction, AND not a
    # regression on the sibling metric. The nominal bound is reported too, so
    # the gap between "nominally significant" and "survives correction" stays
    # visible rather than being quietly resolved one way.
    rps_improves_nominal = rps_ci["ci_upper"] is not None and rps_ci["ci_upper"] < 0.0
    rps_improves = (
        rps_ci.get("ci_upper_bonferroni") is not None
        and rps_ci["ci_upper_bonferroni"] < 0.0
    )
    brier_no_regress = (
        brier_ci["ci_lower"] is not None
        and brier_ci["ci_lower"] < 0.0
        or cand_brier <= base_brier
    )

    return {
        "league": league,
        "status": "EVALUATED",
        "n_cal": train_df.height,
        "n_test": test_df.height,
        "calibration_season": CALIBRATION_SEASON,
        "test_season": TEST_SEASON,
        "temporal_integrity": integrity,
        "base_rps": round(base_rps, 6),
        "cal_rps": round(cand_rps, 6),
        "delta_rps": rps_ci,
        "base_brier": round(base_brier, 6),
        "cal_brier": round(cand_brier, 6),
        "delta_brier": brier_ci,
        "base_ece": round(expected_calibration_error(test_y, test_probs)["mean"], 6),
        "cal_ece": round(expected_calibration_error(test_y, cal_probs)["mean"], 6),
        "weights": [round(w, 6) for w in calibrator.weights.tolist()],
        "bias": [round(b, 6) for b in calibrator.bias.tolist()],
        "optimiser_converged": calibrator.converged,
        "improves_rps_ci_excludes_zero_nominal": bool(rps_improves_nominal),
        "improves_rps_ci_excludes_zero_bonferroni": bool(rps_improves),
        "promotable": bool(rps_improves and brier_no_regress),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--regenerate", action="store_true", help="rebuild the prediction cache"
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=None,
        help="baseline directory (default: models/evaluation_baseline)",
    )
    args = parser.parse_args()

    df = build_prediction_table(force=args.regenerate, models_dir=args.models_dir)
    if df.height == 0:
        logger.error("No served predictions produced; cannot evaluate.")
        return 1

    # Fail closed if the corpus ever stops speaking canonical league ids.
    for name in df["league"].unique().to_list():
        if canonical_league_id(name) != name:
            raise ValueError(f"non-canonical league id in prediction table: {name!r}")

    leagues = sorted(df["league"].unique().to_list())
    results = [evaluate_league(df, league) for league in leagues]

    evaluated = [r for r in results if r["status"] == "EVALUATED"]
    blocked = [
        r["league"] for r in results if r["status"] == "BLOCKED_CONTAMINATED_SPLIT"
    ]
    promotable = [r["league"] for r in evaluated if r["promotable"]]
    report = {
        "experiment_id": "E0-VECTOR-MULTILEAGUE",
        "directive": "v5 §9, §18, §19, §20 B2/B3",
        "target": "base-learner average (PredictionEngine._ensemble_predict_dict shape), not the meta-model",
        "baseline": "models/evaluation_baseline (v11_clean2526) — NOT the serving manifest",
        "calibration_season": CALIBRATION_SEASON,
        "test_season": TEST_SEASON,
        "bootstrap": {
            "method": "paired non-overlapping block bootstrap (Künsch 1989)",
            "n_bootstrap": N_BOOTSTRAP,
            "block_size": BLOCK_SIZE,
            "seed": RNG_SEED,
        },
        "promotion_rule": (
            "Bonferroni family-wise CI upper bound for ΔRPS strictly < 0 "
            "(alpha 0.05 over 5 leagues) and no Brier regression"
        ),
        "leagues_promotable": promotable,
        "leagues_blocked_contaminated_split": blocked,
        "results": results,
    }

    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Report written: %s", _REPORT_PATH)

    for r in results:
        if r["status"] == "EVALUATED":
            ci = r["delta_rps"]
            logger.info(
                "  %-11s ΔRPS %+.5f  CI95 [%+.5f, %+.5f]  CI99 [%+.5f, %+.5f]  %s",
                r["league"],
                ci["mean_delta"],
                ci["ci_lower"],
                ci["ci_upper"],
                ci["ci_lower_bonferroni"],
                ci["ci_upper_bonferroni"],
                "PROMOTABLE"
                if r["promotable"]
                else (
                    "nominal only"
                    if r["improves_rps_ci_excludes_zero_nominal"]
                    else "no"
                ),
            )
        elif r["status"] == "BLOCKED_CONTAMINATED_SPLIT":
            ps = r["temporal_integrity"]["per_season"]
            logger.info(
                "  %-11s BLOCKED — declared holdout %s RPS %.4f; contaminated %s",
                r["league"],
                r["temporal_integrity"]["declared_holdout_season"],
                ps.get(r["temporal_integrity"]["declared_holdout_season"], {}).get(
                    "rps", float("nan")
                ),
                {s: ps[s]["rps"] for s in r["blocking_seasons"]},
            )
    print(
        json.dumps(
            {
                "leagues_promotable": promotable,
                "leagues_blocked_contaminated_split": blocked,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
