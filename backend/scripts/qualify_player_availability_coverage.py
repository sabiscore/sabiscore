"""Portfolio B Phase 3 — player-availability historical coverage measurement.

Directive: `docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md` §22 (Player Availability
Research Programme), Phase 3 (Data Qualification). `docs/DEBT.md` item 65's
live probe proved `api_football.injuries(competition=EPL, season=2024)`
returns 3,168 real, coherent records with a usable `fixture.date`. This
script answers the question that single-league probe could not: **across
every league this platform actually trains on, and every plan-permitted
season, what fraction of those records can be joined to a real historical
fixture** — Gate G1 (fixture coverage) and G4 (cross-league portability),
measured, not assumed from one league.

Design, mirroring `qualify_venue_locations.py`'s established pattern for
exactly this kind of question:

* **The corpus is `backend/data/cache/fd_*.csv`** — the same 12,765-match
  archive the production models train on, loaded directly, no database
  connection (this environment has none reachable; `services/team_identity`
  is deliberately NOT imported here because it pulls in `core/database`,
  which opens a connection at import time per `docs/DEBT.md` item 7 — the
  identity-key algorithm and the already-audited alias tables are inlined
  instead, verbatim, so this script uses the same canonical keys as
  production without triggering that import).
* **Two independent checks, not one.** A team name can resolve while the
  date does not (wrong-season contamination) and a date can exist while the
  team does not (misspelled/unmapped club) — collapsing them into one
  pass/fail would hide which failure mode actually dominates.
* **No alias is invented here.** A team that fails to resolve is reported
  by name in the manifest for human review, exactly like Portfolio F's
  unresolved venues — never silently matched by best-guess proximity.
* **UCL is out of scope, explicitly, not by omission.** football-data.co.uk
  publishes domestic leagues only; there is no local corpus file to
  crosswalk a Champions League fixture against.

Live network calls: up to 18 (6 leagues x 3 seasons); the current-season
query is deliberately NOT repeated here (already answered: blocked outright
on this subscription, docs/DEBT.md item 65).

Usage
-----
    cd backend
    PYTHONPATH=. python scripts/qualify_player_availability_coverage.py
"""

from __future__ import annotations

import asyncio
import glob
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import httpx  # noqa: E402

from src.core.config import settings  # noqa: E402
from src.providers.api_football import APIFootballProvider  # noqa: E402

_CACHE_DIR = _BACKEND_ROOT / "data" / "cache"
_REPORT_DIR = _BACKEND_ROOT.parent / "reports" / "research"

# api_football league key -> football-data.co.uk division code.
# UCL has no domestic-league corpus file and is intentionally absent.
_LEAGUE_TO_DIVISION: dict[str, str] = {
    "EPL": "E0",
    "LA_LIGA": "SP1",
    "SERIE_A": "I1",
    "BUNDESLIGA": "D1",
    "LIGUE_1": "F1",
    "EREDIVISIE": "N1",
}

# api_football season (year the season starts) -> fd.co.uk file suffix.
_SEASONS: dict[int, str] = {2022: "2223", 2023: "2324", 2024: "2425"}

# ---------------------------------------------------------------------------
# Identity normalization — inlined from services/team_identity.py verbatim.
# NOT imported: that module pulls in core/database, which opens a live
# connection at import time (docs/DEBT.md item 7), and this script must run
# with no database reachable. Keeping the algorithm and the already-audited
# alias tables identical to production is what makes this crosswalk trustworthy;
# a re-derived normalizer would silently diverge from what fixture sync uses.
# ---------------------------------------------------------------------------

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
_TRAILING_CLUB_WORDS = {"club", "football", "soccer"}

