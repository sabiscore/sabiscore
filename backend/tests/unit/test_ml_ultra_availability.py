"""Ultra capability detection must be truthful when optional deps are absent."""

from __future__ import annotations

from src import ml_ultra


def test_ultra_unavailable_when_any_core_component_is_missing(monkeypatch) -> None:
    def fake_lazy_import(name: str):
        return object() if name == "DiverseEnsemble" else None

    monkeypatch.setattr(ml_ultra, "_lazy_import", fake_lazy_import)
    assert ml_ultra.is_ultra_available() is False


def test_ultra_available_only_when_both_core_components_load(monkeypatch) -> None:
    monkeypatch.setattr(ml_ultra, "_lazy_import", lambda _name: object())
    assert ml_ultra.is_ultra_available() is True
