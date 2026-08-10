"""Tests for GET /api/v1/sources/freshness — Gap 3 coverage."""

from __future__ import annotations

import json
import time

import pytest

from src.api.endpoints.sources import (
    _last_checked,
    _RECENT_THRESHOLD_S,
    _freshness_status,
    get_sources_freshness,
    get_sources_summary,
    record_source_check,
)
from src.connectors.source_registry import build_source_registry
from src.core.config import settings

_ALL_SOURCE_NAMES = {s.name for s in build_source_registry(settings=settings)}
_EXPECTED_SOURCE_COUNT = 4


@pytest.mark.asyncio
async def test_sources_freshness_returns_all_sources():
    """Endpoint must return all 4 V4 registered sources."""
    result = await get_sources_freshness()
    assert len(result) == _EXPECTED_SOURCE_COUNT, (
        f"Expected {_EXPECTED_SOURCE_COUNT} sources, got {len(result)}"
    )


@pytest.mark.asyncio
async def test_sources_freshness_serialisable():
    """All source items must be JSON-serialisable (no Path or datetime objects)."""
    result = await get_sources_freshness()
    for item in result:
        payload = item.model_dump()
        json.dumps(payload)  # raises if not serialisable


@pytest.mark.asyncio
async def test_sources_all_four_registry_names_present():
    """Response must include all source names from the registry."""
    result = await get_sources_freshness()
    returned_names = {item.name for item in result}
    assert returned_names == _ALL_SOURCE_NAMES, (
        f"Source name mismatch. Expected {_ALL_SOURCE_NAMES}, got {returned_names}"
    )


@pytest.mark.asyncio
async def test_sources_freshness_status_data_gap_when_never_checked():
    """A source that has never been checked must report DATA_GAP."""
    _last_checked.clear()
    result = await get_sources_freshness()
    for item in result:
        assert item.freshness_status == "DATA_GAP", (
            f"{item.name} expected DATA_GAP but got {item.freshness_status}"
        )


def test_freshness_status_live_when_recent():
    """record_source_check should cause status=LIVE immediately."""
    _last_checked.clear()
    record_source_check("odds-market-features")
    assert _freshness_status("odds-market-features") == "LIVE"


def test_freshness_status_data_gap_when_absent():
    """freshness_status returns DATA_GAP when source has never been recorded."""
    _last_checked.clear()
    assert _freshness_status("never-seen-source") == "DATA_GAP"


def test_freshness_status_stale_when_old():
    """A source checked more than 1h ago must be STALE."""
    _last_checked["test-source"] = time.time() - (_RECENT_THRESHOLD_S + 1)
    assert _freshness_status("test-source") == "STALE"
    del _last_checked["test-source"]


@pytest.mark.asyncio
async def test_sources_summary_serialisable():
    """Summary endpoint must return JSON-serialisable dict."""
    result = await get_sources_summary()
    json.dumps(result)


@pytest.mark.asyncio
async def test_sources_summary_has_generated_at():
    """Summary must include a generated_at timestamp."""
    result = await get_sources_summary()
    assert "generated_at" in result
    assert "T" in result["generated_at"]


@pytest.mark.asyncio
async def test_sources_all_items_have_generated_at():
    """Every freshness item must carry a generated_at field."""
    result = await get_sources_freshness()
    for item in result:
        assert item.generated_at, f"{item.name} missing generated_at"