_AUDITED_ALIASES: dict[tuple[str, str], str] = {
    ("BUNDESLIGA", "bayern munchen"): "bayern munich",
    ("BUNDESLIGA", "borussia monchengladbach"): "m gladbach",
    ("BUNDESLIGA", "eintracht frankfurt"): "ein frankfurt",
    ("BUNDESLIGA", "hamburger sv"): "hamburg",
    ("BUNDESLIGA", "rasenballsport leipzig"): "rb leipzig",
    ("BUNDESLIGA", "cologne"): "koln",
    ("EPL", "manchester city"): "man city",
    ("EPL", "newcastle united"): "newcastle",
    ("EPL", "wolverhampton wanderers"): "wolves",
    ("EPL", "west bromwich albion"): "west brom",
    ("LA_LIGA", "celta vigo"): "celta de vigo",
    ("LA_LIGA", "atletico madrid"): "club atletico de madrid",
    ("LIGUE_1", "rennais"): "rennes",
    ("LIGUE_1", "paris sg"): "paris saint germain",
    ("LIGUE_1", "lyon"): "olympique lyonnais",
    ("LIGUE_1", "brest"): "brestois",
    ("LIGUE_1", "nice"): "ogc nice",
    ("LIGUE_1", "lens"): "racing club de lens",
    ("LIGUE_1", "saint etienne"): "st etienne",
    ("SERIE_A", "inter"): "internazionale milano",
}
_MARKET_ALIASES: dict[tuple[str, str], str] = {
    ("LIGUE_1", "lyon"): "olympique lyonnais",
    ("LIGUE_1", "brest"): "brestois",
    ("SERIE_A", "inter milan"): "internazionale milano",
}


def _ascii_text(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
    )


def _collapse_letter_runs(tokens: list[str]) -> list[str]:
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
    tokens = _collapse_letter_runs(
        re.findall(r"[a-z0-9]+", _ascii_text(name).lower().replace("&", " "))
    )
    while tokens and (tokens[0] in _LEGAL_TEAM_TOKENS or tokens[0].isdigit()):
        tokens.pop(0)
    while len(tokens) > 1 and tokens[-1] in _TRAILING_CLUB_WORDS:
        tokens.pop()
    while tokens and (
        tokens[-1] in _LEGAL_TEAM_TOKENS
        or (tokens[-1].isdigit() and len(tokens[-1]) <= 4)
    ):
        tokens.pop()
    return " ".join(tokens)


def _keys_equivalent(left: str, right: str) -> bool:
    if left == right:
        return True
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return False
    return left_tokens <= right_tokens or right_tokens <= left_tokens


def resolve_against_roster(
    provider_name: str, league: str, roster: set[str]
) -> str | None:
    """Return the roster's own spelling that `provider_name` identifies, or None."""
    key = _identity_key(provider_name)
    aliased = (
        _MARKET_ALIASES.get((league, key)) or _AUDITED_ALIASES.get((league, key)) or key
    )
    for candidate in roster:
        candidate_key = _identity_key(candidate)
        if aliased == candidate_key or key == candidate_key:
            return candidate
        if _keys_equivalent(aliased, candidate_key) or _keys_equivalent(
            key, candidate_key
        ):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------


def load_division_season(
    division: str, suffix: str
) -> tuple[set[str], dict[str, set[date]]]:
    """Return (team roster, {team: set of match dates}) for one division/season file."""
    import pandas as pd

    paths = glob.glob(str(_CACHE_DIR / f"fd_{division}_{suffix}.csv"))
    if not paths:
        return set(), {}
    frame = pd.read_csv(paths[0], encoding="utf-8", on_bad_lines="skip")
    home_col = "HomeTeam" if "HomeTeam" in frame.columns else "home_team"
    away_col = "AwayTeam" if "AwayTeam" in frame.columns else "away_team"
    date_col = "Date" if "Date" in frame.columns else "date"
    if (
        home_col not in frame.columns
        or away_col not in frame.columns
        or date_col not in frame.columns
    ):
        return set(), {}

    roster: set[str] = set()
    dates_by_team: dict[str, set[date]] = defaultdict(set)
    for _, row in frame.iterrows():
        # The corpus `date`/`Date` column is already normalized to ISO
        # YYYY-MM-DD (confirmed by direct inspection) -- unambiguous, so
        # dayfirst is irrelevant; False silences pandas's warning about it.
        parsed = pd.to_datetime(row[date_col], errors="coerce", dayfirst=False)
        if pd.isna(parsed):
            continue
        match_date = parsed.date()
        for team in (row[home_col], row[away_col]):
            team = str(team).strip()
            if not team or team.lower() == "nan":
                continue
            roster.add(team)
            dates_by_team[team].add(match_date)
    return roster, dict(dates_by_team)


# ---------------------------------------------------------------------------
# Crosswalk
# ---------------------------------------------------------------------------


