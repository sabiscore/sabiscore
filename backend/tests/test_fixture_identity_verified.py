"""WP-1.0 regression tests: fixture_identity_verified must be computed from
actual team-name resolution, never a hardcoded literal (INV-19).

Also pins WP-0's model de-duplication: canonical/provider classes must be
defined exactly once, in db.models, not core.database.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match, Team
from src.services.upcoming_match_feature_service import UpcomingMatchFeatureProjector


# ---------------------------------------------------------------------------
# WP-0: no duplicate model registration
# ---------------------------------------------------------------------------


def test_canonical_provider_models_defined_only_in_db_models() -> None:
    from src.core import database
    from src.db import models

    duplicated = [
        "ProviderRequestSummary",
        "ProviderCapabilityRecord",
        "ProviderQuotaObservation",
        "CanonicalCompetition",
        "CanonicalTeam",
        "CanonicalFixture",
        "ProviderEventMapping",
        "MarketSnapshot",
    ]
    for name in duplicated:
        assert not hasattr(database, name), f"{name} still defined in core.database"
        assert hasattr(models, name), f"{name} missing from db.models"


# ---------------------------------------------------------------------------
# WP-1.0: identity resolution
# ---------------------------------------------------------------------------


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def projector() -> UpcomingMatchFeatureProjector:
    p = UpcomingMatchFeatureProjector()
    p._use_phase8 = False  # skip parquet/DB-backed Phase 8 enrichment — irrelevant to identity
    return p


async def _seed_teams(session: AsyncSession, home: str = "Arsenal", away: str = "Chelsea") -> None:
    session.add_all(
        [
            Team(id="team-home", name=home, active=True),
            Team(id="team-away", name=away, active=True),
        ]
    )
    await session.commit()


async def test_matchup_path_exact_match_is_verified(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    await _seed_teams(session)
    result = await projector.build_live_feature_vector_from_matchup(
        home_team="Arsenal", away_team="Chelsea", league="epl", db=session,
        match_date=datetime(2026, 8, 10, 15, 0),
    )
    assert result["fixture_identity_verified"] is True
    assert result["identity_resolution"] == {
        "home_team_resolved": True,
        "away_team_resolved": True,
    }


async def test_matchup_path_default_match_date_does_not_raise(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """Regression: production (full_analysis.py) never passes match_date, so the
    method's own `datetime.now(timezone.utc)` default was exercised on every real
    request. That default was tz-aware, which raised TypeError inside
    EloEngine._get_pre_and_trend() (naive-vs-aware comparison) — caught by the
    caller's broad except and silently misreported as an identity failure. This
    pins the fix: the default must be naive, matching Match.match_date's own
    storage convention, and must resolve real teams successfully end-to-end."""
    await _seed_teams(session)
    result = await projector.build_live_feature_vector_from_matchup(
        home_team="Arsenal", away_team="Chelsea", league="epl", db=session,
    )
    assert result["fixture_identity_verified"] is True
    assert result["identity_resolution"] == {
        "home_team_resolved": True,
        "away_team_resolved": True,
    }


async def test_matchup_path_unresolvable_team_is_unverified(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    await _seed_teams(session)
    result = await projector.build_live_feature_vector_from_matchup(
        home_team="Arsenal", away_team="Some Nonexistent FC", league="epl", db=session,
        match_date=datetime(2026, 8, 10, 15, 0),
    )
    assert result["fixture_identity_verified"] is False
    assert result["identity_resolution"] == {
        "home_team_resolved": True,
        "away_team_resolved": False,
    }


async def test_db_match_id_path_with_valid_teams_is_verified(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    await _seed_teams(session)
    session.add(
        Match(
            id="match-1",
            home_team_id="team-home",
            away_team_id="team-away",
            league_id="EPL",
            match_date=datetime(2026, 8, 10, 15, 0),
            status="scheduled",
        )
    )
    await session.commit()

    result = await projector.build_live_feature_vector(match_id="match-1", league="epl", db=session)
    assert result["fixture_identity_verified"] is True
    assert result["identity_resolution"] == {
        "home_team_resolved": True,
        "away_team_resolved": True,
    }
