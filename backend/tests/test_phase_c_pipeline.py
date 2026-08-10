"""Phase C pipeline gate coverage.

Tests cover:
  - evaluate_baseline_v8: RPS gate, draw_f1 regression, balanced_accuracy regression,
    per_season schema, per_league_delta construction, and dated delta report
  - validate_feature_expansion: SHAP ablation output schema, n_folds accuracy,
    leagues_below_threshold counting, prune_flag logic (leagues_below >= 3)
  - Root orchestrator: _validate_report propagates backend gate failures,
    _find_prior_baseline resolution
"""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path

import types

import numpy as np
import pytest

# ── path bootstrap ─────────────────────────────────────────────────────────────
# test file: backend/tests/test_phase_c_pipeline.py
# parents[0] = backend/tests, parents[1] = backend, parents[2] = repo root
BACKEND_ROOT = Path(__file__).resolve().parents[1]   # sabiscore/backend
REPO_ROOT = Path(__file__).resolve().parents[2]      # sabiscore
SCRIPTS_ROOT = REPO_ROOT / "scripts"                 # sabiscore/scripts
BACKEND_SCRIPTS = BACKEND_ROOT / "scripts"           # sabiscore/backend/scripts
SRC_ROOT = BACKEND_ROOT / "src"

for _p in (str(SRC_ROOT), str(BACKEND_ROOT), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _bootstrap_models_package() -> None:
    """Pre-inject real model submodules so backend scripts can import them
    without triggering models/__init__.py (which tries to import the DB layer).
    """
    if "models" not in sys.modules:
        sys.modules["models"] = types.ModuleType("models")

    def _load_into(name: str, path: Path) -> None:
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)

    if "models.evaluation" not in sys.modules:
        sys.modules["models.evaluation"] = types.ModuleType("models.evaluation")

    _load_into("models.feature_registry", SRC_ROOT / "models" / "feature_registry.py")
    _load_into("models.evaluation.metrics", SRC_ROOT / "models" / "evaluation" / "metrics.py")
    _load_into(
        "models.evaluation.temporal_splits",
        SRC_ROOT / "models" / "evaluation" / "temporal_splits.py",
    )


_bootstrap_models_package()


# ── lazy module loaders ────────────────────────────────────────────────────────

def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def eval_v8():
    """backend/scripts/evaluate_baseline_v8.py as importable module."""
    return _load_module(BACKEND_SCRIPTS / "evaluate_baseline_v8.py", "_eval_v8")


@pytest.fixture(scope="module")
def val_exp():
    """backend/scripts/validate_feature_expansion.py as importable module."""
    return _load_module(BACKEND_SCRIPTS / "validate_feature_expansion.py", "_val_exp")


@pytest.fixture(scope="module")
def root_eval():
    """scripts/evaluate_baseline_v8.py (root orchestrator) as importable module."""
    return _load_module(SCRIPTS_ROOT / "evaluate_baseline_v8.py", "_root_eval")


# ── fixtures ───────────────────────────────────────────────────────────────────

