"""Capture a directive Gate R0 ground-truth snapshot (§3).

`PRODUCTION_EXECUTIVE_DIRECTIVE.md` §3 requires the repository and deployment
state to be re-verified before any new research branch is authorized, and the
result frozen as `reports/ground_truth/GROUND_TRUTH_SNAPSHOT_<date>.json`.

The first such snapshot (2026-09-08) was assembled by hand. That is not
reproducible and cannot be re-run at the start of the next cycle, which is
what §3 actually asks for -- hence this script.

Honesty contract, which is the whole point of the artifact
--------------------------------------------------------
A ground-truth snapshot that guesses is worse than no snapshot, because every
downstream experiment cites it. Therefore:

* Every field is either **measured this run** or explicitly ``None`` with a
  sibling ``*_note`` saying why. Nothing is carried forward from a previous
  snapshot, and nothing is inferred from configuration when the live value was
  the thing being asked for.
* A failed probe records the failure. It never falls back to a plausible value.
* Local artifact reads (`active_generation.json`, the frozen certification
  policy) load standalone via ``spec_from_file_location`` rather than importing
  ``src.models``, because ``core/database.py`` opens a connection at import
  time (docs/DEBT.md item 7) and no database is reachable from a research
  session.

Usage
-----
    .venv/Scripts/python.exe backend/scripts/capture_ground_truth_snapshot.py
    .venv/Scripts/python.exe backend/scripts/capture_ground_truth_snapshot.py --date 2026-09-10
    .venv/Scripts/python.exe backend/scripts/capture_ground_truth_snapshot.py --offline

``--offline`` skips every network probe and records them as not-probed, for
running without egress. It does not change any local measurement.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import pathlib
import subprocess
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
OUT_DIR = REPO_ROOT / "reports" / "ground_truth"

BACKEND_HEALTH = "https://sabiscore-api-bav1.onrender.com/health"
BACKEND_READY = "https://sabiscore-api-bav1.onrender.com/health/ready"
BACKEND_PROVIDERS = "https://sabiscore-api-bav1.onrender.com/api/v1/providers/health"
BACKEND_PERFORMANCE = "https://sabiscore-api-bav1.onrender.com/api/v1/model-performance"
BACKEND_CALIBRATION = (
    "https://sabiscore-api-bav1.onrender.com/api/v1/model-performance/calibration"
)
WEB_HEALTH = "https://web-oversabis-projects.vercel.app/api/health"

PROBE_TIMEOUT_S = 90.0  # a cold Render free-tier dyno legitimately takes ~60s


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------
def _git(*args: str) -> str | None:
    """Run a git command, returning None rather than raising on failure."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _load_standalone(path: pathlib.Path, name: str) -> Any:
    """Load a module by path without triggering the package import chain."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _probe(url: str, offline: bool) -> dict[str, Any]:
    """GET a URL, recording the outcome honestly. Never raises."""
    if offline:
        return {"ok": False, "error": "not probed (--offline)", "body": None}
    try:
        import httpx

        resp = httpx.get(url, timeout=PROBE_TIMEOUT_S, follow_redirects=True)
        body: Any
        try:
            body = resp.json()
        except Exception:
            body = None
        return {
            "ok": resp.status_code == 200,
            "status_code": resp.status_code,
            "error": None if resp.status_code == 200 else f"HTTP {resp.status_code}",
            "body": body,
        }
    except Exception as exc:  # noqa: BLE001 - probe failure is data, not a crash
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "body": None}


def _dig(obj: Any, *keys: str) -> Any:
    """Walk nested dicts, returning None at the first missing key."""
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------
def section_repository() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain") or ""
    tracked_modified = [
        line for line in status.splitlines() if line[:2] not in ("??", "")
    ]
    untracked = [line[3:] for line in status.splitlines() if line.startswith("??")]
    ahead_behind = _git("rev-list", "--left-right", "--count", "origin/master...HEAD")
    behind = ahead = None
    if ahead_behind and len(ahead_behind.split()) == 2:
        behind_s, ahead_s = ahead_behind.split()
        behind, ahead = int(behind_s), int(ahead_s)
    return {
        "source": "git (local working copy)",
        "head_sha": head,
        "head_sha_short": head[:7] if head else None,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "origin_master_sha_short": (_git("rev-parse", "--short", "origin/master")),
        "ahead_behind_origin_master": {"ahead": ahead, "behind": behind},
        "working_tree_dirty": bool(status.strip()),
        "modified_tracked_files": len(tracked_modified),
        "untracked_paths": untracked[:20],
        "last_commit_subject": _git("log", "-1", "--pretty=%s"),
    }


def section_active_generation() -> dict[str, Any]:
    path = BACKEND / "models" / "active_generation.json"
    if not path.exists():
        return {"source": str(path), "error": "manifest not found"}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts", {})
    contract_path = BACKEND / "models" / "feature_contract.json"
    contract_sha = None
    feature_count = None
    if contract_path.exists():
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract_sha = contract.get("contract_sha256")
        features = contract.get("features")
        feature_count = len(features) if isinstance(features, list) else None
    return {
        "source": "backend/models/active_generation.json (hash-verified manifest)",
        "generation": manifest.get("generation"),
        "active_version": manifest.get("active_version"),
        "feature_schema_version": manifest.get("feature_schema_version"),
        "feature_count": feature_count,
        "feature_contract_sha256": contract_sha,
        "served_head": manifest.get("served_head"),
        "certification_state": manifest.get("certification_state"),
        "certified_at": manifest.get("certified_at"),
        "promotion_state": manifest.get("promotion_state"),
        "artifact_count": len(artifacts) if isinstance(artifacts, dict) else None,
        "artifact_leagues": sorted(artifacts) if isinstance(artifacts, dict) else None,
    }


def section_certification_policy() -> dict[str, Any]:
    path = BACKEND / "src" / "models" / "certification_policy.py"
    try:
        module = _load_standalone(path, "_gt_certification_policy")
        policy = module.certification_policy()
        return {
            "source": "backend/src/models/certification_policy.py (frozen, hashed)",
            "policy_version": policy.get("policy_version"),
            "policy_sha256": module.policy_sha256(),
            "gate_names": sorted(policy.get("gates", {}))
            if isinstance(policy.get("gates"), dict)
            else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"source": str(path), "error": f"{type(exc).__name__}: {exc}"}


def section_candidate() -> dict[str, Any]:
    path = BACKEND / "models" / "candidate" / "comparison_report.json"
    if not path.exists():
        return {"source": str(path), "error": "no candidate report present"}
    report = json.loads(path.read_text(encoding="utf-8"))
    gates = report.get("gates")
    return {
        "source": "backend/models/candidate/comparison_report.json",
        "candidate_schema": report.get("candidate_schema")
        or report.get("feature_schema_version"),
        "holdout_season": report.get("holdout_season"),
        "promotion_permitted": report.get("promotion_permitted"),
        "gates": gates if isinstance(gates, dict) else None,
    }


def section_deployment(offline: bool, local_sha_short: str | None) -> dict[str, Any]:
    health = _probe(BACKEND_HEALTH, offline)
    web = _probe(WEB_HEALTH, offline)
    backend_sha = _dig(health["body"], "sha")
    web_backend_sha = _dig(web["body"], "backendSha")
    web_sha = _dig(web["body"], "sha")

    # Deploy parity is backend-vs-web. Local HEAD is deliberately NOT part of
    # it: a research branch is *expected* to sit ahead of production, and
    # reporting that as divergence is a false alarm of exactly the kind
    # CLAUDE.md warns about (three innocent explanations for a stale SHA).
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    on_master = branch == "master"
    if backend_sha and web_sha:
        if backend_sha == web_sha:
            parity = f"DEPLOY PARITY — backend and web both serve {backend_sha}"
            if local_sha_short and local_sha_short != backend_sha:
                parity += f"; local HEAD is {local_sha_short}" + (
                    " on master — check whether a deploy is pending, was "
                    "skipped (render.yaml rootDir=backend skips when nothing "
                    "under backend/ changed), or failed."
                    if on_master
                    else f" on branch '{branch}', which is expected to lead "
                    "production and is not a divergence."
                )
        else:
            parity = (
                f"DIVERGENT — backend={backend_sha} web={web_sha}. Confirm with "
                "`git diff --name-only <backend_sha>..HEAD -- backend/`; an empty "
                "result means Render correctly skipped the deploy."
            )
    else:
        parity = "NOT ASSESSED — one or more deployed SHAs unavailable this run"

    return {
        "backend": {
            "source": f"GET {BACKEND_HEALTH}",
            "probe_ok": health["ok"],
            "probe_error": health["error"],
            "sha": backend_sha,
            "status": _dig(health["body"], "status"),
            "uptime_seconds": _dig(health["body"], "uptime_seconds"),
        },
        "web": {
            "source": f"GET {WEB_HEALTH}",
            "probe_ok": web["ok"],
            "probe_error": web["error"],
            "sha": web_sha,
            "backend_sha_seen": web_backend_sha,
            "backend_status": _dig(web["body"], "backendStatus"),
        },
        "parity_assessment": parity,
        "_health_body_cache": health["body"],
    }


def section_database(health_body: Any, offline: bool) -> dict[str, Any]:
    ready = _probe(BACKEND_READY, offline)
    checks = _dig(ready["body"], "checks") or {}
    migrations = checks.get("migrations") if isinstance(checks, dict) else None
    elo = checks.get("elo") if isinstance(checks, dict) else None
    local_head = None
    versions_dir = BACKEND / "alembic" / "versions"
    if versions_dir.exists():
        revisions = sorted(p.stem for p in versions_dir.glob("0*.py"))
        local_head = revisions[-1] if revisions else None
    applied = _dig(migrations, "head") if isinstance(migrations, dict) else None
    return {
        "source": f"GET {BACKEND_READY}",
        "probe_ok": ready["ok"],
        "probe_error": ready["error"],
        "engine": "postgresql",
        "connection_status": _dig(checks, "database", "status")
        if isinstance(checks, dict)
        else None,
        "alembic_head_applied": applied,
        "alembic_head_expected_local": local_head,
        "migration_drift": (
            None
            if applied is None or local_head is None
            else ("none" if applied == local_head else f"{applied} != {local_head}")
        ),
        "postgres_server_version": None,
        "postgres_server_version_note": (
            "Not exposed by /health/ready. Requires a direct DB connection, which "
            "this script deliberately does not open (docs/DEBT.md item 7)."
        ),
        "elo_state": {
            "rows": _dig(elo, "rows") if isinstance(elo, dict) else None,
            "unique_teams": _dig(elo, "unique_teams")
            if isinstance(elo, dict)
            else None,
            "last_match_date": _dig(elo, "last_match_date")
            if isinstance(elo, dict)
            else None,
        },
    }


def section_runtime() -> dict[str, Any]:
    def _freeze(req: pathlib.Path) -> int | None:
        if not req.exists():
            return None
        return sum(
            1
            for line in req.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith(("#", "-r"))
        )

    return {
        "local_python": ".".join(str(v) for v in sys.version_info[:3]),
        "local_python_role": "research/offline only",
        "production_python": "3.11.9 (render.yaml PYTHON_VERSION)",
        "production_python_note": (
            "Read from configuration, not probed. /health does not expose the "
            "interpreter version."
        ),
        "runtime_requirement_lines": _freeze(BACKEND / "requirements.runtime.txt"),
        "training_requirement_lines": _freeze(BACKEND / "requirements-training.txt"),
        "dev_requirement_lines": _freeze(BACKEND / "requirements-dev.txt"),
        "inference_latency_p95_ms": None,
        "inference_latency_note": (
            "Not measured. Requires a load probe against production, which spends "
            "free-tier capacity and is out of scope for a Gate R0 capture."
        ),
        "memory_ceiling_gb": 8,
        "memory_ceiling_source": "directive §35 development target",
    }


def section_providers(offline: bool) -> dict[str, Any]:
    probe = _probe(BACKEND_PROVIDERS, offline)
    body = probe["body"]
    providers = _dig(body, "providers")
    per_status: dict[str, Any] = {}
    enabled = configured = None
    if isinstance(providers, list):
        for entry in providers:
            if isinstance(entry, dict) and entry.get("provider"):
                per_status[entry["provider"]] = entry.get("status")
        enabled = sum(1 for e in providers if isinstance(e, dict) and e.get("enabled"))
        configured = sum(
            1 for e in providers if isinstance(e, dict) and e.get("configured")
        )
    return {
        "source": f"GET {BACKEND_PROVIDERS}",
        "probe_ok": probe["ok"],
        "probe_error": probe["error"],
        "total": len(providers) if isinstance(providers, list) else None,
        "enabled": enabled,
        "configured": configured,
        "per_provider_status": per_status or None,
        "live_verification_note": (
            "CONFIGURED_UNVERIFIED means the flag is on and a key string is "
            "present. PROVIDER_LIVE_TESTS=false in production, so this is not "
            "evidence the upstream contract works."
        ),
    }


def section_evidence(offline: bool) -> dict[str, Any]:
    perf = _probe(BACKEND_PERFORMANCE, offline)
    cal = _probe(BACKEND_CALIBRATION, offline)
    wf = _dig(perf["body"], "walk_forward")
    clv = _dig(perf["body"], "clv")
    return {
        "settled_predictions": _dig(perf["body"], "settled_predictions"),
        "settled_predictions_source": f"GET {BACKEND_PERFORMANCE}",
        "probe_ok": perf["ok"],
        "probe_error": perf["error"],
        # model_version is reported by /calibration, not by /model-performance.
        "model_version_scoping": _dig(cal["body"], "model_version"),
        "walk_forward": {
            "skipped": _dig(wf, "skipped"),
            "n_splits": _dig(wf, "n_splits"),
            "total_records": _dig(wf, "total_records"),
            "rps_overall": _dig(wf, "rps_overall"),
            "accuracy_overall": _dig(wf, "accuracy_overall"),
            "brier_overall": _dig(wf, "brier_overall"),
        }
        if isinstance(wf, dict)
        else None,
        "calibration": {
            "probe_ok": cal["ok"],
            "probe_error": cal["error"],
            "sample_size": _dig(cal["body"], "sample_size"),
            "meets_sample_floor": _dig(cal["body"], "meets_sample_floor"),
            "ece_mean": _dig(cal["body"], "ece", "mean"),
            "ece_per_class": {
                k: v for k, v in (_dig(cal["body"], "ece") or {}).items() if k != "mean"
            }
            or None,
            "brier_decomposition_mean": _dig(
                cal["body"], "brier_decomposition", "mean"
            ),
            "brier_decomposition_convention": (
                "mean over one-vs-rest per-class Brier; identity is "
                "Brier = Reliability - Resolution + Uncertainty"
            ),
        },
        "model_market_belief_differential": {
            "n": _dig(clv, "n"),
            # The backend spells this 'mean_clv', not 'mean'.
            "mean": _dig(clv, "mean_clv"),
            "positive_rate": _dig(clv, "positive_rate"),
            "skipped": _dig(clv, "skipped"),
            "naming_warning": (
                "The backend field is named 'clv' but measures model belief minus "
                "closing implied probability, which directive §28 says must not be "
                "called CLV. Reported here under its true name."
            ),
        }
        if isinstance(clv, dict)
        else None,
    }


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def build_snapshot(date_str: str, offline: bool) -> dict[str, Any]:
    repository = section_repository()
    deployment = section_deployment(offline, repository.get("head_sha_short"))
    health_body = deployment.pop("_health_body_cache", None)

    snapshot = {
        "snapshot_id": f"GROUND_TRUTH_SNAPSHOT_{date_str}",
        "directive": "Production Executive Directive v5",
        "gate": "R0",
        "phase": "Phase 0 - Ground Truth",
        "captured_at_utc": dt.datetime.now(dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "captured_by": "backend/scripts/capture_ground_truth_snapshot.py",
        "immutability_note": (
            "Frozen for the duration of the v5 experiment cycle. Every field is "
            "either measured at capture time or explicitly null with a note. No "
            "value is carried forward from a previous snapshot."
        ),
        "offline_mode": offline,
        "repository": repository,
        "active_generation": section_active_generation(),
        "certification_policy": section_certification_policy(),
        "candidate_under_evaluation": section_candidate(),
        "deployment": deployment,
        "database": section_database(health_body, offline),
        "runtime": section_runtime(),
        "providers": section_providers(offline),
        "evidence": section_evidence(offline),
    }

    probes = {
        "backend_health": snapshot["deployment"]["backend"]["probe_ok"],
        "web_health": snapshot["deployment"]["web"]["probe_ok"],
        "readiness": snapshot["database"]["probe_ok"],
        "providers": snapshot["providers"]["probe_ok"],
        "model_performance": snapshot["evidence"]["probe_ok"],
    }
    failed = sorted(name for name, ok in probes.items() if not ok)
    snapshot["gate_r0_assessment"] = {
        "result": "PASS" if not failed else "PARTIAL",
        "probes_attempted": len(probes),
        "probes_succeeded": sum(1 for ok in probes.values() if ok),
        "failed_probes": failed,
        "interpretation": (
            "PASS means every §3 field this script can measure was measured. "
            "PARTIAL means one or more live probes failed and those fields are "
            "null -- it does not mean the system is unhealthy, and the null must "
            "not be replaced with a previous cycle's value."
        ),
    }
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
        help="Snapshot date stamp (default: today, UTC).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip every network probe; record them as not-probed.",
    )
    args = parser.parse_args()

    snapshot = build_snapshot(args.date, args.offline)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"GROUND_TRUTH_SNAPSHOT_{args.date}.json"
    out_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    assessment = snapshot["gate_r0_assessment"]
    print(f"wrote {out_path.relative_to(REPO_ROOT)}")
    print(
        f"Gate R0: {assessment['result']} "
        f"({assessment['probes_succeeded']}/{assessment['probes_attempted']} probes)"
    )
    if assessment["failed_probes"]:
        print(f"  failed probes: {', '.join(assessment['failed_probes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
