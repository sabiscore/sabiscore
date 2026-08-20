"""SAB-20 regressions for live provider identity -> durable Elo bridging."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.db.models import EloRatingSnapshot, ProviderTeamMapping
from src.db.provider_elo_team_mapping import ProviderEloTeamMapping
from src.services.canonical_identity_service import ensure_canonical_fixture
from src.services.fixture_sync_service import sync_upcoming_fixtures
from src.services.team_identity import (
    bind_provider_elo_team_id,
    resolve_provider_elo_team_id,
    resolve_team_id,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


async def _seed_elo_team(
    session: AsyncSession,
    *,
    team_id: str,
    name: str,
    league_id: str,
    index: int,
) -> None:
    if await session.get(League, league_id) is None:
        session.add(League(id=league_id, name=league_id, country="test"))
        await session.flush()

    opponent_id = f"opponent-{league_id.lower()}-{index}"
    if await session.get(Team, team_id) is None:
        session.add(Team(id=team_id, name=name, league_id=league_id))
    if await session.get(Team, opponent_id) is None:
        session.add(Team(id=opponent_id, name=f"Opponent {index}", league_id=league_id))
    await session.flush()

    match_id = f"history-{league_id.lower()}-{index}"
    match_date = datetime(2026, 5, min(index, 28), 15, 0)
    session.add(
        Match(
            id=match_id,
            league_id=league_id,
            home_team_id=team_id,
            away_team_id=opponent_id,
            match_date=match_date,
            season="2025/2026",
            status="finished",
            home_score=1,
            away_score=0,
        )
    )
    await session.flush()
    session.add(
        EloRatingSnapshot(
            match_id=match_id,
            team_id=team_id,
            pre_match_elo=1510.0,
            post_match_elo=1520.0,
            league=league_id,
            season="2025/2026",
            match_date=match_date,
            created_at=match_date,
        )
    )
    await session.commit()


def _fixture(
    *,
    match_id: str,
    league: str,
    home_provider_id: int,
    away_provider_id: int,
    home_name: str,
    away_name: str,
) -> dict[str, object]:
    return {
        "id": match_id,
        "league": league,
        "home_provider_team_id": home_provider_id,
        "away_provider_team_id": away_provider_id,
        "home_team": home_name,
        "away_team": away_name,
        "match_date": "2026-08-30T18:45:00Z",
        "source": "football-data.org",
    }


async def test_history_required_resolution_ignores_zero_history_exact_duplicate(
    session: AsyncSession,
) -> None:
    await _seed_elo_team(
        session,
        team_id="fdco-team-serie_a-roma",
        name="Roma",
        league_id="SERIE_A",
        index=1,
    )
    session.add(
        Team(
            id="fd-team-serie_a:as_roma",
            name="AS Roma",
            league_id="SERIE_A",
        )
    )
    await session.commit()

    resolved = await resolve_team_id(
        "AS Roma",
        session,
        league_id="SERIE_A",
        require_elo_history=True,
    )
    assert resolved == "fdco-team-serie_a-roma"


@pytest.mark.parametrize(
    ("league_id", "provider_name", "historical_name"),
    [
        ("BUNDESLIGA", "FC Bayern München", "Bayern Munich"),
        ("BUNDESLIGA", "Borussia Mönchengladbach", "M'gladbach"),
        ("EPL", "Manchester City FC", "Man City"),
        ("LIGUE_1", "Stade Rennais FC 1901", "Rennes"),
    ],
)
async def test_audited_live_aliases_resolve_only_to_real_elo_history(
    session: AsyncSession,
    league_id: str,
    provider_name: str,
    historical_name: str,
) -> None:
    await _seed_elo_team(
        session,
        team_id=f"history-{league_id.lower()}",
        name=historical_name,
        league_id=league_id,
        index=2,
    )

    resolved = await resolve_team_id(
        provider_name,
        session,
        league_id=league_id,
        require_elo_history=True,
    )
    assert resolved == f"history-{league_id.lower()}"


async def test_provider_id_bridge_is_durable_and_conflicts_fail_closed(
    session: AsyncSession,
) -> None:
    await _seed_elo_team(
        session,
        team_id="fdco-team-epl-man_city",
        name="Man City",
        league_id="EPL",
        index=3,
    )
    await _seed_elo_team(
        session,
        team_id="fd-team-epl:manchester_united_fc",
        name="Manchester United FC",
        league_id="EPL",
        index=4,
    )

    assert await bind_provider_elo_team_id(
        provider="football-data.org",
        provider_team_id=65,
        provider_team_name="Manchester City FC",
        competition="EPL",
        team_id="fdco-team-epl-man_city",
        db=session,
        evidence={"source": "unit-test"},
    ) is True
    await session.commit()

    assert await resolve_provider_elo_team_id(
        provider="football-data.org",
        provider_team_id=65,
        competition="EPL",
        db=session,
    ) == "fdco-team-epl-man_city"

    assert await bind_provider_elo_team_id(
        provider="football-data.org",
        provider_team_id="65",
        provider_team_name="Manchester City",
        competition="EPL",
        team_id="fdco-team-epl-man_city",
        db=session,
    ) is True
    await session.commit()

    mapping = (
        await session.execute(
            select(ProviderEloTeamMapping).where(
                ProviderEloTeamMapping.provider == "football-data.org",
                ProviderEloTeamMapping.provider_team_id == "65",
                ProviderEloTeamMapping.competition == "EPL",
            )
        )
    ).scalar_one()
    assert mapping.provider_team_name == "Manchester City"
    assert mapping.evidence and mapping.evidence["identity_basis"] == "real_durable_elo_history"

    with pytest.raises(ValueError, match="conflicts with an existing Elo team mapping"):
        await bind_provider_elo_team_id(
            provider="football-data.org",
            provider_team_id=65,
            provider_team_name="Manchester United FC",
            competition="EPL",
            team_id="fd-team-epl:manchester_united_fc",
            db=session,
        )


async def test_new_fixture_uses_historical_elo_teams_and_true_provider_ids(
    session: AsyncSession,
) -> None:
    await _seed_elo_team(
        session,
        team_id="fdco-team-serie_a-roma",
        name="Roma",
        league_id="SERIE_A",
        index=5,
    )
    await _seed_elo_team(
        session,
        team_id="fdco-team-serie_a-fiorentina",
        name="Fiorentina",
        league_id="SERIE_A",
        index=6,
    )

    fetch = AsyncMock(
        return_value=[
            _fixture(
                match_id="fd-9901",
                league="Serie A",
                home_provider_id=100,
                away_provider_id=101,
                home_name="AS Roma",
                away_name="ACF Fiorentina",
            )
        ]
    )
    with patch(
        "src.data.loaders.football_data_api.FootballDataAPIClient.get_upcoming_matches",
        new=fetch,
    ):
        inserted = await sync_upcoming_fixtures(session, provider=object())

    assert inserted == 1
    match = await session.get(Match, "fd-9901")
    assert match is not None
    assert match.home_team_id == "fdco-team-serie_a-roma"
    assert match.away_team_id == "fdco-team-serie_a-fiorentina"

    elo_bridges = (
        await session.execute(
            select(ProviderEloTeamMapping).where(
                ProviderEloTeamMapping.provider == "football-data.org",
                ProviderEloTeamMapping.competition == "SERIE_A",
            )
        )
    ).scalars().all()
    assert {row.provider_team_id for row in elo_bridges} == {"100", "101"}
    assert {row.team_id for row in elo_bridges} == {
        "fdco-team-serie_a-roma",
        "fdco-team-serie_a-fiorentina",
    }

    canonical_mappings = (
        await session.execute(
            select(ProviderTeamMapping).where(
                ProviderTeamMapping.provider == "football-data.org",
                ProviderTeamMapping.competition == "SERIE_A",
            )
        )
    ).scalars().all()
    assert {row.provider_team_id for row in canonical_mappings} == {"100", "101"}


async def test_existing_scheduled_fixture_is_not_silently_rekeyed(
    session: AsyncSession,
) -> None:
    await _seed_elo_team(
        session,
        team_id="fdco-team-serie_a-roma",
        name="Roma",
        league_id="SERIE_A",
        index=7,
    )
    await _seed_elo_team(
        session,
        team_id="fdco-team-serie_a-fiorentina",
        name="Fiorentina",
        league_id="SERIE_A",
        index=8,
    )

    generated_home = "fd-team-serie_a:as_roma"
    generated_away = "fd-team-serie_a:acf_fiorentina"
    session.add_all(
        [
            Team(id=generated_home, name="AS Roma", league_id="SERIE_A"),
            Team(id=generated_away, name="ACF Fiorentina", league_id="SERIE_A"),
        ]
    )
    session.add(
        Match(
            id="fd-9902",
            league_id="SERIE_A",
            home_team_id=generated_home,
            away_team_id=generated_away,
            match_date=datetime(2026, 8, 29, 18, 45),
            season="2026/2027",
            status="scheduled",
        )
    )
    await session.commit()

    fetch = AsyncMock(
        return_value=[
            _fixture(
                match_id="fd-9902",
                league="Serie A",
                home_provider_id=100,
                away_provider_id=101,
                home_name="AS Roma",
                away_name="ACF Fiorentina",
            )
        ]
    )
    with patch(
        "src.data.loaders.football_data_api.FootballDataAPIClient.get_upcoming_matches",
        new=fetch,
    ):
        inserted = await sync_upcoming_fixtures(session, provider=object())

    assert inserted == 0
    persisted = await session.get(Match, "fd-9902")
    assert persisted is not None
    assert persisted.home_team_id == generated_home
    assert persisted.away_team_id == generated_away
    assert persisted.match_date == datetime(2026, 8, 30, 18, 45)

    elo_bridges = (
        await session.execute(
            select(ProviderEloTeamMapping).where(
                ProviderEloTeamMapping.provider == "football-data.org",
                ProviderEloTeamMapping.competition == "SERIE_A",
            )
        )
    ).scalars().all()
    assert {row.provider_team_id for row in elo_bridges} == {"100", "101"}


async def test_history_free_club_stays_unbridged_and_unresolved(
    session: AsyncSession,
) -> None:
    await _seed_elo_team(
        session,
        team_id="fd-team-epl:arsenal_fc",
        name="Arsenal FC",
        league_id="EPL",
        index=9,
    )

    fetch = AsyncMock(
        return_value=[
            _fixture(
                match_id="fd-9903",
                league="EPL",
                home_provider_id=200,
                away_provider_id=201,
                home_name="Coventry City FC",
                away_name="Arsenal FC",
            )
        ]
    )
    with patch(
        "src.data.loaders.football_data_api.FootballDataAPIClient.get_upcoming_matches",
        new=fetch,
    ):
        inserted = await sync_upcoming_fixtures(session, provider=object())

    assert inserted == 1
    match = await session.get(Match, "fd-9903")
    assert match is not None
    assert match.home_team_id == "fd-team-epl:coventry_city_fc"
    assert match.away_team_id == "fd-team-epl:arsenal_fc"

    bridge_ids = set(
        (
            await session.execute(
                select(ProviderEloTeamMapping.provider_team_id).where(
                    ProviderEloTeamMapping.provider == "football-data.org",
                    ProviderEloTeamMapping.competition == "EPL",
                )
            )
        ).scalars().all()
    )
    assert "200" not in bridge_ids
    assert "201" in bridge_ids


async def test_fixture_without_upstream_team_ids_is_rejected(
    session: AsyncSession,
) -> None:
    fetch = AsyncMock(
        return_value=[
            {
                "id": "fd-9904",
                "league": "EPL",
                "home_team": "Arsenal FC",
                "away_team": "Chelsea FC",
                "match_date": "2026-08-30T18:45:00Z",
            }
        ]
    )
    with patch(
        "src.data.loaders.football_data_api.FootballDataAPIClient.get_upcoming_matches",
        new=fetch,
    ):
        inserted = await sync_upcoming_fixtures(session, provider=object())

    assert inserted == 0
    assert await session.get(Match, "fd-9904") is None


async def test_canonical_provider_id_anchor_survives_display_name_change(
    session: AsyncSession,
) -> None:
    first = await ensure_canonical_fixture(
        session,
        provider="football-data.org",
        provider_event_id="fd-name-drift",
        competition_id="EPL",
        competition_name="EPL",
        home_provider_id="65",
        home_name="Manchester City FC",
        away_provider_id="61",
        away_name="Chelsea FC",
        kickoff_utc=datetime(2026, 8, 30, 18, 45),
        season="2026/2027",
        status="scheduled",
        evidence={"source": "unit-test"},
    )
    await session.commit()

    second = await ensure_canonical_fixture(
        session,
        provider="football-data.org",
        provider_event_id="fd-name-drift",
        competition_id="EPL",
        competition_name="EPL",
        home_provider_id="65",
        home_name="Manchester City",
        away_provider_id="61",
        away_name="Chelsea",
        kickoff_utc=datetime(2026, 8, 30, 20, 0),
        season="2026/2027",
        status="scheduled",
        evidence={"source": "unit-test-renamed"},
    )
    await session.commit()

    assert second == first
    mappings = (
        await session.execute(
            select(ProviderTeamMapping).where(
                ProviderTeamMapping.provider == "football-data.org",
                ProviderTeamMapping.competition == "EPL",
            )
        )
    ).scalars().all()
    assert {row.provider_team_id for row in mappings} == {"65", "61"}
    assert {row.provider_team_name for row in mappings} == {"Manchester City", "Chelsea"}
