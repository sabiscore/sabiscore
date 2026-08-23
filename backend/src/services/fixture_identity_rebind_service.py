"""Read-only manifest of live fixtures whose stored identity disagrees with
the already-verified canonical identity.

docs/DEBT.md item 35: ``fixture_sync_service.sync_upcoming_fixtures`` detects
this drift every tick (a participant was first bound to the deterministic
``fd-team-<league>:<slug>`` fallback before a durable Elo/provider identity
existed; a later tick resolves a better-anchored canonical id) and
deliberately leaves ``Match.home_team_id``/``away_team_id`` unchanged, only
logging a warning and bumping an in-process metric. Nothing previously let an
operator ever see the drifted rows themselves. This module builds that review
manifest — read-only, no mutation — mirroring
``historical_identity_repair_manifest_service.py``'s pattern for the sibling
item-34 historical case.

``Match.id`` is the football-data.org provider event id
(``fixture_sync_service.sync_upcoming_fixtures``), and ``ensure_canonical_fixture``
is called with ``provider_event_id=match_id`` on every tick regardless of
whether the legacy row was flagged — so the "verified" identity is already
fully computed and persisted on ``CanonicalFixture.home_team_id``/``away_team_id``
via the ``ProviderEventMapping`` join. No live provider call or re-run of
resolution logic is needed here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..core.database import Match, Team
from ..db.models import (
    CanonicalFixture,
    CanonicalTeam,
    MatchPredictionLog,
    ProviderEventMapping,
)
from ..repositories.fixtures import SETTLED_MATCH_STATUSES

_MANIFEST_SCHEMA_VERSION = 1
_PROVIDER = "football-data.org"


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class FixtureIdentityRebindEntry:
    match_id: str
    league_id: str
    kickoff_utc: str
    status: str
    stored_home_team_id: str | None
    stored_home_team_name: str | None
    stored_away_team_id: str | None
    stored_away_team_name: str | None
    verified_home_team_id: str | None
    verified_home_team_name: str | None
    verified_away_team_id: str | None
    verified_away_team_name: str | None
    blockers: tuple[str, ...]

    @property
    def rebind_ready(self) -> bool:
        return not self.blockers

    @property
    def rebind_status(self) -> str:
        return "READY" if self.rebind_ready else "BLOCKED"

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["rebind_ready"] = self.rebind_ready
        payload["rebind_status"] = self.rebind_status
        return payload


@dataclass(frozen=True)
class FixtureIdentityRebindManifest:
    schema_version: int
    manifest_sha256: str
    summary: dict[str, object]
    entries: tuple[FixtureIdentityRebindEntry, ...]


async def build_fixture_identity_rebind_manifest(
    session: AsyncSession,
) -> FixtureIdentityRebindManifest:
    """Compare persisted vs. verified participant identity for live fixtures.

    Read-only: issues SELECT statements only, never stages or commits a write.
    A caller that wants transactional isolation from concurrent writers may
    wrap this in a rolled-back transaction the way
    ``data_authority.semantic_repair_review`` does for its sibling case; this
    function itself never mutates state either way.
    """
    stored_home = aliased(Team)
    stored_away = aliased(Team)
    verified_home = aliased(CanonicalTeam)
    verified_away = aliased(CanonicalTeam)

    statement = (
        select(
            Match,
            CanonicalFixture,
            stored_home.name,
            stored_away.name,
            verified_home.name,
            verified_away.name,
        )
        .join(
            ProviderEventMapping,
            (ProviderEventMapping.provider_event_id == Match.id)
            & (ProviderEventMapping.provider == _PROVIDER),
        )
        .join(
            CanonicalFixture,
            CanonicalFixture.id == ProviderEventMapping.canonical_fixture_id,
        )
        .outerjoin(stored_home, stored_home.id == Match.home_team_id)
        .outerjoin(stored_away, stored_away.id == Match.away_team_id)
        .outerjoin(verified_home, verified_home.id == CanonicalFixture.home_team_id)
        .outerjoin(verified_away, verified_away.id == CanonicalFixture.away_team_id)
        .where(
            or_(
                Match.status.is_(None),
                func.lower(Match.status).notin_(SETTLED_MATCH_STATUSES),
            )
        )
    )

    rows = (await session.execute(statement)).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    entries: list[FixtureIdentityRebindEntry] = []
    leagues_affected: set[str] = set()
    for (
        match,
        fixture,
        stored_home_name,
        stored_away_name,
        verified_home_name,
        verified_away_name,
    ) in rows:
        if (
            match.home_team_id == fixture.home_team_id
            and match.away_team_id == fixture.away_team_id
        ):
            continue

        blockers: list[str] = []
        if match.match_date is not None and match.match_date < now:
            blockers.append("KICKOFF_PASSED")
        if fixture.competition_id != match.league_id:
            blockers.append("CROSS_LEAGUE_MISMATCH")
        has_predictions = bool(
            await session.scalar(
                select(exists().where(MatchPredictionLog.match_id == match.id))
            )
        )
        if has_predictions:
            blockers.append("HAS_EXISTING_PREDICTIONS")

        entries.append(
            FixtureIdentityRebindEntry(
                match_id=match.id,
                league_id=match.league_id,
                kickoff_utc=match.match_date.isoformat() if match.match_date else "",
                status=match.status or "",
                stored_home_team_id=match.home_team_id,
                stored_home_team_name=stored_home_name,
                stored_away_team_id=match.away_team_id,
                stored_away_team_name=stored_away_name,
                verified_home_team_id=fixture.home_team_id,
                verified_home_team_name=verified_home_name,
                verified_away_team_id=fixture.away_team_id,
                verified_away_team_name=verified_away_name,
                blockers=tuple(blockers),
            )
        )
        leagues_affected.add(match.league_id)

    entries.sort(key=lambda entry: entry.match_id)
    summary = {
        "total_mismatched": len(entries),
        "rebind_ready_count": sum(1 for entry in entries if entry.rebind_ready),
        "blocked_count": sum(1 for entry in entries if not entry.rebind_ready),
        "leagues_affected": sorted(leagues_affected),
    }
    manifest_sha256 = _canonical_sha256(
        {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "entries": [entry.as_dict() for entry in entries],
        }
    )
    return FixtureIdentityRebindManifest(
        schema_version=_MANIFEST_SCHEMA_VERSION,
        manifest_sha256=manifest_sha256,
        summary=summary,
        entries=tuple(entries),
    )


__all__ = [
    "FixtureIdentityRebindEntry",
    "FixtureIdentityRebindManifest",
    "build_fixture_identity_rebind_manifest",
]
