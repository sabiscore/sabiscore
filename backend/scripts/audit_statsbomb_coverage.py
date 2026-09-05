"""StatsBomb Open Data coverage audit against the Understat corpus.

Directive: event-data-crosswalk.md Phase 3 Step 1.
Threshold: 85% coverage required (Path A); below threshold triggers Path B.

Usage
-----
    PYTHONPATH=. python scripts/audit_statsbomb_coverage.py

No dependencies beyond the standard library + pandas.  Does NOT require
statsbombpy — fetches the match manifests directly from the StatsBomb Open
Data GitHub repository via urllib.

Exit codes
----------
0   Audit complete (result written to stdout + reports/evaluation/).
1   Fetch error (network or JSON parse failure).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORPUS_DIR = _REPO_ROOT / "data" / "processed" / "v4_sources"
_REPORT_DIR = _REPO_ROOT / "reports" / "evaluation"

_SB_GITHUB_BASE = (
    "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
)
_SB_COMPETITIONS_URL = f"{_SB_GITHUB_BASE}/competitions.json"

# StatsBomb competition IDs → SabiScore league keys.
# Source: statsbomb/open-data README + competitions.json
_SB_COMP_TO_LEAGUE: Dict[int, str] = {
    2: "EPL",
    7: "LIGUE_1",
    9: "BUNDESLIGA",
    11: "LA_LIGA",
    12: "SERIE_A",
}

# Understat parquet league labels → SabiScore keys.
_UNDERSTAT_TO_LEAGUE: Dict[str, str] = {
    "ENG-Premier League": "EPL",
    "FRA-Ligue 1": "LIGUE_1",
    "GER-Bundesliga": "BUNDESLIGA",
    "ESP-La Liga": "LA_LIGA",
    "ITA-Serie A": "SERIE_A",
}

# Coverage threshold from the directive.
COVERAGE_THRESHOLD_PCT = 85.0

# Legal tokens stripped from team names (same set as team_identity.py).
_LEGAL_TOKENS: Set[str] = {
    "fc", "cf", "sc", "ac", "rc", "afc", "bsc", "ud", "cd", "rcd",
    "sd", "ad", "sv", "bv", "tsv", "fsv", "vfb", "vfl", "1",
    "de", "du", "la", "le", "los", "las",
}

# ---------------------------------------------------------------------------
# Normalisation (inline copy of team_identity._identity_key)
# ---------------------------------------------------------------------------

def _identity_key(name: str) -> str:
    """NFKD-normalise, strip diacritics, lowercase, strip legal tokens.

    Mirrors team_identity._identity_key() exactly so crosswalk uses the same
    canonical key as fixture sync and Elo backfill.
    """
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    lower = stripped.lower()
    # Collapse non-alphanumeric to space
    tokens = []
    for tok in lower.replace("-", " ").replace(".", " ").split():
        tok_clean = "".join(c for c in tok if c.isalnum())
        if tok_clean and tok_clean not in _LEGAL_TOKENS:
            tokens.append(tok_clean)
    return " ".join(tokens)


# ---------------------------------------------------------------------------
# StatsBomb Open Data fetching (no statsbombpy required)
# ---------------------------------------------------------------------------

def _fetch_json(url: str, retries: int = 3) -> object:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                return json.loads(r.read())
        except Exception as exc:
            if attempt == retries - 1:
                raise
            log.warning("Fetch attempt %d failed for %s: %s", attempt + 1, url, exc)
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def fetch_sb_match_tuples() -> List[Tuple[str, str, str, str]]:
    """Return (league, season_name, home_key, away_key) for every
    StatsBomb Open match in our five supported leagues.
    """
    log.info("Fetching StatsBomb competition manifest …")
    competitions = _fetch_json(_SB_COMPETITIONS_URL)
    if not isinstance(competitions, list):
        raise TypeError(
            f"StatsBomb competitions manifest: expected a list, got {type(competitions).__name__}"
        )

    rows: List[Tuple[str, str, str, str]] = []

    target = [
        c for c in competitions
        if c["competition_id"] in _SB_COMP_TO_LEAGUE
    ]
    log.info("  %d StatsBomb seasons span our 5 leagues", len(target))

    for comp in target:
        cid = comp["competition_id"]
        sid = comp["season_id"]
        league = _SB_COMP_TO_LEAGUE[cid]
        season = comp["season_name"]
        url = f"{_SB_GITHUB_BASE}/matches/{cid}/{sid}.json"
        try:
            matches = _fetch_json(url)
            if not isinstance(matches, list):
                raise TypeError(f"expected a list of matches, got {type(matches).__name__}")
        except Exception as exc:
            log.warning("Could not fetch %s %s: %s", league, season, exc)
            continue

        for m in matches:
            home_raw = m.get("home_team", {}).get("home_team_name", "")
            away_raw = m.get("away_team", {}).get("away_team_name", "")
            if home_raw and away_raw:
                rows.append((league, season, _identity_key(home_raw), _identity_key(away_raw)))

        log.info("  %s %s: %d matches", league, season, len(matches))
        time.sleep(0.05)  # polite rate

    return rows


# ---------------------------------------------------------------------------
# Understat corpus loading
# ---------------------------------------------------------------------------

def load_understat_tuples() -> List[Tuple[str, str, str]]:
    """Return (league, home_key, away_key) for every played Understat match."""
    try:
        import pandas as pd
    except ImportError:
        log.error("pandas is required — install it in your venv")
        sys.exit(1)

    parquets = list(_CORPUS_DIR.glob("*.parquet"))
    if not parquets:
        log.error("No parquet files found in %s", _CORPUS_DIR)
        sys.exit(1)

    frames = [pd.read_parquet(p) for p in parquets]
    df = pd.concat(frames, ignore_index=True)

    # Only played matches carry xG
    played = df[df["is_result"] == True].copy()
    log.info("Understat corpus: %d played matches loaded", len(played))

    rows: List[Tuple[str, str, str]] = []
    for _, row in played.iterrows():
        league_raw = str(row.get("league", ""))
        league = _UNDERSTAT_TO_LEAGUE.get(league_raw)
        if not league:
            continue
        home = _identity_key(str(row.get("home_team", "")))
        away = _identity_key(str(row.get("away_team", "")))
        if home and away:
            rows.append((league, home, away))

    return rows


# ---------------------------------------------------------------------------
# Crosswalk
# ---------------------------------------------------------------------------

def run_crosswalk() -> Dict[str, object]:
    """Perform identity crosswalk, compute coverage, return result dict."""
    sb_tuples = fetch_sb_match_tuples()
    us_tuples = load_understat_tuples()

    # Build lookup: (league, home_key, away_key) → count for Understat
    us_set: Set[Tuple[str, str, str]] = set(us_tuples)
    sb_set: Set[Tuple[str, str, str]] = {(lg, h, a) for lg, _s, h, a in sb_tuples}

    # Also try the symmetric orientation (StatsBomb sometimes orders differently)
    sb_symmetric: Set[Tuple[str, str, str]] = sb_set | {
        (lg, a, h) for lg, h, a in sb_set
    }

    intersection = us_set & sb_symmetric
    intersection_count = len(intersection)
    us_total = len(us_set)
    sb_total = len(sb_set)
    coverage_pct = 100.0 * intersection_count / us_total if us_total else 0.0

    # Per-league breakdown
    per_league: Dict[str, Dict[str, int]] = {}
    for lg in _SB_COMP_TO_LEAGUE.values():
        sb_lg = {(h, a) for l, h, a in sb_symmetric if l == lg}
        us_lg = {(h, a) for l, h, a in us_set if l == lg}
        inter_lg = us_lg & sb_lg
        per_league[lg] = {
            "sb_matches": len(sb_lg),
            "understat_matches": len(us_lg),
            "intersection": len(inter_lg),
            "coverage_pct": round(100.0 * len(inter_lg) / len(us_lg), 2) if us_lg else 0.0,
        }

    result = {
        "audit_date": str(date.today()),
        "statsbomb_total_matches": sb_total,
        "understat_played_matches": us_total,
        "intersection_matches": intersection_count,
        "coverage_pct": round(coverage_pct, 2),
        "threshold_pct": COVERAGE_THRESHOLD_PCT,
        "path": "A" if coverage_pct >= COVERAGE_THRESHOLD_PCT else "B",
        "per_league": per_league,
    }
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=== StatsBomb / Understat Coverage Audit ===")
    log.info("Threshold: %.0f%%  |  Corpus: %s", COVERAGE_THRESHOLD_PCT, _CORPUS_DIR)

    result = run_crosswalk()

    print("\n" + "=" * 60)
    print("STATSBOMB COVERAGE AUDIT RESULT")
    print("=" * 60)
    print(f"  StatsBomb Open matches (5 leagues): {result['statsbomb_total_matches']:,}")
    print(f"  Understat played matches:           {result['understat_played_matches']:,}")
    print(f"  Intersection (identity crosswalk):  {result['intersection_matches']:,}")
    print(f"  Coverage:                           {result['coverage_pct']:.2f}%")
    print(f"  Threshold:                          {COVERAGE_THRESHOLD_PCT:.0f}%")
    print(f"  VERDICT:  PATH {'A (viable)' if result['path'] == 'A' else 'B (INVIABLE — event data relegated to ALWAYS_DATA_GAP)'}")
    print()
    print("Per-league breakdown:")
    for lg, d in result["per_league"].items():
        print(
            f"  {lg:<12}  SB={d['sb_matches']:>4}  US={d['understat_matches']:>4}"
            f"  inter={d['intersection']:>4}  cov={d['coverage_pct']:>5.1f}%"
        )
    print("=" * 60 + "\n")

    # Persist report
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = _REPORT_DIR / "statsbomb-coverage-audit-2026.json"
    out.write_text(json.dumps(result, indent=2))
    log.info("Report written to %s", out)

    if result["path"] == "B":
        log.info(
            "PATH B: StatsBomb coverage %.2f%% < %.0f%% threshold. "
            "home_pressing_intensity and progressive_carry_diff are formally relegated "
            "to PHASE7_FEATURES_ALWAYS_DATA_GAP.",
            result["coverage_pct"],
            COVERAGE_THRESHOLD_PCT,
        )
        sys.exit(0)
    else:
        log.info("PATH A: Coverage sufficient. Proceed with parquet population.")
        sys.exit(0)


if __name__ == "__main__":
    main()
