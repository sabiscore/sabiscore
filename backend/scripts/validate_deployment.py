#!/usr/bin/env python3
"""G24 exact deployment SHA parity validator.

Validates three independent identities:
1. Vercel's latest production deployment Git SHA via the Vercel API.
2. Vercel Next.js ``/api/health`` -> ``vercelSha``.
3. Render FastAPI ``/health`` or ``/health/ready`` -> ``release_sha``.

The frontend health response's ``backendSha`` is also compared to Render. The
validator polls with bounded exponential backoff to tolerate Render cold starts
and edge-cache propagation. Missing/invalid SHA is always a failure.

Required environment variables when using the Vercel API:
    VERCEL_TOKEN
Optional:
    VERCEL_TEAM_ID

Example:
    python backend/scripts/validate_deployment.py \
      --expected-sha 3a067... \
      --vercel-project-id prj_xxx \
      --frontend-health-url https://sabiscore.vercel.app/api/health \
      --backend-health-url https://sabiscore-api.onrender.com/health
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.I)


def _sha(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise ValueError(f"{field} is not an exact 40-character Git SHA")
    return text


def _get_json(url: str, *, timeout: float, token: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "sabiscore-g24-validator/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"non-object JSON from {url}")
    return payload


def _vercel_deployment_sha(payload: dict[str, Any]) -> str:
    deployments = payload.get("deployments")
    if not isinstance(deployments, list) or not deployments:
        raise RuntimeError("Vercel returned no production deployments")
    deployment = deployments[0]
    if not isinstance(deployment, dict):
        raise RuntimeError("Vercel deployment entry is not an object")
    candidates = [
        deployment.get("meta", {}).get("githubCommitSha") if isinstance(deployment.get("meta"), dict) else None,
        deployment.get("gitSource", {}).get("sha") if isinstance(deployment.get("gitSource"), dict) else None,
        deployment.get("sha"),
    ]
    for value in candidates:
        if value:
            return _sha(value, "vercel deployment SHA")
    raise RuntimeError("Vercel production deployment did not expose a Git SHA")


def _poll(fn: Any, *, attempts: int, base_delay: float, max_delay: float) -> tuple[Any, list[str]]:
    errors: list[str] = []
    for attempt in range(attempts):
        try:
            return fn(), errors
        except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            errors.append(f"attempt {attempt + 1}: {exc}")
            if attempt + 1 < attempts:
                time.sleep(min(max_delay, base_delay * (2**attempt)))
    raise RuntimeError("; ".join(errors[-3:]) or "poll exhausted")


def validate(args: argparse.Namespace) -> dict[str, Any]:
    expected = _sha(args.expected_sha, "expected SHA")
    token = args.vercel_token or os.getenv("VERCEL_TOKEN")
    if not token:
        raise RuntimeError("VERCEL_TOKEN is required to prove the Vercel production deployment SHA")
    query = {"projectId": args.vercel_project_id, "target": "production", "limit": "1"}
    if args.vercel_team_id or os.getenv("VERCEL_TEAM_ID"):
        query["teamId"] = args.vercel_team_id or os.environ["VERCEL_TEAM_ID"]
    deployments_url = "https://api.vercel.com/v6/deployments?" + urlencode(query)

    def read_all() -> dict[str, Any]:
        deployment_payload = _get_json(deployments_url, timeout=args.timeout, token=token)
        deployment_sha = _vercel_deployment_sha(deployment_payload)
        frontend = _get_json(args.frontend_health_url, timeout=args.timeout)
        backend = _get_json(args.backend_health_url, timeout=args.timeout)
        return {"deployment_sha": deployment_sha, "frontend": frontend, "backend": backend}

    observed, poll_errors = _poll(read_all, attempts=args.attempts, base_delay=args.base_delay, max_delay=args.max_delay)
    frontend = observed["frontend"]
    backend = observed["backend"]
    vercel_sha = observed["deployment_sha"]
    frontend_vercel_sha = _sha(frontend.get("vercelSha"), "frontend.vercelSha")
    frontend_backend_sha = _sha(frontend.get("backendSha"), "frontend.backendSha")
    backend_sha = _sha(backend.get("release_sha"), "backend.release_sha")
    errors: list[str] = []
    for name, actual in (("vercel_deployment_sha", vercel_sha), ("frontend_vercelSha", frontend_vercel_sha), ("frontend_backendSha", frontend_backend_sha), ("render_release_sha", backend_sha)):
        if actual != expected:
            errors.append(f"{name} mismatch: expected={expected} actual={actual}")
    if frontend_backend_sha != backend_sha:
        errors.append(f"frontend/backend mismatch: frontend={frontend_backend_sha} render={backend_sha}")
    if str(frontend.get("status") or "").lower() not in {"ok", "healthy", "ready"}:
        errors.append(f"frontend health status not healthy: {frontend.get('status')!r}")
    return {
        "report_version": "v7.3-harness-1",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": {"name": "sabiscore/sabiscore", "commit_sha": expected, "branch": None, "working_tree_clean": None},
        "deployment": {"backend_sha": backend_sha, "frontend_sha": vercel_sha, "schema_version": frontend.get("schemaVersion"), "migration_revision": backend.get("migration_revision"), "compatibility_status": "PASS" if not errors else "FAIL"},
        "model": {"generation_id": None, "model_family": None, "feature_contract": None, "artifact_hash": None, "schema_version": None, "status": "NOT_EVALUATED", "calibration": None},
        "data": {"dataset_snapshot": None, "temporal_window": None, "coverage": None, "provenance_status": "NOT_EVALUATED", "leakage_status": "NOT_EVALUATED", "forecast_authenticity": "NOT_EVALUATED"},
        "policy": {"policy_version": None, "policy_sha256": None, "metric_convention": None, "class_order": None},
        "metrics": {"deployment_parity": {"expected_sha": expected, "vercel_deployment_sha": vercel_sha, "frontend_vercelSha": frontend_vercel_sha, "frontend_backendSha": frontend_backend_sha, "render_release_sha": backend_sha, "poll_errors": poll_errors}},
        "gates": {"G24": {"status": "PASS" if not errors else "FAIL", "criterion": "exact Git SHA parity across Vercel deployment, frontend health, frontend-observed backend, and Render health", "errors": errors}},
        "operator_gates": {}, "risks": ["This proves release identity parity, not application correctness beyond the exposed health contract."],
        "changes": [], "validation": {"poll_attempts": args.attempts, "backoff_seconds": {"base": args.base_delay, "max": args.max_delay}, "executed": True},
        "decision": "PASS" if not errors else "FAIL",
    }


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Validate G24 exact production SHA parity")
    p.add_argument("--expected-sha", required=True)
    p.add_argument("--vercel-project-id", required=True)
    p.add_argument("--vercel-team-id", default=None)
    p.add_argument("--vercel-token", default=None)
    p.add_argument("--frontend-health-url", required=True)
    p.add_argument("--backend-health-url", required=True)
    p.add_argument("--attempts", type=int, default=6)
    p.add_argument("--base-delay", type=float, default=2.0)
    p.add_argument("--max-delay", type=float, default=20.0)
    p.add_argument("--timeout", type=float, default=15.0)
    return p


def main() -> int:
    args = _parser().parse_args()
    if args.attempts < 1 or args.attempts > 10 or args.timeout <= 0 or args.base_delay < 0 or args.max_delay < args.base_delay:
        raise SystemExit("invalid retry/timeout configuration")
    try:
        result = validate(args)
    except Exception as exc:
        result = {"report_version": "v7.3-harness-1", "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "repository": {"name": "sabiscore/sabiscore", "commit_sha": args.expected_sha}, "gates": {"G24": {"status": "BLOCKED", "errors": [str(exc)]}}, "decision": "BLOCKED"}
    out = Path(os.getenv("SABISCORE_G24_OUTPUT", "artifacts/certification/g24_deployment.json"))
    if not out.is_absolute():
        out = Path(__file__).resolve().parents[2] / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
