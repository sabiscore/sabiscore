"""Per-league calibration selection and ensemble diversity diagnostics.

Per-league method selection rule:
  n_training_rows >= 2000  →  isotonic regression (preferred; enough data to fit monotone map)
  n_training_rows <  2000  →  Platt scaling / logistic (preferred; less overfitting on small sets)
  temperature scaling       →  alternative for ECE minimisation on small held-out folds

Multi-method comparison (compare_calibration_methods):
  Runs all three methods and selects the best by:
    1. Primary: sample count drives the default candidate.
    2. Secondary: ECE delta (must not regress vs default), Brier delta (non-degrading),
       draw-F1 delta (non-degrading).
  Selection rationale + per-method comparison table persisted in calibration_report_{league}.json.

Bivariate Poisson draw overlay (BivariatePoissonDrawOverlay):
  Uses the Skellam distribution (difference of two independent Poisson) to estimate
  P(draw) = e^{-(λH+λA)} · I_0(2√(λH·λA)) where λH, λA are inferred from predicted
  probability triples and the league's expected total goal rate.
  A mixing weight α is fitted on the calibration set.
  Gate: overlay only applied when draw-F1 improves AND Brier does not degrade.
  Intended for draw-heavy leagues (Serie A, Ligue 1, Eredivisie).

Diversity diagnostics:
  - Pairwise Pearson correlation of flattened probability vectors between base learners.
  - Members whose mean off-diagonal correlation exceeds ENSEMBLE_CORRELATION_PRUNE_THRESHOLD
    are flagged. Pruning is only executed when draw-F1 does not degrade after removal.
  - Pruning rationale surfaced in calibration_report_{league}.json.

Usage (standalone):
  from backend.src.models.calibration import (
      select_calibration_method,
      compare_calibration_methods,
      fit_calibrator,
      apply_calibrator,
      compute_ece,
      run_league_calibration,
      BivariatePoissonDrawOverlay,
      EnsembleDiversityDiagnostics,
  )

All public functions accept and return plain numpy arrays so they work independently of
the SabiScoreEnsemble class hierarchy.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score

logger = logging.getLogger(__name__)

# Default thresholds — can be overridden via env var or direct argument.
_DEFAULT_ISOTONIC_MIN_ROWS: int = 2000
_DEFAULT_CORRELATION_PRUNE_THRESHOLD: float = float(
    os.environ.get("ENSEMBLE_CORRELATION_PRUNE_THRESHOLD", "0.92")
)

CalibrationMethodName = Literal["isotonic", "sigmoid", "temperature"]


# ── Method selection ─────────────────────────────────────────────────────────


def select_calibration_method(
    n_training_rows: int,
    *,
    isotonic_min_rows: int = _DEFAULT_ISOTONIC_MIN_ROWS,
    force: Optional[CalibrationMethodName] = None,
) -> CalibrationMethodName:
    """Return the recommended calibration method for a given training corpus size.

    Args:
        n_training_rows: Number of rows in the league training set.
        isotonic_min_rows: Row count threshold above which isotonic is preferred.
        force: Override the selection (for testing or manual control).
    """
    if force is not None:
        return force
    if n_training_rows >= isotonic_min_rows:
        return "isotonic"
    return "sigmoid"


# ── Calibrator dataclass ─────────────────────────────────────────────────────


@dataclass
class FittedCalibrator:
    """Fitted calibration state for a single league.

    Stores per-class isotonic or Platt calibrators (or a single temperature
    scalar) together with metadata for the calibration report.
    """

    method: CalibrationMethodName
    league: str
    n_training_rows: int
    # For isotonic/platt: one calibrator per class (list of 3 objects).
    # For temperature: single float (scale divisor).
    calibrators: object  # List[IsotonicRegression | LogisticRegression] | float
    ece_before: Dict[str, float]
    ece_after: Dict[str, float]
    brier_before: float
    brier_after: float
    draw_f1_before: float
    draw_f1_after: float
    selection_rationale: str
    # Optional: per-method comparison table from compare_calibration_methods().
    method_comparison: Optional[Dict[str, object]] = field(default=None)


# ── Core calibration helpers ─────────────────────────────────────────────────


def compute_ece(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    n_bins: int = 10,
) -> Dict[str, float]:
    """Multiclass Expected Calibration Error (per-class + mean)."""
    n_classes = y_proba.shape[1]
    n = max(len(y_true), 1)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece_per_class: Dict[str, float] = {}

    for cls in range(n_classes):
        binary = (y_true == cls).astype(float)
        probs = y_proba[:, cls]
        ece = 0.0
        for lo, hi in zip(bins[:-1], bins[1:]):
            mask = (probs > lo) & (probs <= hi)
            if mask.any():
                ece += mask.sum() * abs(binary[mask].mean() - probs[mask].mean())
        ece_per_class[f"class_{cls}"] = round(float(ece / n), 4)

    ece_per_class["mean"] = round(
        float(np.mean([ece_per_class[f"class_{i}"] for i in range(n_classes)])), 4
    )
    return ece_per_class


def _compute_brier_multiclass(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    """Multiclass Brier score: mean over samples of sum_c (p_c - 1_{y=c})^2."""
    n = len(y_true)
    if n == 0:
        return 0.0
    n_classes = y_proba.shape[1]
    y_oh = np.zeros((n, n_classes), dtype=float)
    y_oh[np.arange(n), y_true.astype(int)] = 1.0
    return float(np.mean(np.sum((y_proba - y_oh) ** 2, axis=1)))


def _draw_f1(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    y_pred = np.argmax(y_proba, axis=1)
    return float(f1_score(y_true, y_pred, labels=[1], average="macro", zero_division=0))


def fit_calibrator(
    method: CalibrationMethodName,
    y_true: np.ndarray,
    y_proba: np.ndarray,
) -> object:
    """Fit and return a calibrator from training labels and raw probabilities.

    Isotonic: one IsotonicRegression per class, fitted on binary one-vs-rest.
    Platt:    one LogisticRegression per class, fitted on binary one-vs-rest.
    Temperature: single positive scalar that minimises NLL on the validation set.
    """
    n_classes = y_proba.shape[1]

    if method in ("isotonic", "sigmoid"):
        fitted: List[object] = []
        for cls in range(n_classes):
            binary = (y_true == cls).astype(int)
            raw_cls = y_proba[:, cls]
            if method == "isotonic":
                cal = IsotonicRegression(out_of_bounds="clip")
                cal.fit(raw_cls, binary)
            else:
                # Platt scaling: logistic regression on the raw probability score.
                cal = LogisticRegression(max_iter=500)
                cal.fit(raw_cls.reshape(-1, 1), binary)
            fitted.append(cal)
        return fitted

    # Temperature scaling: grid search over T in [0.1, 10].
    best_t, best_nll = 1.0, float("inf")
    y_oh = np.eye(n_classes)[y_true.astype(int)].astype(float)
    for t in np.linspace(0.1, 10.0, 200):
        scaled = np.clip(y_proba ** (1.0 / t), 1e-8, None)
        scaled /= scaled.sum(axis=1, keepdims=True)
        nll = -float(np.mean(np.sum(y_oh * np.log(scaled), axis=1)))
        if nll < best_nll:
            best_nll = nll
            best_t = float(t)
    return best_t


def _platt_probability(cal: object, raw: np.ndarray) -> np.ndarray:
    """P(positive class) for a Platt calibrator, without calling scikit-learn.

    A binary ``LogisticRegression`` fitted under one scikit-learn and unpickled
    under another deserialises with ``coef_``/``intercept_`` fully intact, but
    1.3.2's ``predict_proba`` body reads ``self.multi_class`` -- an attribute 1.7+
    no longer sets -- so the call dies with ``AttributeError: 'LogisticRegression'
    object has no attribute 'multi_class'``. Artifacts are fitted on a developer
    machine (3.14 / sklearn 1.8) and served on Render (3.11 / sklearn 1.3.2), so
    every sigmoid calibrator was rejected at startup by
    ``PredictionEngine._usable_calibrator`` and all six leagues served
    ``calibration_method="raw"`` -- measured live at ECE 10.51% against the ≤3%
    certification ceiling (docs/DEBT.md items 113, 133).

    ``src/core/meta_model.py`` already removed this exact coupling from the
    stacking head by storing plain coefficients; this is the same move one layer
    over. For binary LR on a single feature, sklearn's own definition is
    ``predict_proba(x)[:, 1] == sigmoid(x @ coef_.T + intercept_)``, so this is
    an identity, not an approximation -- verified bit-for-bit (max abs delta
    0.0e+00 over a 501-point sweep x 3 classes) against the committed
    bundesliga/ligue_1 artifacts.

    Falls back to ``predict_proba`` for anything not shaped like a fitted binary
    LR (so an isotonic or future calibrator type is unaffected).
    """
    coef = getattr(cal, "coef_", None)
    intercept = getattr(cal, "intercept_", None)
    if coef is None or intercept is None:
        return cal.predict_proba(raw.reshape(-1, 1))[:, 1]  # type: ignore[attr-defined]

    coef_arr = np.asarray(coef, dtype=np.float64).ravel()
    intercept_arr = np.asarray(intercept, dtype=np.float64).ravel()
    if coef_arr.size != 1 or intercept_arr.size != 1:
        # Not the single-feature binary shape fit_calibrator produces; let
        # scikit-learn own it rather than guessing at a decision function.
        return cal.predict_proba(raw.reshape(-1, 1))[:, 1]  # type: ignore[attr-defined]

    # Clip the logit before exp() so a steep fitted slope cannot overflow.
    logit = np.clip(coef_arr[0] * np.asarray(raw, dtype=np.float64) + intercept_arr[0], -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-logit))


def apply_calibrator(
    method: CalibrationMethodName,
    calibrators: object,
    y_proba: np.ndarray,
) -> np.ndarray:
    """Apply a fitted calibrator to raw probability predictions.

    Returns renormalised probabilities [n_samples, n_classes].
    """
    y_proba.shape[1]

    if method == "temperature":
        t = float(calibrators)  # type: ignore[arg-type]
        scaled = np.clip(y_proba ** (1.0 / t), 1e-8, None)
        scaled /= scaled.sum(axis=1, keepdims=True)
        return scaled

    # isotonic / platt
    cal_list: List[object] = calibrators  # type: ignore[assignment]
    out = np.zeros_like(y_proba)
    for cls, cal in enumerate(cal_list):
        raw = y_proba[:, cls]
        if method == "isotonic":
            out[:, cls] = np.clip(cal.predict(raw), 0.0, 1.0)
        else:
            out[:, cls] = np.clip(_platt_probability(cal, raw), 0.0, 1.0)

    row_sums = out.sum(axis=1, keepdims=True)
    out /= np.where(row_sums > 0, row_sums, 1.0)
    return out


# ── Per-league calibration run ────────────────────────────────────────────────


def run_league_calibration(
    league: str,
    y_train: np.ndarray,
    proba_train: np.ndarray,
    y_val: np.ndarray,
    proba_val: np.ndarray,
    *,
    isotonic_min_rows: int = _DEFAULT_ISOTONIC_MIN_ROWS,
    force_method: Optional[CalibrationMethodName] = None,
) -> FittedCalibrator:
    """Select method, fit on train, evaluate on val, return FittedCalibrator.

    Args:
        league: League identifier (e.g. "epl").
        y_train: Integer class labels [0,1,2] for the calibration training set.
        proba_train: Raw ensemble probabilities [n_train, 3].
        y_val: Integer class labels for the validation set.
        proba_val: Raw ensemble probabilities [n_val, 3].
        isotonic_min_rows: Row count threshold for isotonic vs Platt.
        force_method: Override automatic selection.

    Returns:
        FittedCalibrator with ece_before, ece_after, draw_f1 deltas, and rationale.
    """
    n = len(y_train)
    method = select_calibration_method(
        n, isotonic_min_rows=isotonic_min_rows, force=force_method
    )

    rationale_parts = [
        f"n_training_rows={n}",
        f"threshold={isotonic_min_rows}",
        f"selected={method}",
    ]
    if force_method:
        rationale_parts.append("forced=True")

    ece_before = compute_ece(y_val, proba_val)
    brier_before = _compute_brier_multiclass(y_val, proba_val)
    draw_f1_before = _draw_f1(y_val, proba_val)

    try:
        calibrators = fit_calibrator(method, y_train, proba_train)
        proba_cal = apply_calibrator(method, calibrators, proba_val)
        ece_after = compute_ece(y_val, proba_cal)
        brier_after = _compute_brier_multiclass(y_val, proba_cal)
        draw_f1_after = _draw_f1(y_val, proba_cal)
    except Exception as exc:
        logger.warning(
            "[calibration] %s: %s fit failed — falling back to identity. %s",
            league,
            method,
            exc,
        )
        calibrators = None
        ece_after = ece_before
        brier_after = brier_before
        draw_f1_after = draw_f1_before
        rationale_parts.append(f"fallback=identity reason={exc}")

    rationale = "; ".join(rationale_parts)
    logger.info(
        "[calibration] %s: method=%s ece_before=%.4f ece_after=%.4f "
        "brier_before=%.4f brier_after=%.4f "
        "draw_f1_before=%.4f draw_f1_after=%.4f",
        league,
        method,
        ece_before["mean"],
        ece_after["mean"],
        brier_before,
        brier_after,
        draw_f1_before,
        draw_f1_after,
    )

    return FittedCalibrator(
        method=method,
        league=league,
        n_training_rows=n,
        calibrators=calibrators,
        ece_before=ece_before,
        ece_after=ece_after,
        brier_before=round(brier_before, 4),
        brier_after=round(brier_after, 4),
        draw_f1_before=round(draw_f1_before, 4),
        draw_f1_after=round(draw_f1_after, 4),
        selection_rationale=rationale,
    )


# ── Multi-method comparison ───────────────────────────────────────────────────


def compare_calibration_methods(
    league: str,
    y_train: np.ndarray,
    proba_train: np.ndarray,
    y_val: np.ndarray,
    proba_val: np.ndarray,
    *,
    isotonic_min_rows: int = _DEFAULT_ISOTONIC_MIN_ROWS,
) -> FittedCalibrator:
    """Run all three calibration methods and select the best one.

    Selection logic:
      1. Default candidate: sample-count rule (isotonic ≥2000, platt <2000).
      2. For each alternative method, accept it only when ALL of:
           - ece_delta_mean ≤ default_ece_delta_mean (no ECE regression)
           - brier_after ≤ default_brier_after (no Brier regression)
           - draw_f1_after ≥ default_draw_f1_after (no draw-F1 degradation)
      3. If an alternative beats the default on ECE + Brier without draw-F1
         degradation, it is promoted to the selected method.
      4. The full per-method comparison table is embedded in the returned
         FittedCalibrator.method_comparison for persistence in the report.

    Returns a FittedCalibrator for the selected method with method_comparison
    populated.
    """
    all_methods: List[CalibrationMethodName] = ["isotonic", "sigmoid", "temperature"]
    n = len(y_train)

    ece_before = compute_ece(y_val, proba_val)
    brier_before = _compute_brier_multiclass(y_val, proba_val)
    draw_f1_before = _draw_f1(y_val, proba_val)

    comparison_table: Dict[str, Dict[str, object]] = {}
    method_results: Dict[CalibrationMethodName, Dict[str, object]] = {}

    for m in all_methods:
        try:
            cal = fit_calibrator(m, y_train, proba_train)
            proba_cal = apply_calibrator(m, cal, proba_val)
            ece_after = compute_ece(y_val, proba_cal)
            brier_after = _compute_brier_multiclass(y_val, proba_cal)
            draw_f1_after = _draw_f1(y_val, proba_cal)
            method_results[m] = {
                "calibrators": cal,
                "ece_after": ece_after,
                "brier_after": round(brier_after, 4),
                "draw_f1_after": round(draw_f1_after, 4),
                "ece_delta_mean": round(ece_after["mean"] - ece_before["mean"], 4),
                "brier_delta": round(brier_after - brier_before, 4),
                "draw_f1_delta": round(draw_f1_after - draw_f1_before, 4),
                "fit_error": None,
            }
        except Exception as exc:
            method_results[m] = {
                "calibrators": None,
                "ece_after": ece_before,
                "brier_after": round(brier_before, 4),
                "draw_f1_after": round(draw_f1_before, 4),
                "ece_delta_mean": 0.0,
                "brier_delta": 0.0,
                "draw_f1_delta": 0.0,
                "fit_error": str(exc),
            }

    for m, r in method_results.items():
        comparison_table[m] = {k: v for k, v in r.items() if k != "calibrators"}

    # Default candidate from sample-count rule.
    default_method = select_calibration_method(n, isotonic_min_rows=isotonic_min_rows)
    selected_method = default_method
    default_res = method_results[default_method]

    for m in all_methods:
        if m == default_method:
            continue
        r = method_results[m]
        if r["fit_error"] is not None:
            continue
        # Promote only when strictly better on ECE + Brier AND draw-F1 non-degrading.
        if (
            r["ece_delta_mean"] <= default_res["ece_delta_mean"]
            and r["brier_after"] <= default_res["brier_after"]
            and r["draw_f1_after"] >= default_res["draw_f1_after"]
        ):
            selected_method = m
            default_res = r
            logger.info(
                "[calibration] %s: promoted %s over %s "
                "(ece_delta=%.4f brier_after=%.4f draw_f1_after=%.4f)",
                league,
                m,
                selected_method,
                r["ece_delta_mean"],
                r["brier_after"],
                r["draw_f1_after"],
            )

    sel = method_results[selected_method]
    rationale_parts = [
        f"n_training_rows={n}",
        f"threshold={isotonic_min_rows}",
        f"default_candidate={default_method}",
        f"selected={selected_method}",
    ]
    if selected_method != default_method:
        rationale_parts.append("promoted_by_multi_method_comparison=True")

    logger.info(
        "[calibration] %s: compare_methods selected=%s "
        "ece_delta=%.4f brier_delta=%.4f draw_f1_delta=%.4f",
        league,
        selected_method,
        sel["ece_delta_mean"],
        sel["brier_delta"],
        sel["draw_f1_delta"],
    )

    return FittedCalibrator(
        method=selected_method,
        league=league,
        n_training_rows=n,
        calibrators=sel["calibrators"],
        ece_before=ece_before,
        ece_after=sel["ece_after"],
        brier_before=round(brier_before, 4),
        brier_after=sel["brier_after"],
        draw_f1_before=round(draw_f1_before, 4),
        draw_f1_after=sel["draw_f1_after"],
        selection_rationale="; ".join(rationale_parts),
        method_comparison=comparison_table,
    )


# ── Bivariate Poisson draw overlay ────────────────────────────────────────────


@dataclass
class BivariatePoissonDrawOverlay:
    """Skellam-based draw probability blending for draw-heavy leagues.

    Uses the Skellam distribution P(X - Y = 0) = e^{-(λH+λA)} · I_0(2√(λH·λA))
    to compute an alternative draw probability estimate, then blends it with the
    ensemble's predicted draw probability via a fitted mixing weight α.

    Infers λH and λA from predicted probability triples:
      - Total goal rate λ_total = league_avg_goals (default 2.65).
      - Split: λH = λ_total · p_home / (p_home + p_away + ε)
               λA = λ_total · p_away / (p_home + p_away + ε)
      - When p_home ≈ p_away the lambdas converge → higher Skellam draw probability.

    Gate: overlay is applied only when, on a GENUINELY DISJOINT holdout set:
      - draw_f1_after ≥ draw_f1_before (non-degrading)
      - brier_after ≤ brier_before (non-degrading)
    If either gate fails, alpha is set to 0.0 (no blending, identity).

    ⚠️ The gate is evaluated on `holdout`, never on the `calibration` set alpha
    was grid-searched against — the same circular-evaluation defect
    docs/DEBT.md item 64 found and fixed for temperature/isotonic selection in
    `scripts/train_on_real_matches.py::_select_calibrator`. A small alpha grid
    minimising draw-NLL on a set, then graded against its own draw-F1/Brier on
    that identical set, is expected to look good regardless of whether the
    blend generalises. This class had no production caller when that defect
    was found (`src/models/prediction.py`'s consumer path requires a
    `bivariate_poisson_overlay` key nothing currently trains — see
    docs/DEBT.md item 71), so fixing it here changed no served behaviour.

    Attributes:
        alpha: Mixing weight ∈ [0, 1].  blended_draw = (1-α)·model + α·skellam.
        league_avg_goals: Total expected goals used to estimate lambdas.
        calibration_draw_f1_before: Draw-F1 before overlay, on the set alpha was fit to.
        calibration_draw_f1_after:  Draw-F1 after overlay, on that same set.
        calibration_brier_before:   Multiclass Brier before overlay, on that same set.
        calibration_brier_after:    Multiclass Brier after overlay, on that same set.
        holdout_draw_f1_before: Draw-F1 before overlay, on the disjoint holdout — what the gate reads.
        holdout_draw_f1_after:  Draw-F1 after overlay, on the disjoint holdout.
        holdout_brier_before:   Multiclass Brier before overlay, on the disjoint holdout.
        holdout_brier_after:    Multiclass Brier after overlay, on the disjoint holdout.
        gate_passed: True when both F1 and Brier gates were met ON THE HOLDOUT.
    """

    alpha: float = 0.0
    league_avg_goals: float = 2.65
    calibration_draw_f1_before: float = 0.0
    calibration_draw_f1_after: float = 0.0
    calibration_brier_before: float = 0.0
    calibration_brier_after: float = 0.0
    holdout_draw_f1_before: float = 0.0
    holdout_draw_f1_after: float = 0.0
    holdout_brier_before: float = 0.0
    holdout_brier_after: float = 0.0
    gate_passed: bool = False

    @staticmethod
    def _skellam_draw_proba(
        y_proba: np.ndarray,
        league_avg_goals: float,
    ) -> np.ndarray:
        """Return Skellam P(draw) for each row in y_proba [n, 3].

        Requires scipy.special.iv (modified Bessel function of first kind).
        Falls back to uniform draw prior (1/3) if scipy unavailable.
        """
        try:
            from scipy.special import iv as bessel_i0_fn  # type: ignore
        except ImportError:
            return np.full(len(y_proba), 1.0 / 3.0)

        p_home = np.clip(y_proba[:, 0], 1e-9, 1.0)
        p_away = np.clip(y_proba[:, 2], 1e-9, 1.0)
        denom = p_home + p_away
        lam_h = league_avg_goals * p_home / denom
        lam_a = league_avg_goals * p_away / denom
        # Skellam P(diff=0): e^{-(λH+λA)} · I_0(2√(λH·λA))
        p_draw_sk = np.exp(-(lam_h + lam_a)) * bessel_i0_fn(
            0, 2.0 * np.sqrt(lam_h * lam_a)
        )
        return np.clip(p_draw_sk, 0.0, 1.0)

    def _blend(self, y_proba: np.ndarray) -> np.ndarray:
        """Apply Skellam blend and renormalise rows to sum=1."""
        if self.alpha <= 0.0:
            return y_proba
        sk_draw = self._skellam_draw_proba(y_proba, self.league_avg_goals)
        blended = y_proba.copy()
        blended[:, 1] = (1.0 - self.alpha) * y_proba[:, 1] + self.alpha * sk_draw
        row_sums = blended.sum(axis=1, keepdims=True)
        blended /= np.where(row_sums > 0, row_sums, 1.0)
        return blended

    @classmethod
    def fit(
        cls,
        y_calibration: np.ndarray,
        proba_calibration: np.ndarray,
        *,
        y_holdout: np.ndarray,
        proba_holdout: np.ndarray,
        league_avg_goals: float = 2.65,
        n_alpha_steps: int = 51,
    ) -> "BivariatePoissonDrawOverlay":
        """Fit α on the calibration set; gate on a genuinely disjoint holdout.

        Alpha is grid-searched to minimise draw-class NLL on
        `(y_calibration, proba_calibration)` — the set it is allowed to overfit.
        The accept/reject gate (draw-F1 non-degrading AND Brier non-degrading)
        is then measured on `(y_holdout, proba_holdout)`, a set alpha never saw.
        Returns an instance with alpha=0.0 (identity) when the holdout gate is
        not passed, regardless of how well the calibration set scored.
        """
        calibration_brier_before = _compute_brier_multiclass(
            y_calibration, proba_calibration
        )
        calibration_draw_f1_before = _draw_f1(y_calibration, proba_calibration)

        sk_draw_calibration = cls._skellam_draw_proba(
            proba_calibration, league_avg_goals
        )

        best_alpha = 0.0
        best_nll = float("inf")
        eps = 1e-9
        draw_mask = y_calibration == 1

        for alpha in np.linspace(0.0, 1.0, n_alpha_steps):
            blended_draw = (1.0 - alpha) * proba_calibration[
                :, 1
            ] + alpha * sk_draw_calibration
            blended = proba_calibration.copy()
            blended[:, 1] = blended_draw
            row_sums = blended.sum(axis=1, keepdims=True)
            blended /= np.where(row_sums > 0, row_sums, 1.0)
            # Optimise on draw-class NLL.
            draw_probs = np.clip(blended[draw_mask, 1], eps, 1.0 - eps)
            nll = (
                -float(np.mean(np.log(draw_probs))) if draw_mask.any() else float("inf")
            )
            if nll < best_nll:
                best_nll = nll
                best_alpha = float(alpha)

        # Report calibration-set before/after for audit (not the gate).
        candidate = cls(alpha=best_alpha, league_avg_goals=league_avg_goals)
        calibration_blended = candidate._blend(proba_calibration)
        calibration_brier_after = _compute_brier_multiclass(
            y_calibration, calibration_blended
        )
        calibration_draw_f1_after = _draw_f1(y_calibration, calibration_blended)

        # Gate on the disjoint holdout — this decides whether alpha ships.
        holdout_brier_before = _compute_brier_multiclass(y_holdout, proba_holdout)
        holdout_draw_f1_before = _draw_f1(y_holdout, proba_holdout)
        holdout_blended = candidate._blend(proba_holdout)
        holdout_brier_after = _compute_brier_multiclass(y_holdout, holdout_blended)
        holdout_draw_f1_after = _draw_f1(y_holdout, holdout_blended)

        gate_passed = (
            holdout_draw_f1_after >= holdout_draw_f1_before
            and holdout_brier_after <= holdout_brier_before
        )

        if not gate_passed:
            logger.info(
                "[bivariate_poisson] holdout gate not passed — alpha reset to 0.0 "
                "(calibration draw_f1 %.4f→%.4f brier %.4f→%.4f; "
                "holdout draw_f1 %.4f→%.4f brier %.4f→%.4f)",
                calibration_draw_f1_before,
                calibration_draw_f1_after,
                calibration_brier_before,
                calibration_brier_after,
                holdout_draw_f1_before,
                holdout_draw_f1_after,
                holdout_brier_before,
                holdout_brier_after,
            )
            best_alpha = 0.0
            holdout_brier_after = holdout_brier_before
            holdout_draw_f1_after = holdout_draw_f1_before
        else:
            logger.info(
                "[bivariate_poisson] holdout gate passed — alpha=%.3f "
                "holdout draw_f1 %.4f→%.4f brier %.4f→%.4f",
                best_alpha,
                holdout_draw_f1_before,
                holdout_draw_f1_after,
                holdout_brier_before,
                holdout_brier_after,
            )

        return cls(
            alpha=round(best_alpha, 4),
            league_avg_goals=league_avg_goals,
            calibration_draw_f1_before=round(calibration_draw_f1_before, 4),
            calibration_draw_f1_after=round(calibration_draw_f1_after, 4),
            calibration_brier_before=round(calibration_brier_before, 4),
            calibration_brier_after=round(calibration_brier_after, 4),
            holdout_draw_f1_before=round(holdout_draw_f1_before, 4),
            holdout_draw_f1_after=round(holdout_draw_f1_after, 4),
            holdout_brier_before=round(holdout_brier_before, 4),
            holdout_brier_after=round(holdout_brier_after, 4),
            gate_passed=gate_passed,
        )

    def apply(self, y_proba: np.ndarray) -> np.ndarray:
        """Apply the fitted Skellam blend to a probability matrix [n, 3]."""
        return self._blend(y_proba)


def write_bivariate_poisson_report(
    overlay: BivariatePoissonDrawOverlay,
    league: str,
    output_dir: Path,
) -> Path:
    """Persist Bivariate Poisson overlay metadata as bivariate_poisson_{league}.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "league": league,
        "alpha": overlay.alpha,
        "league_avg_goals": overlay.league_avg_goals,
        "calibration_draw_f1_before": overlay.calibration_draw_f1_before,
        "calibration_draw_f1_after": overlay.calibration_draw_f1_after,
        "calibration_brier_before": overlay.calibration_brier_before,
        "calibration_brier_after": overlay.calibration_brier_after,
        "holdout_draw_f1_before": overlay.holdout_draw_f1_before,
        "holdout_draw_f1_after": overlay.holdout_draw_f1_after,
        "holdout_draw_f1_delta": round(
            overlay.holdout_draw_f1_after - overlay.holdout_draw_f1_before, 4
        ),
        "holdout_brier_before": overlay.holdout_brier_before,
        "holdout_brier_after": overlay.holdout_brier_after,
        "holdout_brier_delta": round(
            overlay.holdout_brier_after - overlay.holdout_brier_before, 4
        ),
        "gate_passed": overlay.gate_passed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = output_dir / f"bivariate_poisson_{league}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("[bivariate_poisson] report written → %s", path)
    return path


