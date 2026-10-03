"""Unit and integration tests for Understat ingestion and ML feature pipeline."""

from __future__ import annotations

import codecs
import json
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from bs4 import BeautifulSoup
from fastapi import BackgroundTasks

from src.services.understat.entity_map import (
    UNDERSTAT_ENTITY_MAP,
    UnmappedEntityError,
    resolve_slug,
)
from src.services.understat.formatter import (
    MAX_MEMORY_BYTES,
    UNDERSTAT_FEATURE_NAMES,
    UnderstatTensorFormatter,
)
from src.services.understat.orchestrator import (
    UPSERT_MATCH_TELEMETRY_SQL,
    ingest_single_match,
    ingest_understat_telemetry,
    invalidate_telemetry_cache,
)
from src.services.understat.scraper import (
    MatchInfo,
    ShotsData,
    UnderstatMatchPayload,
    UnderstatScraper,
    _decode_understat_payload,
)

# ---------------------------------------------------------------------------
# Test Fixtures & Synthetic Payloads
# ---------------------------------------------------------------------------

SAMPLE_MATCH_INFO = {
    "id": "11662",
    "isResult": True,
    "h": {"id": "87", "title": "Inter", "short_title": "INT"},
    "a": {"id": "111", "title": "AC Milan", "short_title": "ACM"},
    "goals": {"h": "2", "a": "1"},
    "xG": {"h": "2.145", "a": "1.320"},
    "datetime": "2026-09-20 18:45:00",
    "league_id": "2",
    "league": "Serie A",
    "season": "2026",
}

SAMPLE_SHOTS_DATA = {
    "h": [
        {
            "id": "501",
            "minute": "15",
            "result": "Goal",
            "X": "0.91",
            "Y": "0.48",
            "xG": "0.45",
            "player": "Lautaro Martinez",
            "h_a": "h",
            "player_id": "2099",
            "situation": "OpenPlay",
            "season": "2026",
            "shotType": "RightFoot",
            "match_id": "11662",
            "h_team": "Inter",
            "a_team": "AC Milan",
            "h_goals": "1",
            "a_goals": "0",
            "date": "2026-09-20 18:45:00",
            "player_assisted": "Nicolo Barella",
            "lastAction": "Pass",
        },
        {
            "id": "502",
            "minute": "42",
            "result": "SavedShot",
            "X": "0.85",
            "Y": "0.55",
            "xG": "0.15",
            "player": "Marcus Thuram",
            "h_a": "h",
            "player_id": "2100",
            "situation": "OpenPlay",
            "season": "2026",
            "shotType": "Head",
            "match_id": "11662",
            "h_team": "Inter",
            "a_team": "AC Milan",
            "h_goals": "1",
            "a_goals": "0",
            "date": "2026-09-20 18:45:00",
            "player_assisted": None,  # unassisted (no xA)
            "lastAction": "Cross",
        },
    ],
    "a": [
        {
            "id": "503",
            "minute": "67",
            "result": "Goal",
            "X": "0.88",
            "Y": "0.52",
            "xG": "0.38",
            "player": "Rafael Leao",
            "h_a": "a",
            "player_id": "3001",
            "situation": "OpenPlay",
            "season": "2026",
            "shotType": "RightFoot",
            "match_id": "11662",
            "h_team": "Inter",
            "a_team": "AC Milan",
            "h_goals": "1",
            "a_goals": "1",
            "date": "2026-09-20 18:45:00",
            "player_assisted": "Christian Pulisic",
            "lastAction": "Throughball",
        }
    ],
}


def _encode_to_understat_hex(data: dict) -> str:
    """Simulate Understat's hex-unicode-escaped single-quoted string formatting."""
    raw_json = json.dumps(data)
    # Convert characters to hex escaped sequence like \x7b\x22...
    return "".join(f"\\x{ord(c):02x}" for c in raw_json)


# ---------------------------------------------------------------------------
# Phase 2: Canonical Entity Resolution Tests
# ---------------------------------------------------------------------------


def test_entity_map_mandatory_mappings() -> None:
    """Verify common Understat abbreviations map to canonical PostgreSQL slugs."""
    assert resolve_slug("Inter") == "inter_milan"
    assert resolve_slug("AC Milan") == "ac_milan"
    assert resolve_slug("Roma") == "as_roma"
    assert resolve_slug("Spurs") == "tottenham_hotspur"
    assert resolve_slug("Man Utd") == "manchester_united"


