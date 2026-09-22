"""Regression: relative path settings must anchor to the project root, not the CWD.

Every Path field in Settings declares a `_PROJECT_ROOT`-anchored default, but a
value supplied via .env (as `PHASE7_MODELS_PATH=backend/models`,
`ELO_PARQUET_PATH=data/processed/elo_ratings.parquet`,
`STATSBOMB_CACHE_PATH=...` all are) arrives as a bare relative string. Those were
previously resolved against the process CWD, which differs between pytest
(backend/), uvicorn, Docker and Render.

Every consumer of these paths fails *silently* when the path doesn't exist:

- `PredictionEngine._load_from_disk` skipped the missing `phase7_models_path`
  and fell through to `<root>/models`, which holds the legacy 86-feature
  artifacts under the pre-WP-18 naming scheme (`home_form_5`). That produced
  `SCHEMA_MISMATCH — 68 features supplied, EPL model expects 86` →
  `model_version="fallback"` on every league, and no artifact at all for
  eredivisie (it has no legacy file). The certified 68-feature artifacts sitting
  correctly in `backend/models/` were never reachable.
- `EloEngine._load_table()` returns an empty DataFrame for a missing parquet, so
  all four Elo features — including `elo_difference`, the highest-ATE feature in
  the registry (0.335) — were pinned at their registry defaults on every single
  prediction, making feature vectors nearly identical across fixtures.
- `StatsBombAggregator._load_cache()` does the same.

None of these raise, so the only symptom was undifferentiated predictions and a
fallback model version.
"""

from __future__ import annotations

from pathlib import Path

from src.core.config import Settings, settings


def _project_root() -> Path:
    # backend/tests/unit/ -> repo root
    return Path(__file__).resolve().parents[3]


def test_relative_path_settings_anchor_to_project_root():
    """A relative override must resolve under the repo root, not the CWD."""
    cfg = Settings(
        PHASE7_MODELS_PATH="backend/models",
        ELO_PARQUET_PATH="data/processed/elo_ratings.parquet",
    )
    root = _project_root()

    assert cfg.phase7_models_path.is_absolute()
    assert cfg.phase7_models_path == root / "backend" / "models"
    assert cfg.elo_parquet_path == root / "data" / "processed" / "elo_ratings.parquet"


def test_absolute_path_settings_are_left_alone(tmp_path):
    """An explicit absolute override must never be re-anchored."""
    cfg = Settings(PHASE7_MODELS_PATH=str(tmp_path))
    assert cfg.phase7_models_path == tmp_path


def test_live_artifact_paths_actually_exist():
    """The whole point: these must resolve to real files as the app is configured.

    Guards the silent-fallback class of bug directly — if this fails, inference
    is serving the wrong artifacts (or none) and Elo/StatsBomb are empty, with
    no exception raised anywhere.
    """
    assert settings.phase7_models_path.exists(), (
        f"{settings.phase7_models_path} missing — PredictionEngine would fall "
        "through to the legacy 86-feature artifacts and return model_version='fallback'"
    )
    assert settings.elo_parquet_path.exists(), (
        f"{settings.elo_parquet_path} missing — EloEngine would silently return an "
        "empty table and default every Elo feature"
    )
