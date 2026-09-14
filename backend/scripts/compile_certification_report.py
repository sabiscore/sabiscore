#!/usr/bin/env python3
"""Compile v7.3 evidence artifacts into one immutable certification report.

This is an evidence compiler, not a threshold-editing escape hatch. The frozen
repository policy is imported and hashed; the small evidence-policy extension
below only defines the newly requested measurement gates (G11/G15/G16/G18/G24)
and is itself versioned and hashed into every report.

The compiler refuses to certify when evidence is missing, blocked, internally
inconsistent, generated from different commits, or below the declared evidence
thresholds. It never overwrites an existing certification report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ("G11", "G15", "G16", "G18", "G24")
EVIDENCE_POLICY = {
    "version": "v7.3-evidence-1",
    "G11": {"adaptive_confidence_ece_max": 0.03},
    "G15": {"murphy_decomposition_abs_error_max": 1e-6},
    "G16": {"nominal_levels": [0.80, 0.90], "require_empirical_coverage_at_least_nominal": True},
    "G18": {"bootstrap_replicates": 10000, "ci": 0.95, "require_upper_bound_below_zero": True},
    "G24": {"require_exact_sha_parity": True},
}


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
    except Exception:
        return os.getenv("SABISCORE_GIT_SHA")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def artifact_commit(artifact: dict[str, Any], path: Path) -> str | None:
    return ((artifact.get("repository") or {}).get("commit_sha")) or None


def gate_result(name: str, artifact: dict[str, Any]) -> dict[str, Any]:
    gate = ((artifact.get("gates") or {}).get(name))
    if not isinstance(gate, dict):
        raise ValueError(f"{path_name(artifact)} is missing {name}")
    return gate


def path_name(artifact: dict[str, Any]) -> str:
    return str(artifact.get("_source_path") or "artifact")


def evaluate_g11(a: dict[str, Any]) -> dict[str, Any]:
    value = float((((a.get("metrics") or {}).get("ece") or {}).get("ece")))
    passed = value <= EVIDENCE_POLICY["G11"]["adaptive_confidence_ece_max"]
    return {"status": "PASS" if passed else "FAIL", "value": value, "threshold": EVIDENCE_POLICY["G11"]["adaptive_confidence_ece_max"], "criterion": "adaptive equal-mass confidence ECE <= 0.03"}


def evaluate_g15(a: dict[str, Any]) -> dict[str, Any]:
    value = abs(float((((a.get("metrics") or {}).get("brier") or {}).get("decomposition_error"))))
    threshold = EVIDENCE_POLICY["G15"]["murphy_decomposition_abs_error_max"]
    return {"status": "PASS" if value <= threshold else "FAIL", "value": value, "threshold": threshold, "criterion": "Murphy decomposition identity residual <= 1e-6"}


def evaluate_g16(a: dict[str, Any]) -> dict[str, Any]:
    pooled = (((a.get("metrics") or {}).get("conformal") or {}).get("pooled") or {})
    errors = (((a.get("data") or {}).get("coverage") or {}).get("errors") or {})
    values = {}
    failures = []
    for nominal in EVIDENCE_POLICY["G16"]["nominal_levels"]:
        key = f"{nominal:.2f}"
        row = pooled.get(key)
        if not isinstance(row, dict):
            failures.append(f"missing pooled coverage {key}")
            continue
        actual = float(row["empirical_marginal_coverage"])
        values[key] = actual
        if actual < nominal:
            failures.append(f"{key}: empirical coverage {actual:.6f} < nominal {nominal:.2f}")
    if errors:
        failures.append(f"league execution errors: {sorted(errors)}")
    return {"status": "PASS" if not failures else "FAIL", "coverage": values, "criterion": "served-path empirical marginal coverage >= nominal at 80% and 90%", "errors": failures}


def evaluate_g18(a: dict[str, Any]) -> dict[str, Any]:
    rps = ((a.get("metrics") or {}).get("rps") or {})
    scopes = [rps.get("pooled")]
    by_league = rps.get("by_league") or {}
    scopes.extend(by_league.values())
    failures = []
    for scope in scopes:
        if not isinstance(scope, dict) or scope.get("status") == "INSUFFICIENT_EVIDENCE":
            failures.append("missing or insufficient league evidence")
            continue
        if int(scope.get("bootstrap_replicates", 0)) != 10000:
            failures.append("scope does not contain exactly 10,000 bootstrap replicates")
        ci = scope.get("block_bootstrap_ci_95")
        if not isinstance(ci, list) or len(ci) != 2 or float(ci[1]) >= 0:
            failures.append(f"RPS CI upper bound is not < 0: {ci}")
    return {"status": "PASS" if not failures and bool(scopes) else "FAIL", "criterion": "10,000-replicate paired block-bootstrap 95% CI upper bound < 0", "errors": failures, "scopes": len(scopes)}


def evaluate_g24(a: dict[str, Any]) -> dict[str, Any]:
    gate = gate_result("G24", a)
    parity = ((a.get("metrics") or {}).get("deployment_parity") or {})
    values = [parity.get(k) for k in ("expected_sha", "vercel_deployment_sha", "frontend_vercelSha", "frontend_backendSha", "render_release_sha")]
    valid = all(isinstance(v, str) and len(v) == 40 for v in values)
    passed = gate.get("status") == "PASS" and valid and len(set(values)) == 1
    return {"status": "PASS" if passed else "FAIL", "criterion": "exact SHA parity across Vercel and Render", "observed": dict(zip(("expected_sha", "vercel_deployment_sha", "frontend_vercelSha", "frontend_backendSha", "render_release_sha"), values))}


def main() -> int:
    ap = argparse.ArgumentParser(description="Compile immutable v7.3 certification report")
    ap.add_argument("--g11", type=Path, required=True)
    ap.add_argument("--g16", type=Path, required=True)
    ap.add_argument("--g18", type=Path, required=True)
    ap.add_argument("--g24", type=Path, required=True)
    ap.add_argument("--core-evidence", type=Path, help="Optional JSON containing the pre-existing v7.3 core gates")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    inputs = {"G11": args.g11, "G16": args.g16, "G18": args.g18, "G24": args.g24}
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    artifacts: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    try:
        for gate, path in inputs.items():
            artifact = load_json(path)
            artifact["_source_path"] = str(path)
            artifacts[gate] = artifact
        if args.output.exists():
            raise RuntimeError(f"refusing to overwrite existing certification report: {args.output}")
        commits = {artifact_commit(a, p) for a, p in zip(artifacts.values(), inputs.values()) if artifact_commit(a, p)}
        if len(commits) > 1:
            failures.append(f"evidence commit mismatch: {sorted(commits)}")
        results = {"G11": evaluate_g11(artifacts["G11"]), "G15": evaluate_g15(artifacts["G11"]), "G16": evaluate_g16(artifacts["G16"]), "G18": evaluate_g18(artifacts["G18"]), "G24": evaluate_g24(artifacts["G24"])}
        if args.core_evidence:
            core = load_json(args.core_evidence)
            core_gates = core.get("gates") or {}
            for name, gate in core_gates.items():
                if isinstance(gate, dict):
                    results[name] = gate
                if isinstance(gate, dict) and gate.get("status") != "PASS":
                    failures.append(f"core gate {name} is {gate.get('status')}")
        else:
            failures.append("core certification evidence not supplied; promotion cannot be certified")
        for name, result in results.items():
            if name in REQUIRED and result.get("status") != "PASS":
                failures.append(f"{name} is {result.get('status')}")
        policy_sha = None
        try:
            import sys
            sys.path.insert(0, str(REPO_ROOT / "backend"))
            from src.models.certification_policy import CERTIFICATION_POLICY_VERSION, certification_policy, policy_sha256
            policy = certification_policy()
            policy_sha = policy_sha256(policy)
        except Exception as exc:
            failures.append(f"unable to load frozen certification policy: {exc}")
            CERTIFICATION_POLICY_VERSION = "UNAVAILABLE"
            policy = {"status": "UNAVAILABLE"}
        report = {"report_version": "v7.3-certificate-1", "generated_at": generated, "repository": {"name": "sabiscore/sabiscore", "commit_sha": next(iter(commits), git_sha())}, "deployment": artifacts["G24"].get("deployment", {}), "model": artifacts["G16"].get("model", {}), "data": {"evidence_sources": {name: str(path) for name, path in inputs.items()}}, "policy": {"policy_version": CERTIFICATION_POLICY_VERSION, "policy_sha256": policy_sha, "frozen_policy": policy, "evidence_policy_version": EVIDENCE_POLICY["version"], "evidence_policy_sha256": canonical_sha(EVIDENCE_POLICY)}, "metrics": {name: artifacts[name].get("metrics", {}) for name in artifacts}, "gates": results, "operator_gates": {"mode": "AUTONOMOUS_IMPLEMENTATION", "ci_bypass_does_not_equal_test_pass": True}, "risks": ["Certification is fail-closed when any required evidence or core gate is missing.", "Historical/reanalysis artifacts cannot substitute for current served-path evidence.", "This compiler never changes certification policy."], "changes": [], "validation": {"inputs_immutable": True, "output_overwrite_prohibited": True, "required_gates": list(REQUIRED)}, "decision": "ACTIONABLE_CERTIFIED" if not failures else "HOLD", "failure_reasons": failures}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["decision"] == "ACTIONABLE_CERTIFIED" else 2
    except Exception as exc:
        result = {"report_version": "v7.3-certificate-1", "generated_at": generated, "repository": {"name": "sabiscore/sabiscore", "commit_sha": git_sha()}, "gates": {name: {"status": "BLOCKED"} for name in REQUIRED}, "decision": "HOLD", "failure_reasons": [str(exc)]}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
