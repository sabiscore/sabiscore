"""docs/DEBT.md item 35: fixture-identity rebind review manifest is read-only.

⚠️ Rewritten 2026-08-25. The original version of this file seeded a
``CanonicalFixture``/``CanonicalTeam`` "verified" identity and asserted the
manifest surfaced it -- exactly the wrong table for what
``Match.home_team_id``/``away_team_id`` actually foreign-keys to
(``teams.id``, not ``canonical_teams.id``). A live apply built on that
manifest failed with a real ``ForeignKeyViolationError`` before this was
caught and both the builder and these tests were corrected. See
``fixture_identity_rebind_service``'s module docstring for the full account.

The correct "verified" identity is a durable ``ProviderEloTeamMapping`` bridge
(``VERIFIED`` status, target has real Elo history) resolved through
``team_identity.resolve_provider_elo_team_id`` -- the same bridge
``fixture_sync_service._resolve_upcoming_team_id``'s fast path uses on every
sync tick.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.db.models import EloRatingSnapshot, MatchPredictionLog
from src.services.canonical_identity_service import ensure_canonical_fixture
from src.services.fixture_identity_rebind_service import (
    build_fixture_identity_rebind_manifest,
)
from src.services.team_identity import bind_provider_elo_team_id

_FUTURE = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
_PAST = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)
_PROVIDER = "football-data.org"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


async def _give_team_elo_history(session: AsyncSession, *, team_id: str, league_id: str) -> None:
    hist_date = datetime(2025, 9, 20, 15, 0)
    hist_match_id = f"hist-{team_id}"
    session.add(Team(id=f"opponent-{team_id}", name="Historical Opponent", league_id=league_id))
    await session.flush()
    session.add(
        Match(
            id=hist_match_id,
            league_id=league_id,
            home_team_id=team_id,
            away_team_id=f"opponent-{team_id}",
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
            match_id=hist_match_id,
            team_id=team_id,
            pre_match_elo=1500.0,
            post_match_elo=1520.0,
            league=league_id,
            season="2025/2026",
            match_date=hist_date,
            created_at=hist_date,
        )
    )
    await session.flush()


async def _seed_mismatched_match(
    session: AsyncSession,
    *,
    match_id: str,
    league_id: str = "SERIE_A",
    kickoff: datetime = _FUTURE,
    status: str = "scheduled",
    stored_home_name: str = "Stored Home",
) -> None:
    """A match bound to the old deterministic ``fd-team-`` id, while the
    provider's home/away ids already carry a durable, Elo-bearing binding to
    a *different* Team -- the exact drift ``fixture_sync_service`` logs and
    leaves unchanged.
    """
    if not await session.get(League, league_id):
        session.add(League(id=league_id, name=league_id, country="test"))

    stored_home = f"fd-team-{league_id.lower()}:home-{match_id}"
    stored_away = f"fd-team-{league_id.lower()}:away-{match_id}"
    verified_home = f"fdco-team-{league_id.lower()}-home-{match_id}"
    verified_away = f"fdco-team-{league_id.lower()}-away-{match_id}"
    session.add(Team(id=stored_home, name=stored_home_name, league_id=league_id))
    session.add(Team(id=stored_away, name="Stored Away", league_id=league_id))
    session.add(Team(id=verified_home, name="Verified Home", league_id=league_id))
    session.add(Team(id=verified_away, name="Verified Away", league_id=league_id))
    await session.flush()

    await _give_team_elo_history(session, team_id=verified_home, league_id=league_id)
    await _give_team_elo_history(session, team_id=verified_away, league_id=league_id)

    session.add(
        Match(
            id=match_id,
            league_id=league_id,
            home_team_id=stored_home,
            away_team_id=stored_away,
            match_date=kickoff,
            season="2026/2027",
            status=status,
        )
    )
    await session.flush()

    home_provider_id = f"home-provider-{match_id}"
    away_provider_id = f"away-provider-{match_id}"
    await ensure_canonical_fixture(
        session,
        provider=_PROVIDER,
        provider_event_id=match_id,
        competition_id=league_id,
        competition_name=league_id,
        home_provider_id=home_provider_id,
        home_name="Verified Home",
        away_provider_id=away_provider_id,
        away_name="Verified Away",
        kickoff_utc=kickoff,
        season="2026/2027",
        status=status,
        evidence={
            "home_provider_team_id": home_provider_id,
            "away_provider_team_id": away_provider_id,
        },
    )
    await bind_provider_elo_team_id(
        provider=_PROVIDER,
        provider_team_id=home_provider_id,
        provider_team_name="Verified Home",
        competition=league_id,
        team_id=verified_home,
        db=session,
    )
    await bind_provider_elo_team_id(
        provider=_PROVIDER,
        provider_team_id=away_provider_id,
        provider_team_name="Verified Away",
        competition=league_id,
        team_id=verified_away,
        db=session,
    )
    await session.commit()


async def test_manifest_flags_mismatched_unsettled_fixture(session: AsyncSession) -> None:
    await _seed_mismatched_match(session, match_id="fd-1")

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert manifest.summary["total_mismatched"] == 1
    assert manifest.summary["rebind_ready_count"] == 1
    assert manifest.summary["blocked_count"] == 0
    assert manifest.summary["leagues_affected"] == ["SERIE_A"]
    entry = manifest.entries[0]
    assert entry.match_id == "fd-1"
    assert entry.stored_home_team_id == "fd-team-serie_a:home-fd-1"
    assert entry.stored_home_team_name == "Stored Home"
    assert entry.verified_home_team_name == "Verified Home"
    assert entry.verified_home_team_id == "fdco-team-serie_a-home-fd-1"
    assert entry.verified_home_team_id != entry.stored_home_team_id
    assert entry.blockers == ()
    assert entry.rebind_ready is True
    assert entry.rebind_status == "READY"


async def test_manifest_omits_fixtures_with_agreeing_identity(session: AsyncSession) -> None:
    league_id = "SERIE_A"
    match_id = "fd-2"
    verified_id = "fdco-team-serie_a-agreeing"
    session.add(League(id=league_id, name=league_id, country="test"))
    session.add(Team(id=verified_id, name="Agreeing Team", league_id=league_id))
    await session.flush()
    await _give_team_elo_history(session, team_id=verified_id, league_id=league_id)

    session.add(
        Match(
            id=match_id,
            league_id=league_id,
            # Already bound to the correct, durable id -- no drift to report.
            home_team_id=verified_id,
            away_team_id=f"opponent-{verified_id}",
            match_date=_FUTURE,
            season="2026/2027",
            status="scheduled",
        )
    )
    await session.flush()
    await ensure_canonical_fixture(
        session,
        provider=_PROVIDER,
        provider_event_id=match_id,
        competition_id=league_id,
        competition_name=league_id,
        home_provider_id="200",
        home_name="Agreeing Team",
        away_provider_id="201",
        away_name="Opponent",
        kickoff_utc=_FUTURE,
        season="2026/2027",
        status="scheduled",
        evidence={"home_provider_team_id": "200", "away_provider_team_id": "201"},
    )
    await bind_provider_elo_team_id(
        provider=_PROVIDER,
        provider_team_id="200",
        provider_team_name="Agreeing Team",
        competition=league_id,
        team_id=verified_id,
        db=session,
    )
    await bind_provider_elo_team_id(
        provider=_PROVIDER,
        provider_team_id="201",
        provider_team_name="Opponent",
        competition=league_id,
        team_id=f"opponent-{verified_id}",
        db=session,
    )
    await session.commit()

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert manifest.entries == ()
    assert manifest.summary["total_mismatched"] == 0


async def test_manifest_excludes_matches_with_no_durable_binding(
    session: AsyncSession,
) -> None:
    """A fixture with only the canonical-identity system resolved (no
    ``ProviderEloTeamMapping`` yet) cannot be safely reconciled without live
    data -- it must be silently excluded, never guessed."""
    league_id = "SERIE_A"
    match_id = "fd-no-binding"
    session.add(League(id=league_id, name=league_id, country="test"))
    session.add(Team(id="fd-team-serie_a:stored", name="Stored", league_id=league_id))
    await session.flush()
    session.add(
        Match(
            id=match_id,
            league_id=league_id,
            home_team_id="fd-team-serie_a:stored",
            away_team_id="fd-team-serie_a:stored-away",
            match_date=_FUTURE,
            season="2026/2027",
            status="scheduled",
        )
    )
    session.add(Team(id="fd-team-serie_a:stored-away", name="Stored Away", league_id=league_id))
    await session.flush()
    await ensure_canonical_fixture(
        session,
        provider=_PROVIDER,
        provider_event_id=match_id,
        competition_id=league_id,
        competition_name=league_id,
        home_provider_id="900",
        home_name="Unbridged Home",
        away_provider_id="901",
        away_name="Unbridged Away",
        kickoff_utc=_FUTURE,
        season="2026/2027",
        status="scheduled",
        evidence={"home_provider_team_id": "900", "away_provider_team_id": "901"},
    )
    # Deliberately no bind_provider_elo_team_id call -- no durable Elo bridge.
    await session.commit()

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert manifest.entries == ()
    assert manifest.summary["total_mismatched"] == 0


async def test_manifest_excludes_settled_matches(session: AsyncSession) -> None:
    await _seed_mismatched_match(session, match_id="fd-3", status="finished")

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert manifest.entries == ()


async def test_manifest_flags_kickoff_passed_blocker(session: AsyncSession) -> None:
    await _seed_mismatched_match(session, match_id="fd-4", kickoff=_PAST)

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert "KICKOFF_PASSED" in entry.blockers
    assert entry.rebind_ready is False
    assert entry.rebind_status == "BLOCKED"


async def test_manifest_flags_existing_predictions_blocker(session: AsyncSession) -> None:
    await _seed_mismatched_match(session, match_id="fd-5")
    session.add(
        MatchPredictionLog(
            match_id="fd-5",
            model_version="v5_phase7",
            home_probability=0.4,
            draw_probability=0.3,
            away_probability=0.3,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    await session.commit()

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert len(manifest.entries) == 1
    assert "HAS_EXISTING_PREDICTIONS" in manifest.entries[0].blockers


async def test_manifest_flags_mojibake_stored_identity(session: AsyncSession) -> None:
    """The exact production shape: a lossy stored name vs a clean verified one.

    Live v3 held `fd-team-la_liga:m??laga_cf` / "M??laga CF" while the
    durably-bridged Elo team was the clean, history-bearing club. Those rows
    are the highest-value rebinds, so the manifest must single them out.
    """
    await _seed_mismatched_match(
        session,
        match_id="fd-7",
        league_id="LA_LIGA",
        stored_home_name="M??laga CF",
    )

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert manifest.summary["stored_identity_unusable_count"] == 1
    entry = manifest.entries[0]
    assert entry.stored_identity_unusable is True
    assert entry.verified_home_team_name == "Verified Home"
    assert entry.as_dict()["stored_identity_unusable"] is True


async def test_clean_mismatch_is_not_flagged_as_unusable(session: AsyncSession) -> None:
    await _seed_mismatched_match(session, match_id="fd-8")

    manifest = await build_fixture_identity_rebind_manifest(session)

    assert manifest.summary["stored_identity_unusable_count"] == 0
    assert manifest.entries[0].stored_identity_unusable is False


async def test_manifest_sha256_is_deterministic(session: AsyncSession) -> None:
    await _seed_mismatched_match(session, match_id="fd-6")

    first = await build_fixture_identity_rebind_manifest(session)
    second = await build_fixture_identity_rebind_manifest(session)

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.manifest_sha256 != ""
