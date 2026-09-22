#!/usr/bin/env python3
"""Offline G24 (deployment parity) preparatory audit -- config-vs-route
static analysis only. Needs no VERCEL_TOKEN and makes no network call.

Corrections applied relative to the original request, recorded here rather
than silently:

1. **Entry point is ``src/api/main.py``, not ``src/main.py``.** The request
   named a path that does not exist in this repository; confirmed against
   ``render.yaml``'s own ``startCommand`` (``uvicorn src.api.main:app``).
2. **Reuses the existing safe-import pattern** from
   ``scripts/verify_openapi.py`` (``_import_app()``) rather than a fresh
   ``from src.api.main import app``. That existing script sets
   ``ALLOW_SQLITE_FALLBACK=true`` / a local SQLite ``DATABASE_URL`` *before*
   import specifically so importing the app package does not attempt a real
   database connection, plus a Windows-safe timeout -- both real, previously
   solved problems this script does not need to re-solve or risk getting
   wrong.
3. **This is explicitly PARTIAL evidence for G24, not a full pass.** Per
   the directive's own P16: release identity requires *both* release-time
   *and* runtime verification (live SHA, live health) -- this script can
   only ever check "does the static config make sense", which is real,
   useful, but categorically cannot replace ``validate_deployment.py``
   (needs ``VERCEL_TOKEN``, not run here). The output says so explicitly.
4. **Does not invent an API-key-auth finding.** The request asked to flag
   "missing authentication headers" -- but per ``PRODUCTION_EXECUTIVE_
   DIRECTIVE.md`` sec 15.3.8/sec 27 (as of commit 623bb9e), no customer-facing
   API-key auth layer exists in this repository yet; it is explicitly a
   standing *future* policy, not implemented code. Reporting a finding
   against code that does not exist would itself be a fabrication. This
   script instead reports that check as N/A with the reason, and focuses on
   what it can actually observe: route-vs-rewrite coverage, and Vercel cron
   registration vs. the Next.js route files that actually exist.

Usage:

    cd backend
    PYTHONPATH=. python scripts/audit_g24_deployment_parity.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
for p in (str(BACKEND_ROOT), str(SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_vercel_json() -> dict[str, Any]:
    path = REPO_ROOT / "vercel.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    return json.loads(path.read_text(encoding="utf-8"))


def _backend_paths() -> tuple[set[str], dict[str, list[str]]]:
    """Returns (all paths, {path: [methods]}) from the real, safely-imported
    FastAPI OpenAPI schema -- see module docstring point 2."""
    from verify_openapi import (
        _import_app,
    )  # same directory; reuses the safe-import timeout dance

    app = _import_app()
    schema = app.openapi()
    paths = schema.get("paths", {})
    methods = {
        path: sorted(
            m.upper()
            for m in ops
            if m.lower() in {"get", "post", "put", "patch", "delete"}
        )
        for path, ops in paths.items()
    }
    return set(paths), methods


def _rewrite_prefix_covered(rewrite_source: str, backend_paths: set[str]) -> bool:
    """A rewrite source like '/api/v1/:path*' or '/api/v1/health' is
    considered covered if at least one real backend path matches its
    static (non-wildcard) prefix. This cannot prove full coverage of a
    wildcard rewrite (that needs the live traffic Vercel actually sees,
    G24's runtime half) -- only that the rewrite isn't pointed at a
    completely dead prefix."""
    static_prefix = re.split(r":\w+\*?", rewrite_source, maxsplit=1)[0]
    if rewrite_source in backend_paths:
        return True
    return (
        any(p.startswith(static_prefix) for p in backend_paths)
        if static_prefix
        else False
    )


def audit() -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    vercel = _load_vercel_json()

    try:
        backend_paths, backend_methods = _backend_paths()
        backend_status = "IMPORTED"
    except Exception as exc:  # noqa: BLE001 - report, do not crash the audit
        backend_paths, backend_methods = set(), {}
        backend_status = f"IMPORT_FAILED: {exc}"
        findings.append(
            {"severity": "BLOCKED", "area": "backend_import", "detail": str(exc)}
        )

    # 1. Rewrites -> real backend paths.
    for rewrite in vercel.get("rewrites", []):
        source, dest = rewrite.get("source", ""), rewrite.get("destination", "")
        if "onrender.com" not in dest and "localhost" not in dest:
            continue
        covered = (
            _rewrite_prefix_covered(source, backend_paths) if backend_paths else None
        )
        if covered is False:
            findings.append(
                {
                    "severity": "MISMATCH",
                    "area": "rewrite",
                    "detail": f"vercel.json rewrite '{source}' -> '{dest}' has no matching backend path prefix in the live OpenAPI schema",
                }
            )

    # 2. Crons -> the Next.js route files that actually exist.
    registered_crons = {c.get("path") for c in vercel.get("crons", [])}
    cron_dir = REPO_ROOT / "apps" / "web" / "src" / "app" / "api" / "cron"
    existing_cron_routes = (
        {
            f"/api/cron/{d.name}"
            for d in cron_dir.iterdir()
            if d.is_dir() and (d / "route.ts").exists()
        }
        if cron_dir.exists()
        else set()
    )
    for route_path in sorted(existing_cron_routes - registered_crons):
        findings.append(
            {
                "severity": "MISMATCH",
                "area": "cron",
                "detail": f"{route_path}/route.ts exists but is NOT in vercel.json's crons array -- per sec 25 of the governing directive, it will never fire automatically (Vercel only registers crons listed there at deploy time)",
            }
        )
    for route_path in sorted(registered_crons - existing_cron_routes):
        findings.append(
            {
                "severity": "MISMATCH",
                "area": "cron",
                "detail": f"vercel.json registers cron '{route_path}' but no matching Next.js route file was found",
            }
        )

    # 3. Auth headers -- explicitly N/A, not fabricated. See module docstring point 4.
    findings.append(
        {
            "severity": "N/A",
            "area": "auth_headers",
            "detail": "No customer-facing API-key auth layer exists in this repository as of this audit (directive sec 15.3.8/sec 27 -- standing future policy, not implemented code). Nothing to check.",
        }
    )

    # 4. HTTP methods -- report what exists, flag nothing unverifiable.
    unusual = {
        p: m
        for p, m in backend_methods.items()
        if any(x in m for x in ("PUT", "DELETE", "PATCH"))
    }
    if unusual:
        findings.append(
            {
                "severity": "INFO",
                "area": "http_methods",
                "detail": f"{len(unusual)} backend path(s) accept PUT/DELETE/PATCH -- verify these are intentional, not evaluated further by this offline audit",
                "paths": list(unusual)[:10],
            }
        )

    decision = (
        "BLOCKED"
        if backend_status != "IMPORTED"
        else (
            "PARTIAL_MISMATCHES_FOUND"
            if any(f["severity"] == "MISMATCH" for f in findings)
            else "PARTIAL_NO_MISMATCHES_FOUND"
        )
    )

    return {
        "report_kind": "g24_offline_deployment_parity_audit",
        "scope": "STATIC CONFIG-VS-ROUTE ANALYSIS ONLY -- not a full G24 pass. No VERCEL_TOKEN, no network call, no live SHA/health check. Run scripts/validate_deployment.py separately for that.",
        "backend_import_status": backend_status,
        "backend_path_count": len(backend_paths),
        "vercel_rewrite_count": len(vercel.get("rewrites", [])),
        "vercel_cron_count": len(registered_crons),
        "findings": findings,
        "decision": decision,
    }


def main() -> int:
    report = audit()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["decision"] != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
