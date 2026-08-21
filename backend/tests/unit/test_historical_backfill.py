"""Unit tests for historical_backfill_service.

The load-bearing contract is team-name resolution between football-data.co.uk
short names and football-data.org legal names. A wrong join is far worse than no
join: it would attribute one club's form to another. Every ambiguous case must
therefore fail closed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.services import historical_backfill_service
from src.services.historical_backfill_service import (
    TeamIndex,
    backfill_historical_matches,
    historical_match_id,
    normalise_team_tokens,
    parse_fd_csv,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Arsenal FC", ("arsenal",)),
        ("Club Atlético de Madrid", ("atletico", "madrid")),  # accents + particles
        ("Real Sociedad de Fútbol", ("real", "sociedad")),  # 'futbol' is noise
        ("Como 1907", ("como",)),  # bare year dropped
        ("FC Twente '65", ("twente",)),  # apostrophe-year dropped
        ("Stade Brestois 29", ("stade", "brestois")),
        ("Willem II Tilburg", ("willem", "ii", "tilburg")),
    ],
)
def test_normalise_team_tokens(raw, expected):
    assert normalise_team_tokens(raw) == expected


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def test_resolves_short_name_to_legal_name():
    index = TeamIndex([("t1", "Manchester United FC"), ("t2", "Arsenal FC")])
    assert index.resolve("Man United") == "t1"
    assert index.resolve("Arsenal") == "t2"


def test_resolves_via_curated_alias():
    """'Ath Bilbao' cannot reach 'Athletic Club' by prefix — the alias must carry it."""
    index = TeamIndex([("t1", "Athletic Club"), ("t2", "Club Atlético de Madrid")])
    assert index.resolve("Ath Bilbao") == "t1"
    assert index.resolve("Ath Madrid") == "t2"


def test_ambiguous_prefix_fails_closed():
    """'Milan' prefixes both 'AC Milan' and 'Internazionale Milano'.

    Without the alias entry that pins Inter, a bare prefix match would bind one
    club's history to the other. Resolution must refuse instead of guessing.
    """
    index = TeamIndex([("inter", "Internazionale Milano"), ("milan", "AC Milan")])
    assert index.resolve("Milan") == "milan"  # exact-normalised beats prefix
    assert index.resolve("Inter") == "inter"  # alias-pinned
    # A genuinely ambiguous probe resolves to nothing rather than to either club.
    assert index.resolve("Milano Calcio") is None


def test_unique_exact_name_beats_another_teams_alias():
    index = TeamIndex(
        [
            ("historical-man-city", "Man City"),
            ("provider-manchester-city", "Manchester City FC"),
        ]
    )

    assert index.resolve("Man City") == "historical-man-city"
    assert index.resolve("Manchester City") == "provider-manchester-city"


def test_ambiguous_curated_alias_fails_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(
        historical_backfill_service._TEAM_ALIASES, "alpha united", "shared"
    )
    monkeypatch.setitem(
        historical_backfill_service._TEAM_ALIASES, "beta united", "shared"
    )
    index = TeamIndex([("alpha", "Alpha United"), ("beta", "Beta United")])

    assert index.resolve("Shared") is None


def test_resolves_ipswich_only_through_measured_alias():
    index = TeamIndex([("ipswich", "Ipswich Town FC")])

    assert index.resolve("Ipswich") == "ipswich"


def test_short_token_cannot_prefix_swallow_a_real_word():
    """Regression: 'Le' (Le Mans FC) prefix-matched 'Leeds', making Leeds United
    ambiguous and silently costing it its entire match history."""
    index = TeamIndex([("leeds", "Leeds United FC"), ("lemans", "Le Mans FC")])
    assert index.resolve("Leeds") == "leeds"
    assert index.resolve("Le Havre") != "leeds"


def test_identical_normalisation_between_two_teams_fails_closed():
    index = TeamIndex([("a", "Real Madrid CF"), ("b", "Real Madrid FC")])
    assert index.resolve("Real Madrid") is None


def test_unknown_team_resolves_to_none():
    index = TeamIndex([("t1", "Arsenal FC")])
    assert index.resolve("Wigan Athletic") is None
    assert index.resolve("") is None


# --------------------------------------------------------------------------- #
# Deterministic ids
# --------------------------------------------------------------------------- #


def test_match_id_is_deterministic_and_dialect_independent():
    a = historical_match_id("EPL", datetime(2024, 8, 16), "Man United", "Fulham")
    b = historical_match_id("EPL", datetime(2024, 8, 16), "  man united  ", "Fulham")
    assert (
        a
        == b
        == historical_match_id("EPL", datetime(2024, 8, 16), "Man United", "Fulham")
    )
    assert a != historical_match_id(
        "EPL", datetime(2024, 8, 16), "Fulham", "Man United"
    )


# --------------------------------------------------------------------------- #
# CSV parsing — three header dialects and two date formats exist in-repo
# --------------------------------------------------------------------------- #

_RAW = (
    "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\n"
    "E0,15/08/2025,20:00,Liverpool,Bournemouth,4,2\n"
)
_NORMALISED = (
    "Div,date,Time,home_team,away_team,home_goals,away_goals\n"
    "E0,2024-08-16,20:00,Man United,Fulham,1,0\n"
)


def test_parse_handles_raw_provider_dialect(tmp_path: Path):
    path = tmp_path / "fd_E0_2526.csv"
    path.write_text(_RAW, encoding="utf-8-sig")  # provider ships a BOM
    rows = parse_fd_csv(path)
    assert len(rows) == 1
    assert rows[0].league_id == "EPL"
    assert rows[0].match_date == datetime(2025, 8, 15)
    assert (rows[0].home_score, rows[0].away_score) == (4, 2)


def test_parse_handles_normalised_dialect(tmp_path: Path):
    path = tmp_path / "fd_E0_2425.csv"
    path.write_text(_NORMALISED, encoding="utf-8")
    rows = parse_fd_csv(path)
    assert len(rows) == 1
    assert rows[0].match_date == datetime(2024, 8, 16)
    assert rows[0].home_team == "Man United"


def test_parse_skips_malformed_rows_without_failing_the_file(tmp_path: Path):
    path = tmp_path / "fd_E0_2526.csv"
    path.write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
        "E0,not-a-date,Liverpool,Bournemouth,4,2\n"  # bad date
        "E0,15/08/2025,Liverpool,,4,2\n"  # missing away team
        "E0,15/08/2025,Arsenal,Chelsea,,\n"  # unplayed fixture, no score
        "E0,16/08/2025,Arsenal,Chelsea,2,1\n",  # good
        encoding="utf-8",
    )
    rows = parse_fd_csv(path)
    assert len(rows) == 1
    assert rows[0].home_team == "Arsenal"


def test_parse_rejects_unsupported_division(tmp_path: Path):
    """E1 (Championship) is outside the seven-competition closed set."""
    path = tmp_path / "fd_E1_2526.csv"
    path.write_text(_RAW.replace("E0,", "E1,"), encoding="utf-8")
    assert parse_fd_csv(path) == []


# --------------------------------------------------------------------------- #
# Backfill behaviour
# --------------------------------------------------------------------------- #


def _write_season(directory: Path) -> None:
    (directory / "fd_E0_2425.csv").write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
        "E0,16/08/2024,Man United,Fulham,1,0\n"
        "E0,17/08/2024,Arsenal,Fulham,2,1\n",
        encoding="utf-8",
    )


async def test_backfill_inserts_finished_matches(session: AsyncSession, tmp_path: Path):
    _write_season(tmp_path)
    report = await backfill_historical_matches(session, cache_dir=tmp_path)

    assert report.matches_inserted == 2
    rows = (await session.execute(select(Match))).scalars().all()
    assert len(rows) == 2
    assert {r.status for r in rows} == {"finished"}
    assert {r.league_id for r in rows} == {"EPL"}
    assert all(r.home_score is not None and r.away_score is not None for r in rows)


async def test_backfill_is_idempotent(session: AsyncSession, tmp_path: Path):
    _write_season(tmp_path)
    first = await backfill_historical_matches(session, cache_dir=tmp_path)
    second = await backfill_historical_matches(session, cache_dir=tmp_path)

    assert first.matches_inserted == 2
    assert second.matches_inserted == 0
    assert second.matches_existing == 2
    assert len((await session.execute(select(Match))).scalars().all()) == 2


async def test_backfill_joins_onto_existing_fixture_sync_teams(
    session: AsyncSession, tmp_path: Path
):
    """The whole point: history must attach to the Team rows fixture sync created,
    not mint parallel ones under the provider's other spelling."""
    session.add(
        Team(
            id="fd-team-epl:manchester_united_fc",
            name="Manchester United FC",
            league_id="EPL",
        )
    )
    session.add(Team(id="fd-team-epl:fulham_fc", name="Fulham FC", league_id="EPL"))
    await session.commit()

    _write_season(tmp_path)
    report = await backfill_historical_matches(session, cache_dir=tmp_path)

    match = (
        (
            await session.execute(
                select(Match).where(Match.away_team_id == "fd-team-epl:fulham_fc")
            )
        )
        .scalars()
        .first()
    )
    assert match is not None, "history did not join onto the fixture-sync team rows"
    assert match.home_team_id == "fd-team-epl:manchester_united_fc"
    # Arsenal was genuinely unknown, so exactly one new team row is minted.
    assert report.teams_created == 1


