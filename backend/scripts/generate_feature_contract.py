#!/usr/bin/env python3
"""Generate backend/models/feature_contract.json for the active generation.

Regenerate this after any change to feature_registry.py's schema
definitions/derivation rules, or after active_generation.json's
feature_schema_version changes. active_generation.py's
verify_feature_contract_freshness() re-derives the contract and fails
closed if this checked-in copy has drifted, but only at build time via
scripts/verify_active_artifacts.py — not on every load_active_generation()
call, so a drift here fails a deploy rather than crash-looping a running
service (docs/DEBT.md item 36) — running this script is how you keep it
in sync.

Loads feature_registry.py standalone by file path, the same pattern
verify_active_artifacts.py uses, so this script never needs a database
connection: build_feature_contract() is pure stdlib computation and has no
business depending on src.models's package-level DB import chain.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = BACKEND_ROOT / "models"


def _load_feature_registry():
    path = BACKEND_ROOT / "src" / "models" / "feature_registry.py"
    spec = importlib.util.spec_from_file_location("_sabiscore_feature_registry", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    registry = _load_feature_registry()
    manifest = json.loads((MODELS_DIR / "active_generation.json").read_text(encoding="utf-8"))
    schema_version = manifest.get("feature_schema_version")
    contract = registry.build_feature_contract(schema_version)
    out_path = MODELS_DIR / "feature_contract.json"
    out_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {out_path} for feature_schema_version={schema_version!r} "
        f"({contract['feature_count']} features)"
    )


if __name__ == "__main__":
    main()