# ── Calibration report persistence ───────────────────────────────────────────


def write_calibration_report(
    fc: FittedCalibrator,
    output_dir: Path,
) -> Path:
    """Persist calibration metadata as calibration_report_{league}.json.

    The calibrator objects themselves are NOT serialised here (joblib artifact
    handles that). This JSON is the human-readable audit trail for gate review.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    report: Dict[str, object] = {
        "league": fc.league,
        "method": fc.method,
        "n_training_rows": fc.n_training_rows,
        "selection_rationale": fc.selection_rationale,
        "ece_before": fc.ece_before,
        "ece_after": fc.ece_after,
        "ece_delta_mean": round(fc.ece_after["mean"] - fc.ece_before["mean"], 4),
        "brier_before": fc.brier_before,
        "brier_after": fc.brier_after,
        "brier_delta": round(fc.brier_after - fc.brier_before, 4),
        "draw_f1_before": fc.draw_f1_before,
        "draw_f1_after": fc.draw_f1_after,
        "draw_f1_delta": round(fc.draw_f1_after - fc.draw_f1_before, 4),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_date": date.today().isoformat(),
    }
    if fc.method_comparison is not None:
        report["method_comparison"] = fc.method_comparison
    path = output_dir / f"calibration_report_{fc.league}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("[calibration] report written → %s", path)
    return path


# ── Ensemble diversity diagnostics ────────────────────────────────────────────


@dataclass
class DiversityReport:
    """Pairwise correlation summary and pruning decisions for a league's ensemble."""

    league: str
    member_names: List[str]
    correlation_matrix: List[List[float]]  # [n_members, n_members]
    mean_off_diagonal_correlation: float
    pruning_threshold: float
    flagged_members: List[str]  # members above threshold (candidate for pruning)
    pruned_members: List[str]  # members actually pruned (draw-F1 gate passed)
    retained_members: List[str]  # members kept after pruning
    pruning_rationale: Dict[str, str]  # member → reason kept/removed


