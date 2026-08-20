"""Fail-closed team identity resolution shared by serving and fixture sync.

Live provider names and historical dataset names are not the same identity
contract. Fixture sync therefore resolves in this order:

1. durable provider-ID -> Elo-Team mapping when one already exists;
2. league-scoped deterministic historical-name reconciliation;
3. the existing high-confidence fuzzy matcher (threshold unchanged);
4. caller-owned unresolved fallback.

The resolver never treats a neutral/default Elo value as identity evidence.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Team
from ..db.models import EloRatingSnapshot
from ..db.provider_elo_team_mapping import ProviderEloTeamMapping
from ..providers.reconciliation import TeamCandidate, reconcile_team

_CLUB_AFFIXES = re.compile(r"^(afc|cf|1\.)\s+|\s+(fc|afc|cf|sc)$", flags=re.IGNORECASE)
_LEGAL_TEAM_TOKENS = {
    "ac",
    "acf",
    "afc",
    "as",
    "bc",
    "ca",
    "cf",
    "fc",
    "fsv",
    "osc",
    "rc",
    "sc",
    "sco",
    "ss",
    "ssc",
    "stade",
    "ud",
    "us",
    "vfb",
}

# Explicit, league-scoped aliases established from production identity evidence.
# These are identity assertions, not fuzzy-threshold exceptions. Once the real
# upstream provider team ID is observed, ProviderEloTeamMapping becomes the
# durable anchor and the alias is no longer needed for subsequent syncs.
_AUDITED_ALIASES: dict[tuple[str, str], str] = {
    ("BUNDESLIGA", "bayern munchen"): "bayern munich",
    ("BUNDESLIGA", "borussia monchengladbach"): "m gladbach",
    ("EPL", "manchester city"): "man city",
    ("LIGUE_1", "rennais"): "rennes",
}


def _strip_affixes(name: str) -> str:
    stripped = _CLUB_AFFIXES.sub("", name.strip()).strip()
    return stripped or name.strip()


def _ascii_text(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def _identity_key(name: str) -> str:
    """Normalize legal-name decoration without guessing nicknames.

    Only bounded club-designator/founding-number tokens are removed. Semantic
    words such as ``United`` or ``City`` remain part of the identity key.
    """
    tokens = re.findall(r"[a-z0-9]+", _ascii_text(name).lower().replace("&", " "))
    while tokens and (tokens[0] in _LEGAL_TEAM_TOKENS or tokens[0].isdigit()):
        tokens.pop(0)
    while tokens and (
        tokens[-1] in _LEGAL_TEAM_TOKENS
        or (tokens[-1].isdigit() and len(tokens[-1]) <= 4)
    ):
        tokens.pop()
    return " ".join(tokens)


def _unique_match(rows: list[tuple[str, str]], predicate: Any) -> str | None:
    matches = [row_id for row_id, row_name in rows if predicate(row_name)]
    return matches[0] if len(matches) == 1 else None


async def _candidate_rows(
    db: AsyncSession,
    *,
    league_id: str | None,
    require_elo_history: bool,
) -> list[tuple[str, str]]:
    statement = select(Team.id, Team.name)
    if league_id:
        statement = statement.where(Team.league_id == league_id)
    if require_elo_history:
        statement = statement.join(
            EloRatingSnapshot,
            EloRatingSnapshot.team_id == Team.id,
        )
        if league_id:
            statement = statement.where(EloRatingSnapshot.league == league_id)
        statement = statement.distinct()
    return [(str(row_id), str(row_name)) for row_id, row_name in (await db.execute(statement)).all()]


async def resolve_provider_elo_team_id(
    *,
    provider: str,
    provider_team_id: str | int | None,
    competition: str,
    db: AsyncSession,
) -> str | None:
    """Resolve a real provider team ID through an already-verified Elo bridge."""
    normalized_id = str(provider_team_id or "").strip()
    if not provider or not normalized_id or not competition:
        return None

    row = (
        await db.execute(
            select(ProviderEloTeamMapping).where(
                ProviderEloTeamMapping.provider == provider,
                ProviderEloTeamMapping.provider_team_id == normalized_id,
                ProviderEloTeamMapping.competition == competition,
                ProviderEloTeamMapping.reconciliation_status == "VERIFIED",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    team = await db.get(Team, row.team_id)
    if team is None or team.league_id != competition:
        return None

    has_history = bool(
        await db.scalar(
            select(EloRatingSnapshot.id)
            .where(
                EloRatingSnapshot.team_id == row.team_id,
                EloRatingSnapshot.league == competition,
            )
            .limit(1)
        )
    )
    return row.team_id if has_history else None


async def bind_provider_elo_team_id(
    *,
    provider: str,
    provider_team_id: str | int | None,
    provider_team_name: str,
    competition: str,
    team_id: str,
    db: AsyncSession,
    evidence: dict[str, object] | None = None,
) -> bool:
    """Persist an auditable provider-ID -> historical Elo Team assertion.

    The target must already have a real Elo snapshot in the same competition.
    Existing conflicting mappings fail closed rather than being overwritten.
    """
    normalized_id = str(provider_team_id or "").strip()
    if not provider or not normalized_id or not provider_team_name.strip() or not competition:
        return False

    team = await db.get(Team, team_id)
    if team is None or team.league_id != competition:
        raise ValueError("provider Elo mapping target is missing or in another competition")

    has_history = bool(
        await db.scalar(
            select(EloRatingSnapshot.id)
            .where(
                EloRatingSnapshot.team_id == team_id,
                EloRatingSnapshot.league == competition,
            )
            .limit(1)
        )
    )
    if not has_history:
        return False

    mapping = (
        await db.execute(
            select(ProviderEloTeamMapping).where(
                ProviderEloTeamMapping.provider == provider,
                ProviderEloTeamMapping.provider_team_id == normalized_id,
                ProviderEloTeamMapping.competition == competition,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    safe_evidence = dict(evidence or {})
    safe_evidence["identity_basis"] = "real_durable_elo_history"

    if mapping is None:
        db.add(
            ProviderEloTeamMapping(
                provider=provider,
                provider_team_id=normalized_id,
                provider_team_name=provider_team_name.strip(),
                competition=competition,
                team_id=team_id,
                reconciliation_status="VERIFIED",
                reconciliation_confidence=1.0,
                evidence=safe_evidence,
                checked_at=now,
            )
        )
        return True

    if mapping.team_id != team_id:
        raise ValueError("provider team ID conflicts with an existing Elo team mapping")
    mapping.provider_team_name = provider_team_name.strip()
    mapping.reconciliation_status = "VERIFIED"
    mapping.reconciliation_confidence = 1.0
    mapping.evidence = safe_evidence
    mapping.checked_at = now
    return True


async def resolve_team_id(
    name: str,
    db: AsyncSession,
    *,
    league_id: str | None = None,
    require_elo_history: bool = False,
) -> str | None:
    """Resolve a supplied team name to ``Team.id`` or fail closed.

    ``require_elo_history`` is used by upcoming fixture sync so a previously
    generated zero-history duplicate cannot mask the historical Elo identity.
    The fuzzy auto-accept threshold remains the repository-wide 0.94.
    """
    name = name.strip()
    if not name:
        return None

    rows = await _candidate_rows(
        db,
        league_id=league_id,
        require_elo_history=require_elo_history,
    )
    if not rows:
        return None

    lname = name.lower()
    exact = _unique_match(rows, lambda row_name: row_name.lower() == lname)
    if exact:
        return exact

    normalized_affix = _strip_affixes(name).lower()
    affix = _unique_match(
        rows,
        lambda row_name: _strip_affixes(row_name).lower() == normalized_affix,
    )
    if affix:
        return affix

    identity_key = _identity_key(name)
    if identity_key:
        deterministic = _unique_match(rows, lambda row_name: _identity_key(row_name) == identity_key)
        if deterministic:
            return deterministic

        # Safe containment handles long official names such as
        # ``Brighton & Hove Albion FC`` vs historical ``Brighton``. Ambiguity
        # remains fail-closed because exactly one candidate must match.
        if len(identity_key) >= 5:
            contained = _unique_match(
                rows,
                lambda row_name: (
                    len(_identity_key(row_name)) >= 5
                    and (
                        f" {identity_key} " in f" {_identity_key(row_name)} "
                        or f" {_identity_key(row_name)} " in f" {identity_key} "
                    )
                ),
            )
            if contained:
                return contained

        if league_id:
            alias_target = _AUDITED_ALIASES.get((league_id, identity_key))
            if alias_target:
                aliased = _unique_match(rows, lambda row_name: _identity_key(row_name) == alias_target)
                if aliased:
                    return aliased

    candidates = [TeamCandidate(team_id=row_id, name=row_name) for row_id, row_name in rows]
    decision = reconcile_team(name, candidates)
    if decision.status == "VERIFIED" and decision.team_id:
        return decision.team_id
    return None


__all__ = [
    "bind_provider_elo_team_id",
    "resolve_provider_elo_team_id",
    "resolve_team_id",
]
