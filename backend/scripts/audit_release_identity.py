#!/usr/bin/env python3
"""Audit the release identity chain of the SERVED generation.

Directive §10/§23 require that the source SHA, model artifacts, calibrator,
conformal layer, dataset snapshot, feature contract, certification policy and
serving manifest all refer to **one** certification generation — and that this
can be established from the repository, not from a developer's memory.

This script establishes what is actually bound, and says `UNBOUND` where
nothing binds it. It never infers a link from a filename: two files sharing a
version string is not provenance.

It is an **audit, not a gate**. It exits 0 by default even when links are
missing, and is deliberately not wired into `verify_active_artifacts.py` or the
Render build command: a documentation-shaped finding must not be able to fail a
deploy and hold a healthy release (the vΩ.47 shape). Use `--strict` to exit
non-zero when a required link is unbound, for ad-hoc or future gate use.

    python backend/scripts/audit_release_identity.py \
        --output backend/reports/certification/release-identity-audit.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO_ROOT / "backend" / "models"

BOUND = "BOUND"
UNBOUND = "UNBOUND"
MISMATCH = "MISMATCH"
NOT_APPLICABLE = "NOT_APPLICABLE"


def git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except Exception:
        return os.getenv("SABISCORE_GIT_SHA")


def sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def live_policy() -> tuple[str | None, str | None]:
    """Read the certification policy standalone.

    Importing `src.models` opens a database connection at import time
    (`docs/DEBT.md` item 7), which an offline audit must never do.
    """
    path = REPO_ROOT / "backend" / "src" / "models" / "certification_policy.py"
    try:
        spec = importlib.util.spec_from_file_location("sabiscore_cert_policy", path)
        if spec is None or spec.loader is None:
            return None, None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return (
            str(module.CERTIFICATION_POLICY_VERSION),
            str(module.policy_sha256()),
        )
    except Exception:
        return None, None


def audit() -> dict[str, Any]:
    generation = load_json(MODELS_DIR / "active_generation.json") or {}
    contract = load_json(MODELS_DIR / "feature_contract.json") or {}
    policy_version, policy_hash = live_policy()

    served = str(generation.get("generation") or "")
    served_schema = str(generation.get("feature_schema_version") or "")

    # --- artifact integrity ------------------------------------------------
    artifacts: dict[str, Any] = {}
    artifact_links_ok = True
    for league, entry in sorted((generation.get("artifacts") or {}).items()):
        if not isinstance(entry, dict):
            continue
        path = MODELS_DIR / str(entry.get("artifact"))
        declared = str(entry.get("artifact_sha256") or "")
        actual = sha256_file(path)
        matches = actual is not None and actual == declared
        artifact_links_ok &= matches
        artifacts[league] = {
            "artifact": entry.get("artifact"),
            "declared_sha256": declared,
            "recomputed_sha256": actual,
            "status": BOUND if matches else MISMATCH,
            "required": bool(entry.get("required")),
        }

    # --- does ANY training manifest bind the served generation? ------------
    # A manifest binds only if it names this generation. Sharing a directory or
    # a version substring is not a binding.
    candidates: list[dict[str, Any]] = []
    for path in sorted(MODELS_DIR.rglob("training_manifest*.json")):
        manifest = load_json(path) or {}
        git_block = manifest.get("git") or {}
        candidates.append(
            {
                # Posix-style so a committed report doesn't churn between OSes.
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "declares_generation_id": manifest.get("generation_id"),
                "binds_served_generation": manifest.get("generation_id") == served
                and served != "",
                "feature_schema_version": (manifest.get("features") or {}).get(
                    "feature_schema_version"
                ),
                "certification_policy_sha256": manifest.get(
                    "certification_policy_sha256"
                ),
                "artifact_hashes": manifest.get("artifact_hashes"),
                "git_commit": git_block.get("commit"),
                "git_dirty": git_block.get("dirty"),
                "dataset_sha256": (manifest.get("dataset") or {}).get("dataset_sha256"),
            }
        )

    binding = next((c for c in candidates if c["binds_served_generation"]), None)

    # --- the chain ---------------------------------------------------------
    def link(status: str, detail: str, **extra: Any) -> dict[str, Any]:
        return {"status": status, "detail": detail, **extra}

    chain: dict[str, Any] = {}

    chain["model_artifacts"] = link(
        BOUND if artifact_links_ok and artifacts else UNBOUND,
        "Per-league artifact and metadata SHA-256 are pinned in active_generation.json "
        "and recomputed here.",
        leagues=len(artifacts),
    )

    chain["feature_contract"] = link(
        BOUND
        if contract.get("feature_schema_version") == served_schema and served_schema
        else MISMATCH,
        "feature_contract.json must describe the schema the serving manifest declares.",
        manifest_declares=served_schema,
        contract_declares=contract.get("feature_schema_version"),
        contract_sha256=contract.get("feature_contract_sha256"),
    )

    chain["certification_policy"] = link(
        BOUND if policy_hash else UNBOUND,
        "The policy is hashed and verifiable at runtime, but the serving manifest does "
        "not record WHICH policy version judged this generation — the binding is "
        "implicit, established only by the deployed code.",
        live_policy_version=policy_version,
        live_policy_sha256=policy_hash,
        recorded_in_serving_manifest=False,
    )

    chain["source_commit"] = link(
        BOUND
        if binding and binding.get("git_commit") and not binding.get("git_dirty")
        else UNBOUND,
        "No file records the commit that produced the served artifacts. "
        "active_generation.json has no git field, and per-league metadata carries only "
        "performance figures and trained_at.",
        binding_manifest=(binding or {}).get("path"),
    )

    chain["dataset_snapshot"] = link(
        BOUND if binding and binding.get("dataset_sha256") else UNBOUND,
        "No file records the dataset that produced the served artifacts.",
        binding_manifest=(binding or {}).get("path"),
    )

    chain["calibrator"] = link(
        NOT_APPLICABLE,
        "Calibrators live inside the artifact pickles and are therefore covered by "
        "artifact_sha256. Measured separately: 0 of 6 leagues has a USABLE calibrator "
        "(docs/DEBT.md item 122), so no calibrator participates in serving.",
    )

    chain["conformal"] = link(
        NOT_APPLICABLE,
        "No conformal layer exists in serving. Absent is the honest state, not a gap.",
    )

    required = (
        "model_artifacts",
        "feature_contract",
        "source_commit",
        "dataset_snapshot",
    )
    unbound = [k for k in required if chain[k]["status"] != BOUND]

    return {
        "report_version": "release-identity-audit-1",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": {"name": "sabiscore/sabiscore", "audited_at_commit": git_sha()},
        "served_generation": {
            "generation": served,
            "active_version": generation.get("active_version"),
            "feature_schema_version": served_schema,
            "certification_state": generation.get("certification_state"),
            "promotion_state": generation.get("promotion_state"),
            "certified_at": generation.get("certified_at"),
        },
        "artifact_integrity": artifacts,
        "identity_chain": chain,
        "training_manifests_found": candidates,
        "binding_training_manifest": (binding or {}).get("path"),
        "result": {
            "chain_complete": not unbound,
            "unbound_links": unbound,
            "verdict": (
                "RELEASE_IDENTITY_INCOMPLETE"
                if unbound
                else "RELEASE_IDENTITY_COMPLETE"
            ),
            "interpretation": (
                "Artifacts are hash-pinned, so it is provable they have not CHANGED. "
                "Their ORIGIN is not recorded: no file binds the served generation to a "
                "source commit or a dataset snapshot. Reproducing or re-deriving this "
                "generation from the repository alone is therefore not possible."
                if unbound
                else "Every required link in the release identity chain is bound."
            ),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path)
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when a required link is unbound. Off by default: this is an "
        "audit, and a documentation-shaped finding must not fail a deploy.",
    )
    args = ap.parse_args()

    report = audit()
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)

    result = report["result"]
    print(f"\nverdict: {result['verdict']}")
    for name, link in report["identity_chain"].items():
        print(f"  {link['status']:<15} {name}")

    return 1 if args.strict and not result["chain_complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