class EnsembleDiversityDiagnostics:
    """Compute pairwise correlation and prune redundant base learners.

    Correlation is computed on flattened probability vectors from a held-out set.
    Two learners are considered redundant when their Pearson r exceeds the
    configured threshold AND removing one does not degrade draw-F1.
    """

    def __init__(
        self,
        prune_threshold: float = _DEFAULT_CORRELATION_PRUNE_THRESHOLD,
    ) -> None:
        self.prune_threshold = prune_threshold

    def pairwise_correlation(
        self,
        models: Dict[str, object],
        X: np.ndarray,
    ) -> Tuple[List[str], np.ndarray]:
        """Compute pairwise Pearson correlation of flattened probability vectors.

        Returns (member_names, correlation_matrix [n_members, n_members]).
        """
        names: List[str] = list(models.keys())
        proba_vecs: List[np.ndarray] = []
        for name in names:
            model = models[name]
            p = model.predict_proba(X)  # [n, 3]
            proba_vecs.append(p.ravel())  # flatten to [n*3]

        n = len(names)
        corr = np.zeros((n, n), dtype=float)
        for i in range(n):
            for j in range(n):
                if i == j:
                    corr[i, j] = 1.0
                else:
                    r = float(np.corrcoef(proba_vecs[i], proba_vecs[j])[0, 1])
                    corr[i, j] = round(r, 4)
        return names, corr

    def flag_redundant(
        self,
        names: List[str],
        corr: np.ndarray,
    ) -> List[str]:
        """Return names of members whose max off-diagonal correlation exceeds threshold."""
        flagged: List[str] = []
        n = len(names)
        for i in range(n):
            off_diag = [corr[i, j] for j in range(n) if j != i]
            if off_diag and max(off_diag) > self.prune_threshold:
                flagged.append(names[i])
        return flagged

    def prune_if_safe(
        self,
        models: Dict[str, object],
        X_holdout: np.ndarray,
        y_holdout: np.ndarray,
        names: List[str],
        corr: np.ndarray,
        flagged: List[str],
    ) -> Tuple[Dict[str, object], Dict[str, str]]:
        """Prune flagged members only when draw-F1 is non-degrading after removal.

        Returns (pruned_models_dict, rationale_dict).
        """
        if not flagged:
            return models, {n: "retained: not flagged" for n in names}

        # Baseline draw-F1 with all members.
        all_proba = np.mean(
            [models[n].predict_proba(X_holdout) for n in models], axis=0
        )
        baseline_draw_f1 = _draw_f1(y_holdout, all_proba)

        retained = dict(models)
        rationale: Dict[str, str] = {
            n: "retained: below threshold" for n in names if n not in flagged
        }

        for candidate in flagged:
            without = {k: v for k, v in retained.items() if k != candidate}
            if not without:
                rationale[candidate] = "retained: last remaining member"
                continue
            pruned_proba = np.mean(
                [without[n].predict_proba(X_holdout) for n in without], axis=0
            )
            pruned_draw_f1 = _draw_f1(y_holdout, pruned_proba)
            if pruned_draw_f1 >= baseline_draw_f1:
                rationale[candidate] = (
                    f"pruned: max_corr>{self.prune_threshold:.2f}, "
                    f"draw_f1 non-degrading ({pruned_draw_f1:.4f}>={baseline_draw_f1:.4f})"
                )
                retained = without
                baseline_draw_f1 = pruned_draw_f1
                logger.info(
                    "[diversity] pruned %s — draw_f1=%.4f", candidate, pruned_draw_f1
                )
            else:
                rationale[candidate] = (
                    f"retained: pruning would degrade draw_f1 "
                    f"({pruned_draw_f1:.4f} < {baseline_draw_f1:.4f})"
                )

        return retained, rationale

    def run(
        self,
        league: str,
        models: Dict[str, object],
        X_holdout: np.ndarray,
        y_holdout: np.ndarray,
    ) -> Tuple[Dict[str, object], DiversityReport]:
        """Full diversity diagnostic pipeline for one league.

        Returns (retained_models, DiversityReport).
        """
        names, corr = self.pairwise_correlation(models, X_holdout)
        n = len(names)

        # Mean off-diagonal correlation.
        off_diag_vals = [corr[i, j] for i in range(n) for j in range(n) if i != j]
        mean_off_diag = round(
            float(np.mean(off_diag_vals)) if off_diag_vals else 0.0, 4
        )

        flagged = self.flag_redundant(names, corr)
        retained_models, rationale = self.prune_if_safe(
            models, X_holdout, y_holdout, names, corr, flagged
        )
        pruned = [n for n in names if n not in retained_models]
        retained = list(retained_models.keys())

        report = DiversityReport(
            league=league,
            member_names=names,
            correlation_matrix=corr.tolist(),
            mean_off_diagonal_correlation=mean_off_diag,
            pruning_threshold=self.prune_threshold,
            flagged_members=flagged,
            pruned_members=pruned,
            retained_members=retained,
            pruning_rationale=rationale,
        )

        if flagged:
            logger.info(
                "[diversity] %s: flagged=%s pruned=%s retained=%s mean_off_diag=%.4f",
                league,
                flagged,
                pruned,
                retained,
                mean_off_diag,
            )
        else:
            logger.info(
                "[diversity] %s: no redundant members (mean_off_diag=%.4f < threshold=%.2f)",
                league,
                mean_off_diag,
                self.prune_threshold,
            )

        return retained_models, report


def write_diversity_report(
    report: DiversityReport,
    output_dir: Path,
) -> Path:
    """Persist diversity diagnostic results as diversity_report_{league}.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "league": report.league,
        "member_names": report.member_names,
        "correlation_matrix": report.correlation_matrix,
        "mean_off_diagonal_correlation": report.mean_off_diagonal_correlation,
        "pruning_threshold": report.pruning_threshold,
        "flagged_members": report.flagged_members,
        "pruned_members": report.pruned_members,
        "retained_members": report.retained_members,
        "pruning_rationale": report.pruning_rationale,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = output_dir / f"diversity_report_{report.league}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("[diversity] report written → %s", path)
    return path