async def test_backfill_same_name_other_league_cannot_poison_valid_local_identity(
    session: AsyncSession, tmp_path: Path
):
    """An exact duplicate name in another league must not make EPL resolution ambiguous."""
    session.add_all(
        [
            League(id="EPL", name="Premier League", country="England"),
            League(id="BUNDESLIGA", name="Bundesliga", country="Germany"),
            Team(id="epl-arsenal", name="Arsenal FC", league_id="EPL"),
            Team(id="foreign-arsenal", name="Arsenal FC", league_id="BUNDESLIGA"),
        ]
    )
    await session.commit()
    (tmp_path / "fd_E0_2425.csv").write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,17/08/2024,Arsenal,Chelsea,2,1\n",
        encoding="utf-8",
    )

    report = await backfill_historical_matches(session, cache_dir=tmp_path)
    match = (await session.execute(select(Match))).scalars().one()

    assert match.home_team_id == "epl-arsenal"
    assert match.home_team_id != "foreign-arsenal"
    assert report.teams_resolved == 1


async def test_backfill_other_league_only_candidate_is_never_reused(
    session: AsyncSession, tmp_path: Path
):
    """A globally exact name match is still ineligible when Team.league_id differs."""
    session.add_all(
        [
            League(id="BUNDESLIGA", name="Bundesliga", country="Germany"),
            Team(id="foreign-arsenal", name="Arsenal FC", league_id="BUNDESLIGA"),
        ]
    )
    await session.commit()
    (tmp_path / "fd_E0_2425.csv").write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,17/08/2024,Arsenal,Chelsea,2,1\n",
        encoding="utf-8",
    )

    report = await backfill_historical_matches(session, cache_dir=tmp_path)
    match = (await session.execute(select(Match))).scalars().one()
    local = await session.get(Team, match.home_team_id)

    assert match.home_team_id == "fdco-team-epl-arsenal"
    assert match.home_team_id != "foreign-arsenal"
    assert local is not None and local.league_id == "EPL"
    assert report.teams_created == 2  # Arsenal and Chelsea are both new to EPL.


async def test_backfill_reports_nothing_when_cache_dir_absent(
    session: AsyncSession, tmp_path: Path
):
    report = await backfill_historical_matches(session, cache_dir=tmp_path / "nope")
    assert report.files_read == 0
    assert report.matches_inserted == 0