def test_entity_map_unmapped_entity_raises() -> None:
    """Strict validator: unknown entity raises UnmappedEntityError with raw_name preserved."""
    unknown = "NonExistent FC"
    with pytest.raises(UnmappedEntityError) as exc_info:
        resolve_slug(unknown)
    assert exc_info.value.raw_name == unknown
    assert "NonExistent FC" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Phase 3: Scraper Core & Decoding Tests
# ---------------------------------------------------------------------------


def test_decode_understat_payload_hex_unicode_escape() -> None:
    """Test unicode_escape decoding on utf-8 encoded hex bytes."""
    hex_str = _encode_to_understat_hex(SAMPLE_MATCH_INFO)
    decoded = _decode_understat_payload(hex_str)
    assert decoded["id"] == "11662"
    assert decoded["h"]["title"] == "Inter"
    assert decoded["xG"]["h"] == "2.145"


def test_pydantic_payload_model_validation() -> None:
    """Validate UnderstatMatchPayload parses correctly and computes expected properties."""
    shots = ShotsData.model_validate(SAMPLE_SHOTS_DATA)
    info = MatchInfo.model_validate(SAMPLE_MATCH_INFO)

    payload = UnderstatMatchPayload(
        match_id=11662,
        match_info=info,
        shots_data=shots,
    )

    assert payload.match_id == 11662
    assert payload.home_xg == 2.145
    assert payload.away_xg == 1.320
    # Home assisted shot xG was 0.45; unassisted was 0.15 -> home xA = 0.45
    assert abs(payload.home_xa - 0.45) < 1e-5
    # Away assisted shot xG was 0.38 -> away xA = 0.38
    assert abs(payload.away_xa - 0.38) < 1e-5


