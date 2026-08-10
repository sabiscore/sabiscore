"""Deterministic canonical identity writes shared by sync and ingestion jobs."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import (
    CanonicalCompetition,
    CanonicalFixture,
    CanonicalTeam,
    ProviderEventMapping,
    ProviderTeamMapping,
)


def _key(value: str) -> str:
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.lower())
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _stable_id(namespace: str, *parts: str) -> str:
    payload = "|".join(_key(part) for part in parts)
    return f"{namespace}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


async def canonical_fixture_id_for_provider_event(
    session: AsyncSession, *, provider: str, provider_event_id: str
) -> str | None:
    return (
        await session.execute(
            select(ProviderEventMapping.canonical_fixture_id).where(
                ProviderEventMapping.provider == provider,
                ProviderEventMapping.provider_event_id == provider_event_id,
                ProviderEventMapping.reconciliation_status == "VERIFIED",
            )
        )
    ).scalars().first()


async def ensure_canonical_fixture(
    session: AsyncSession,
    *,
    provider: str,
    provider_event_id: str,
    competition_id: str,
    competition_name: str,
    home_provider_id: str,
    home_name: str,
    away_provider_id: str,
    away_name: str,
    kickoff_utc: datetime,
    season: str | None,
    status: str,
    evidence: dict[str, object],
) -> str:
    """Upsert a verified fixture and mappings without guessing ambiguous names."""

    if not all((provider, provider_event_id, competition_id, home_name, away_name)):
        raise ValueError("canonical identity requires explicit provider and fixture fields")
    if _key(home_name) == _key(away_name):
        raise ValueError("home and away teams must be distinct")
    if kickoff_utc.tzinfo is not None:
        kickoff_utc = kickoff_utc.astimezone(timezone.utc).replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    competition = await session.get(CanonicalCompetition, competition_id)
    if competition is None:
        session.add(CanonicalCompetition(
            id=competition_id,
            name=competition_name,
            coverage_tier="STANDARD",
            active=True,
            created_at=now,
            updated_at=now,
        ))

    team_ids: list[str] = []
    for provider_team_id, team_name in (
        (home_provider_id, home_name),
        (away_provider_id, away_name),
    ):
        team_id = _stable_id("team", competition_id, team_name)
        team_ids.append(team_id)
        if await session.get(CanonicalTeam, team_id) is None:
            session.add(CanonicalTeam(
                id=team_id,
                competition_id=competition_id,
                name=team_name,
                normalized_name=_key(team_name),
                active=True,
                created_at=now,
                updated_at=now,
            ))
        mapping = (
            await session.execute(
                select(ProviderTeamMapping).where(
                    ProviderTeamMapping.provider == provider,
                    ProviderTeamMapping.provider_team_id == provider_team_id,
                    ProviderTeamMapping.competition == competition_id,
                )
            )
        ).scalar_one_or_none()
        if mapping is None:
            session.add(ProviderTeamMapping(
                provider=provider,
                provider_team_id=provider_team_id,
                provider_team_name=team_name,
                canonical_team_id=team_id,
                competition=competition_id,
                reconciliation_status="VERIFIED",
                reconciliation_confidence=1.0,
                evidence=evidence,
                checked_at=now,
            ))

    # Flush the canonical team rows before inserting the fixture. Without this
    # boundary, the fixture insert can reach the database before the matching
    # canonical_teams rows are visible, which trips the FK observed in Render.
    await session.flush()

    fixture_id = _stable_id(
        "fixture", competition_id, kickoff_utc.isoformat(), home_name, away_name
    )
    if await session.get(CanonicalFixture, fixture_id) is None:
        session.add(CanonicalFixture(
            id=fixture_id,
            competition_id=competition_id,
            season=season,
            home_team_id=team_ids[0],
            away_team_id=team_ids[1],
            kickoff_utc=kickoff_utc,
            status=status,
            reconciliation_status="VERIFIED",
            reconciliation_confidence=1.0,
            evidence=evidence,
            created_at=now,
            updated_at=now,
        ))

    event_mapping = (
        await session.execute(
            select(ProviderEventMapping).where(
                ProviderEventMapping.provider == provider,
                ProviderEventMapping.provider_event_id == provider_event_id,
                ProviderEventMapping.competition == competition_id,
            )
        )
    ).scalar_one_or_none()
    if event_mapping is None:
        session.add(ProviderEventMapping(
            provider=provider,
            provider_event_id=provider_event_id,
            canonical_fixture_id=fixture_id,
            competition=competition_id,
            reconciliation_status="VERIFIED",
            reconciliation_confidence=1.0,
            evidence=evidence,
            checked_at=now,
        ))
    elif event_mapping.canonical_fixture_id != fixture_id:
        raise ValueError("provider event conflicts with an existing canonical fixture")
    return fixture_id
