"""Deterministic canonical identity writes shared by sync and ingestion jobs."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import (
    CanonicalCompetition,
    CanonicalFixture,
    CanonicalTeam,
    MarketSnapshot,
    MatchPredictionLog,
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


async def _remove_unreferenced_reschedule_orphans(
    session: AsyncSession,
    *,
    mapped_fixture_id: str,
    provider_event_id: str,
    competition_id: str,
    home_team_id: str,
    away_team_id: str,
    kickoff_utc: datetime,
) -> int:
    """Delete only duplicate fixtures provably left by the old reschedule bug.

    The pre-fix writer could insert a kickoff-derived canonical fixture and then
    discover that ``provider_event_id`` was already mapped to an older fixture.
    Because the caller caught the conflict and committed the batch, that new
    fixture survived without a provider mapping. A candidate is safe to remove
    only when all stable identity fields and provider-event evidence match the
    verified reschedule and no mapping, market snapshot, or prediction log
    references it.
    """

    candidates = (
        (
            await session.execute(
                select(CanonicalFixture).where(
                    CanonicalFixture.id != mapped_fixture_id,
                    CanonicalFixture.competition_id == competition_id,
                    CanonicalFixture.home_team_id == home_team_id,
                    CanonicalFixture.away_team_id == away_team_id,
                    CanonicalFixture.kickoff_utc == kickoff_utc,
                )
            )
        )
        .scalars()
        .all()
    )

    removed = 0
    for candidate in candidates:
        candidate_evidence = candidate.evidence or {}
        if candidate_evidence.get("provider_event_id") != provider_event_id:
            continue

        has_event_mapping = bool(
            await session.scalar(
                select(
                    exists().where(ProviderEventMapping.canonical_fixture_id == candidate.id)
                )
            )
        )
        has_market_snapshot = bool(
            await session.scalar(
                select(exists().where(MarketSnapshot.canonical_fixture_id == candidate.id))
            )
        )
        has_prediction = bool(
            await session.scalar(
                select(exists().where(MatchPredictionLog.canonical_fixture_id == candidate.id))
            )
        )
        if has_event_mapping or has_market_snapshot or has_prediction:
            continue

        await session.delete(candidate)
        removed += 1

    return removed


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
    """Upsert a verified fixture and mappings without guessing ambiguous names.

    A verified ``(provider, provider_event_id)`` mapping is the durable identity
    anchor once it exists. Kickoff time is mutable fixture metadata: legitimate
    reschedules update the already-mapped canonical fixture in place, but only
    when the competition and both canonical participants are unchanged.
    Participant or competition drift remains a hard identity conflict.
    """

    if not all((provider, provider_event_id, competition_id, home_name, away_name)):
        raise ValueError("canonical identity requires explicit provider and fixture fields")
    if _key(home_name) == _key(away_name):
        raise ValueError("home and away teams must be distinct")
    if kickoff_utc.tzinfo is not None:
        kickoff_utc = kickoff_utc.astimezone(timezone.utc).replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Resolve the durable provider-event anchor before staging canonical rows.
    # This catches competition drift without leaving pending side effects.
    event_mapping = (
        await session.execute(
            select(ProviderEventMapping).where(
                ProviderEventMapping.provider == provider,
                ProviderEventMapping.provider_event_id == provider_event_id,
            )
        )
    ).scalar_one_or_none()
    if event_mapping is not None and event_mapping.competition != competition_id:
        raise ValueError("provider event conflicts with an existing competition")

    team_ids = [
        _stable_id("team", competition_id, home_name),
        _stable_id("team", competition_id, away_name),
    ]

    mapped_fixture: CanonicalFixture | None = None
    if event_mapping is not None:
        mapped_fixture_id = event_mapping.canonical_fixture_id
        if not mapped_fixture_id:
            raise ValueError("provider event mapping has no canonical fixture")
        mapped_fixture = await session.get(CanonicalFixture, mapped_fixture_id)
        if mapped_fixture is None:
            raise ValueError("provider event mapping references a missing canonical fixture")
        if (
            mapped_fixture.competition_id != competition_id
            or mapped_fixture.home_team_id != team_ids[0]
            or mapped_fixture.away_team_id != team_ids[1]
        ):
            raise ValueError("provider event conflicts with an existing canonical fixture")

    competition = await session.get(CanonicalCompetition, competition_id)
    if competition is None:
        session.add(
            CanonicalCompetition(
                id=competition_id,
                name=competition_name,
                coverage_tier="STANDARD",
                active=True,
                created_at=now,
                updated_at=now,
            )
        )

    for provider_team_id, team_name, team_id in (
        (home_provider_id, home_name, team_ids[0]),
        (away_provider_id, away_name, team_ids[1]),
    ):
        if await session.get(CanonicalTeam, team_id) is None:
            session.add(
                CanonicalTeam(
                    id=team_id,
                    competition_id=competition_id,
                    name=team_name,
                    normalized_name=_key(team_name),
                    active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
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
            session.add(
                ProviderTeamMapping(
                    provider=provider,
                    provider_team_id=provider_team_id,
                    provider_team_name=team_name,
                    canonical_team_id=team_id,
                    competition=competition_id,
                    reconciliation_status="VERIFIED",
                    reconciliation_confidence=1.0,
                    evidence=evidence,
                    checked_at=now,
                )
            )
        elif mapping.canonical_team_id != team_id:
            raise ValueError("provider team conflicts with an existing canonical team")
        else:
            mapping.provider_team_name = team_name
            mapping.reconciliation_status = "VERIFIED"
            mapping.reconciliation_confidence = 1.0
            mapping.evidence = evidence
            mapping.checked_at = now

    await session.flush()

    if event_mapping is not None and mapped_fixture is not None:
        mapped_fixture_id = mapped_fixture.id
        mapped_fixture.kickoff_utc = kickoff_utc
        mapped_fixture.season = season
        mapped_fixture.status = status
        mapped_fixture.reconciliation_status = "VERIFIED"
        mapped_fixture.reconciliation_confidence = 1.0
        mapped_fixture.evidence = evidence
        mapped_fixture.updated_at = now
        event_mapping.reconciliation_status = "VERIFIED"
        event_mapping.reconciliation_confidence = 1.0
        event_mapping.evidence = evidence
        event_mapping.checked_at = now

        await _remove_unreferenced_reschedule_orphans(
            session,
            mapped_fixture_id=mapped_fixture_id,
            provider_event_id=provider_event_id,
            competition_id=competition_id,
            home_team_id=team_ids[0],
            away_team_id=team_ids[1],
            kickoff_utc=kickoff_utc,
        )
        return mapped_fixture_id

    fixture_id = _stable_id(
        "fixture", competition_id, kickoff_utc.isoformat(), home_name, away_name
    )
    fixture = await session.get(CanonicalFixture, fixture_id)
    if fixture is None:
        session.add(
            CanonicalFixture(
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
            )
        )
    else:
        if (
            fixture.competition_id != competition_id
            or fixture.home_team_id != team_ids[0]
            or fixture.away_team_id != team_ids[1]
        ):
            raise ValueError("canonical fixture hash collision or participant conflict")
        fixture.season = season
        fixture.status = status
        fixture.evidence = evidence
        fixture.updated_at = now

    session.add(
        ProviderEventMapping(
            provider=provider,
            provider_event_id=provider_event_id,
            canonical_fixture_id=fixture_id,
            competition=competition_id,
            reconciliation_status="VERIFIED",
            reconciliation_confidence=1.0,
            evidence=evidence,
            checked_at=now,
        )
    )
    return fixture_id
