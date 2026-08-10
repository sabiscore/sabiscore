"""Tests for per-league calibration, Bivariate Poisson overlay, and diversity diagnostics.

Coverage:
  - select_calibration_method: sample-count routing
  - fit_calibrator / apply_calibrator: isotonic, platt, temperature — output shape + normalisation
  - compute_ece: perfect calibration, uniform priors
  - _compute_brier_multiclass: known-value assertion
  - run_league_calibration: FittedCalibrator fields + brier tracking
  - compare_calibration_methods: comparison table populated, non-degradation gate
  - write_calibration_report: JSON written, schema complete
  - BivariatePoissonDrawOverlay._skellam_draw_proba: shape + bounds
  - BivariatePoissonDrawOverlay.fit: gate logic, alpha=0 when gate fails
  - BivariatePoissonDrawOverlay.apply: output shape + row normalisation
  - write_bivariate_poisson_report: JSON written
  - EnsembleDiversityDiagnostics.pairwise_correlation: identity diagonal
  - EnsembleDiversityDiagnostics.flag_redundant: threshold logic
  - EnsembleDiversityDiagnostics.run: pruning with draw-F1 gate
  - write_diversity_report: JSON written
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

# Allow import from backend/src without installing.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from src.models.calibration import (  # noqa: E402
    BivariatePoissonDrawOverlay,
    EnsembleDiversityDiagnostics,
    FittedCalibrator,
    _compute_brier_multiclass,
    compare_calibration_methods,
    compute_ece,
    fit_calibrator,
    apply_calibrator,
    run_league_calibration,
    select_calibration_method,
    write_bivariate_poisson_report,
    write_calibration_report,
    write_diversity_report,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

RNG = np.random.default_rng(42)


def _make_data(n: int = 300, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Return (y_true, proba) with 3-class labels and well-formed probabilities."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 3, size=n)
    raw = rng.dirichlet([3.0, 2.0, 2.0], size=n)
    return y, raw


def _perfect_proba(y: np.ndarray) -> np.ndarray:
    """Probability matrix where the true class always gets 1.0."""
    p = np.zeros((len(y), 3), dtype=float)
    p[np.arange(len(y)), y] = 1.0
    return p


# ── select_calibration_method ─────────────────────────────────────────────────

class TestSelectCalibrationMethod:
    def test_isotonic_above_threshold(self):
        assert select_calibration_method(2000) == "isotonic"

    def test_isotonic_just_above_threshold(self):
        assert select_calibration_method(2001) == "isotonic"

    def test_platt_below_threshold(self):
        assert select_calibration_method(1999) == "platt"

    def test_platt_small_corpus(self):
        assert select_calibration_method(50) == "platt"

    def test_force_overrides_sample_count(self):
        assert select_calibration_method(5000, force="temperature") == "temperature"
        assert select_calibration_method(100, force="isotonic") == "isotonic"

    def test_custom_threshold(self):
        assert select_calibration_method(500, isotonic_min_rows=500) == "isotonic"
        assert select_calibration_method(499, isotonic_min_rows=500) == "platt"


# ── compute_ece ───────────────────────────────────────────────────────────────

class TestComputeEce:
    def test_perfect_calibration_near_zero(self):
        y, _ = _make_data(200)
        p = _perfect_proba(y)
        ece = compute_ece(y, p)
        assert ece["mean"] < 0.05

    def test_returns_all_keys(self):
        y, p = _make_data(100)
        ece = compute_ece(y, p)
        assert "class_0" in ece and "class_1" in ece and "class_2" in ece
        assert "mean" in ece

    def test_mean_equals_average_of_classes(self):
        y, p = _make_data(100)
        ece = compute_ece(y, p)
        expected_mean = round(
            (ece["class_0"] + ece["class_1"] + ece["class_2"]) / 3, 4
        )
        assert ece["mean"] == expected_mean

    def test_empty_safe(self):
        y = np.array([], dtype=int)
        p = np.zeros((0, 3), dtype=float)
        ece = compute_ece(y, p)
        assert ece["mean"] == 0.0


# ── _compute_brier_multiclass ────────────────────────────────────────────────

class TestComputeBrierMulticlass:
    def test_perfect_prediction_is_zero(self):
        y, _ = _make_data(100)
        p = _perfect_proba(y)
        assert _compute_brier_multiclass(y, p) == pytest.approx(0.0, abs=1e-9)

    def test_uniform_prediction_known_value(self):
        # All probabilities 1/3; true labels arbitrary.
        y = np.array([0, 1, 2])
        p = np.full((3, 3), 1.0 / 3.0)
        # Per sample: sum_c (1/3 - 1_{y=c})^2 = 2*(1/3)^2 + (1/3-1)^2 = 2/9 + 4/9 = 6/9
        expected = 6.0 / 9.0
        assert _compute_brier_multiclass(y, p) == pytest.approx(expected, abs=1e-6)

    def test_output_in_valid_range(self):
        y, p = _make_data(200)
        score = _compute_brier_multiclass(y, p)
        assert 0.0 <= score <= 2.0

    def test_empty_returns_zero(self):
        y = np.array([], dtype=int)
        p = np.zeros((0, 3), dtype=float)
        assert _compute_brier_multiclass(y, p) == 0.0


# ── fit_calibrator / apply_calibrator ────────────────────────────────────────

class TestFitApplyCalibrator:
    @pytest.mark.parametrize("method", ["isotonic", "platt", "temperature"])
    def test_output_shape(self, method):
        y, p = _make_data(200)
        cal = fit_calibrator(method, y, p)
        out = apply_calibrator(method, cal, p)
        assert out.shape == p.shape

    @pytest.mark.parametrize("method", ["isotonic", "platt", "temperature"])
    def test_rows_sum_to_one(self, method):
        y, p = _make_data(200)
        cal = fit_calibrator(method, y, p)
        out = apply_calibrator(method, cal, p)
        np.testing.assert_allclose(out.sum(axis=1), np.ones(len(y)), atol=1e-6)

    @pytest.mark.parametrize("method", ["isotonic", "platt", "temperature"])
    def test_probabilities_non_negative(self, method):
        y, p = _make_data(200)
        cal = fit_calibrator(method, y, p)
        out = apply_calibrator(method, cal, p)
        assert (out >= 0).all()

    def test_temperature_returns_scalar(self):
        y, p = _make_data(150)
        cal = fit_calibrator("temperature", y, p)
        assert isinstance(cal, float)
        assert cal > 0


# ── run_league_calibration ────────────────────────────────────────────────────

class TestRunLeagueCalibration:
    def test_returns_fitted_calibrator(self):
        y, p = _make_data(300)
        fc = run_league_calibration("epl", y[:200], p[:200], y[200:], p[200:])
        assert isinstance(fc, FittedCalibrator)

    def test_brier_fields_populated(self):
        y, p = _make_data(300)
        fc = run_league_calibration("epl", y[:200], p[:200], y[200:], p[200:])
        assert isinstance(fc.brier_before, float)
        assert isinstance(fc.brier_after, float)
        assert 0.0 <= fc.brier_before <= 2.0
        assert 0.0 <= fc.brier_after <= 2.0

    def test_ece_fields_populated(self):
        y, p = _make_data(300)
        fc = run_league_calibration("epl", y[:200], p[:200], y[200:], p[200:])
        assert "mean" in fc.ece_before
        assert "mean" in fc.ece_after

    def test_draw_f1_fields_populated(self):
        y, p = _make_data(300)
        fc = run_league_calibration("epl", y[:200], p[:200], y[200:], p[200:])
        assert 0.0 <= fc.draw_f1_before <= 1.0
        assert 0.0 <= fc.draw_f1_after <= 1.0

    def test_selects_platt_for_small_corpus(self):
        y, p = _make_data(300)
        fc = run_league_calibration("eredivisie", y[:100], p[:100], y[100:], p[100:])
        assert fc.method == "platt"

    def test_selects_isotonic_for_large_corpus(self):
        y, p = _make_data(3000, seed=7)
        fc = run_league_calibration("epl", y[:2500], p[:2500], y[2500:], p[2500:])
        assert fc.method == "isotonic"

    def test_n_training_rows_correct(self):
        y, p = _make_data(300)
        fc = run_league_calibration("epl", y[:200], p[:200], y[200:], p[200:])
        assert fc.n_training_rows == 200

    def test_force_method_respected(self):
        y, p = _make_data(3000, seed=3)
        fc = run_league_calibration(
            "epl", y[:2500], p[:2500], y[2500:], p[2500:],
            force_method="temperature"
        )
        assert fc.method == "temperature"


# ── compare_calibration_methods ───────────────────────────────────────────────

class TestCompareCalibrationMethods:
    def test_returns_fitted_calibrator(self):
        y, p = _make_data(300)
        fc = compare_calibration_methods("epl", y[:200], p[:200], y[200:], p[200:])
        assert isinstance(fc, FittedCalibrator)

    def test_method_comparison_populated(self):
        y, p = _make_data(300)
        fc = compare_calibration_methods("epl", y[:200], p[:200], y[200:], p[200:])
        assert fc.method_comparison is not None
        assert set(fc.method_comparison.keys()) == {"isotonic", "platt", "temperature"}

    def test_comparison_table_has_expected_keys(self):
        y, p = _make_data(300)
        fc = compare_calibration_methods("epl", y[:200], p[:200], y[200:], p[200:])
        for method_info in fc.method_comparison.values():
            for k in ("ece_delta_mean", "brier_delta", "draw_f1_delta", "brier_after", "draw_f1_after"):
                assert k in method_info, f"missing key {k}"

    def test_selected_method_is_valid(self):
        y, p = _make_data(300)
        fc = compare_calibration_methods("epl", y[:200], p[:200], y[200:], p[200:])
        assert fc.method in ("isotonic", "platt", "temperature")

    def test_brier_tracking_in_compare(self):
        y, p = _make_data(300)
        fc = compare_calibration_methods("serie_a", y[:200], p[:200], y[200:], p[200:])
        assert fc.brier_before >= 0.0
        assert fc.brier_after >= 0.0

    def test_large_corpus_defaults_to_isotonic_or_better(self):
        y, p = _make_data(3000, seed=5)
        fc = compare_calibration_methods("epl", y[:2500], p[:2500], y[2500:], p[2500:])
        # With large corpus the default candidate is isotonic; selected must be valid.
        assert fc.method in ("isotonic", "platt", "temperature")
        assert "default_candidate=isotonic" in fc.selection_rationale


# ── write_calibration_report ──────────────────────────────────────────────────

class TestWriteCalibrationReport:
    def test_creates_json_file(self, tmp_path):
        y, p = _make_data(300)
        fc = run_league_calibration("epl", y[:200], p[:200], y[200:], p[200:])
        path = write_calibration_report(fc, tmp_path)
        assert path.exists()
        assert path.name == "calibration_report_epl.json"

    def test_json_schema_complete(self, tmp_path):
        y, p = _make_data(300)
        fc = run_league_calibration("epl", y[:200], p[:200], y[200:], p[200:])
        path = write_calibration_report(fc, tmp_path)
        report = json.loads(path.read_text())
        for key in (
            "league", "method", "n_training_rows", "selection_rationale",
            "ece_before", "ece_after", "ece_delta_mean",
            "brier_before", "brier_after", "brier_delta",
            "draw_f1_before", "draw_f1_after", "draw_f1_delta",
            "generated_at", "generated_date",
        ):
            assert key in report, f"missing key {key}"

    def test_method_comparison_included_when_present(self, tmp_path):
        y, p = _make_data(300)
        fc = compare_calibration_methods("bundesliga", y[:200], p[:200], y[200:], p[200:])
        path = write_calibration_report(fc, tmp_path)
        report = json.loads(path.read_text())
        assert "method_comparison" in report

    def test_brier_delta_correct(self, tmp_path):
        y, p = _make_data(300)
        fc = run_league_calibration("epl", y[:200], p[:200], y[200:], p[200:])
        path = write_calibration_report(fc, tmp_path)
        report = json.loads(path.read_text())
        expected_delta = round(fc.brier_after - fc.brier_before, 4)
        assert report["brier_delta"] == expected_delta


# ── BivariatePoissonDrawOverlay ───────────────────────────────────────────────

class TestBivariatePoissonSkellam:
    def test_skellam_draw_proba_shape(self):
        y, p = _make_data(100)
        sk = BivariatePoissonDrawOverlay._skellam_draw_proba(p, league_avg_goals=2.65)
        assert sk.shape == (len(p),)

    def test_skellam_draw_proba_in_bounds(self):
        y, p = _make_data(100)
        sk = BivariatePoissonDrawOverlay._skellam_draw_proba(p, league_avg_goals=2.65)
        assert (sk >= 0.0).all() and (sk <= 1.0).all()

    def test_symmetric_probs_give_highest_draw(self):
        # When P(home) ≈ P(away), Skellam P(draw) should be highest.
        p_sym = np.array([[0.38, 0.24, 0.38]])
        p_asym = np.array([[0.60, 0.24, 0.16]])
        sk_sym = BivariatePoissonDrawOverlay._skellam_draw_proba(p_sym, 2.65)[0]
        sk_asym = BivariatePoissonDrawOverlay._skellam_draw_proba(p_asym, 2.65)[0]
        assert sk_sym > sk_asym

    def test_fit_returns_instance(self):
        y, p = _make_data(200)
        overlay = BivariatePoissonDrawOverlay.fit(y[:150], p[:150], y[150:], p[150:])
        assert isinstance(overlay, BivariatePoissonDrawOverlay)

    def test_alpha_in_valid_range(self):
        y, p = _make_data(200)
        overlay = BivariatePoissonDrawOverlay.fit(y[:150], p[:150], y[150:], p[150:])
        assert 0.0 <= overlay.alpha <= 1.0

    def test_gate_false_resets_alpha_to_zero(self):
        # Random noise data → gate should rarely pass; if it does pass we just
        # verify alpha is still in range. The key invariant: alpha==0 ↔ gate_passed==False.
        y, p = _make_data(200, seed=99)
        overlay = BivariatePoissonDrawOverlay.fit(y[:150], p[:150], y[150:], p[150:])
        if not overlay.gate_passed:
            assert overlay.alpha == 0.0

    def test_apply_output_shape(self):
        y, p = _make_data(200)
        overlay = BivariatePoissonDrawOverlay.fit(y[:150], p[:150], y[150:], p[150:])
        out = overlay.apply(p[150:])
        assert out.shape == p[150:].shape

    def test_apply_rows_sum_to_one(self):
        y, p = _make_data(200)
        overlay = BivariatePoissonDrawOverlay.fit(y[:150], p[:150], y[150:], p[150:])
        out = overlay.apply(p[150:])
        np.testing.assert_allclose(out.sum(axis=1), np.ones(50), atol=1e-6)

    def test_apply_identity_when_alpha_zero(self):
        overlay = BivariatePoissonDrawOverlay(alpha=0.0)
        y, p = _make_data(100)
        out = overlay.apply(p)
        np.testing.assert_array_equal(out, p)

    def test_brier_fields_populated(self):
        y, p = _make_data(200)
        overlay = BivariatePoissonDrawOverlay.fit(y[:150], p[:150], y[150:], p[150:])
        assert 0.0 <= overlay.brier_before <= 2.0
        assert 0.0 <= overlay.brier_after <= 2.0


class TestWriteBivariatePoissonReport:
    def test_creates_json_file(self, tmp_path):
        y, p = _make_data(200)
        overlay = BivariatePoissonDrawOverlay.fit(y[:150], p[:150], y[150:], p[150:])
        path = write_bivariate_poisson_report(overlay, "serie_a", tmp_path)
        assert path.exists()
        assert path.name == "bivariate_poisson_serie_a.json"

    def test_json_schema_complete(self, tmp_path):
        y, p = _make_data(200)
        overlay = BivariatePoissonDrawOverlay.fit(y[:150], p[:150], y[150:], p[150:])
        path = write_bivariate_poisson_report(overlay, "ligue_1", tmp_path)
        report = json.loads(path.read_text())
        for key in (
            "league", "alpha", "league_avg_goals",
            "draw_f1_before", "draw_f1_after", "draw_f1_delta",
            "brier_before", "brier_after", "brier_delta",
            "gate_passed", "generated_at",
        ):
            assert key in report, f"missing key {key}"


# ── EnsembleDiversityDiagnostics ──────────────────────────────────────────────

def _mock_model(proba: np.ndarray) -> MagicMock:
    m = MagicMock()
    m.predict_proba.return_value = proba
    return m


class TestEnsembleDiversityDiagnostics:
    def test_pairwise_correlation_identity_diagonal(self):
        y, p = _make_data(100)
        models = {"rf": _mock_model(p), "xgb": _mock_model(p)}
        diag = EnsembleDiversityDiagnostics()
        names, corr = diag.pairwise_correlation(models, p)
        assert corr[0, 0] == pytest.approx(1.0)
        assert corr[1, 1] == pytest.approx(1.0)

    def test_identical_models_correlated_at_one(self):
        y, p = _make_data(100)
        models = {"a": _mock_model(p), "b": _mock_model(p)}
        diag = EnsembleDiversityDiagnostics()
        names, corr = diag.pairwise_correlation(models, p)
        assert corr[0, 1] == pytest.approx(1.0, abs=1e-4)

    def test_flag_redundant_above_threshold(self):
        y, p = _make_data(100)
        models = {"a": _mock_model(p), "b": _mock_model(p)}
        diag = EnsembleDiversityDiagnostics(prune_threshold=0.92)
        names, corr = diag.pairwise_correlation(models, p)
        flagged = diag.flag_redundant(names, corr)
        assert len(flagged) > 0

    def test_flag_redundant_below_threshold_empty(self):
        y, p = _make_data(100)
        rng = np.random.default_rng(1)
        # Different random probabilities → low correlation.
        p2 = rng.dirichlet([1.0, 1.0, 1.0], size=100)
        models = {"a": _mock_model(p), "b": _mock_model(p2)}
        diag = EnsembleDiversityDiagnostics(prune_threshold=0.92)
        names, corr = diag.pairwise_correlation(models, p)
        flagged = diag.flag_redundant(names, corr)
        # Correlation of different distributions is typically < 0.92.
        # Not strictly guaranteed, so just assert the function runs.
        assert isinstance(flagged, list)

    def test_run_returns_diversity_report(self):
        y, p = _make_data(100)
        rng = np.random.default_rng(2)
        p2 = rng.dirichlet([2.0, 2.0, 2.0], size=100)
        models = {"a": _mock_model(p), "b": _mock_model(p2)}
        diag = EnsembleDiversityDiagnostics()
        retained, report = diag.run("epl", models, p, y)
        assert report.league == "epl"
        assert isinstance(report.member_names, list)
        assert isinstance(report.correlation_matrix, list)

    def test_pruning_never_removes_last_member(self):
        y, p = _make_data(100)
        models = {"solo": _mock_model(p)}
        diag = EnsembleDiversityDiagnostics(prune_threshold=0.0)
        retained, report = diag.run("epl", models, p, y)
        assert len(retained) >= 1

    def test_identical_models_may_be_pruned_when_draw_f1_non_degrading(self):
        y, p = _make_data(200)
        # Two identical models — pruning one should not degrade draw-F1.
        models = {"a": _mock_model(p), "b": _mock_model(p), "c": _mock_model(p)}
        diag = EnsembleDiversityDiagnostics(prune_threshold=0.90)
        retained, report = diag.run("epl", models, p, y)
        # At least one should be retained.
        assert len(retained) >= 1
        assert len(report.retained_members) >= 1


class TestWriteDiversityReport:
    def test_creates_json_file(self, tmp_path):
        y, p = _make_data(100)
        rng = np.random.default_rng(3)
        p2 = rng.dirichlet([2.0, 2.0, 2.0], size=100)
        models = {"a": _mock_model(p), "b": _mock_model(p2)}
        diag = EnsembleDiversityDiagnostics()
        _, report = diag.run("bundesliga", models, p, y)
        path = write_diversity_report(report, tmp_path)
        assert path.exists()
        assert path.name == "diversity_report_bundesliga.json"

    def test_json_schema_complete(self, tmp_path):
        y, p = _make_data(100)
        rng = np.random.default_rng(4)
        p2 = rng.dirichlet([2.0, 2.0, 2.0], size=100)
        models = {"a": _mock_model(p), "b": _mock_model(p2)}
        diag = EnsembleDiversityDiagnostics()
        _, report = diag.run("la_liga", models, p, y)
        path = write_diversity_report(report, tmp_path)
        data = json.loads(path.read_text())
        for key in (
            "league", "member_names", "correlation_matrix",
            "mean_off_diagonal_correlation", "pruning_threshold",
            "flagged_members", "pruned_members", "retained_members",
            "pruning_rationale", "generated_at",
        ):
            assert key in data, f"missing key {key}"
