"""Tests for backend/src/connectors/source_registry.py.

Run:
    cd backend && pytest tests/test_connectors/test_source_registry.py -v
"""

from __future__ import annotations


from src.connectors.source_registry import (
    build_source_registry,
    enabled_source_names,
    offline_sources,
    registry_summary,
    request_time_safe_sources,
)


class _MockSettings:
    """Minimal settings-like object for testing."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class TestBuildSourceRegistry:
    def test_returns_four_sources_by_default(self):
        registry = build_source_registry()
        assert len(registry) == 4

    def test_odds_market_always_enabled(self):
        registry = build_source_registry()
        odds = next(s for s in registry if s.name == "odds-market-features")
        assert odds.enabled is True
        assert odds.request_time_safe is True

    def test_football_data_disabled_without_key(self):
        registry = build_source_registry(settings=_MockSettings(football_data_api_key=None))
        fd = next(s for s in registry if s.name == "football-data.org")
        assert fd.enabled is False

    def test_football_data_enabled_with_key(self):
        registry = build_source_registry(
            settings=_MockSettings(football_data_api_key="abc123")
        )
        fd = next(s for s in registry if s.name == "football-data.org")
        assert fd.enabled is True

    def test_understat_enabled_with_phase9_flag(self):
        registry = build_source_registry(
            settings=_MockSettings(use_phase9_candidate_features=True)
        )
        us = next(s for s in registry if s.name == "understat/soccerdata")
        assert us.enabled is True

    def test_understat_disabled_by_default(self):
        registry = build_source_registry()
        us = next(s for s in registry if s.name == "understat/soccerdata")
        assert us.enabled is False

    def test_statsbomb_enabled_with_cache_path(self):
        registry = build_source_registry(
            settings=_MockSettings(statsbomb_cache_path="/data/statsbomb")
        )
        sb = next(s for s in registry if s.name == "statsbomb-open-data")
        assert sb.enabled is True

    def test_works_with_none_settings(self):
        registry = build_source_registry(settings=None)
        assert len(registry) == 4

    def test_offline_sources_not_request_time_safe(self):
        registry = build_source_registry()
        offline = offline_sources(registry)
        for s in offline:
            assert not s.request_time_safe


class TestEnabledSourceNames:
    def test_only_enabled_returned(self):
        registry = build_source_registry()
        names = enabled_source_names(registry)
        assert "odds-market-features" in names
        assert "football-data.org" not in names  # disabled without key

    def test_with_all_enabled(self):
        registry = build_source_registry(
            settings=_MockSettings(
                football_data_api_key="key",
                use_phase9_candidate_features=True,
                statsbomb_cache_path="/data",
            )
        )
        names = enabled_source_names(registry)
        assert len(names) == 4


class TestRequestTimeSafeSources:
    def test_only_odds_market_is_request_time_safe(self):
        registry = build_source_registry()
        safe = request_time_safe_sources(registry)
        assert len(safe) == 1
        assert safe[0].name == "odds-market-features"


class TestRegistrySummary:
    def test_summary_shape(self):
        registry = build_source_registry()
        summary = registry_summary(registry)
        assert "total" in summary
        assert "enabled" in summary
        assert "request_time_safe" in summary
        assert "sources" in summary
        assert summary["total"] == 4
        assert summary["request_time_safe"] == 1

    def test_sources_are_serialisable(self):
        """All fields must be JSON-compatible types."""
        import json

        registry = build_source_registry()
        summary = registry_summary(registry)
        json.dumps(summary)  # must not raise