def test_extract_json_payloads_with_beautifulsoup() -> None:
    """Verify script tag parsing extracts both shotsData and match_info using BeautifulSoup."""
    hex_shots = _encode_to_understat_hex(SAMPLE_SHOTS_DATA)
    hex_info = _encode_to_understat_hex(SAMPLE_MATCH_INFO)

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Understat Match</title></head>
    <body>
      <div id="content">Some content</div>
      <script>
        var someOtherVar = 123;
        var shotsData = JSON.parse('{hex_shots}');
        var match_info = JSON.parse('{hex_info}');
      </script>
    </body>
    </html>
    """

    shots_raw, info_raw = UnderstatScraper._extract_json_payloads(html_content)
    assert shots_raw == hex_shots
    assert info_raw == hex_info


# ---------------------------------------------------------------------------
# Phase 4: Orchestration & Redis Invalidation Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_telemetry_cache_pipeline() -> None:
    """Test Redis pipeline delete commands target expected keys."""
    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.execute = AsyncMock(return_value=[1, 1, 1])

    await invalidate_telemetry_cache(
        match_id=11662,
        home_team_slug="inter_milan",
        away_team_slug="ac_milan",
        redis_client=mock_redis,
    )

    expected_keys = [
        "sabiscore:telemetry:11662",
        "sabiscore:rolling_xg:inter_milan",
        "sabiscore:rolling_xg:ac_milan",
    ]
    assert mock_pipeline.delete.call_count == 3
    calls = [c[0][0] for c in mock_pipeline.delete.call_args_list]
    assert calls == expected_keys
    mock_pipeline.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_single_match_upsert_and_invalidation() -> None:
    """Verify single match ingestion performs parameterized asyncpg upsert and invalidation."""
    mock_scraper = MagicMock()
    payload = UnderstatMatchPayload(
        match_id=11662,
        match_info=MatchInfo.model_validate(SAMPLE_MATCH_INFO),
        shots_data=ShotsData.model_validate(SAMPLE_SHOTS_DATA),
    )
    mock_scraper.fetch_match = AsyncMock(return_value=payload)

    mock_conn = MagicMock()
    mock_tx = MagicMock()
    mock_tx.__aenter__ = AsyncMock(return_value=None)
    mock_tx.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction.return_value = mock_tx
    mock_conn.execute = AsyncMock(return_value=None)

    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.execute = AsyncMock(return_value=[1, 1, 1])

    result = await ingest_single_match(
        match_id=11662,
        scraper=mock_scraper,
        conn=mock_conn,
        redis_client=mock_redis,
    )

    assert result["match_id"] == 11662
    assert result["home_slug"] == "inter_milan"
    assert result["away_slug"] == "ac_milan"
    assert result["home_xg"] == 2.145
    assert result["away_xg"] == 1.320

    # Verify SQL query executed with expected arguments
    mock_conn.execute.assert_awaited_once()
    args = mock_conn.execute.call_args[0]
    assert args[0] == UPSERT_MATCH_TELEMETRY_SQL
    assert args[1] == 11662  # match_id
    assert args[2] == "11662"  # provider_id
    assert args[3] == "inter_milan"  # home_team_slug
    assert args[4] == "ac_milan"  # away_team_slug
    assert args[5] == 2.145  # home_xg
    assert args[6] == 1.320  # away_xg
    assert abs(args[7] - 0.45) < 1e-5  # home_xa
    assert abs(args[8] - 0.38) < 1e-5  # away_xa
    assert args[10] is not None  # kickoff_utc
    assert args[10].year == 2026
    assert len(args[13]) == 64  # payload_sha256
    assert args[14] == "AUTHORIZED_PRODUCTION_SOURCE"  # source_policy
    assert result["payload_sha256"] == args[13]
    assert result["source_policy"] == "AUTHORIZED_PRODUCTION_SOURCE"


@pytest.mark.asyncio
async def test_ingest_batch_unmapped_entity_fails_closed_without_breaking_batch() -> None:
    """Verify an unmapped team logs warning and skips match without failing the batch."""
    unmapped_match_info = dict(SAMPLE_MATCH_INFO)
    unmapped_match_info["h"] = {"id": "999", "title": "TotallyUnknownFC", "short_title": "UNK"}

    payload_valid = UnderstatMatchPayload(
        match_id=11662,
        match_info=MatchInfo.model_validate(SAMPLE_MATCH_INFO),
        shots_data=ShotsData.model_validate(SAMPLE_SHOTS_DATA),
    )
    payload_invalid = UnderstatMatchPayload(
        match_id=11663,
        match_info=MatchInfo.model_validate(unmapped_match_info),
        shots_data=ShotsData.model_validate(SAMPLE_SHOTS_DATA),
    )

    mock_scraper = MagicMock()
    async def mock_fetch(m_id: int):
        if m_id == 11662:
            return payload_valid
        return payload_invalid
    mock_scraper.fetch_match = AsyncMock(side_effect=mock_fetch)
    mock_scraper.__aenter__ = AsyncMock(return_value=mock_scraper)
    mock_scraper.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(return_value=None)
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_redis = MagicMock()
    mock_pipeline = MagicMock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.execute = AsyncMock(return_value=[1, 1, 1])

    with patch("src.services.understat.orchestrator.UnderstatScraper", return_value=mock_scraper):
        summary = await ingest_understat_telemetry(
            match_ids=[11662, 11663],
            pool=mock_pool,
            redis_client=mock_redis,
        )

    assert summary["processed"] == 2
    assert summary["succeeded"] == 1
    assert summary["unmapped"] == 1
    assert summary["failed"] == 0
    assert 11662 in summary["succeeded_ids"]
    assert summary["unmapped_details"][0]["match_id"] == 11663


# ---------------------------------------------------------------------------
# Phase 5: ML Tensor Formatter Tests
# ---------------------------------------------------------------------------


def test_tensor_formatter_directional_metrics_and_shape() -> None:
    """Verify UnderstatTensorFormatter outputs contiguous float32 array with correct values."""
    records = [
        {
            "match_id": 1,
            "home_team_slug": "inter_milan",
            "away_team_slug": "ac_milan",
            "home_xg": 2.5,
            "away_xg": 1.0,
            "home_xa": 1.8,
            "away_xa": 0.7,
            "shot_telemetry": SAMPLE_SHOTS_DATA,
        },
        {
            "match_id": 2,
            "home_team_slug": "inter_milan",
            "away_team_slug": "juventus",
            "home_xg": 1.5,
            "away_xg": 1.5,
            "home_xa": 1.0,
            "away_xa": 1.2,
            "shot_telemetry": None,
        },
    ]

    tensor = UnderstatTensorFormatter.format_batch(records)

    assert isinstance(tensor, np.ndarray)
    assert tensor.dtype == np.float32
    assert tensor.shape == (2, len(UNDERSTAT_FEATURE_NAMES))
    # Memory safety: verify memory-contiguous layout
    assert tensor.flags["C_CONTIGUOUS"]

    # Match 1:
    # home_xg=2.5, away_xg=1.0, delta_xg=1.5, total_xg=3.5
    # shot_telemetry extraction: home_xa=0.45, away_xa=0.38
    # delta_xa = 0.45 - 0.38 = 0.07, total_xa = 0.83
    assert abs(tensor[0, 0] - 2.5) < 1e-4  # home_xg
    assert abs(tensor[0, 1] - 1.0) < 1e-4  # away_xg
    assert abs(tensor[0, 2] - 1.5) < 1e-4  # delta_xg
    assert abs(tensor[0, 3] - 3.5) < 1e-4  # total_xg
    assert abs(tensor[0, 4] - 0.45) < 1e-4  # home_xa from shots
    assert abs(tensor[0, 5] - 0.38) < 1e-4  # away_xa from shots
    assert abs(tensor[0, 6] - 0.07) < 1e-4  # delta_xa
    assert abs(tensor[0, 7] - 0.83) < 1e-4  # total_xa


def test_tensor_formatter_rolling_xg_averages() -> None:
    """Verify rolling 5-match xG average across historical sequences."""
    records = []
    # Team A produces 1.0, 2.0, 3.0, 4.0, 5.0, 6.0 in 6 consecutive matches
    for i, xg in enumerate([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]):
        records.append(
            {
                "match_id": i + 1,
                "home_team_slug": "team_a",
                "away_team_slug": "team_b",
                "home_xg": xg,
                "away_xg": 1.0,
                "home_xa": 0.5,
                "away_xa": 0.5,
                "shot_telemetry": None,
            }
        )

    tensor = UnderstatTensorFormatter.format_batch(records)

    # In match 6 (index 5), prior 5 matches for team_a had xG: [1.0, 2.0, 3.0, 4.0, 5.0]
    # Mean = 15.0 / 5 = 3.0
    home_rolling_idx = UNDERSTAT_FEATURE_NAMES.index("home_rolling_xg_5")
    assert abs(tensor[5, home_rolling_idx] - 3.0) < 1e-4


def test_tensor_formatter_memory_safety_constraint() -> None:
    """Verify MemoryError is raised when array allocation would exceed 512MB limit."""
    # 512MB / (11 * 4 bytes) ~ 12,201,607 rows
    # Simulate a mockup records object with excessive length
    class FakeHugeSequence:
        def __len__(self) -> int:
            return 20_000_000  # 20M rows * 44 bytes = ~880MB

        def __getitem__(self, idx: int) -> dict:
            return {}

    with pytest.raises(MemoryError) as exc_info:
        UnderstatTensorFormatter.format_batch(FakeHugeSequence())
    assert "exceeding the strict 512.0 MB limit" in str(exc_info.value)


# ---------------------------------------------------------------------------
# FastAPI Router Endpoint Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_understat_ingestion_endpoint() -> None:
    """FastAPI endpoint must enqueue ingest_understat_telemetry as BackgroundTask."""
    from src.api.endpoints.telemetry import (
        UnderstatIngestRequest,
        get_features_schema,
        trigger_understat_ingestion,
    )

    bg_tasks = MagicMock(spec=BackgroundTasks)
    req = UnderstatIngestRequest(match_ids=[11662, 11663])
    resp = await trigger_understat_ingestion(payload=req, background_tasks=bg_tasks)

    assert resp.status == "queued"
    assert resp.enqueued_count == 2
    assert resp.match_ids == [11662, 11663]
    bg_tasks.add_task.assert_called_once_with(ingest_understat_telemetry, [11662, 11663])

    schema = await get_features_schema()
    assert schema["dtype"] == "float32"
    assert schema["memory_order"] == "C_CONTIGUOUS"
    assert schema["feature_count"] == len(UNDERSTAT_FEATURE_NAMES)

