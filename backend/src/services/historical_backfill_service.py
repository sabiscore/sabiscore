"""Seed the matches table with real *completed* matches from football-data.co.uk CSVs.

Why this exists
---------------
``fixture_sync_service`` is forward-only: it seeds a 14-day window of SCHEDULED
fixtures, and ``sync_settled_results`` only ever UPDATEs a row that sync already
created. Nothing in the running API can create a *historical* finished match. On
a fresh database that leaves ``matches`` with zero ``status="finished"`` rows, so
``UpcomingMatchFeatureProjector._get_team_stats()`` returns ``None`` for both
sides of every fixture, which sets ``is_synthetic: true``, which sets
``publishable = False`` — i.e. **no prediction is ever published, for any fixture,
in any league** (measured in production 2026-08-08: ``feature_defaulted_ratio``
0.9077 on 5/5 fixtures, ``predictions: null`` on all of them).

The repository already carries the data to fix this: ``backend/data/cache/fd_*.csv``
holds full football-data.co.uk seasons with real scores. This module reads them and
upserts ``status="finished"`` Match rows keyed to the *same* Team ids that fixture
sync uses, so the two datasets join.

Team identity is the load-bearing part
--------------------------------------
football-data.co.uk uses short names ("Man United", "Ath Bilbao", "Inter") while
football-data.org — the provider fixture sync reads — uses legal names
("Manchester United FC", "Athletic Club", "FC Internazionale Milano"). Measured
against live production team rows, exact + affix-stripped matching alone joins only
23% of teams. This module therefore resolves in three stages (exact-normalised →
unique token-prefix → curated alias) and **always fails closed on ambiguity**.
Loose prefix matching is directional from the incoming football-data.co.uk name
toward a richer legal name, and single-token source names never prefix-match a
multi-token candidate. An unresolved team simply gets reduced evidence — never a
wrong join — and a final match-level invariant rejects any identity collision that
would otherwise make a club play itself.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..utils.season import canonical_season

logger = logging.getLogger(__name__)

# football-data.co.uk division code → (canonical SabiScore league_id, country).
# Closed set, deliberately mirroring fixture_sync_service._LEAGUE_META's canonical
# ids. A code outside this map is skipped, never guessed into a league.
_FD_CODE_TO_LEAGUE: Dict[str, Tuple[str, str]] = {
    "E0": ("EPL", "England"),
    "SP1": ("LA_LIGA", "Spain"),
    "D1": ("BUNDESLIGA", "Germany"),
    "I1": ("SERIE_A", "Italy"),
    "F1": ("LIGUE_1", "France"),
    "N1": ("EREDIVISIE", "Netherlands"),
}

# Column aliases. Three header dialects exist in-repo: raw football-data.co.uk
# ("Date"/"HomeTeam"/"FTHG"), and two normalised families already committed under
# backend/data/cache ("date"/"home_team"/"home_goals"). Only these five columns are
# needed — _get_team_stats() derives form purely from dates, team ids and scores.
_COLUMN_ALIASES: Dict[str, Tuple[str, ...]] = {
    "date": ("date", "Date"),
    "home_team": ("home_team", "HomeTeam"),
    "away_team": ("away_team", "AwayTeam"),
    "home_goals": ("home_goals", "FTHG"),
    "away_goals": ("away_goals", "FTAG"),
}

# Tokens carrying no identifying signal — legal forms, sponsor prefixes, particles.
# Stripped from both sides before comparison.
_NOISE_TOKENS = frozenset({
    "fc", "afc", "cf", "sc", "ac", "ca", "rc", "rcd", "ssc", "cfc", "us", "as",
    "ss", "ud", "sd", "cd", "bv", "sbv", "sv", "vv", "ogc", "aj", "es", "asc",
    "calcio", "balompie", "futbol", "fussball", "club", "de", "del", "der",
    "the", "and",
})

# Curated only for names the measured matcher cannot bridge safely — either a
# genuine short-form divergence or a prefix collision that must fail closed.
# Keys and values are both normalised token strings (see _normalise_key).
# Derived empirically from the 2026-08-08 production team list; extend only with
# a measured miss, never speculatively.
_TEAM_ALIASES: Dict[str, str] = {
    # Spain — "Ath" collides between Bilbao and Madrid.
    "athletic": "ath bilbao",
    "atletico madrid": "ath madrid",
    "espanyol barcelona": "espanol",
    "celta vigo": "celta",
    "rayo vallecano madrid": "vallecano",
    "real sociedad": "sociedad",
    "real betis": "betis",
    # Italy — "Milan" is a prefix of "Milano"; refuse the collision via alias.
    "internazionale milano": "inter",
    "milan": "milan",
    "napoli": "napoli",
    # England
    "nottingham forest": "nott'm forest",
    "wolverhampton wanderers": "wolves",
    "tottenham hotspur": "tottenham",
    "manchester united": "man united",
    "manchester city": "man city",
    # Netherlands
    "nec": "nijmegen",
    "psv": "psv eindhoven",
    "az": "az alkmaar",
    "fortuna sittard": "for sittard",
    "twente 65": "twente",
    # France
    "paris saint germain": "paris sg",
    "olympique marseille": "marseille",
    "olympique lyonnais": "lyon",
    "racing lens": "lens",
    "stade brestois": "brest",
}


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)
    )


def normalise_team_tokens(name: str) -> Tuple[str, ...]:
    """Reduce a club name to comparable identifying tokens.

    Lowercases, strips accents and punctuation, drops standalone year/number
    tokens ("Como 1907", "FC Twente '65", "Stade Brestois 29") and legal-form
    noise, preserving order.
    """
    text = _strip_accents(name).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\b\d{1,4}\b", " ", text)
    return tuple(tok for tok in text.split() if tok and tok not in _NOISE_TOKENS)


def _normalise_key(name: str) -> str:
    return " ".join(normalise_team_tokens(name))


# A token shorter than this may only match another token exactly. Without the
# floor, a 2-letter club token swallows a real word by prefix — "Le" (Le Mans FC)
# prefix-matches "Leeds", which made Leeds United ambiguous and silently cost it
# its entire match history. Three is the shortest length that still bridges the
# real abbreviations in use ("Man"→Manchester, "Ath"→Atlético, "For"→Fortuna).
_MIN_PREFIX_TOKEN_LEN = 3


def _token_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) < _MIN_PREFIX_TOKEN_LEN:
        return False
    return left.startswith(right) or right.startswith(left)


def _tokens_prefix_match(shorter: Sequence[str], longer: Sequence[str]) -> bool:
    """True when every source token prefix-matches a distinct candidate token.

    This helper is intentionally used in one direction by ``TeamIndex.resolve``:
    the incoming football-data.co.uk token set may abbreviate the provider legal
    name, but a shorter provider candidate must never consume a richer source
    identity. Single-token source names require exact/curated evidence before a
    multi-token candidate is accepted.
    """
    pool = list(longer)
    for token in shorter:
        hit: Optional[int] = None
        for index, candidate in enumerate(pool):
            if _token_compatible(candidate, token):
                hit = index
                break
        if hit is None:
            return False
        pool.pop(hit)
    return True


class TeamIndex:
    """Resolve football-data.co.uk short names to existing ``Team.id`` values.

    Built once from all known teams, then queried in-memory — ``team_identity.
    resolve_team_id()`` re-reads the whole teams table per call, which is fine for
    one fixture but not for ~26k historical team references.
    """

    def __init__(self, rows: Iterable[Tuple[str, str]]) -> None:
        self._by_key: Dict[str, str] = {}
        self._ambiguous_keys: set[str] = set()
        self._tokens: List[Tuple[Tuple[str, ...], str]] = []
        for team_id, team_name in rows:
            self.add(team_id, team_name)

    def add(self, team_id: str, team_name: str) -> None:
        key = _normalise_key(team_name)
        if not key:
            return
        self._register(key, team_id)
        # Register the football-data.co.uk spelling too, so a CSV lookup is a
        # direct hit rather than relying on the loose prefix stage.
        alias = _TEAM_ALIASES.get(key)
        if alias:
            self._register(_normalise_key(alias), team_id)
        self._tokens.append((tuple(key.split()), team_id))

    def _register(self, key: str, team_id: str) -> None:
        existing = self._by_key.get(key)
        if existing is None:
            self._by_key[key] = team_id
        elif existing != team_id:
            # Two distinct teams normalise identically — refuse both rather than
            # bind history to whichever was inserted first.
            self._ambiguous_keys.add(key)

    def resolve(self, name: str) -> Optional[str]:
        key = _normalise_key(name)
        if not key or key in self._ambiguous_keys:
            return None

        direct = self._by_key.get(key)
        if direct is not None:
            return direct

        aliased = _TEAM_ALIASES.get(key)
        if aliased:
            direct = self._by_key.get(_normalise_key(aliased))
            if direct is not None:
                return direct

        tokens = tuple(key.split())
        matches = {
            team_id
            for cand_tokens, team_id in self._tokens
            if len(tokens) <= len(cand_tokens)
            and not (len(tokens) == 1 and len(cand_tokens) > 1)
            and _tokens_prefix_match(tokens, cand_tokens)
        }
        if len(matches) == 1:
            return next(iter(matches))
        return None  # zero matches, or ambiguous — fail closed either way


def historical_match_id(league_id: str, match_date: datetime, home: str, away: str) -> str:
    """Deterministic id so re-running the backfill is a no-op, not a duplicate.

    Namespaced ``fdco-`` to stay distinct from fixture sync's ``fd-<providerId>``.
    """
    payload = "|".join(
        [league_id, match_date.strftime("%Y-%m-%d"), _normalise_key(home), _normalise_key(away)]
    )
    return f"fdco-{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]}"


def _parse_date(raw: str) -> Optional[datetime]:
    """Accept the ISO form used by the committed files and the provider's own
    ``DD/MM/YYYY`` / ``DD/MM/YY``. Returned naive-UTC, matching the
    ``Match.match_date`` column convention (TIMESTAMP WITHOUT TIME ZONE)."""
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _column(row: Dict[str, str], field_name: str) -> str:
    for alias in _COLUMN_ALIASES[field_name]:
        value = row.get(alias)
        if value not in (None, ""):
            return str(value)
    return ""


@dataclass(frozen=True)
class HistoricalMatch:
    league_id: str
    match_date: datetime
    home_team: str
    away_team: str
    home_score: int
    away_score: int

    @property
    def match_id(self) -> str:
        return historical_match_id(
            self.league_id, self.match_date, self.home_team, self.away_team
        )


def parse_fd_csv(path: Path) -> List[HistoricalMatch]:
    """Parse one football-data.co.uk season file. Malformed rows are skipped, not fatal."""
    stem = path.stem  # fd_E0_2425
    parts = stem.split("_")
    if len(parts) < 2:
        return []
    meta = _FD_CODE_TO_LEAGUE.get(parts[1])
    if meta is None:
        return []
    league_id = meta[0]

    out: List[HistoricalMatch] = []
    # utf-8-sig: the provider ships a BOM on the Div column.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            match_date = _parse_date(_column(row, "date"))
            home = _column(row, "home_team").strip()
            away = _column(row, "away_team").strip()
            raw_home_goals = _column(row, "home_goals")
            raw_away_goals = _column(row, "away_goals")
            if not (match_date and home and away and raw_home_goals and raw_away_goals):
                continue
            try:
                home_score = int(float(raw_home_goals))
                away_score = int(float(raw_away_goals))
            except (TypeError, ValueError):
                continue
            out.append(
                HistoricalMatch(
                    league_id=league_id,
                    match_date=match_date,
                    home_team=home,
                    away_team=away,
                    home_score=home_score,
                    away_score=away_score,
                )
            )
    return out


def default_cache_dir() -> Path:
    """``backend/data/cache`` — resolved from this file, not the CWD, so it works
    identically under uvicorn on Render and from a CLI run in any directory."""
    return Path(__file__).resolve().parents[2] / "data" / "cache"


@dataclass
class BackfillReport:
    files_read: int = 0
    rows_parsed: int = 0
    matches_inserted: int = 0
    matches_existing: int = 0
    teams_created: int = 0
    teams_resolved: int = 0
    skipped_unparseable: int = 0
    identity_conflicts_skipped: int = 0
    leagues: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, object]:
        return {
            "files_read": self.files_read,
            "rows_parsed": self.rows_parsed,
            "matches_inserted": self.matches_inserted,
            "matches_existing": self.matches_existing,
            "teams_created": self.teams_created,
            "teams_resolved": self.teams_resolved,
            "skipped_unparseable": self.skipped_unparseable,
            "identity_conflicts_skipped": self.identity_conflicts_skipped,
            "leagues": dict(self.leagues),
        }


def _historical_team_id(team_name: str, league_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _normalise_key(team_name)).strip("_")
    return f"fdco-team-{league_id.lower()}-{slug or 'unknown'}"


async def backfill_historical_matches(
    session: AsyncSession,
    *,
    cache_dir: Optional[Path] = None,
) -> BackfillReport:
    """Upsert finished matches from every ``fd_*.csv`` in ``cache_dir``.

    Idempotent by construction: match ids are deterministic and existing ids are
    loaded once up front, so a partial previous run completes rather than
    duplicating. Safe to call on every boot.
    """
    from ..core.database import League, Match, Team

    directory = cache_dir or default_cache_dir()
    report = BackfillReport()
    if not directory.is_dir():
        logger.warning("historical_backfill: cache dir %s not found — nothing to do", directory)
        return report

    parsed: List[HistoricalMatch] = []
    for path in sorted(directory.glob("fd_*.csv")):
        try:
            rows = parse_fd_csv(path)
        except Exception:
            logger.exception("historical_backfill: failed to parse %s", path.name)
            report.skipped_unparseable += 1
            continue
        report.files_read += 1
        parsed.extend(rows)
    report.rows_parsed = len(parsed)
    if not parsed:
        return report

    # Leagues first — Team and Match both carry an FK to it.
    needed_leagues = {m.league_id for m in parsed}
    for league_id in sorted(needed_leagues):
        if not await session.get(League, league_id):
            country = next(
                (c for code, (lid, c) in _FD_CODE_TO_LEAGUE.items() if lid == league_id), None
            )
            session.add(League(id=league_id, name=league_id.replace("_", " ").title(), country=country))
    await session.flush()

    index = TeamIndex((await session.execute(select(Team.id, Team.name))).all())

    # Resolve every distinct (league, name) once rather than per row.
    distinct_teams = {(m.league_id, name) for m in parsed for name in (m.home_team, m.away_team)}
    team_ids: Dict[Tuple[str, str], str] = {}
    for league_id, name in sorted(distinct_teams):
        resolved = index.resolve(name)
        if resolved is not None:
            team_ids[(league_id, name)] = resolved
            report.teams_resolved += 1
            continue
        new_id = _historical_team_id(name, league_id)
        if not await session.get(Team, new_id):
            session.add(Team(id=new_id, name=name, league_id=league_id))
            report.teams_created += 1
        team_ids[(league_id, name)] = new_id
        index.add(new_id, name)
    await session.flush()

    existing_ids = set(
        (
            await session.execute(
                select(Match.id).where(Match.id.in_([m.match_id for m in parsed]))
            )
        )
        .scalars()
        .all()
    )

    for item in parsed:
        match_id = item.match_id
        if match_id in existing_ids:
            report.matches_existing += 1
            continue

        home_team_id = team_ids[(item.league_id, item.home_team)]
        away_team_id = team_ids[(item.league_id, item.away_team)]
        if home_team_id == away_team_id:
            report.identity_conflicts_skipped += 1
            logger.warning(
                "historical_backfill: refusing identity collision for %s: %r vs %r -> %s",
                match_id,
                item.home_team,
                item.away_team,
                home_team_id,
            )
            continue

        existing_ids.add(match_id)  # guard against duplicate rows within the CSVs
        session.add(
            Match(
                id=match_id,
                league_id=item.league_id,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                match_date=item.match_date,
                season=canonical_season(item.match_date),
                status="finished",
                home_score=item.home_score,
                away_score=item.away_score,
            )
        )
        report.matches_inserted += 1
        report.leagues[item.league_id] = report.leagues.get(item.league_id, 0) + 1

    await session.commit()
    return report


async def count_finished_matches(session: AsyncSession) -> int:
    from ..core.database import Match

    result = await session.execute(
        select(func.count()).select_from(Match).where(Match.status == "finished")
    )
    return int(result.scalar() or 0)


async def run_historical_backfill() -> Optional[BackfillReport]:
    """Entry point for the startup background task and the CLI.

    Owns its own session, and swallows its own failures — history is an
    enrichment: the API must still serve (fail-closed, reduced-evidence) if this
    cannot run. Failures are recorded in metrics so they are not silent, matching
    ``run_fixture_sync``'s convention.
    """
    from ..db.session import AsyncSessionLocal
    from ..monitoring.metrics import metrics_collector

    if AsyncSessionLocal is None:
        logger.warning("historical_backfill: DB not ready, skipping")
        return None

    try:
        async with AsyncSessionLocal() as session:
            report = await backfill_historical_matches(session)
    except Exception as exc:  # pragma: no cover - defensive, mirrors run_fixture_sync
        logger.exception("historical_backfill: unhandled error — continuing without history")
        metrics_collector.increment("historical_backfill.failures")
        metrics_collector.record_error(
            error_type=type(exc).__name__,
            message=str(exc),
            context={"task": "historical_backfill"},
        )
        return None

    if report.matches_inserted:
        logger.info(
            "historical_backfill: inserted %d matches (%d already present) from %d files; "
            "teams resolved=%d created=%d; per-league=%s",
            report.matches_inserted,
            report.matches_existing,
            report.files_read,
            report.teams_resolved,
            report.teams_created,
            report.leagues,
        )
    else:
        logger.info(
            "historical_backfill: no new matches (%d already present, %d files)",
            report.matches_existing,
            report.files_read,
        )
    return report