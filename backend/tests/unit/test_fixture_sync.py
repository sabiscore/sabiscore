"""Unit tests for fixture_sync_service.sync_upcoming_fixtures().

Contracts verified:
  1. Idempotency — re-syncing the same data inserts 0 new rows.
  2. Unsupported competition — unknown league names are silently dropped.
  3. Malformed date — un-parseable match_date skips that match; valid ones still insert.
  4. Provider reschedules update mutable kickoff metadata without changing
     canonical identity and safely remove only unreferenced legacy duplicates.
  5. Provider display-name drift does not silently re-key an existing raw
     scheduled Match while canonical provider identity remains stable.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db import models as _db_models  # noqa: F401
from src.db.models import CanonicalFixture


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _match(n: int, league: str = "EPL", date: str = "2026-07-15T15:00:00Z") -> dict:
    return {
        "id": f"fd-match-{n}",
        "league": league,
        "home_provider_team_id": n * 10,
        "away_provider_team_id": n * 10 + 1,
        "home_team": f"TeamA {n}",
        "away_team": f"TeamB {n}",
        "match_date": date,
    }


def _mock_client(matches: list) -> AsyncMock:
    mock = AsyncMock()
    mock.get_upcoming_matches.return_value = matches
    return mock


async def test_idempotent_resync(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [_match(1), _match(2)]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count_first = await sync_upcoming_fixtures(session)

        MockCls.return_value = _mock_client(matches)
        count_second = await sync_upcoming_fixtures(session)

    assert count_first == 2
    assert count_second == 0


async def test_unsupported_competition_skipped(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [
        _match(10, league="EPL"),
        _match(11, league="FIFA World Cup"),
        _match(12, league="EPL"),
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count = await sync_upcoming_fixtures(session)

    assert count == 2


async def test_malformed_date_skipped(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [
        _match(20, league="EPL"),
        _match(21, league="EPL", date="not-a-date"),
        _match(22, league="EPL"),
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count = await sync_upcoming_fixtures(session)

    assert count == 2


async def test_synced_league_id_is_canonical(session: AsyncSession) -> None:
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    matches = [
        _match(30, league="EPL"),
        _match(31, league="Eredivisie"),
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        await sync_upcoming_fixtures(session)

    rows = (await session.execute(text("SELECT id FROM leagues"))).fetchall()
    stored_ids = {row[0] for row in rows}
    assert "EPL" in stored_ids, f"Expected canonical 'EPL', got: {stored_ids}"
    assert "EREDIVISIE" in stored_ids, f"Expected canonical 'EREDIVISIE', got: {stored_ids}"
    assert "PL" not in stored_ids
    assert "DED" not in stored_ids

    match_rows = (await session.execute(text("SELECT league_id FROM matches"))).fetchall()
    match_league_ids = {row[0] for row in match_rows}
    assert match_league_ids <= {"EPL", "EREDIVISIE"}


async def test_provider_reschedule_updates_kickoff_without_identity_drift(
    session: AsyncSession,
) -> None:
    """Same provider event + same participants remains one canonical fixture."""
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([_match(40, date="2026-07-15T15:00:00Z")])
        await sync_upcoming_fixtures(session)

    original_mapping = (
        await session.execute(
            text(
                "SELECT canonical_fixture_id FROM provider_event_mappings "
                "WHERE provider='football-data.org' AND provider_event_id='fd-match-40'"
            )
        )
    ).scalar_one()
    original_fixture = await session.get(CanonicalFixture, original_mapping)
    assert original_fixture is not None

    legacy_orphan_id = "fixture-legacy-reschedule-orphan"
    session.add(
        CanonicalFixture(
            id=legacy_orphan_id,
            competition_id=original_fixture.competition_id,
            season=original_fixture.season,
            home_team_id=original_fixture.home_team_id,
            away_team_id=original_fixture.away_team_id,
            kickoff_utc=datetime(2026, 8, 1, 18, 0),
            status="scheduled",
            reconciliation_status="VERIFIED",
            reconciliation_confidence=1.0,
            evidence={"provider_event_id": "fd-match-40", "source": "football-data.org"},
        )
    )
    await session.commit()

    matches = [
        _match(40, date="2026-08-01T18:00:00Z"),
        _match(41),
    ]
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client(matches)
        count = await sync_upcoming_fixtures(session)

    assert count == 1

    match_kickoff = (
        await session.execute(select(Match.match_date).where(Match.id == "fd-match-40"))
    ).scalar_one()
    assert match_kickoff == datetime(2026, 8, 1, 18, 0)

    refreshed_mapping = (
        await session.execute(
            text(
                "SELECT canonical_fixture_id FROM provider_event_mappings "
                "WHERE provider='football-data.org' AND provider_event_id='fd-match-40'"
            )
        )
    ).scalar_one()
    assert refreshed_mapping == original_mapping

    canonical_kickoff = (
        await session.execute(
            select(CanonicalFixture.kickoff_utc).where(CanonicalFixture.id == original_mapping)
        )
    ).scalar_one()
    assert canonical_kickoff == datetime(2026, 8, 1, 18, 0)
    assert await session.get(CanonicalFixture, legacy_orphan_id) is None

    canonical_count = int(
        (await session.execute(text("SELECT count(*) FROM canonical_fixtures"))).scalar_one()
    )
    assert canonical_count == 2, "reschedule left or minted an orphan canonical fixture"

    rows = (await session.execute(text("SELECT id FROM matches"))).fetchall()
    ids = {row[0] for row in rows}
    assert "fd-match-41" in ids


async def test_provider_name_drift_preserves_raw_identity_and_canonical_anchor(
    session: AsyncSession,
) -> None:
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([_match(50)])
        await sync_upcoming_fixtures(session)

    changed_name = _match(50, date="2026-08-02T18:00:00Z")
    changed_name["home_team"] = "Different Team 50"
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([changed_name, _match(51)])
        count = await sync_upcoming_fixtures(session)

    assert count == 1

    raw_home = (
        await session.execute(
            text(
                "SELECT t.name FROM matches m JOIN teams t ON t.id=m.home_team_id "
                "WHERE m.id='fd-match-50'"
            )
        )
    ).scalar_one()
    assert raw_home == "TeamA 50"
    assert (
        await session.execute(text("SELECT count(*) FROM matches WHERE id='fd-match-51'"))
    ).scalar_one() == 1

    assert (
        await session.execute(
            text(
                "SELECT count(*) FROM provider_event_mappings "
                "WHERE provider='football-data.org' AND provider_event_id='fd-match-50'"
            )
        )
    ).scalar_one() == 1
    assert (
        await session.execute(
            text("SELECT count(*) FROM canonical_teams WHERE name='Different Team 50'")
        )
    ).scalar_one() == 0
    assert (
        await session.execute(text("SELECT count(*) FROM canonical_fixtures"))
    ).scalar_one() == 2


async def _seed_corrupted_but_elo_bearing_team(
    session: AsyncSession,
    *,
    team_id: str,
    corrupted_name: str,
    league_id: str,
    provider_team_id: str,
) -> None:
    """Reproduce production's exact La Liga shape (docs/DEBT.md item 39).

    These rows predate PR #82's mojibake guard, which now correctly refuses to
    let sync mint a *new* corrupted team -- so they are seeded directly, the
    same approach test_orphan_team_reconciliation_service.py takes.

    The load-bearing detail is that the corrupted row **carries real Elo
    history and a VERIFIED ProviderEloTeamMapping**. That is why live metrics
    show zero `fixture_sync.unusable_team_name` and zero identity conflicts for
    LA_LIGA while it still renders mojibake: resolution short-circuits at the
    durable provider-ID anchor and returns this very row, so the computed id
    equals the stored id and no drift is ever reported. The name is the only
    thing wrong.
    """
    from src.core.database import League, Team
    from src.db.models import EloRatingSnapshot
    from src.db.provider_elo_team_mapping import ProviderEloTeamMapping

    if await session.get(League, league_id) is None:
        session.add(League(id=league_id, name=league_id, country="test"))
    opponent_id = f"{team_id}-opponent"
    session.add(Team(id=team_id, name=corrupted_name, league_id=league_id))
    session.add(Team(id=opponent_id, name="Historic Opponent", league_id=league_id))
    await session.flush()

    hist_id = f"hist-{team_id}"
    hist_date = datetime(2025, 9, 20, 15, 0)
    session.add(
        Match(
            id=hist_id,
            league_id=league_id,
            home_team_id=team_id,
            away_team_id=opponent_id,
            match_date=hist_date,
            season="2025/2026",
            status="finished",
            home_score=2,
            away_score=1,
        )
    )
    await session.flush()
    session.add(
        EloRatingSnapshot(
            match_id=hist_id,
            team_id=team_id,
            pre_match_elo=1500.0,
            post_match_elo=1520.0,
            league=league_id,
            season="2025/2026",
            match_date=hist_date,
            created_at=hist_date,
        )
    )
    session.add(
        ProviderEloTeamMapping(
            provider="football-data.org",
            provider_team_id=provider_team_id,
            provider_team_name=corrupted_name,
            competition=league_id,
            team_id=team_id,
            reconciliation_status="VERIFIED",
            reconciliation_confidence=1.0,
            evidence={"identity_basis": "real_durable_elo_history"},
            checked_at=datetime(2026, 8, 20, 12, 0),
        )
    )
    await session.commit()


async def test_corrupted_stored_team_name_is_repaired_from_a_clean_provider_name(
    session: AsyncSession,
) -> None:
    """Team.name was write-once, so a row created while the provider name was
    mojibake-corrupted kept that corruption forever and rendered it to users
    (9 of 50 live fixtures on 2026-08-25). Once upstream is clean again, the
    next sync tick must repair the stored display name -- without touching
    identity, Elo, or the durable provider mapping.
    """
    from src.core.database import Team
    from src.db.provider_elo_team_mapping import ProviderEloTeamMapping
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    corrupted_id = "fd-team-la_liga:real_betis_balompi??"
    await _seed_corrupted_but_elo_bearing_team(
        session,
        team_id=corrupted_id,
        corrupted_name="Real Betis Balompi??",
        league_id="LA_LIGA",
        provider_team_id="90",
    )

    fixture = _match(9, league="La Liga")
    fixture["home_provider_team_id"] = 90
    fixture["home_team"] = "Real Betis Balompié"
    with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
        MockCls.return_value = _mock_client([fixture])
        await sync_upcoming_fixtures(session)

    repaired = await session.get(Team, corrupted_id)
    assert repaired is not None, "identity must survive a display-name repair"
    assert repaired.name == "Real Betis Balompié"
    assert repaired.id == corrupted_id, "Team.id is identity and must never change"

    # The durable anchor and its Elo evidence are untouched by a name repair.
    mapping = (
        await session.execute(
            select(ProviderEloTeamMapping).where(
                ProviderEloTeamMapping.provider_team_id == "90"
            )
        )
    ).scalar_one()
    assert mapping.team_id == corrupted_id


async def test_a_clean_stored_name_is_never_overwritten(session: AsyncSession) -> None:
    """The repair is strictly one-directional. Historical corpus spellings
    ("Bayern Munich", "Ein Frankfurt") are what resolve_team_id matches
    against, so a clean stored name must never be renamed by a provider --
    including when the provider regresses to a corrupted one.
    """
    from src.core.database import Team
    from src.services.fixture_sync_service import sync_upcoming_fixtures

    clean_id = "fdco-team-la_liga-betis"
    await _seed_corrupted_but_elo_bearing_team(
        session,
        team_id=clean_id,
        corrupted_name="Real Betis",  # already clean
        league_id="LA_LIGA",
        provider_team_id="91",
    )

    for incoming in ("Real Betis Balompi??", "Real Betis Balompié"):
        fixture = _match(9, league="La Liga")
        fixture["home_provider_team_id"] = 91
        fixture["home_team"] = incoming
        with patch("src.data.loaders.football_data_api.FootballDataAPIClient") as MockCls:
            MockCls.return_value = _mock_client([fixture])
            await sync_upcoming_fixtures(session)

        still = await session.get(Team, clean_id)
        assert still is not None and still.name == "Real Betis", (
            f"a clean stored name must survive incoming {incoming!r}"
        )
