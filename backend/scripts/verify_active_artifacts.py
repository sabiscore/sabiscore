"""Fail a production build when the hash-locked active generation is invalid."""

from __future__ import annotations

import importlib.util
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "active_generation", BACKEND_ROOT / "src" / "models" / "active_generation.py"
)
if _SPEC is None or _SPEC.loader is None:
    raise SystemExit("Unable to load active-generation verifier")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
load_active_generation = _MODULE.load_active_generation


REQUIRED_LEAGUES = {"epl", "la_liga", "bundesliga", "serie_a", "ligue_1"}


def main() -> None:
    generation = load_active_generation()
    missing = sorted(REQUIRED_LEAGUES - set(generation["artifacts"]))
    if missing:
        raise SystemExit(f"Missing required active artifacts: {', '.join(missing)}")
    print(
        f"Verified {len(generation['artifacts'])} hash-locked artifact pairs "
        f"for {generation['generation']} ({generation['certification_state']})"
    )


if __name__ == "__main__":
    main()