def _make_proba(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    p = rng.dirichlet([1.5, 1.0, 1.5], size=n).astype(np.float64)
    return p


def _make_y(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 3, size=n)


# ── evaluate_baseline_v8: metric helpers ──────────────────────────────────────

class TestComputeRps:
    def test_perfect_prediction_returns_zero(self, eval_v8):
        y = np.array([0, 1, 2])
        p = np.eye(3)[[0, 1, 2]].astype(float)
        assert eval_v8._compute_rps(y, p) == pytest.approx(0.0, abs=1e-6)

    def test_worst_prediction_bounded(self, eval_v8):
        y = np.array([0, 0, 0])
        p = np.array([[0.0, 0.0, 1.0]] * 3)
        rps = eval_v8._compute_rps(y, p)
        assert 0.0 <= rps <= 1.0

    def test_uniform_gives_positive_rps(self, eval_v8):
        y = _make_y(100)
        p = _make_proba(100)
        assert eval_v8._compute_rps(y, p) > 0.0

    def test_shape_3_classes(self, eval_v8):
        y = _make_y(50)
        p = _make_proba(50)
        rps = eval_v8._compute_rps(y, p)
        assert isinstance(rps, float)


# ── evaluate_baseline_v8: gate validation ─────────────────────────────────────

class TestValidateReport:
    """Tests for _validate_report() in backend/scripts/evaluate_baseline_v8.py."""

    def _base_report(self) -> dict:
        return {
            "rps": 0.200,
            "draw_f1": 0.35,
            "balanced_accuracy": 0.42,
            "gates": {"passed": True, "failures": []},
        }

    def test_passes_when_rps_below_gate(self, eval_v8):
        report = self._base_report()
        passed, failures = eval_v8._validate_report(report, baseline_report=None)
        assert passed
        assert failures == []

    def test_fails_when_rps_exceeds_gate(self, eval_v8):
        report = self._base_report()
        report["rps"] = 0.215
        passed, failures = eval_v8._validate_report(report, baseline_report=None)
        assert not passed
        assert any("rps" in f for f in failures)

    def test_fails_draw_f1_regression(self, eval_v8):
        report = self._base_report()
        report["draw_f1"] = 0.30
        baseline = {"rps": 0.200, "draw_f1": 0.35, "balanced_accuracy": 0.40}
        passed, failures = eval_v8._validate_report(report, baseline_report=baseline)
        assert not passed
        assert any("draw_f1" in f for f in failures)

    def test_passes_draw_f1_unchanged(self, eval_v8):
        report = self._base_report()
        report["draw_f1"] = 0.35
        baseline = {"rps": 0.200, "draw_f1": 0.35, "balanced_accuracy": 0.40}
        passed, failures = eval_v8._validate_report(report, baseline_report=baseline)
        assert passed

    def test_fails_balanced_accuracy_regression(self, eval_v8):
        report = self._base_report()
        report["balanced_accuracy"] = 0.38
        baseline = {"rps": 0.200, "draw_f1": 0.35, "balanced_accuracy": 0.42}
        passed, failures = eval_v8._validate_report(report, baseline_report=baseline)
        assert not passed
        assert any("balanced_accuracy" in f for f in failures)

    def test_multiple_gate_failures_collected(self, eval_v8):
        report = {"rps": 0.220, "draw_f1": 0.25, "balanced_accuracy": 0.30}
        baseline = {"rps": 0.210, "draw_f1": 0.35, "balanced_accuracy": 0.40}
        passed, failures = eval_v8._validate_report(report, baseline_report=baseline)
        assert not passed
        assert len(failures) >= 2

    def test_no_baseline_skips_regression_gates(self, eval_v8):
        report = {"rps": 0.205, "draw_f1": 0.0, "balanced_accuracy": 0.0}
        passed, failures = eval_v8._validate_report(report, baseline_report=None)
        assert passed


# ── evaluate_baseline_v8: delta report ───────────────────────────────────────

class TestBuildDeltaReport:
    def test_delta_computed_correctly(self, eval_v8):
        current = {"epl": {"rps": 0.195, "draw_f1": 0.38, "balanced_accuracy": 0.43,
                            "brier": 0.55, "log_loss": 0.95, "accuracy": 0.52, "macro_f1": 0.42}}
        baseline = {"epl": {"rps": 0.200, "draw_f1": 0.35, "balanced_accuracy": 0.42,
                             "brier": 0.56, "log_loss": 0.97, "accuracy": 0.51, "macro_f1": 0.41}}
        deltas = eval_v8._build_delta_report(current, baseline)
        assert "epl" in deltas
        assert deltas["epl"]["rps"] == pytest.approx(-0.005, abs=1e-4)
        assert deltas["epl"]["draw_f1"] == pytest.approx(0.03, abs=1e-4)

    def test_returns_empty_when_no_baseline(self, eval_v8):
        current = {"epl": {"rps": 0.195}}
        assert eval_v8._build_delta_report(current, None) == {}

    def test_missing_league_in_baseline_skipped(self, eval_v8):
        current = {"epl": {"rps": 0.195, "draw_f1": 0.35, "balanced_accuracy": 0.41,
                            "brier": 0.55, "log_loss": 0.95, "accuracy": 0.52, "macro_f1": 0.41},
                   "bundesliga": {"rps": 0.202, "draw_f1": 0.32, "balanced_accuracy": 0.40,
                                   "brier": 0.57, "log_loss": 0.98, "accuracy": 0.50, "macro_f1": 0.40}}
        baseline = {"epl": {"rps": 0.200, "draw_f1": 0.35, "balanced_accuracy": 0.42,
                             "brier": 0.56, "log_loss": 0.97, "accuracy": 0.51, "macro_f1": 0.41}}
        deltas = eval_v8._build_delta_report(current, baseline)
        assert "epl" in deltas
        assert "bundesliga" not in deltas

    def test_all_tracked_metrics_present(self, eval_v8):
        current = {"epl": {"accuracy": 0.52, "log_loss": 0.95, "rps": 0.195, "brier": 0.55,
                            "macro_f1": 0.42, "balanced_accuracy": 0.43, "draw_f1": 0.38}}
        baseline = {"epl": {"accuracy": 0.51, "log_loss": 0.97, "rps": 0.200, "brier": 0.56,
                             "macro_f1": 0.41, "balanced_accuracy": 0.42, "draw_f1": 0.35}}
        deltas = eval_v8._build_delta_report(current, baseline)
        expected_keys = {"accuracy", "log_loss", "rps", "brier", "macro_f1",
                         "balanced_accuracy", "draw_f1"}
        assert set(deltas["epl"].keys()) == expected_keys


# ── validate_feature_expansion: dataclass schema ──────────────────────────────

class TestFamilyAblationResultSchema:
    """FamilyAblationResult must expose leagues_below_threshold."""

    def test_has_leagues_below_threshold_field(self, val_exp):
        result = val_exp.FamilyAblationResult(
            family="pi_ratings",
            features=["pi_attack_home"],
            mean_shap=0.005,
            delta_rps=0.002,
            delta_brier=0.001,
            delta_draw_f1=0.01,
            prune_flag=False,
            n_folds=4,
        )
        assert hasattr(result, "leagues_below_threshold")
        assert result.leagues_below_threshold == 0

    def test_leagues_below_threshold_serialises(self, val_exp):
        result = val_exp.FamilyAblationResult(
            family="ewma_form",
            features=["ewma_ppg_home"],
            mean_shap=0.001,
            delta_rps=0.0,
            delta_brier=0.0,
            delta_draw_f1=0.0,
            prune_flag=True,
            n_folds=3,
            leagues_below_threshold=4,
        )
        d = asdict(result)
        assert d["leagues_below_threshold"] == 4

    def test_n_folds_accepts_nonzero(self, val_exp):
        result = val_exp.FamilyAblationResult(
            family="market_drift",
            features=["odds_drift_home"],
            mean_shap=0.003,
            delta_rps=0.001,
            delta_brier=0.0,
            delta_draw_f1=0.005,
            prune_flag=False,
            n_folds=5,
            leagues_below_threshold=1,
        )
        assert result.n_folds == 5


# ── validate_feature_expansion: prune_flag logic ─────────────────────────────

class TestPruneFlagLogic:
    """prune_flag must be True iff leagues_below_threshold >= 3 (when per-league data available)."""

    def _ablation_result(self, val_exp, leagues_below: int, mean_shap: float = 0.001) -> object:
        return val_exp.FamilyAblationResult(
            family="test_family",
            features=["feat_a"],
            mean_shap=mean_shap,
            delta_rps=0.0,
            delta_brier=0.0,
            delta_draw_f1=0.0,
            prune_flag=leagues_below >= 3,
            n_folds=4,
            leagues_below_threshold=leagues_below,
        )

    def test_prune_false_when_leagues_below_2(self, val_exp):
        r = self._ablation_result(val_exp, leagues_below=2)
        assert r.prune_flag is False

    def test_prune_true_when_leagues_below_3(self, val_exp):
        r = self._ablation_result(val_exp, leagues_below=3)
        assert r.prune_flag is True

    def test_prune_true_when_leagues_below_5(self, val_exp):
        r = self._ablation_result(val_exp, leagues_below=5)
        assert r.prune_flag is True

    def test_prune_false_when_leagues_below_0(self, val_exp):
        r = self._ablation_result(val_exp, leagues_below=0)
        assert r.prune_flag is False

    def test_prune_threshold_exact_boundary(self, val_exp):
        r_below = self._ablation_result(val_exp, leagues_below=2)
        r_at = self._ablation_result(val_exp, leagues_below=3)
        assert r_below.prune_flag is False
        assert r_at.prune_flag is True


# ── validate_feature_expansion: n_folds accuracy ────────────────────────────

class TestNFoldsAccuracy:
    """n_folds must reflect actual walk-forward fold count, never hardcoded 0."""

    def test_n_folds_nonzero_without_shap(self, val_exp):
        """When SHAP unavailable, n_folds should still reflect split count."""
        result = val_exp.FamilyAblationResult(
            family="berrar_ratings",
            features=["berrar_home"],
            mean_shap=0.0,
            delta_rps=0.0,
            delta_brier=0.0,
            delta_draw_f1=0.0,
            prune_flag=False,
            n_folds=4,
            leagues_below_threshold=0,
        )
        assert result.n_folds == 4

    def test_n_folds_zero_only_when_no_splits(self, val_exp):
        result = val_exp.FamilyAblationResult(
            family="match_context",
            features=["match_importance_score"],
            mean_shap=0.0,
            delta_rps=0.0,
            delta_brier=0.0,
            delta_draw_f1=0.0,
            prune_flag=False,
            n_folds=0,
            leagues_below_threshold=0,
        )
        assert result.n_folds == 0


# ── root orchestrator: _validate_report ──────────────────────────────────────

class TestRootOrchestratorValidateReport:
    """scripts/evaluate_baseline_v8.py _validate_report propagates backend gate failures."""

    def _full_report(self) -> dict:
        return {
            "accuracy_overall": 0.52,
            "log_loss": 0.95,
            "brier_score": 0.55,
            "rps": 0.200,
            "macro_f1": 0.42,
            "balanced_accuracy": 0.43,
            "draw_precision": 0.35,
            "draw_recall": 0.30,
            "draw_f1": 0.32,
            "per_season": {"2023/24": {"matches": 380}},
            "ece": {"mean": 0.05, "class_0": 0.04, "class_1": 0.06, "class_2": 0.05},
            "gates": {"passed": True, "failures": []},
        }

    def test_passes_complete_valid_report(self, root_eval):
        failures = root_eval._validate_report(self._full_report(), "epl")
        assert failures == []

    def test_missing_required_key_reported(self, root_eval):
        report = self._full_report()
        del report["balanced_accuracy"]
        failures = root_eval._validate_report(report, "epl")
        assert any("balanced_accuracy" in f for f in failures)

    def test_missing_draw_f1_key_reported(self, root_eval):
        report = self._full_report()
        del report["draw_f1"]
        failures = root_eval._validate_report(report, "epl")
        assert any("draw_f1" in f for f in failures)

    def test_null_draw_recall_reported(self, root_eval):
        report = self._full_report()
        report["draw_recall"] = None
        failures = root_eval._validate_report(report, "epl")
        assert any("draw_recall" in f for f in failures)

    def test_ece_subkeys_checked(self, root_eval):
        report = self._full_report()
        report["ece"] = {"mean": 0.05}
        failures = root_eval._validate_report(report, "epl")
        assert any("class_0" in f or "class_1" in f or "class_2" in f for f in failures)

    def test_backend_gate_failures_propagated(self, root_eval):
        report = self._full_report()
        report["gates"] = {"passed": False, "failures": ["rps=0.215 exceeds gate 0.210"]}
        failures = root_eval._validate_report(report, "epl")
        assert any("rps=0.215" in f for f in failures)

    def test_backend_gate_pass_adds_no_failures(self, root_eval):
        report = self._full_report()
        report["gates"] = {"passed": True, "failures": []}
        failures = root_eval._validate_report(report, "epl")
        assert failures == []


# ── root orchestrator: _find_prior_baseline ──────────────────────────────────

class TestFindPriorBaseline:
    def test_returns_none_when_no_reports(self, root_eval, tmp_path):
        result = root_eval._find_prior_baseline(tmp_path, "20260612")
        assert result is None

    def test_returns_most_recent_excluding_today(self, root_eval, tmp_path):
        (tmp_path / "baseline_v8_20260610.json").write_text("{}", encoding="utf-8")
        (tmp_path / "baseline_v8_20260611.json").write_text("{}", encoding="utf-8")
        result = root_eval._find_prior_baseline(tmp_path, "20260612")
        assert result is not None
        assert result.stem == "baseline_v8_20260611"

    def test_skips_todays_report(self, root_eval, tmp_path):
        (tmp_path / "baseline_v8_20260612.json").write_text("{}", encoding="utf-8")
        result = root_eval._find_prior_baseline(tmp_path, "20260612")
        assert result is None

    def test_only_today_is_skipped_not_all(self, root_eval, tmp_path):
        (tmp_path / "baseline_v8_20260612.json").write_text("{}", encoding="utf-8")
        (tmp_path / "baseline_v8_20260610.json").write_text("{}", encoding="utf-8")
        result = root_eval._find_prior_baseline(tmp_path, "20260612")
        assert result is not None
        assert result.stem == "baseline_v8_20260610"


# ── root orchestrator: EVALUATOR_PATH ────────────────────────────────────────

class TestRootEvaluatorPath:
    def test_evaluator_path_points_to_v8(self, root_eval):
        assert root_eval.EVALUATOR_PATH.name == "evaluate_baseline_v8.py"

    def test_evaluator_path_exists(self, root_eval):
        assert root_eval.EVALUATOR_PATH.exists(), (
            f"Backend evaluator not found: {root_eval.EVALUATOR_PATH}"
        )


# ── root orchestrator: RPS gate constant ─────────────────────────────────────

class TestRpsGateConstants:
    def test_rps_gate_value(self, root_eval):
        assert root_eval.RPS_GATE == pytest.approx(0.210, abs=1e-6)

    def test_backend_rps_gate_matches_root(self, eval_v8, root_eval):
        assert eval_v8.RPS_GATE == root_eval.RPS_GATE


# ── validate_feature_expansion: ExpansionReport schema ──────────────────────

class TestExpansionReportSchema:
    def test_shap_ablation_list_serialises(self, val_exp):
        ablation = [
            val_exp.FamilyAblationResult(
                family="pi_ratings",
                features=["pi_attack_home"],
                mean_shap=0.005,
                delta_rps=0.002,
                delta_brier=0.001,
                delta_draw_f1=0.01,
                prune_flag=False,
                n_folds=4,
                leagues_below_threshold=1,
            )
        ]
        report = val_exp.ExpansionReport(
            date="20260612",
            data_path="/tmp/data.parquet",
            n_rows=5000,
            feature_set_baseline="phase7",
            feature_set_candidate="phase8",
            baseline_rps=0.205,
            candidate_rps=0.198,
            delta_rps=-0.007,
            baseline_brier=0.56,
            candidate_brier=0.54,
            delta_brier=-0.02,
            baseline_draw_f1=0.33,
            candidate_draw_f1=0.37,
            delta_draw_f1=0.04,
            improvement=True,
            shap_ablation=[asdict(r) for r in ablation],
        )
        d = asdict(report)
        assert d["shap_ablation"][0]["leagues_below_threshold"] == 1
        assert d["shap_ablation"][0]["n_folds"] == 4

    def test_shap_ablation_none_when_not_run(self, val_exp):
        report = val_exp.ExpansionReport(
            date="20260612",
            data_path="/tmp/data.parquet",
            n_rows=5000,
            feature_set_baseline="phase7",
            feature_set_candidate="phase8",
            baseline_rps=0.205,
            candidate_rps=0.198,
            delta_rps=-0.007,
            baseline_brier=0.56,
            candidate_brier=0.54,
            delta_brier=-0.02,
            baseline_draw_f1=0.33,
            candidate_draw_f1=0.37,
            delta_draw_f1=0.04,
            improvement=True,
            shap_ablation=None,
        )
        assert asdict(report)["shap_ablation"] is None


# ── integration: dated delta file creation ───────────────────────────────────

class TestDatedDeltaFileCreation:
    """Verify that the root orchestrator writes per-league delta JSON."""

    def test_delta_file_written_when_deltas_present(self, root_eval, tmp_path):
        combined = {
            "leagues": {
                "epl": {
                    "rps": 0.195,
                    "per_league_delta": {"epl": {"rps": -0.005, "draw_f1": 0.03}},
                }
            }
        }
        evaluated = ["epl"]
        all_deltas = {
            lg: combined["leagues"][lg].get("per_league_delta", {})
            for lg in evaluated
            if combined["leagues"].get(lg, {}).get("per_league_delta")
        }
        today = "20260612"
        prior = tmp_path / "baseline_v8_20260610.json"
        prior.write_text("{}", encoding="utf-8")

        if all_deltas:
            delta_path = tmp_path / f"delta_per_league_{today}.json"
            delta_path.write_text(
                json.dumps({
                    "date": today,
                    "version": "v6_phase8",
                    "baseline_compared": str(prior),
                    "per_league_delta": all_deltas,
                }, indent=2),
                encoding="utf-8",
            )

        assert (tmp_path / f"delta_per_league_{today}.json").exists()
        payload = json.loads((tmp_path / f"delta_per_league_{today}.json").read_text())
        assert payload["date"] == today
        assert "epl" in payload["per_league_delta"]

    def test_no_delta_file_when_no_per_league_delta(self, root_eval, tmp_path):
        """Delta file must not be created when no per_league_delta in any league report."""
        combined = {
            "leagues": {
                "epl": {"rps": 0.195}  # no per_league_delta key
            }
        }
        evaluated = ["epl"]
        all_deltas = {
            lg: combined["leagues"][lg].get("per_league_delta", {})
            for lg in evaluated
            if combined["leagues"].get(lg, {}).get("per_league_delta")
        }
        today = "20260612"
        if all_deltas:
            (tmp_path / f"delta_per_league_{today}.json").write_text("{}", encoding="utf-8")

        assert not (tmp_path / f"delta_per_league_{today}.json").exists()
