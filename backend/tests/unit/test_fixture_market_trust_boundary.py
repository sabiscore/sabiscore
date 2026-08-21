"""Legacy and user-supplied odds must remain research-only evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api.endpoints.fixtures import (
    ManualOddsSnapshotRequest,
    _build_evidence,
    analyze_fixture,
    create_manual_odds_snapshot,
    provider_odds_candidates,
)
from src.core.database import Base, League, Match, Team
from src.features.market import MARKET_FEATURE_NAMES, compute_market_drift
from src.schemas.odds import OddsResponse


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _seed_fixture(db: AsyncSession) -> str:
    fixture_id = "manual-market-trust"
    kickoff = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    db.add(League(id="EPL", name="Premier League", country="England"))
    db.add_all(
        [
            Team(id="home", name="Home", league_id="EPL"),
            Team(id="away", name="Away", league_id="EPL"),
        ]
    )
    db.add(
        Match(
            id=fixture_id,
            league_id="EPL",
            home_team_id="home",
            away_team_id="away",
            match_date=kickoff,
            season="2026-2027",
            status="scheduled",
        )
    )
    await db.commit()
    return fixture_id


async def test_manual_snapshot_is_persisted_only_as_non_executable_research(
    session: AsyncSession,
) -> None:
    fixture_id = await _seed_fixture(session)
    payload = ManualOddsSnapshotRequest(
        bookmaker="Example Book",
        home_odds=2.1,
        draw_odds=3.4,
        away_odds=3.8,
        observed_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        source_label="user reference",
        user_confirmed=True,
    )

    created = await create_manual_odds_snapshot(fixture_id, payload, session)
    assert created.executable is False
    assert created.provenance["evidence_state"] == "HYPOTHETICAL_NON_EXECUTABLE"
    assert created.provenance["eligible_for_clv"] is False
    assert created.provenance["eligible_for_staking"] is False

    _, _, stored, evidence = await _build_evidence(session, fixture_id)
    assert stored is not None
    assert evidence.fixture.odds_status == "RESEARCH_ONLY"
    assert evidence.source_status["market"] == "RESEARCH_ONLY"
    assert "DATA_GAP: market_snapshot_provenance_unverified" in evidence.data_gaps
    assert evidence.source_comparison[0]["status"] == "RESEARCH_ONLY"

    candidates = await provider_odds_candidates(fixture_id, session)
    assert candidates.warnings == ["legacy_snapshots_are_research_only"]
    assert len(candidates.candidates) == 1
    assert candidates.candidates[0].provider == "legacy_unverified"
    assert candidates.candidates[0].executable is False


async def test_manual_snapshot_cannot_enable_market_analysis_or_staking(
    session: AsyncSession,
) -> None:
    fixture_id = await _seed_fixture(session)
    await create_manual_odds_snapshot(
        fixture_id,
        ManualOddsSnapshotRequest(
            bookmaker="Example Book",
            home_odds=2.1,
            draw_odds=3.4,
            away_odds=3.8,
            observed_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            user_confirmed=True,
        ),
        session,
    )

    result = await analyze_fixture(fixture_id, session)
    assert result.verdict.value == "PARTIAL"
    assert result.source_summary["market"] == "DATA_GAP"
    assert result.analysis_mode.value == "FORECAST_ONLY"
    assert result.execution_eligible is False
    assert result.stake == "pass"
    assert result.stake_fraction == 0.0
    assert result.edge is None
    assert result.expected_value is None


async def test_market_drift_never_falls_back_to_unprovenanced_legacy_odds() -> None:
    no_history = MagicMock()
    no_history.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=no_history)

    result = await compute_market_drift(
        current_odds={"home_win": 2.1, "draw": 3.4, "away_win": 3.8},
        match_id="legacy-only",
        db=db,
        max_staleness_hours=24,
    )

    assert db.execute.await_count == 1
    assert set(result.data_gaps) == set(MARKET_FEATURE_NAMES)
    assert all(
        result.per_feature_freshness_seconds[name] is None
        for name in MARKET_FEATURE_NAMES
    )


def test_legacy_odds_schema_is_always_research_only() -> None:
    response = OddsResponse(
        match_id="legacy-reference",
        bookmaker="Example Book",
        home_win=2.1,
        draw=3.4,
        away_win=3.8,
    )

    assert response.evidence_state == "RESEARCH_ONLY"
    assert response.executable is False
