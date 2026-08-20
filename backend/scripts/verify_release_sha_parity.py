"""Fail-closed exact-SHA production release verifier.

The backend must expose Render's exact Git SHA through ``/health/ready`` and the
frontend must expose Vercel's exact Git SHA through ``/api/health``.  A healthy
process is not sufficient: all independent release identities must equal the
reviewed GitHub master SHA.

Example:

    # backend/
    python scripts/verify_release_sha_parity.py \
      --expected-sha 0123456789abcdef0123456789abcdef01234567 \
      --backend-ready-url https://api.example.com/health/ready \
      --frontend-health-url https://www.example.com/api/health
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def _normalize_sha(value: object, *, field: str) -> str:
    candidate = str(value or "").strip().lower()
    if not _SHA_RE.fullmatch(candidate):
        raise ValueError(f"{field} must be an exact 40-character Git SHA")
    return candidate


def _fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "sabiscore-release-parity-verifier/1",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"release parity request failed for {url}: {exc}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"release parity endpoint returned invalid JSON: {url}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"release parity endpoint returned non-object JSON: {url}")
    return payload


def evaluate_release_parity(
    *,
    expected_sha: str,
    backend_payload: dict[str, Any],
    frontend_payload: dict[str, Any],
) -> dict[str, Any]:
    expected = _normalize_sha(expected_sha, field="expected_sha")
    observed: dict[str, str | None] = {
        "github_master_sha": expected,
        "render_api_sha": None,
        "vercel_sha": None,
        "frontend_observed_backend_sha": None,
    }
    errors: list[str] = []

    for output_key, source, source_key in (
        ("render_api_sha", backend_payload, "release_sha"),
        ("vercel_sha", frontend_payload, "vercelSha"),
        ("frontend_observed_backend_sha", frontend_payload, "backendSha"),
    ):
        try:
            observed[output_key] = _normalize_sha(source.get(source_key), field=source_key)
        except ValueError as exc:
            errors.append(str(exc))

    for key in ("render_api_sha", "vercel_sha", "frontend_observed_backend_sha"):
        actual = observed[key]
        if actual is not None and actual != expected:
            errors.append(f"{key} mismatch: expected={expected} actual={actual}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "expected_sha": expected,
        "observed": observed,
        "errors": errors,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify exact Git SHA parity in production")
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--backend-ready-url", required=True)
    parser.add_argument("--frontend-health-url", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.timeout_seconds <= 0 or args.timeout_seconds > 60:
        raise SystemExit("--timeout-seconds must be > 0 and <= 60")
    try:
        expected = _normalize_sha(args.expected_sha, field="--expected-sha")
        backend = _fetch_json(args.backend_ready_url, timeout_seconds=args.timeout_seconds)
        frontend = _fetch_json(args.frontend_health_url, timeout_seconds=args.timeout_seconds)
        result = evaluate_release_parity(
            expected_sha=expected,
            backend_payload=backend,
            frontend_payload=frontend,
        )
    except (RuntimeError, ValueError) as exc:
        result = {
            "status": "FAIL",
            "expected_sha": args.expected_sha,
            "observed": {},
            "errors": [str(exc)],
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
