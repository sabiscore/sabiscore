"""Config-driven source registry for V4/Phase 9 candidate enrichment.

Keeps the new data stack explicit, auditable, and discoverable. It does not
instantiate network clients until callers request them; it is purely a
descriptor catalogue that can be serialised to logs/metadata/health checks.

Usage::

    from src.connectors.source_registry import build_source_registry, registry_summary

    registry = build_source_registry(settings=settings)
    for source in registry:
        if source.enabled:
            logger.info("V4 source enabled: %s (%s)", source.name, source.category)

    # Health-endpoint friendly summary
    summary = registry_summary(registry)
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceDescriptor:
    """Immutable descriptor for one V4 enrichment source.

    Attributes
    ----------
    name:
        Canonical source identifier.
    category:
        Broad data category: ``"fixtures_results"``, ``"xg"``,
        ``"event_data"``, ``"betting_market"``.
    enabled:
        Whether this source is active in the current config.
    official_api:
        ``True`` when the source has an official API with published ToS.
        ``False`` for scraping-backed or unofficial sources.
    request_time_safe:
        ``True`` only when the source can safely be called *during*
        inference request handling (i.e. low-latency, cached, pure-math).
        ``False`` for batch-only / offline sources.
    notes:
        Human-readable policy / usage note.
    """

    name: str
    category: str
    enabled: bool
    official_api: bool
    request_time_safe: bool
    notes: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_source_registry(*, settings: object | None = None) -> list[SourceDescriptor]:
    """Build the V4 source registry from the current ``settings`` object.

    Any attribute access on ``settings`` that is absent falls back to
    ``None``/``False`` so this function is safe even with a partial config
    (e.g. in unit tests using a minimal mock settings object).
    """

    def _get(key: str, default: Any = None) -> Any:
        return getattr(settings, key, default) if settings is not None else default

    registry: list[SourceDescriptor] = [
        SourceDescriptor(
            name="football-data.org",
            category="fixtures_results",
            enabled=bool(_get("football_data_api_key")),
            official_api=True,
            request_time_safe=False,
            notes=(
                "Official API-first fixture and result reconciliation. "
                "Free tier: 10 req/min. Use offline / scheduled "
                "(see backend/scripts/backfill_v4_data_sources.py)."
            ),
        ),
        SourceDescriptor(
            name="understat/soccerdata",
            category="xg",
            enabled=bool(_get("use_phase9_candidate_features", False)),
            official_api=False,
            request_time_safe=False,
            notes=(
                "Unofficial xG source via soccerdata. "
                "Keep in offline/shadow workflows unless ToS policy is approved."
            ),
        ),
        SourceDescriptor(
            name="statsbomb-open-data",
            category="event_data",
            # NOTE: gates on the Phase 8 `statsbomb_cache_path` setting as a
            # coarse proxy for "StatsBomb infrastructure is configured in
            # this deployment". That setting always has a non-None default
            # (see core/config.py), so this currently reports `enabled=True`
            # regardless of whether an open-data clone exists on disk. A
            # dedicated `statsbomb_open_data_root` setting is the Phase 9.1
            # follow-up to make this strictly accurate (see
            # docs/V4_PHASE9_SHADOW_MODE.md, "Known limitations").
            enabled=bool(_get("statsbomb_cache_path")),
            official_api=True,
            request_time_safe=False,
            notes=(
                "StatsBomb open-data event experiments and xG feature research. "
                "Offline only - data must be pre-cloned from GitHub. Distinct "
                "from the Phase 8 statsbomb_features_cache.parquet artifact."
            ),
        ),
        SourceDescriptor(
            name="odds-market-features",
            category="betting_market",
            enabled=True,
            official_api=True,
            request_time_safe=True,
            notes=(
                "Pure-math over supplied odds snapshots "
                "(backend/src/connectors/odds_market.py). "
                "No network I/O - safe to compute during inference."
            ),
        ),
    ]
    return registry


def enabled_source_names(registry: Iterable[SourceDescriptor]) -> list[str]:
    """Return names of all enabled sources in registration order."""
    return [s.name for s in registry if s.enabled]


def request_time_safe_sources(
    registry: Iterable[SourceDescriptor],
) -> list[SourceDescriptor]:
    """Return sources that are safe to call during live inference."""
    return [s for s in registry if s.enabled and s.request_time_safe]


def offline_sources(
    registry: Iterable[SourceDescriptor],
) -> list[SourceDescriptor]:
    """Return enabled sources that must run offline/batch only."""
    return [s for s in registry if s.enabled and not s.request_time_safe]


def registry_summary(registry: list[SourceDescriptor]) -> dict[str, Any]:
    """Produce a JSON-serialisable summary for metadata / health endpoints."""
    return {
        "total": len(registry),
        "enabled": sum(1 for s in registry if s.enabled),
        "request_time_safe": sum(
            1 for s in registry if s.enabled and s.request_time_safe
        ),
        "sources": [s.as_dict() for s in registry],
    }
