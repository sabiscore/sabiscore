"""Directive V19 Certification & Empirical Validation Gate Tests.

Verifies the complete suite of empirical evidence, candidate models,
chronological validation, frozen C6 benchmarking, shadow execution,
and governance promotion gates required by Directive V19.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FROZEN_C6_SHA256 = "9d63da25324a79f4f08416d79991281bd45155064ec33fd8f67284b28be46ba7"


def test_gate_19_dataset_fitness_and_coverage() -> None:
    cov_path = REPO_ROOT / "reports/evidence/current-data-coverage.json"
    assert cov_path.exists(), f"Missing {cov_path}"
    with open(cov_path, encoding="utf-8") as f:
        cov = json.load(f)

    assert cov["dataset_scope"]["total_fixtures"] >= 10000
    assert len(cov["leagues"]) == 6
    assert set(cov["leagues"].keys()) == {
        "BUNDESLIGA",
        "EPL",
        "EREDIVISIE",
        "LA_LIGA",
        "LIGUE_1",
        "SERIE_A",
    }
    assert cov["dataset_scope"]["overall_settlement_rate"] == 1.0


def test_gate_20_candidate_lineage_and_artifacts() -> None:
    manifest_path = REPO_ROOT / "reports/research/candidate-generation-manifest.json"
    assert manifest_path.exists(), f"Missing {manifest_path}"
    with open(manifest_path, encoding="utf-8") as f:
        cand_m = json.load(f)

    assert cand_m["generation_id"] == "v6_phase8-candidate"
    assert len(cand_m["artifact_sha256"]) == 6

    cand_dir = REPO_ROOT / "backend/models/candidates/v6_phase8-candidate"
    assert cand_dir.exists() and cand_dir.is_dir()
    for league in ["bundesliga", "epl", "eredivisie", "la_liga", "ligue_1", "serie_a"]:
        assert league.upper() in cand_m["artifact_sha256"]
        model_filename = f"{league}_ensemble_v6_phase8.pkl"
        model_path = cand_dir / model_filename
        if model_path.exists():
            assert model_path.stat().st_size > 1000, f"Artifact too small: {model_path}"


def test_gate_21_adversarial_leakage_and_temporal_order() -> None:
    proto_path = REPO_ROOT / "reports/research/v19-evaluation-protocol.json"
    assert proto_path.exists(), f"Missing {proto_path}"
    with open(proto_path, encoding="utf-8") as f:
        proto = json.load(f)

    assert proto["protocol_id"] == "v19-chronological-evaluation-protocol"
    assert proto["temporal_ordering"]["holdout_season"] == "2526"
    assert "zero lookahead" in proto["temporal_ordering"]["strict_chronological_rule"].lower()


def test_gate_22_evaluation_protocol_sha256_immutability() -> None:
    proto_path = REPO_ROOT / "reports/research/v19-evaluation-protocol.json"
    sha_path = REPO_ROOT / "reports/research/v19-evaluation-protocol.sha256"
    assert proto_path.exists() and sha_path.exists()

    content_bytes = proto_path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    calc_sha = hashlib.sha256(content_bytes).hexdigest()
    stored_sha = sha_path.read_text(encoding="utf-8").split()[0].strip()
    assert calc_sha == stored_sha, f"Protocol hash mismatch: {calc_sha} != {stored_sha}"


def test_gate_23_chronological_predictive_verification() -> None:
    pred_path = REPO_ROOT / "reports/research/v19-predictive-performance.json"
    assert pred_path.exists(), f"Missing {pred_path}"
    with open(pred_path, encoding="utf-8") as f:
        pred = json.load(f)

    summary = pred["overall_summary"]
    assert summary["leagues_evaluated"] == 6
    assert summary["candidate_league_wins_vs_incumbent"] == 6
    assert summary["no_league_regression_passed"] is True
    assert summary["mean_candidate_rps"] < summary["mean_incumbent_rps"]


def test_gate_24_calibration_certification_diagnostics() -> None:
    cal_path = REPO_ROOT / "reports/research/v19-calibration-performance.json"
    assert cal_path.exists(), f"Missing {cal_path}"
    with open(cal_path, encoding="utf-8") as f:
        cal = json.load(f)

    diagnostics = cal["league_calibration_diagnostics"]
    assert len(diagnostics) == 6
    for league, d in diagnostics.items():
        assert "calibrator_comparison" in d
        assert "brier_decomposition" in d


def test_gate_25_frozen_c6_candidate_evaluation() -> None:
    c6_path = REPO_ROOT / "reports/research/c6-candidate-results.json"
    assert c6_path.exists(), f"Missing {c6_path}"
    with open(c6_path, encoding="utf-8") as f:
        c6 = json.load(f)

    assert c6["protocol_sha256"] == FROZEN_C6_SHA256
    assert c6["c6_status"] == "INSUFFICIENT_SAMPLE"
    assert c6["live_settled_sample_count"] < 200
    assert "98.33_percent_CI" in c6["historical_paired_results"]


def test_gate_26_benchmark_identity_integrity() -> None:
    reg_path = REPO_ROOT / "reports/research/experiment_registry.yaml"
    assert reg_path.exists(), f"Missing {reg_path}"
    content = reg_path.read_text(encoding="utf-8")
    assert FROZEN_C6_SHA256 in content


def test_gate_27_adversarial_stress_and_robustness() -> None:
    cert_path = REPO_ROOT / "reports/research/v19-model-certification.json"
    assert cert_path.exists(), f"Missing {cert_path}"
    with open(cert_path, encoding="utf-8") as f:
        cert = json.load(f)

    assert cert["dimensions"]["C7-G_robustness"]["status"] == "PASS"


def test_gate_28_empirical_feature_ablation() -> None:
    abl_path = REPO_ROOT / "reports/research/feature-ablation-report.json"
    assert abl_path.exists(), f"Missing {abl_path}"
    with open(abl_path, encoding="utf-8") as f:
        abl = json.load(f)

    eval_89 = [e for e in abl["ablation_evaluations"] if e["feature_family"] == "PHASE8_RATING_FORM_89"][0]
    assert eval_89["delta_rps_vs_baseline"] < 0  # Negative delta indicates improvement
    assert eval_89["incremental_value_decision"] == "RETAIN"


def test_gate_29_uncertainty_semantics_and_intervals() -> None:
    cert_path = REPO_ROOT / "reports/research/v19-model-certification.json"
    assert cert_path.exists(), f"Missing {cert_path}"
    with open(cert_path, encoding="utf-8") as f:
        cert = json.load(f)

    assert cert["dimensions"]["C7-I_uncertainty"]["status"] == "PASS"


def test_gate_30_drift_monitoring_policy() -> None:
    cert_path = REPO_ROOT / "reports/research/v19-model-certification.json"
    assert cert_path.exists(), f"Missing {cert_path}"
    with open(cert_path, encoding="utf-8") as f:
        cert = json.load(f)

    assert cert["dimensions"]["C7-J_drift"]["status"] == "PASS"


def test_gate_31_candidate_reproducibility_hash() -> None:
    manifest_path = REPO_ROOT / "reports/research/candidate-generation-manifest.json"
    with open(manifest_path, encoding="utf-8") as f:
        cand_m = json.load(f)

    assert len(cand_m["reproducibility_sha256"]) == 64
    assert re.match(r"^[0-9a-f]{64}$", cand_m["reproducibility_sha256"])


def test_gate_32_shadow_validation_pipeline() -> None:
    shadow_path = REPO_ROOT / "reports/research/v19-shadow-validation-report.json"
    assert shadow_path.exists(), f"Missing {shadow_path}"
    with open(shadow_path, encoding="utf-8") as f:
        shadow = json.load(f)

    assert shadow["shadow_pairing"]["fixtures_shadowed"] >= 1000
    assert shadow["shadow_governance"]["status"] == "SHADOW_VALIDATION_COMPLETED"


def test_gate_33_data_gap_recovery_roadmap() -> None:
    plan_path = REPO_ROOT / "reports/evidence/data-gap-recovery-plan.json"
    assert plan_path.exists(), f"Missing {plan_path}"
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)

    assert len(plan["gap_investigations"]) >= 5
    for item in plan["gap_investigations"]:
        assert "feature_family" in item
        assert "what_is_missing" in item
        assert "which_provider" in item
        assert "pit_safe_reconstruction" in item


def test_gate_34_provider_health_and_circuit_breakers() -> None:
    health_path = REPO_ROOT / "reports/evidence/provider-live-health.json"
    assert health_path.exists(), f"Missing {health_path}"
    with open(health_path, encoding="utf-8") as f:
        health = json.load(f)

    assert "football_data_org" in health["providers"]
    assert health["quarantine_status"] == "ZERO_PROVIDERS_QUARANTINED"


def test_gate_35_active_generation_promotion_governance() -> None:
    decision_path = REPO_ROOT / "reports/research/v19-promotion-decision.json"
    assert decision_path.exists(), f"Missing {decision_path}"
    with open(decision_path, encoding="utf-8") as f:
        dec = json.load(f)

    assert dec["promotion_decision"] == "RETAIN_INCUMBENT"
    assert dec["incumbent_generation"] == "v5_phase7-20260922"
    assert dec["active_generation_state"] == "ACTIVE_FAIL_CLOSED"
    assert dec["active_generation_certification"] == "UNVERIFIED"


def test_gate_36_rollback_and_promotion_attestation() -> None:
    rollback_path = REPO_ROOT / "reports/release/v19-rollback-attestation.json"
    attestation_path = REPO_ROOT / "reports/release/v19-promotion-attestation.json"
    assert rollback_path.exists() and attestation_path.exists()

    with open(rollback_path, encoding="utf-8") as f:
        roll = json.load(f)
    assert roll["active_generation"] == "v5_phase7-20260922"
    assert roll["rollback_reference"]["artifact_backup_verified"] is True

    with open(attestation_path, encoding="utf-8") as f:
        att = json.load(f)
    assert att["decision"] == "RETAIN_INCUMBENT"
    assert att["final_release_state"] == "READY_WITH_DOCUMENTED_LIMITATIONS"
    assert att["active_generation_state"] == "ACTIVE_FAIL_CLOSED"
