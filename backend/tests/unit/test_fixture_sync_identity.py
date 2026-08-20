"""Regression coverage for fixture-sync team identity integrity."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.services.fixture_sync_service import sync_upcoming_fixtures


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


def _collision_fixture(*, match_id: str = "fd-self-play-guard") -> dict[str, object]:
    return {
        "id": match_id,
        "league": "Serie A",
        "home_provider_team_id": 108,
        "away_provider_team_id": 98,
        "home_team": "FC Internazionale Milano",
        "away_team": "AC Milan",
        "match_date": "2026-08-30T18:45:00Z",
        "source": "football-data.org",
    }


async def test_sync_rejects_resolver_collision_before_any_fixture_write(
    session: AsyncSession,
) -> None:
    """Two distinct provider names resolving to one Team.id must fail closed."""
    fetch = AsyncMock(return_value=[_collision_fixture()])
    resolve = AsyncMock(return_value="fd-team-serie_a:fc_internazionale_milano")
    bind = AsyncMock(return_value=True)
    canonical = AsyncMock()

    with (
        patch(
            "src.data.loaders.football_data_api.FootballDataAPIClient.get_upcoming_matches",
            new=fetch,
        ),
        patch("src.services.fixture_sync_service.resolve_team_id", new=resolve),
        patch("src.services.fixture_sync_service.bind_provider_elo_team_id", new=bind),
        patch("src.services.canonical_identity_service.ensure_canonical_fixture", new=canonical),
    ):
        inserted = await sync_upcoming_fixtures(session, provider=object())

    assert inserted == 0
    assert (await session.execute(select(Match))).scalars().all() == []
    assert (await session.execute(select(Team))).scalars().all() == []
    assert (await session.execute(select(League))).scalars().all() == []
    canonical.assert_not_awaited()


async def test_sync_does_not_rewrite_existing_fixture_into_self_play(
    session: AsyncSession,
) -> None:
    """A later resolver collision must not poison an already-distinct Match row."""
    session.add(League(id="SERIE_A", name="Serie A", country="Italy"))
    session.add_all(
        [
            Team(
                id="fd-team-serie_a:fc_internazionale_milano",
                name="FC Internazionale Milano",
                league_id="SERIE_A",
            ),
            Team(
                id="fd-team-serie_a:ac_milan",
                name="AC Milan",
                league_id="SERIE_A",
            ),
        ]
    )
    session.add(
        Match(
            id="fd-existing-distinct",
            league_id="SERIE_A",
            home_team_id="fd-team-serie_a:fc_internazionale_milano",
            away_team_id="fd-team-serie_a:ac_milan",
            match_date=datetime(2026, 8, 29, 18, 45),
            season="2026/2027",
            status="scheduled",
        )
    )
    await session.commit()

    fetch = AsyncMock(return_value=[_collision_fixture(match_id="fd-existing-distinct")])
    resolve = AsyncMock(return_value="fd-team-serie_a:fc_internazionale_milano")
    bind = AsyncMock(return_value=True)
    canonical = AsyncMock()

    with (
        patch(
            "src.data.loaders.football_data_api.FootballDataAPIClient.get_upcoming_matches",
            new=fetch,
        ),
        patch("src.services.fixture_sync_service.resolve_team_id", new=resolve),
        patch("src.services.fixture_sync_service.bind_provider_elo_team_id", new=bind),
        patch("src.services.canonical_identity_service.ensure_canonical_fixture", new=canonical),
    ):
        inserted = await sync_upcoming_fixtures(session, provider=object())

    assert inserted == 0
    persisted = await session.get(Match, "fd-existing-distinct")
    assert persisted is not None
    assert persisted.home_team_id == "fd-team-serie_a:fc_internazionale_milano"
    assert persisted.away_team_id == "fd-team-serie_a:ac_milan"
    assert persisted.match_date == datetime(2026, 8, 29, 18, 45)
    canonical.assert_not_awaited()
