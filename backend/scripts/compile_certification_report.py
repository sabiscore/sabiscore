#!/usr/bin/env python3
"""Compile v7.4 evidence artifacts into one immutable certification report.

The compiler is deliberately evidence-only: it normalizes known harness output
shapes, never invents a metric, refuses mixed commits, and keeps missing or
incompatible evidence fail-closed.
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
def _load_release_gate_policy() -> tuple[tuple[str, ...], dict[str, Any], str]:
    """Read the release-gate thresholds from the frozen certification policy.

    These thresholds used to live here as a plain module dict. That meant the
    numbers deciding whether a release certifies belonged to no policy: editing
    `adaptive_confidence_ece_max` flipped gate outcomes while every recorded
    policy hash stayed identical, so the change tripped no control (directive
    §20, OG-06). They now live in `src/models/certification_policy.py`, inside
    the payload `policy_sha256()` covers, so altering one necessarily moves the
    digest.

    Loaded by path rather than as a package import: importing `src.models` pulls
    in the application chain, which opens a database connection, and this script
    must run in a bare build environment. Same approach
    `verify_active_artifacts.py` uses, and for the same reason.
    """
    import importlib.util

    policy_path = REPO_ROOT / "backend" / "src" / "models" / "certification_policy.py"
    spec = importlib.util.spec_from_file_location("_sabiscore_cert_policy", policy_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load certification policy from {policy_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    policy = module.certification_policy()
    gates = dict(policy["release_gates"])
    # The digest is over the WHOLE policy, so it also covers the promotion gates
    # and evidence floors. That is deliberate: a report citing this hash is
    # citing the complete certification contract it was judged under.
    gates["version"] = policy["policy_version"]
    return tuple(policy["required_release_gates"]), gates, module.policy_sha256(policy)


REQUIRED, EVIDENCE_POLICY, _POLICY_SHA256 = _load_release_gate_policy()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except Exception:
        return os.getenv("SABISCORE_GIT_SHA")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _numeric_metric(value: Any, *, key: str, label: str) -> float:
    """Normalize a scalar metric or the current harness' nested metric object."""
    if isinstance(value, dict):
        value = value.get(key)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label} evidence has no numeric '{key}' value")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} evidence '{key}' is not numeric: {value!r}") from exc
    if not (result == result and abs(result) != float("inf")):
        raise ValueError(f"{label} evidence '{key}' is non-finite")
    return result


def evaluate_g11(a: dict[str, Any]) -> dict[str, Any]:
    metric = ((a.get("metrics") or {}).get("ece"))
    value = _numeric_metric(metric, key="ece", label="G11")
    threshold = float(EVIDENCE_POLICY["G11"]["adaptive_confidence_ece_max"])
    return {
        "status": "PASS" if value <= threshold else "FAIL",
        "value": value,
        "threshold": threshold,
        "criterion": "adaptive equal-mass confidence ECE <= 0.03",
    }


def evaluate_g15(a: dict[str, Any]) -> dict[str, Any]:
    metric = ((a.get("metrics") or {}).get("brier"))
    value = abs(_numeric_metric(metric, key="decomposition_error", label="G15"))
    threshold = float(EVIDENCE_POLICY["G15"]["murphy_decomposition_abs_error_max"])
    return {
        "status": "PASS" if value <= threshold else "FAIL",
        "value": value,
        "threshold": threshold,
        "criterion": "Murphy decomposition residual <= 1e-6",
    }


def evaluate_g16(a: dict[str, Any]) -> dict[str, Any]:
    pooled = (((a.get("metrics") or {}).get("conformal") or {}).get("pooled") or {})
    errors = (((a.get("data") or {}).get("coverage") or {}).get("errors") or {})
    coverage: dict[str, float] = {}
    failures: list[str] = []
    for nominal in EVIDENCE_POLICY["G16"]["nominal_levels"]:
        key = f"{nominal:.2f}"
        row = pooled.get(key)
        if not isinstance(row, dict):
            failures.append(f"missing pooled coverage {key}")
            continue
        try:
            actual = float(row["empirical_marginal_coverage"])
        except (KeyError, TypeError, ValueError) as exc:
            failures.append(f"{key}: invalid empirical coverage ({exc})")
            continue
        coverage[key] = actual
        if actual < nominal:
            failures.append(f"{key}: {actual:.6f} < {nominal:.2f}")
    if errors:
        failures.append(f"league execution errors: {sorted(errors)}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "coverage": coverage,
        "criterion": "served-path empirical marginal coverage >= nominal at 80% and 90%",
        "errors": failures,
    }


def evaluate_g18(a: dict[str, Any]) -> dict[str, Any]:
    rps = ((a.get("metrics") or {}).get("rps") or {})
    scopes = [rps.get("pooled"), *list((rps.get("by_league") or {}).values())]
    failures: list[str] = []
    for scope in scopes:
        if not isinstance(scope, dict) or scope.get("status") == "INSUFFICIENT_EVIDENCE":
            failures.append("missing/insufficient scope")
            continue
        if int(scope.get("bootstrap_replicates", 0)) != 10000:
            failures.append("scope is not based on exactly 10,000 replicates")
        ci = scope.get("block_bootstrap_ci_95")
        if not isinstance(ci, list) or len(ci) != 2 or float(ci[1]) >= 0:
            failures.append(f"CI upper bound is not < 0: {ci}")
    return {
        "status": "PASS" if scopes and not failures else "FAIL",
        "criterion": "10,000-replicate paired block-bootstrap 95% CI upper bound < 0",
        "errors": failures,
        "scopes": len(scopes),
    }


