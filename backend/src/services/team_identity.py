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
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Team
from ..db.models import EloRatingSnapshot
from ..db.provider_elo_team_mapping import ProviderEloTeamMapping
from ..providers.reconciliation import TeamCandidate, reconcile_team

T = TypeVar("T")

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

# Spelled-out club designators, stripped from the end of a name only.
_TRAILING_CLUB_WORDS = {"club", "football", "soccer"}

# Explicit, league-scoped aliases established from production identity evidence.
# These are identity assertions, not fuzzy-threshold exceptions. Once the real
# upstream provider team ID is observed, ProviderEloTeamMapping becomes the
# durable anchor and the alias is no longer needed for subsequent syncs.
_AUDITED_ALIASES: dict[tuple[str, str], str] = {
    ("BUNDESLIGA", "bayern munchen"): "bayern munich",
    ("BUNDESLIGA", "borussia monchengladbach"): "m gladbach",
    # The historical Elo corpus (backend/data/cache/fd_D1_*.csv, football-data.co.uk)
    # abbreviates these two, so the live provider's full legal name reaches
    # reconcile_team() at 0.81 / 0.74 -- REQUIRES_REVIEW, correctly below the
    # 0.94 auto-accept threshold. Both corpus spellings were read out of the
    # committed CSVs across all seven seasons before being asserted here.
    ("BUNDESLIGA", "eintracht frankfurt"): "ein frankfurt",
    ("BUNDESLIGA", "hamburger sv"): "hamburg",
    # 12 entries below (interspersed by league to match this dict's existing
    # grouping), from docs/DEBT.md item 56 Finding 7: a real review run of
    # the full tracked Understat corpus against sabiscore-db-v3 on
    # 2026-09-03 found these were the ENTIRE set of TEAM_UNRESOLVED
    # (league, name) pairs across all 12,459 rows, accounting for all 2,532
    # unresolved rows. Each target was confirmed present with substantial
    # real match/Elo history (138-520 rows) via read-only production SQL
    # before being asserted; none is a guess.
    ("BUNDESLIGA", "rasenballsport leipzig"): "rb leipzig",
    ("BUNDESLIGA", "cologne"): "koln",  # Understat anglicizes; the corpus row is German-transliterated
    ("EPL", "manchester city"): "man city",
    # Same shape as Manchester City below: fdco-team-epl-newcastle carries 268
    # real matches / 267 Elo rows; fd-team-epl:newcastle_united_fc is a
    # near-orphaned duplicate with exactly 1 of each. Understat's corpus
    # writes the full "Newcastle United", which affix-strips to an exact
    # match against the near-orphan's "Newcastle United FC" before this
    # alias stage used to run. Verified against sabiscore-db-v3 2026-09-03.
    ("EPL", "newcastle united"): "newcastle",
    ("EPL", "wolverhampton wanderers"): "wolves",
    ("EPL", "west bromwich albion"): "west brom",
    ("LA_LIGA", "celta vigo"): "celta de vigo",  # "de" breaks containment's contiguous-substring check
    ("LA_LIGA", "atletico madrid"): "club atletico de madrid",  # same "de"-in-the-middle shape
    ("LIGUE_1", "rennais"): "rennes",
    # Paris FC and Paris SG are two genuinely different clubs that both appear
    # in the Ligue 1 corpus. `_identity_key` reduces "Paris FC" to the bare
    # place name "paris", which the containment heuristic below then finds
    # inside "paris sg" -- silently merging PSG's entire history into the
    # Paris FC row. Confirmed in production: `fd-team-ligue_1:paris_fc` held
    # 276 Elo snapshots spanning 2019/2020 onward, including results
    # (3-0 Nimes, 4-0 Toulouse, 1-0 at Lyon in Aug/Sep 2019) that are PSG's,
    # in seasons when Paris FC was in Ligue 2. Asserting the identity here is
    # what stops the heuristic from guessing. See docs/DEBT.md item 40.
    ("LIGUE_1", "paris sg"): "paris saint germain",
    ("LIGUE_1", "lyon"): "olympique lyonnais",
    ("LIGUE_1", "brest"): "brestois",
    ("LIGUE_1", "nice"): "ogc nice",
    ("LIGUE_1", "lens"): "racing club de lens",
    ("LIGUE_1", "saint etienne"): "st etienne",
    ("SERIE_A", "inter"): "internazionale milano",
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


def _collapse_letter_runs(tokens: list[str]) -> list[str]:
    """Rejoin single-letter runs so dotted abbreviations read as one token.

    ``Chelsea F.C.`` and ``C.F. Monterrey`` tokenize to ``["chelsea","f","c"]``
    and ``["c","f","monterrey"]``. Without this, the designator never matches
    ``_LEGAL_TEAM_TOKENS`` and survives into the identity key, so the dotted
    spelling fails to match the same club written ``Chelsea FC``.
    """
    collapsed: list[str] = []
    run: list[str] = []
    for token in tokens:
        if len(token) == 1 and token.isalpha():
            run.append(token)
            continue
        if run:
            collapsed.append("".join(run) if len(run) > 1 else run[0])
            run = []
        collapsed.append(token)
    if run:
        collapsed.append("".join(run) if len(run) > 1 else run[0])
    return collapsed


def _identity_key(name: str) -> str:
    """Normalize legal-name decoration without guessing nicknames.

    Only bounded club-designator/founding-number tokens are removed. Semantic
    words such as ``United`` or ``City`` remain part of the identity key.
    """
    tokens = _collapse_letter_runs(
        re.findall(r"[a-z0-9]+", _ascii_text(name).lower().replace("&", " "))
    )
    while tokens and (tokens[0] in _LEGAL_TEAM_TOKENS or tokens[0].isdigit()):
        tokens.pop(0)
    # Spelled-out designators are trailing decoration only. Leading ``Club`` is
    # deliberately preserved: it is a real name component in ``Club Atletico de
    # Madrid`` and ``Club Brugge``, whereas a trailing ``Football Club`` never is.
    while len(tokens) > 1 and tokens[-1] in _TRAILING_CLUB_WORDS:
        tokens.pop()
    while tokens and (
        tokens[-1] in _LEGAL_TEAM_TOKENS
        or (tokens[-1].isdigit() and len(tokens[-1]) <= 4)
    ):
        tokens.pop()
    return " ".join(tokens)


# Market-scoped identity assertions: live betting-market provider names vs the
# ``Team.name`` values fixture sync persists. These are deliberately SEPARATE
# from ``_AUDITED_ALIASES`` because the two tables point in opposite directions.
# ``_AUDITED_ALIASES`` maps a provider legal name onto the shorter historical
# Elo-corpus spelling ("Olympique Lyonnais" would need to become "Lyon"); the
# market matcher needs the reverse ("Lyon" -> "Olympique Lyonnais"). Merging
# them would make ``resolve_team_id`` fail closed on corpus rows it currently
# resolves, because an alias that names an absent target returns unresolved.
#
# Each entry was established by observing a real provider board against the
# live fixture list: same competition, same kickoff, with the OTHER side of the
# same fixture already matching, which determines the club uniquely.
_MARKET_ALIASES: dict[tuple[str, str], str] = {
    ("LIGUE_1", "lyon"): "olympique lyonnais",
    ("LIGUE_1", "brest"): "brestois",
    ("SERIE_A", "inter milan"): "internazionale milano",
}


def identity_key(name: str) -> str:
    """Public normalizer shared by identity resolution and market matching."""
    return _identity_key(name)


def market_identity_key(name: str, league: str) -> str:
    """Identity key with league-scoped alias folding, applied symmetrically.

    Both the provider name and the stored fixture name go through this, so an
    alias collapses the two spellings onto one representative regardless of
    which side happens to carry the decorated form.
    """
    key = _identity_key(name)
    return _MARKET_ALIASES.get((league, key)) or _AUDITED_ALIASES.get((league, key)) or key


def _keys_equivalent(left: str, right: str) -> bool:
    """Exact match, or one name's tokens fully contained in the other's.

    Providers publish short trade names ("Udinese", "Strasbourg") where fixture
    sync stores full legal names ("Udinese Calcio", "RC Strasbourg Alsace").
    Subset rather than substring because the legal form frequently inserts
    tokens: ``celta vigo`` vs ``celta de vigo``.

    This is deliberately permissive and is ONLY usable behind the staged
    uniqueness guard in ``select_unique_by_team_names``. Two clubs sharing a
    place name (Paris FC / Paris SG) both satisfy it, so the exact stage runs
    first and any residual tie fails closed as ambiguous.

    ⚠️ Residual exposure, stated plainly: if the genuinely-correct fixture is
    absent from the candidate set, a bare place name can still be the sole
    subset match for a larger club and be accepted. Three independent
    constraints bound that -- same competition, kickoff within
    ``_KICKOFF_MATCH_TOLERANCE_MINUTES``, and BOTH sides matching -- and a
    known cross-vocabulary pair belongs in ``_MARKET_ALIASES`` so the exact
    stage resolves it before this one is ever reached.
    """
    if left == right:
        return True
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return False
    return left_tokens <= right_tokens or right_tokens <= left_tokens


def select_unique_by_team_names(
    candidates: Sequence[T],
    *,
    home: str,
    away: str,
    league: str,
    names: Callable[[T], tuple[str, str]],
) -> tuple[T | None, bool]:
    """Resolve one fixture from ``candidates`` by home/away name, or fail closed.

    Returns ``(match, ambiguous)``. Exact keys are tried across the whole
    candidate set before the permissive stage, so a club whose short name is
    contained in a different club's name (Paris FC inside Paris Saint-Germain)
    is resolved by its own exact key and never reaches the loose comparison.
    """
    home_key = market_identity_key(home, league)
    away_key = market_identity_key(away, league)
    if not home_key or not away_key:
        return None, False

    keyed = [
        (market_identity_key(pair[0], league), market_identity_key(pair[1], league), candidate)
        for candidate in candidates
        for pair in (names(candidate),)
    ]

    for predicate in (
        lambda h, a: h == home_key and a == away_key,
        lambda h, a: _keys_equivalent(h, home_key) and _keys_equivalent(a, away_key),
    ):
        matches = [candidate for h, a, candidate in keyed if predicate(h, a)]
        if len(matches) == 1:
            return matches[0], False
        if len(matches) > 1:
            return None, True
    return None, False


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

    identity_key = _identity_key(name)

    # An audited alias is an explicit human identity assertion, so it must
    # outrank every heuristic below it -- including affix-stripping, not only
    # containment. This ordering is load-bearing, not cosmetic: production
    # carries a near-orphaned duplicate Team row for several clubs (e.g.
    # "Manchester City FC" / "Newcastle United FC", each with 1-2 real
    # matches) alongside the real historical row ("Man City" / "Newcastle",
    # 267+ matches). Affix-stripping the full legal name lands on an EXACT
    # match against the near-orphan's decorated spelling -- "Manchester City
    # FC" strips to "Manchester City", "Newcastle United FC" strips to
    # "Newcastle United" -- so the affix stage used to resolve to the
    # near-orphan before this alias was ever consulted. Checking the alias
    # immediately after the true-exact stage (and before affix-stripping)
    # closes that window. Verified against sabiscore-db-v3 2026-09-03.
    #
    # "Paris SG" reduces to `paris sg`, which contains the bare place name
    # `paris` that "Paris FC" reduces to, so containment would otherwise
    # resolve PSG to a different real club before the alias was ever
    # consulted. Verified by reverting only this block, with the alias left
    # in place: the Paris regression test goes red.
    #
    # An alias that names a target we cannot find fails CLOSED rather than
    # falling through: the assertion says this name means one specific
    # club, so when that club is absent the honest answer is "unresolved",
    # never "let the next heuristic guess".
    if identity_key and league_id and (league_id, identity_key) in _AUDITED_ALIASES:
        alias_target = _AUDITED_ALIASES[(league_id, identity_key)]
        return _unique_match(rows, lambda row_name: _identity_key(row_name) == alias_target)

    normalized_affix = _strip_affixes(name).lower()
    affix = _unique_match(
        rows,
        lambda row_name: _strip_affixes(row_name).lower() == normalized_affix,
    )
    if affix:
        return affix

    if identity_key:
        deterministic = _unique_match(rows, lambda row_name: _identity_key(row_name) == identity_key)
        if deterministic:
            return deterministic

        # Safe containment handles long official names such as
        # ``Brighton & Hove Albion FC`` vs historical ``Brighton``. Ambiguity
        # remains fail-closed because exactly one candidate must match.
        #
        # ⚠️ Uniqueness does NOT make this safe on its own. Two distinct clubs
        # sharing a place name (Paris FC / Paris SG) produce exactly one
        # containment match and are still merged. Every such corpus pair must
        # be disambiguated by an audited alias above -- enforced by
        # ``test_team_identity_containment_collisions.py``, which fails if the
        # committed corpora ever introduce an uncovered collision.
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

    candidates = [TeamCandidate(team_id=row_id, name=row_name) for row_id, row_name in rows]
    decision = reconcile_team(name, candidates)
    if decision.status == "VERIFIED" and decision.team_id:
        return decision.team_id
    return None


__all__ = [
    "bind_provider_elo_team_id",
    "identity_key",
    "market_identity_key",
    "select_unique_by_team_names",
    "resolve_provider_elo_team_id",
    "resolve_team_id",
]
