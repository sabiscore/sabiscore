from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db.models import CanonicalFixture, MarketSnapshot
from src.services.canonical_manifest_ingestion import ingest_manifest
from src.services.manifest_ingestion import ManifestValidationError


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def manifest_workspace() -> Path:
    root = Path.cwd() / ".pytest_tmp" / "canonical_ingestion" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _manifest(root: Path, *, league: str = "EPL", future_finished: bool = False) -> Path:
    payload = root / "processed" / "football-data-csv" / "fixtures-EPL.json"
    payload.parent.mkdir(parents=True, exist_ok=True)
    fixture = {
        "source": "football-data-csv",
        "source_native_id": None,
        "source_row_index": 2,
        "league": league,
        "match_date": "11/08/2026" if future_finished else "10/08/2025",
        "match_time": "15:00",
        "source_timezone": "Europe/London",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "home_goals": 2,
        "away_goals": 1,
        "market": {
            "bookmaker": "bet365",
            "market_type": "1X2",
            "coherent": True,
            "raw_odds": {"home": 2.0, "draw": 3.5, "away": 4.0},
            "devigged_probabilities": {
                "home": 0.4827586206896552,
                "draw": 0.27586206896551724,
                "away": 0.2413793103448276,
            },
        },
    }
    payload.write_text(json.dumps([fixture]), encoding="utf-8")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest_path = root / "manifests" / "run.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "manifest_version": "2.0",
        "run_id": "run-1",
        "source_id": "football-data-csv",
        "adapter_version": "2.0.0",
        "schema_version": "2.0.0",
        "registry_version": "2.0.0",
        "started_at": "2026-08-10T10:00:00Z",
        "completed_at": "2026-08-10T10:01:00Z",
        "status": "SUCCESS",
        "record_count": 1,
        "raw_files": [],
        "processed_files": [{
            "file": str(payload),
            "uri": str(payload),
            "object_key": f"processed/football-data-csv/run-1/{digest}.json",
            "hash": digest,
        }],
        "payload_hashes": {str(payload): digest},
        "freshness": "FRESH",
        "errors": [],
        "licence": {"source_policy": "fixture"},
        "attribution": "football-data.co.uk",
    }), encoding="utf-8")
    return manifest_path


async def test_commit_is_idempotent_and_market_is_non_executable(
    session_factory, manifest_workspace: Path
) -> None:
    manifest = _manifest(manifest_workspace)
    async with session_factory() as session:
        first = await ingest_manifest(
            session, manifest_path=manifest, data_root=manifest_workspace, commit=True
        )
    async with session_factory() as session:
        second = await ingest_manifest(
            session, manifest_path=manifest, data_root=manifest_workspace, commit=True
        )
        match_count = await session.scalar(select(func.count()).select_from(Match))
        canonical_count = await session.scalar(select(func.count()).select_from(CanonicalFixture))
        snapshots = (await session.execute(select(MarketSnapshot))).scalars().all()

    assert first.fixtures_inserted == 1
    assert second.fixtures_existing == 1
    assert match_count == canonical_count == 1
    assert len(snapshots) == 1
    assert snapshots[0].coherent is True
    assert snapshots[0].executable is False


async def test_dry_run_rolls_back(session_factory, manifest_workspace: Path) -> None:
    manifest = _manifest(manifest_workspace)
    async with session_factory() as session:
        report = await ingest_manifest(
            session, manifest_path=manifest, data_root=manifest_workspace, commit=False
        )
        count = await session.scalar(select(func.count()).select_from(Match))
    assert report.dry_run is True
    assert count == 0


async def test_unknown_competition_and_future_result_fail_closed(
    session_factory, manifest_workspace: Path
) -> None:
    for manifest in (
        _manifest(manifest_workspace / "unknown", league="UNKNOWN"),
        _manifest(manifest_workspace / "future", future_finished=True),
    ):
        async with session_factory() as session:
            with pytest.raises(ManifestValidationError):
                await ingest_manifest(
                    session,
                    manifest_path=manifest,
                    data_root=manifest.parent.parent,
                    commit=True,
                )
