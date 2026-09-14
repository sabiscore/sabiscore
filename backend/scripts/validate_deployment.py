#!/usr/bin/env python3
"""G24 exact production deployment SHA parity validator."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import Request, urlopen
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.I)


def sha(value: Any, field: str) -> str:
    value = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(value):
        raise ValueError(f"{field} is not an exact 40-character Git SHA")
    return value


def get_json(url: str, *, timeout: float, token: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json", "Cache-Control": "no-cache", "Pragma": "no-cache", "User-Agent": "sabiscore-g24-validator/2"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise RuntimeError(f"non-object JSON from {url}")
    return body


def cache_bust(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["_g24"] = str(time.time_ns())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def vercel_deployment(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    deployments = payload.get("deployments")
    if not isinstance(deployments, list) or not deployments:
        raise RuntimeError("Vercel returned no production deployment")
    deployment = deployments[0]
    if not isinstance(deployment, dict):
        raise RuntimeError("Vercel deployment entry is not an object")
    meta = deployment.get("meta") if isinstance(deployment.get("meta"), dict) else {}
    source = deployment.get("gitSource") if isinstance(deployment.get("gitSource"), dict) else {}
    for value in (meta.get("githubCommitSha"), source.get("sha"), deployment.get("sha")):
        if value:
            return sha(value, "Vercel deployment SHA"), deployment
    raise RuntimeError("Vercel production deployment did not expose a Git SHA")


def poll(fn: Any, attempts: int, base: float, maximum: float) -> tuple[Any, list[str]]:
    errors: list[str] = []
    for attempt in range(attempts):
        try:
            return fn(), errors
        except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            errors.append(f"attempt {attempt + 1}: {exc}")
            if attempt + 1 < attempts:
                time.sleep(min(maximum, base * (2 ** attempt)))
    raise RuntimeError("; ".join(errors[-3:]) or "poll exhausted")


def validate(args: argparse.Namespace) -> dict[str, Any]:
    expected = sha(args.expected_sha, "expected SHA")
    token = args.vercel_token or os.getenv("VERCEL_TOKEN")
    if not token:
        raise RuntimeError("VERCEL_TOKEN is required")
    query = {"projectId": args.vercel_project_id, "target": "production", "limit": "1"}
    team = args.vercel_team_id or os.getenv("VERCEL_TEAM_ID")
    if team:
        query["teamId"] = team
    deployments_url = "https://api.vercel.com/v6/deployments?" + urlencode(query)

    def read() -> dict[str, Any]:
        deployment_payload = get_json(deployments_url, timeout=args.timeout, token=token)
        deployment_sha, deployment = vercel_deployment(deployment_payload)
        if str(deployment.get("readyState") or "").upper() != "READY":
            raise RuntimeError(f"latest production deployment is not READY: {deployment.get('readyState')!r}")
        frontend = get_json(cache_bust(args.frontend_health_url), timeout=args.timeout)
        backend = get_json(cache_bust(args.backend_health_url), timeout=args.timeout)
        return {"deployment_sha": deployment_sha, "deployment": deployment, "frontend": frontend, "backend": backend}

    observed, poll_errors = poll(read, args.attempts, args.base_delay, args.max_delay)
    frontend = observed["frontend"]
    backend = observed["backend"]
    deployment_sha = observed["deployment_sha"]
    frontend_vercel = sha(frontend.get("vercelSha"), "frontend.vercelSha")
    frontend_backend = sha(frontend.get("backendSha"), "frontend.backendSha")
    backend_release = sha(backend.get("release_sha"), "backend.release_sha")
    errors: list[str] = []
    for label, actual in (("vercel_deployment_sha", deployment_sha), ("frontend_vercelSha", frontend_vercel), ("frontend_backendSha", frontend_backend), ("render_release_sha", backend_release)):
        if actual != expected:
            errors.append(f"{label}: expected {expected}, observed {actual}")
    if frontend_backend != backend_release:
        errors.append(f"frontend/backend SHA mismatch: {frontend_backend} != {backend_release}")
    for label, payload in (("frontend", frontend), ("backend", backend)):
        status = str(payload.get("status") or "").lower()
        if status not in {"ok", "healthy", "ready"}:
            errors.append(f"{label} health status is not healthy: {payload.get('status')!r}")
    return {"report_version": "v7.3-harness-2", "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "repository": {"name": "sabiscore/sabiscore", "commit_sha": expected}, "deployment": {"backend_sha": backend_release, "frontend_sha": deployment_sha, "schema_version": frontend.get("schemaVersion"), "migration_revision": backend.get("migration_revision"), "compatibility_status": "PASS" if not errors else "FAIL", "vercel_ready_state": observed["deployment"].get("readyState")}, "model": {"status": "NOT_EVALUATED"}, "data": {"provenance_status": "NOT_EVALUATED"}, "policy": {"metric_convention": "exact deployment identity parity"}, "metrics": {"deployment_parity": {"expected_sha": expected, "vercel_deployment_sha": deployment_sha, "frontend_vercelSha": frontend_vercel, "frontend_backendSha": frontend_backend, "render_release_sha": backend_release, "poll_errors": poll_errors}}, "gates": {"G24": {"status": "PASS" if not errors else "FAIL", "criterion": "exact SHA parity across Vercel deployment, Next.js health and Render health", "errors": errors}}, "operator_gates": {}, "risks": ["G24 proves release identity and health-contract parity, not functional correctness of the deployed application."], "changes": [], "validation": {"executed": True, "cache_busting": True, "backoff_seconds": {"base": args.base_delay, "max": args.max_delay}}, "decision": "PASS" if not errors else "FAIL"}


def main() -> int:
    ap = argparse.ArgumentParser(description="G24 exact production SHA parity")
    ap.add_argument("--expected-sha", required=True)
    ap.add_argument("--vercel-project-id", required=True)
    ap.add_argument("--vercel-team-id")
    ap.add_argument("--vercel-token")
    ap.add_argument("--frontend-health-url", required=True)
    ap.add_argument("--backend-health-url", required=True)
    ap.add_argument("--attempts", type=int, default=6)
    ap.add_argument("--base-delay", type=float, default=2.0)
    ap.add_argument("--max-delay", type=float, default=20.0)
    ap.add_argument("--timeout", type=float, default=15.0)
    args = ap.parse_args()
    if not 1 <= args.attempts <= 10 or args.timeout <= 0 or args.base_delay < 0 or args.max_delay < args.base_delay:
        raise SystemExit("invalid retry configuration")
    try:
        result = validate(args)
    except Exception as exc:
        result = {"report_version": "v7.3-harness-2", "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "repository": {"name": "sabiscore/sabiscore", "commit_sha": args.expected_sha}, "gates": {"G24": {"status": "BLOCKED", "errors": [str(exc)]}}, "decision": "BLOCKED"}
    out = Path(os.getenv("SABISCORE_G24_OUTPUT", "artifacts/certification/g24_deployment.json"))
    if not out.is_absolute():
        out = Path(__file__).resolve().parents[2] / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
