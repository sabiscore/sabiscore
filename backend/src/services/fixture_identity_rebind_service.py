"""Read-only manifest of live fixtures whose stored identity disagrees with
the durably-verified Elo-bridge identity.

docs/DEBT.md item 35: ``fixture_sync_service.sync_upcoming_fixtures`` detects
this drift every tick (a participant was first bound to the deterministic
``fd-team-<league>:<slug>`` fallback before a durable Elo/provider identity
existed; a later tick resolves a better-anchored ``Team`` id) and deliberately
leaves ``Match.home_team_id``/``away_team_id`` unchanged, only logging a
warning and bumping an in-process metric. Nothing previously let an operator
ever see the drifted rows themselves. This module builds that review
manifest — read-only, no mutation.

⚠️ **Corrected 2026-08-25.** The original version of this module joined
``CanonicalFixture.home_team_id``/``away_team_id`` and called that the
"verified" identity. That is wrong: ``CanonicalFixture`` is keyed by
``canonical_teams.id`` (a wholly separate identity domain,
``canonical_identity_service``/``ProviderTeamMapping``), while
``Match.home_team_id``/``away_team_id`` are a foreign key to ``teams.id``.
Docs/DEBT.md item 39's own 2026-08-24 correction had already named this exact
trap for this exact endpoint — it went unheeded when this module was built,
and a live apply attempt failed with a real
``ForeignKeyViolationError`` (safely; nothing committed) before it was caught
and fixed here.

The actually-correct verified identity is the same durable Elo bridge
``fixture_sync_service._resolve_upcoming_team_id()`` uses on its fast path:
``ProviderEventMapping.evidence`` durably stores each side's
``home_provider_team_id``/``away_provider_team_id`` (written every sync tick,
independent of the canonical-identity system), and
``team_identity.resolve_provider_elo_team_id()`` resolves that provider id to
a real, same-league, Elo-bearing ``Team.id`` through the ``VERIFIED``
``ProviderEloTeamMapping`` bridge — no live provider call needed, and no
canonical-identity table involved. A side that has no durable ``VERIFIED``
binding yet cannot be safely reconciled without live data (the fuzzy
name-match path needs the freshest provider name), so a fixture is only
included when **both** sides resolve durably.
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
from ..db.models import MatchPredictionLog, ProviderEventMapping
from ..repositories.fixtures import SETTLED_MATCH_STATUSES
from .fixture_sync_service import is_unusable_team_name
from .team_identity import resolve_provider_elo_team_id

_MANIFEST_SCHEMA_VERSION = 3
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

    @property
    def stored_identity_unusable(self) -> bool:
        """True when the *stored* side carries a name no decode should produce.

        Production surfaced rows like `fd-team-la_liga:m??laga_cf` whose
        verified counterpart (`Málaga CF`) is clean and Elo-bearing. Those are
        the highest-value rebinds — the drift is not a genuine identity
        question, it is a lossy name that cost the fixture its history — so
        the manifest flags them rather than making an operator eyeball 49 rows.
        """
        return any(
            value is not None and is_unusable_team_name(value)
            for value in (
                self.stored_home_team_id,
                self.stored_home_team_name,
                self.stored_away_team_id,
                self.stored_away_team_name,
            )
        )

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["rebind_ready"] = self.rebind_ready
        payload["rebind_status"] = self.rebind_status
        payload["stored_identity_unusable"] = self.stored_identity_unusable
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
    """Compare persisted vs. durably-verified participant identity for live
    fixtures.

    Read-only: issues SELECT statements only, never stages or commits a write.
    A caller that wants transactional isolation from concurrent writers may
    wrap this in a rolled-back transaction the way
    ``data_authority.semantic_repair_review`` does for its sibling case; this
    function itself never mutates state either way.
    """
    stored_home = aliased(Team)
    stored_away = aliased(Team)

    statement = (
        select(Match, ProviderEventMapping, stored_home.name, stored_away.name)
        .join(
            ProviderEventMapping,
            (ProviderEventMapping.provider_event_id == Match.id)
            & (ProviderEventMapping.provider == _PROVIDER),
        )
        .outerjoin(stored_home, stored_home.id == Match.home_team_id)
        .outerjoin(stored_away, stored_away.id == Match.away_team_id)
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
    for match, mapping, stored_home_name, stored_away_name in rows:
        evidence = mapping.evidence or {}
        home_provider_id = evidence.get("home_provider_team_id")
        away_provider_id = evidence.get("away_provider_team_id")

        verified_home_id = (
            await resolve_provider_elo_team_id(
                provider=_PROVIDER,
                provider_team_id=home_provider_id,
                competition=match.league_id,
                db=session,
            )
            if home_provider_id
            else None
        )
        verified_away_id = (
            await resolve_provider_elo_team_id(
                provider=_PROVIDER,
                provider_team_id=away_provider_id,
                competition=match.league_id,
                db=session,
            )
            if away_provider_id
            else None
        )

        # Neither side can be safely reconciled without a live provider call
        # (the fuzzy name-match fallback needs the freshest display name) --
        # skip rather than guess. Fails toward silence, matching the
        # convention used throughout this codebase for absent evidence.
        if verified_home_id is None or verified_away_id is None:
            continue
        if (
            match.home_team_id == verified_home_id
            and match.away_team_id == verified_away_id
        ):
            continue

        verified_home_name = None
        verified_away_name = None
        if verified_home_id:
            team = await session.get(Team, verified_home_id)
            verified_home_name = team.name if team is not None else None
        if verified_away_id:
            team = await session.get(Team, verified_away_id)
            verified_away_name = team.name if team is not None else None

        blockers: list[str] = []
        if match.match_date is not None and match.match_date < now:
            blockers.append("KICKOFF_PASSED")
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
                verified_home_team_id=verified_home_id,
                verified_home_team_name=verified_home_name,
                verified_away_team_id=verified_away_id,
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
        "stored_identity_unusable_count": sum(
            1 for entry in entries if entry.stored_identity_unusable
        ),
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