async def qualify_league_season(
    provider: APIFootballProvider, league: str, season: int
) -> dict[str, Any]:
    division = _LEAGUE_TO_DIVISION[league]
    suffix = _SEASONS[season]
    roster, dates_by_team = load_division_season(division, suffix)
    if not roster:
        return {
            "league": league,
            "season": season,
            "corpus_file_found": False,
            "queried": False,
        }

    result = await provider.injuries(competition=league, season=season)
    if result.status.name != "VERIFIED":
        return {
            "league": league,
            "season": season,
            "corpus_file_found": True,
            "queried": True,
            "api_status": result.status.name,
            "api_error_code": result.error_code,
            "record_count": 0,
        }

    coherent = [r for r in result.records if r.get("coherent")]
    team_resolved = 0
    date_matched = 0
    unresolved_teams: set[str] = set()
    for record in coherent:
        resolved = resolve_against_roster(record.get("team_name", ""), league, roster)
        if resolved is None:
            unresolved_teams.add(record.get("team_name", ""))
            continue
        team_resolved += 1
        fixture_date_raw = record.get("fixture_date")
        if not fixture_date_raw:
            continue
        try:
            record_date = datetime.fromisoformat(str(fixture_date_raw)).date()
        except ValueError:
            continue
        if record_date in dates_by_team.get(resolved, set()):
            date_matched += 1

    total = len(coherent)
    return {
        "league": league,
        "season": season,
        "corpus_file_found": True,
        "queried": True,
        "api_status": result.status.name,
        "record_count": total,
        "team_resolved": team_resolved,
        "team_resolved_pct": round(100.0 * team_resolved / total, 2) if total else 0.0,
        "date_matched": date_matched,
        "date_matched_pct_of_resolved": (
            round(100.0 * date_matched / team_resolved, 2) if team_resolved else 0.0
        ),
        "unresolved_team_names": sorted(unresolved_teams),
    }


async def main() -> int:
    if not settings.api_football_key:
        print("No api_football credential configured — nothing to probe.")
        return 1

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        provider = APIFootballProvider(
            api_key=settings.api_football_key,
            enabled=True,
            live_tests=True,
            http_client=client,
        )
        for league in _LEAGUE_TO_DIVISION:
            for season in _SEASONS:
                row = await qualify_league_season(provider, league, season)
                rows.append(row)
                # A back-to-back sweep with zero delay produced transient
                # api_logical_error responses on 5 of 18 calls that succeeded
                # cleanly when re-run individually moments later -- a burst
                # throttle, not a genuine per-league/season restriction.
                # Confirmed by re-querying BUNDESLIGA/2023 and LIGUE_1/2022
                # in isolation (both VERIFIED). A polite pause avoids it.
                await asyncio.sleep(1.0)
                print(
                    f"{league:<12} {season}  "
                    f"{'no corpus file' if not row.get('corpus_file_found') else ''}"
                    f"{'' if row.get('queried') else ''}"
                    f"status={row.get('api_status', 'n/a')} "
                    f"records={row.get('record_count', 0):>5}  "
                    f"team_resolved={row.get('team_resolved_pct', 0):>5.1f}%  "
                    f"date_matched(of resolved)={row.get('date_matched_pct_of_resolved', 0):>5.1f}%"
                )

    out = _REPORT_DIR / "portfolio-b-availability-coverage-manifest.json"
    out.write_text(json.dumps(rows, indent=2, default=str))
    print(f"\nManifest written to {out}")

    # "queried" includes UNAVAILABLE responses (no team_resolved/date_matched
    # keys, since qualify_league_season returns early for those) -- the
    # aggregate must sum only over rows that actually resolved records.
    queried = [r for r in rows if r.get("api_status") == "VERIFIED"]
    if queried:
        total_records = sum(r["record_count"] for r in queried)
        total_resolved = sum(r["team_resolved"] for r in queried)
        total_date_matched = sum(r["date_matched"] for r in queried)
        print("\n" + "=" * 70)
        print(
            f"AGGREGATE across {len(queried)} league-seasons: "
            f"{total_records} records, "
            f"{100.0 * total_resolved / total_records:.1f}% team-resolved, "
            f"{100.0 * total_date_matched / total_resolved:.1f}% of those date-matched"
            if total_records and total_resolved
            else "AGGREGATE: no queryable records"
        )
        print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
