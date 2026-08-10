"""Fail a production build when the configured active artifact set is incomplete."""

from __future__ import annotations

import json
from pathlib import Path


REQUIRED_LEAGUES = ("epl", "la_liga", "bundesliga", "serie_a", "ligue_1")
OPTIONAL_LEAGUES = ("eredivisie",)
VERSION = "v5_phase7"


def main() -> None:
    models_dir = Path(__file__).resolve().parents[1] / "models"
    missing: list[str] = []
    for league in (*REQUIRED_LEAGUES, *OPTIONAL_LEAGUES):
        artifact = models_dir / f"{league}_ensemble_{VERSION}.pkl"
        metadata = models_dir / f"{league}_ensemble_{VERSION}_metadata.json"
        if league in REQUIRED_LEAGUES and (not artifact.is_file() or not metadata.is_file()):
            missing.append(league)
            continue
        if metadata.is_file():
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            if not isinstance(payload.get("feature_count"), int):
                raise SystemExit(f"Invalid feature_count metadata for {league}")

    if missing:
        raise SystemExit(f"Missing required active artifacts: {', '.join(missing)}")
    print(f"Verified {len(REQUIRED_LEAGUES)} required {VERSION} artifact pairs")


if __name__ == "__main__":
    main()
