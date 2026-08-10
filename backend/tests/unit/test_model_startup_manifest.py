from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api import main


def test_strict_startup_loads_only_manifested_generation(monkeypatch) -> None:
    manifest_dir = Path("C:/verified-models")
    generation = {
        "active_version": "v5_phase7",
        "generation": "v5_phase7-test",
        "manifest_sha256": "a" * 64,
        "manifest_path": manifest_dir / "active_generation.json",
        "artifacts": {"epl": {}},
    }
    model = SimpleNamespace(model_metadata={"league": "epl"}, is_trained=True)
    captured: dict[str, object] = {}

    monkeypatch.setattr(main, "load_active_generation", lambda: generation)
    monkeypatch.setattr(main, "_resolve_active_leagues", lambda: ("epl",))
    monkeypatch.setattr(main, "_prime_prediction_service_cache", lambda models: None)

    def fake_load(**kwargs):
        captured.update(kwargs)
        return {"epl": model}

    monkeypatch.setattr(main, "load_ensemble_per_league", fake_load)
    monkeypatch.setenv("ACTIVE_BASELINE_VERSION", "v5_phase7")
    app = SimpleNamespace(state=SimpleNamespace())

    main._startup_load_models_strict(app)

    assert captured["model_base_url"] is None
    assert captured["fetch_token"] is None
    assert captured["local_model_dirs"] == [manifest_dir]
    assert app.state.model_generation == "v5_phase7-test"
    assert app.state.model_manifest_sha256 == "a" * 64


def test_strict_startup_rejects_version_outside_manifest(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "load_active_generation",
        lambda: {
            "active_version": "v5_phase7",
            "artifacts": {"epl": {}},
        },
    )
    monkeypatch.setattr(main, "_resolve_active_leagues", lambda: ("epl",))
    monkeypatch.setenv("ACTIVE_BASELINE_VERSION", "apex")
    app = SimpleNamespace(state=SimpleNamespace())

    with pytest.raises(RuntimeError, match="does not match"):
        main._startup_load_models_strict(app)
