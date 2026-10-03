"""Understat Ingestion & ML Feature Pipeline Package."""

from .entity_map import (
    UNDERSTAT_ENTITY_MAP,
    UnmappedEntityError,
    resolve_slug,
)
from .formatter import (
    MAX_MEMORY_BYTES,
    UNDERSTAT_FEATURE_NAMES,
    UnderstatTensorFormatter,
)
from .orchestrator import (
    close_asyncpg_pool,
    get_asyncpg_pool,
    ingest_single_match,
    ingest_understat_telemetry,
    invalidate_telemetry_cache,
)
from .scraper import (
    MatchInfo,
    ShotRecord,
    ShotsData,
    UnderstatMatchPayload,
    UnderstatScraper,
)

__all__ = [
    # Entity mapping
    "UNDERSTAT_ENTITY_MAP",
    "UnmappedEntityError",
    "resolve_slug",
    # Scraper
    "UnderstatScraper",
    "UnderstatMatchPayload",
    "MatchInfo",
    "ShotsData",
    "ShotRecord",
    # Orchestrator
    "ingest_understat_telemetry",
    "ingest_single_match",
    "invalidate_telemetry_cache",
    "get_asyncpg_pool",
    "close_asyncpg_pool",
    # Tensor Formatter
    "UnderstatTensorFormatter",
    "UNDERSTAT_FEATURE_NAMES",
    "MAX_MEMORY_BYTES",
]