def evaluate_g24(a: dict[str, Any]) -> dict[str, Any]:
    gate = ((a.get("gates") or {}).get("G24") or {})
    parity = ((a.get("metrics") or {}).get("deployment_parity") or {})
    names = (
        "expected_sha",
        "vercel_deployment_sha",
        "frontend_vercelSha",
        "frontend_backendSha",
        "render_release_sha",
    )
    values = {name: parity.get(name) for name in names}
    passed = (
        gate.get("status") == "PASS"
        and all(isinstance(v, str) and len(v) == 40 for v in values.values())
        and len(set(values.values())) == 1
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "criterion": "exact SHA parity across Vercel deployment, Next.js health and Render health",
        "observed": values,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Compile immutable v7.4 certification report")
    ap.add_argument("--g11", type=Path, required=True)
    ap.add_argument("--g16", type=Path, required=True)
    ap.add_argument("--g18", type=Path, required=True)
    ap.add_argument("--g24", type=Path, required=True)
    ap.add_argument("--core-evidence", type=Path, help="JSON containing pre-existing core gates")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    inputs = {"G11": args.g11, "G16": args.g16, "G18": args.g18, "G24": args.g24}
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    failures: list[str] = []
    try:
        artifacts = {name: load_json(path) for name, path in inputs.items()}
        if args.output.exists():
            raise RuntimeError(f"refusing to overwrite existing certification report: {args.output}")
        commits = {
            ((artifact.get("repository") or {}).get("commit_sha"))
            for artifact in artifacts.values()
            if (artifact.get("repository") or {}).get("commit_sha")
        }
        if len(commits) != 1:
            failures.append(f"evidence commit set must contain exactly one SHA; observed={sorted(commits)}")
        try:
            results = {
                "G11": evaluate_g11(artifacts["G11"]),
                "G15": evaluate_g15(artifacts["G11"]),
                "G16": evaluate_g16(artifacts["G16"]),
                "G18": evaluate_g18(artifacts["G18"]),
                "G24": evaluate_g24(artifacts["G24"]),
            }
        except ValueError as exc:
            failures.append(f"evidence schema/metric error: {exc}")
            results = {name: {"status": "BLOCKED", "errors": [str(exc)]} for name in REQUIRED}

        if args.core_evidence:
            core = load_json(args.core_evidence)
            core_commit = ((core.get("repository") or {}).get("commit_sha"))
            if core_commit and commits and core_commit not in commits:
                failures.append(f"core evidence commit mismatch: {core_commit} != {next(iter(commits))}")
            for name, gate in (core.get("gates") or {}).items():
                if name in REQUIRED:
                    continue
                if isinstance(gate, dict):
                    results[name] = gate
                    if gate.get("status") != "PASS":
                        failures.append(f"core gate {name} is {gate.get('status')}")
        else:
            failures.append("core certification evidence not supplied; promotion cannot be certified")

        for name in REQUIRED:
            if results[name].get("status") != "PASS":
                failures.append(f"{name} is {results[name].get('status')}")

        try:
            import sys
            sys.path.insert(0, str(REPO_ROOT / "backend"))
            from src.models.certification_policy import CERTIFICATION_POLICY_VERSION, certification_policy, policy_sha256
            frozen_policy = certification_policy()
            frozen_policy_sha = policy_sha256(frozen_policy)
        except Exception as exc:
            failures.append(f"unable to load frozen certification policy: {exc}")
            CERTIFICATION_POLICY_VERSION = "UNAVAILABLE"
            frozen_policy = {"status": "UNAVAILABLE"}
            frozen_policy_sha = None

        report = {
            "report_version": "v7.4-certificate-1",
            "generated_at": generated,
            "repository": {
                "name": "sabiscore/sabiscore",
                "commit_sha": next(iter(commits), git_sha()),
            },
            "deployment": artifacts["G24"].get("deployment", {}),
            "model": artifacts["G16"].get("model", {}),
            "data": {"evidence_sources": {name: str(path) for name, path in inputs.items()}},
            "policy": {
                "policy_version": CERTIFICATION_POLICY_VERSION,
                "policy_sha256": frozen_policy_sha,
                "frozen_policy": frozen_policy,
                "evidence_policy_version": EVIDENCE_POLICY["version"],
                # The frozen policy's own digest — not a re-hash of the subset
                # read above, which would drift from the authority it cites.
                "evidence_policy_sha256": _POLICY_SHA256,
            },
            "metrics": {name: artifacts[name].get("metrics", {}) for name in artifacts},
            "gates": results,
            "operator_gates": {
                "mode": "AUTONOMOUS_IMPLEMENTATION",
                "ci_bypass_does_not_equal_test_pass": True,
            },
            "risks": [
                "Missing, blocked, inconsistent or stale evidence remains fail-closed.",
                "Historical/reanalysis evidence cannot substitute for current served-path evidence.",
                "The compiler does not modify certification policy.",
            ],
            "changes": [],
            "validation": {
                "inputs_immutable": True,
                "output_overwrite_prohibited": True,
                "required_gates": list(REQUIRED),
            },
            "decision": "ACTIONABLE_CERTIFIED" if not failures else "HOLD",
            "failure_reasons": failures,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["decision"] == "ACTIONABLE_CERTIFIED" else 2
    except Exception as exc:
        result = {
            "report_version": "v7.4-certificate-1",
            "generated_at": generated,
            "repository": {"name": "sabiscore/sabiscore", "commit_sha": git_sha()},
            "gates": {name: {"status": "BLOCKED"} for name in REQUIRED},
            "decision": "HOLD",
            "failure_reasons": [str(exc)],
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
