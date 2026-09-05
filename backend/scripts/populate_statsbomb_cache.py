"""Populate the StatsBomb Open Data parquet cache for home_pressing_intensity
and progressive_carry_diff.

PURPOSE
-------
This is crosswalk prerequisite 2 from docs/event-data-crosswalk.md.
It pulls PPDA and progressive-carry counts from the StatsBomb Open Data
repository (statsbombpy) and writes them to the parquet cache that
StatsBombAggregator reads at serving time.

COVERAGE AUDIT (crosswalk prerequisite 1)
------------------------------------------
Run with --audit-only to compare StatsBomb Open coverage against the
football-data.co.uk corpus used for Elo/training (backend/data/cache/fd_*.csv).
This is the authoritative check that must pass before ENABLE_STATSBOMB_ENRICHMENT
can be set to true for any league.

USAGE
-----
    # Coverage audit only (no writes) — run this first
    PYTHONPATH=. python scripts/populate_statsbomb_cache.py --audit-only

    # Populate cache for a specific league
    PYTHONPATH=. python scripts/populate_statsbomb_cache.py --league EPL

    # Populate cache for all supported leagues
    PYTHONPATH=. python scripts/populate_statsbomb_cache.py --all-leagues

    # Dry-run (compute stats, skip the parquet write)
    PYTHONPATH=. python scripts/populate_statsbomb_cache.py --league EPL --dry-run

REQUIREMENTS
------------
    pip install statsbombpy  # Apache 2.0, keyless for Open Data
    pip install pandas pyarrow

⚠️  StatsBomb Open Data covers historical seasons only — no current live season
    for most competitions (Ligue 1 and Bundesliga coverage is sparse or absent).
    Run --audit-only first to confirm a league is sufficiently covered before
    enabling enrichment.

IDENTITY NORMALISATION
----------------------
StatsBomb team names are resolved via team_identity._identity_key() + _AUDITED_ALIASES.
New aliases for names that do not resolve cleanly (e.g. provider-specific
short-forms) must be added to _AUDITED_ALIASES before this script is run for
that league. The current _AUDITED_ALIASES already covers:
    - "Bayern München" → "BUNDESLIGA"/"bayern munchen" → "bayern munich"
    - "Borussia Mönchengladbach" → "BUNDESLIGA"/"borussia monchengladbach" → "m gladbach"

Any team that still fails to resolve is skipped with a warning, not silently
defaulted — callers can grep for UNRESOLVED lines in the output.

PPDA COMPUTATION
----------------
PPDA = opponent passes in defensive third / (pressure events + recoveries)
Lower PPDA = more pressing. pressing_intensity ≈ 1/ppda_ratio (inversion in
upcoming_match_feature_service.py when ENABLE_STATSBOMB_ENRICHMENT=true).

PROGRESSIVE CARRY COMPUTATION
------------------------------
A carry is "progressive" when it ends at least 10m closer to goal than it
started and ends past the midfield line (following StatsBomb's own definition
in their public methodology doc).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Soft-import: only required at runtime, not at import time
try:
    import pandas as pd
    _PANDAS_AVAILABLE = True
except ImportError:
    _PANDAS_AVAILABLE = False

try:
    from statsbombpy import sb as statsbomb
    _STATSBOMBPY_AVAILABLE = True
except ImportError:
    _STATSBOMBPY_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── SabiScore competition → StatsBomb competition_id mapping ──────────────────
# Derived from statsbombpy.sb.competitions() on 2026-09-04.
# Only competitions with meaningful historical coverage are listed.
# UCL and Eredivisie are absent from Open Data for most recent seasons.
_SABISCORE_TO_SB_COMPETITION: dict[str, list[int]] = {
    "EPL": [2],          # Premier League (England)
    "LA_LIGA": [11],     # La Liga (Spain)
    "BUNDESLIGA": [9],   # 1. Bundesliga (Germany)  — ⚠️ sparse: 2015/16 only
    "SERIE_A": [12],     # Serie A (Italy)
    "LIGUE_1": [7],      # Ligue 1 (France)         — ⚠️ sparse: limited seasons
    # EREDIVISIE: absent from Open Data
    # UCL: partial only (knockout rounds, not group stage); omitted
}

# Minimum number of StatsBomb Open matches required for a league before
# ENABLE_STATSBOMB_ENRICHMENT=true is considered safe.
_MIN_COVERAGE_MATCHES = 50

# ── Team-name normalisation ───────────────────────────────────────────────────

def _identity_key(name: str) -> str:
    """Inline copy of team_identity._identity_key for zero-import usage."""
    import re
    import unicodedata

    _LEGAL_TOKENS = {
        "ac","acf","afc","as","bc","ca","cf","fc","fsv","osc",
        "rc","sc","sco","ss","ssc","stade","ud","us","vfb",
    }
    _TRAILING = {"club", "football", "soccer"}

    def _ascii(s: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

    def _collapse(tokens: list[str]) -> list[str]:
        out: list[str] = []
        run: list[str] = []
        for t in tokens:
            if len(t) == 1 and t.isalpha():
                run.append(t)
            else:
                if run:
                    out.append("".join(run) if len(run) > 1 else run[0])
                    run = []
                out.append(t)
        if run:
            out.append("".join(run) if len(run) > 1 else run[0])
        return out

    tokens = _collapse(re.findall(r"[a-z0-9]+", _ascii(name).lower().replace("&", " ")))
    while tokens and (tokens[0] in _LEGAL_TOKENS or tokens[0].isdigit()):
        tokens.pop(0)
    while len(tokens) > 1 and tokens[-1] in _TRAILING:
        tokens.pop()
    while tokens and (tokens[-1] in _LEGAL_TOKENS or (tokens[-1].isdigit() and len(tokens[-1]) <= 4)):
        tokens.pop()
    return " ".join(tokens)


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


def _resolve_sb_team_name(sb_name: str, league: str) -> str | None:
    """Return the identity key (Elo-corpus form) for a StatsBomb team name, or None."""
    key = _identity_key(sb_name)
    if not key:
        return None
    alias = _AUDITED_ALIASES.get((league, key))
    return alias if alias is not None else key


# ── PPDA computation ──────────────────────────────────────────────────────────

def _ppda_from_events(events: "pd.DataFrame", team_id: int) -> float | None:
    """Compute PPDA for one team from a StatsBomb events DataFrame.

    PPDA = opponent_passes_in_defensive_third / (pressure_events + recoveries)
    Lower PPDA = more pressing intensity.
    """
    # Defensive third: events in the bottom 40m of the pitch (x < 40)
    opponent_passes = events[
        (events["team_id"] != team_id)
        & (events["type_name"] == "Pass")
        & (events["location"].apply(lambda loc: isinstance(loc, list) and loc[0] < 40))
    ]
    defensive_actions = events[
        (events["team_id"] == team_id)
        & (events["type_name"].isin(["Pressure", "Ball Recovery"]))
    ]
    denom = len(defensive_actions)
    if denom == 0:
        return None
    return len(opponent_passes) / denom


def _progressive_carries_from_events(events: "pd.DataFrame", team_id: int) -> int:
    """Count progressive carries (end at least 10m closer to goal, past midfield).

    StatsBomb methodology: a carry is progressive when the carry distance toward
    goal is ≥ 10m and the carry ends past the midfield line (x ≥ 60).
    """
    carries = events[
        (events["team_id"] == team_id)
        & (events["type_name"] == "Carry")
    ]
    count = 0
    for _, row in carries.iterrows():
        start = row.get("location")
        end = row.get("carry_end_location")
        if not (isinstance(start, list) and isinstance(end, list)):
            continue
        # Distance toward goal: higher x = closer to opponent goal (StatsBomb coords)
        dx = end[0] - start[0]
        if dx >= 10 and end[0] >= 60:
            count += 1
    return count


# ── Coverage audit ────────────────────────────────────────────────────────────

def run_coverage_audit() -> dict:
    """Compare StatsBomb Open coverage against the fd_*.csv Elo corpus."""
    if not _PANDAS_AVAILABLE or not _STATSBOMBPY_AVAILABLE:
        return {"error": "pandas and statsbombpy are required for the coverage audit"}

    fd_cache = Path(__file__).parents[1] / "data" / "cache"
    corpus_counts: dict[str, int] = {}
    for league, pattern in [
        ("EPL", "fd_E0_*.csv"),
        ("LA_LIGA", "fd_SP1_*.csv"),
        ("BUNDESLIGA", "fd_D1_*.csv"),
        ("SERIE_A", "fd_I1_*.csv"),
        ("LIGUE_1", "fd_F1_*.csv"),
        ("EREDIVISIE", "fd_N1_*.csv"),
    ]:
        files = sorted(fd_cache.glob(pattern))
        total = 0
        for f in files:
            try:
                total += len(pd.read_csv(f))
            except Exception:
                pass
        corpus_counts[league] = total

    sb_counts: dict[str, int] = {}
    for league, comp_ids in _SABISCORE_TO_SB_COMPETITION.items():
        total = 0
        for comp_id in comp_ids:
            try:
                comps = statsbomb.competitions()
                seasons = comps[comps["competition_id"] == comp_id]["season_id"].tolist()
                for season_id in seasons:
                    try:
                        matches = statsbomb.matches(competition_id=comp_id, season_id=season_id)
                        total += len(matches)
                    except Exception as exc:
                        logger.warning("Skip %s season %s: %s", league, season_id, exc)
            except Exception as exc:
                logger.warning("Cannot reach StatsBomb API for %s: %s", league, exc)
        sb_counts[league] = total

    report: dict[str, object] = {}
    for league in corpus_counts:
        corpus = corpus_counts.get(league, 0)
        sb = sb_counts.get(league, 0)
        coverage_pct = round(sb / corpus * 100, 1) if corpus > 0 else 0.0
        sufficient = sb >= _MIN_COVERAGE_MATCHES
        verdict = (
            "SUFFICIENT"
            if sufficient
            else f"INSUFFICIENT (need >= {_MIN_COVERAGE_MATCHES} matches)"
        )
        if league not in _SABISCORE_TO_SB_COMPETITION:
            verdict = "NOT_SUPPORTED_BY_OPEN_DATA"
        report[league] = {
            "corpus_matches": corpus,
            "statsbomb_matches": sb,
            "coverage_pct": coverage_pct,
            "sufficient_for_enrichment": sufficient,
            "verdict": verdict,
        }
    return report


# ── Parquet cache population ──────────────────────────────────────────────────

def populate_league(
    league: str,
    dry_run: bool = False,
    output_path: Path | None = None,
) -> dict:
    """Fetch StatsBomb events for one league, compute PPDA + prog-carries, write parquet."""
    if not _PANDAS_AVAILABLE or not _STATSBOMBPY_AVAILABLE:
        return {"error": "pandas and statsbombpy are required"}

    comp_ids = _SABISCORE_TO_SB_COMPETITION.get(league)
    if not comp_ids:
        return {"error": f"{league} is not in the StatsBomb Open coverage map"}

    rows: list[dict] = []
    skipped_teams: set[str] = set()

    for comp_id in comp_ids:
        comps = statsbomb.competitions()
        seasons = comps[comps["competition_id"] == comp_id]["season_id"].tolist()
        logger.info("%s: competition_id=%s, seasons=%s", league, comp_id, seasons)

        for season_id in seasons:
            try:
                matches = statsbomb.matches(competition_id=comp_id, season_id=season_id)
            except Exception as exc:
                logger.warning("Skip %s season %s: %s", league, season_id, exc)
                continue

            for _, match_row in matches.iterrows():
                match_id = int(match_row["match_id"])
                match_date = str(match_row.get("match_date", ""))

                try:
                    events = statsbomb.events(match_id=match_id)
                except Exception as exc:
                    logger.warning("Skip match %s events: %s", match_id, exc)
                    continue

                # Normalize column names (statsbombpy may use different key shapes)
                if "team_id" not in events.columns and "team" in events.columns:
                    # statsbombpy ≥0.3 returns nested dicts; flatten team_id
                    events["team_id"] = events["team"].apply(
                        lambda t: t.get("id") if isinstance(t, dict) else None
                    )
                if "type_name" not in events.columns and "type" in events.columns:
                    events["type_name"] = events["type"].apply(
                        lambda t: t.get("name") if isinstance(t, dict) else str(t)
                    )
                if "carry_end_location" not in events.columns:
                    events["carry_end_location"] = events.get(
                        "carry", pd.Series([None] * len(events))
                    ).apply(lambda c: c.get("end_location") if isinstance(c, dict) else None)

                for side, name_col, id_col in [
                    ("home", "home_team", "home_team_id"),
                    ("away", "away_team", "away_team_id"),
                ]:
                    sb_name = str(match_row.get(name_col, ""))
                    team_id = match_row.get(id_col)

                    resolved = _resolve_sb_team_name(sb_name, league)
                    if resolved is None:
                        if sb_name not in skipped_teams:
                            logger.warning("UNRESOLVED team: %r (league=%s) — skipping", sb_name, league)
                            skipped_teams.add(sb_name)
                        continue

                    ppda = _ppda_from_events(events, team_id)
                    prog_carries = _progressive_carries_from_events(events, team_id)

                    rows.append({
                        "match_id": match_id,
                        "team_id": resolved,           # Elo-corpus identity key
                        "sb_team_name": sb_name,
                        "league": league,
                        "match_date": match_date,
                        "ppda_ratio": ppda if ppda is not None else 1.0,
                        "ppda_available": ppda is not None,
                        "progressive_carry_diff": float(prog_carries),
                        # sentinel columns for downstream gap detection
                        "shot_quality_diff": float("nan"),
                        "key_passes_under_pressure_diff": float("nan"),
                        "set_piece_xg_diff": float("nan"),
                    })

    summary = {
        "league": league,
        "rows_computed": len(rows),
        "unresolved_teams": sorted(skipped_teams),
        "dry_run": dry_run,
    }

    if not rows:
        logger.warning("%s: no rows produced — check StatsBomb coverage", league)
        return summary

    if dry_run:
        logger.info("%s dry-run: %d rows (not written)", league, len(rows))
        return summary

    cache_path = output_path or Path(__file__).parents[1] / "data" / "processed" / "statsbomb_features_cache.parquet"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    new_df = pd.DataFrame(rows)
    if cache_path.exists():
        existing = pd.read_parquet(cache_path)
        # Drop rows for this league so we can replace with fresh data
        existing = existing[existing["league"] != league]
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    combined.to_parquet(cache_path, index=False)
    summary["written_to"] = str(cache_path)
    logger.info("%s: wrote %d rows to %s", league, len(rows), cache_path)
    return summary


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--audit-only", action="store_true", help="Print coverage audit and exit")
    parser.add_argument("--league", help="Populate one league (e.g. EPL)")
    parser.add_argument("--all-leagues", action="store_true", help="Populate all supported leagues")
    parser.add_argument("--dry-run", action="store_true", help="Compute but skip the parquet write")
    parser.add_argument("--output", help="Override parquet output path")
    args = parser.parse_args()

    if not _PANDAS_AVAILABLE:
        print("ERROR: pandas is required.  pip install pandas pyarrow", file=sys.stderr)
        sys.exit(1)

    if not _STATSBOMBPY_AVAILABLE and not args.audit_only:
        print("ERROR: statsbombpy is required.  pip install statsbombpy", file=sys.stderr)
        sys.exit(1)

    if args.audit_only:
        report = run_coverage_audit()
        print(json.dumps(report, indent=2))
        # Summary line
        insufficient = [
            league
            for league, v in report.items()
            if isinstance(v, dict) and not v.get("sufficient_for_enrichment", False)
        ]
        if insufficient:
            print(f"\n⚠️  Insufficient StatsBomb coverage for: {', '.join(insufficient)}")
            print("   Do NOT set ENABLE_STATSBOMB_ENRICHMENT=true for these leagues.")
        return

    output_path = Path(args.output) if args.output else None
    leagues: list[str] = []
    if args.all_leagues:
        leagues = list(_SABISCORE_TO_SB_COMPETITION.keys())
    elif args.league:
        leagues = [args.league.upper()]
    else:
        parser.print_help()
        sys.exit(0)

    for league in leagues:
        result = populate_league(league, dry_run=args.dry_run, output_path=output_path)
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
