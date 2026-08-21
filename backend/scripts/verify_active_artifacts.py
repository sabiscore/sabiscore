"""Fail a production build when the hash-locked active generation is invalid."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Unable to load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_active_generation = _load_module(
    "active_generation", BACKEND_ROOT / "src" / "models" / "active_generation.py"
)
_release_identity = _load_module(
    "release_identity", BACKEND_ROOT / "src" / "core" / "release_identity.py"
)
load_active_generation = _active_generation.load_active_generation
verify_feature_contract_freshness = _active_generation.verify_feature_contract_freshness
ActiveGenerationError = _active_generation.ActiveGenerationError
write_release_identity_manifest = _release_identity.write_release_identity_manifest


REQUIRED_LEAGUES = {"epl", "la_liga", "bundesliga", "serie_a", "ligue_1"}


def main() -> None:
    generation = load_active_generation()
    missing = sorted(REQUIRED_LEAGUES - set(generation["artifacts"]))
    if missing:
        raise SystemExit(f"Missing required active artifacts: {', '.join(missing)}")

    # Build-time only, never on the startup or staking path — a stale derived
    # contract must fail the deploy (previous release keeps serving), not make
    # the API unbootable. See verify_feature_contract_freshness's docstring.
    try:
        verify_feature_contract_freshness()
    except ActiveGenerationError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        identity = write_release_identity_manifest(
            strict=bool(os.getenv("RENDER_SERVICE_ID"))
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    print(
        f"Verified {len(generation['artifacts'])} hash-locked artifact pairs "
        f"for {generation['generation']} ({generation['certification_state']})"
    )
    if identity is not None:
        print(
            "Verified exact build release identity "
            f"{identity['release_sha']}"
        )


if __name__ == "__main__":
    main()
