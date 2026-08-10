"""Unit tests for settlement_service.run_settlement_pass() and
get_walk_forward_registry().

Contracts verified:
  1. A full pass composes sync -> get_settled_predictions -> walk_forward_validate
     against real seeded rows and reports outcome="ok".
  2. A provider outage during sync is graceful degradation, not an error:
     outcome stays "ok", consecutive_failures does not increment.
  3. A genuine unexpected exception yields outcome="error" and increments
     consecutive_failures; the next successful pass resets it to 0.
  4. AsyncSessionLocal is None -> outcome="db_not_ready", no raise.
  5. get_walk_forward_registry() is memoized (same instance across calls).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import shutil
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.data.loaders.football_data_api import FootballDataAPIError
from src.db.models import MatchPredictionLog


@pytest.fixture(autouse=True)
def _reset_settlement_module_state():
    """settlement_service holds module-level mutable state — reset it before
    every test so results don't leak across tests in the same process."""
    from src.services import settlement_service

    settlement_service._last_result = {"outcome": "never_run", "consecutive_failures": 0}
    settlement_service._registry_instance = None
    yield


@pytest.fixture
def registry_tmp() -> Path:
    root = Path.cwd() / ".pytest_tmp" / "settlement_registry" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


async def _seed_settled_predictions(session_factory, n: int = 10) -> None:
    """walk_forward_validate needs >= n_splits*2 (10 at the default n_splits=5)."""
    async with session_factory() as session:
        base_date = datetime(2026, 8, 1, 15, 0)
        for i in range(n):
            match_id = f"fd-settled-{i}"
            session.add(
                Match(
                    id=match_id,
                    home_team_id="team-home",
                    away_team_id="team-away",
                    league_id="DED",
                    match_date=base_date + timedelta(days=i),
                    status="finished",
                    home_score=i % 3,
                    away_score=(i + 1) % 3,
                )
            )
            session.add(
                MatchPredictionLog(
                    match_id=match_id,
                    canonical_fixture_id=None,
                    model_version="v5_phase7",
                    calibration_method=None,
                    home_probability=0.4,
                    draw_probability=0.3,
                    away_probability=0.3,
                    confidence=0.4,
                    created_at=base_date + timedelta(days=i, hours=-1),
                )
            )
        await session.commit()


async def test_run_settlement_pass_composes_sync_and_validation(factory) -> None:
    from src.services.settlement_service import run_settlement_pass

    await _seed_settled_predictions(factory, n=10)

    empty_provider = AsyncMock()
    empty_provider.get_recent_results.return_value = []
    with patch("src.db.session.AsyncSessionLocal", new=factory), patch(
        "src.data.loaders.football_data_api.FootballDataAPIClient", return_value=empty_provider
    ):
        result = await run_settlement_pass()

    assert result["outcome"] == "ok"
    assert result["sync"] == {"updated": 0, "unmatched": 0, "already_settled": 0}
    assert result["settled_predictions_total"] == 10
    assert result["walk_forward"]["skipped"] is False
    assert result["consecutive_failures"] == 0


async def test_run_settlement_pass_provider_outage_is_graceful_degradation(factory) -> None:
    from src.services.settlement_service import run_settlement_pass

    await _seed_settled_predictions(factory, n=10)

    failing_provider = AsyncMock()
    failing_provider.get_recent_results.side_effect = FootballDataAPIError("rate limited")
    with patch("src.db.session.AsyncSessionLocal", new=factory), patch(
        "src.data.loaders.football_data_api.FootballDataAPIClient", return_value=failing_provider
    ):
        result = await run_settlement_pass()

    assert result["outcome"] == "ok"  # validation still ran against existing data
    assert result["consecutive_failures"] == 0


async def test_run_settlement_pass_genuine_exception_then_recovers(factory) -> None:
    from src.services import settlement_service

    await _seed_settled_predictions(factory, n=10)
    empty_provider = AsyncMock()
    empty_provider.get_recent_results.return_value = []

    with patch("src.db.session.AsyncSessionLocal", new=factory), patch(
        "src.data.loaders.football_data_api.FootballDataAPIClient", return_value=empty_provider
    ), patch(
        "src.repositories.fixtures.get_settled_predictions",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        failed = await settlement_service.run_settlement_pass()

    assert failed["outcome"] == "error"
    assert failed["consecutive_failures"] == 1

    with patch("src.db.session.AsyncSessionLocal", new=factory), patch(
        "src.data.loaders.football_data_api.FootballDataAPIClient", return_value=empty_provider
    ):
        recovered = await settlement_service.run_settlement_pass()

    assert recovered["outcome"] == "ok"
    assert recovered["consecutive_failures"] == 0


async def test_run_settlement_pass_db_not_ready() -> None:
    from src.services.settlement_service import run_settlement_pass

    with patch("src.db.session.AsyncSessionLocal", new=None):
        result = await run_settlement_pass()

    assert result["outcome"] == "db_not_ready"


def test_get_walk_forward_registry_is_memoized(registry_tmp: Path) -> None:
    from src.core.config import settings
    from src.services.settlement_service import get_walk_forward_registry

    with patch.object(settings, "models_path", registry_tmp):
        first = get_walk_forward_registry()
        second = get_walk_forward_registry()

    assert first is second
