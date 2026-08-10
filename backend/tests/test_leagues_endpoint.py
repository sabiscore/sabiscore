"""Tests for GET /api/v1/leagues — Gap 2 coverage."""

from __future__ import annotations

import pytest

from src.api.endpoints.leagues import LeagueListItem, _to_item, list_leagues
from src.core.league_config import ACTIVE_LEAGUES


@pytest.mark.asyncio
async def test_leagues_returns_all_seven():
    """Endpoint must return exactly 7 league items."""
    result = await list_leagues()
    assert len(result) == 7, f"Expected 7 leagues, got {len(result)}"


@pytest.mark.asyncio
async def test_leagues_includes_ucl():
    """UCL must be present in the response."""
    result = await list_leagues()
    ids = {item.id for item in result}
    assert "UCL" in ids, f"UCL missing from league list: {ids}"


@pytest.mark.asyncio
async def test_ucl_has_soft_coverage():
    """UCL must report SOFT coverage tier."""
    result = await list_leagues()
    ucl = next(item for item in result if item.id == "UCL")
    assert ucl.coverage == "SOFT"


@pytest.mark.asyncio
async def test_ucl_caveat_in_league_response():
    """UCL must include a non-empty caveat_text."""
    result = await list_leagues()
    ucl = next(item for item in result if item.id == "UCL")
    assert ucl.caveat_text is not None
    assert len(ucl.caveat_text) > 10, "caveat_text is suspiciously short"
    assert "UCL" in ucl.caveat_text or "soft" in ucl.caveat_text.lower()


@pytest.mark.asyncio
async def test_ucl_low_evidence_allowed():
    """UCL must have low_evidence_allowed=True."""
    result = await list_leagues()
    ucl = next(item for item in result if item.id == "UCL")
    assert ucl.low_evidence_allowed is True


@pytest.mark.asyncio
async def test_full_leagues_have_no_caveat():
    """FULL-coverage leagues must not carry a caveat_text."""
    result = await list_leagues()
    for item in result:
        if item.coverage == "FULL":
            assert item.caveat_text is None, (
                f"{item.id} is FULL coverage but has caveat_text: {item.caveat_text}"
            )


@pytest.mark.asyncio
async def test_ucl_model_artifact_is_generic():
    """UCL must point to the generic production model, not a league-specific pkl."""
    result = await list_leagues()
    ucl = next(item for item in result if item.id == "UCL")
    assert "sabiscore_production_v2" in ucl.model_artifact or ucl.model_artifact.endswith(".joblib")


@pytest.mark.asyncio
async def test_ucl_next_season_start_present():
    """UCL must have a next_season_start date."""
    result = await list_leagues()
    ucl = next(item for item in result if item.id == "UCL")
    assert ucl.next_season_start is not None
    assert ucl.next_season_start.startswith("2026")


@pytest.mark.asyncio
async def test_all_items_have_generated_at():
    """All league list items must include a generated_at ISO timestamp."""
    result = await list_leagues()
    for item in result:
        assert item.generated_at, f"{item.id} missing generated_at"
        assert "T" in item.generated_at, f"{item.id} generated_at not ISO format: {item.generated_at}"


def test_league_list_item_schema():
    """LeagueListItem can be constructed and serialised for all ACTIVE_LEAGUES."""
    for profile in ACTIVE_LEAGUES:
        item = _to_item(profile)
        assert isinstance(item, LeagueListItem)
        payload = item.model_dump()
        assert payload["id"] == profile.id
        assert payload["coverage"] in ("FULL", "SOFT", "EXPERIMENTAL")
