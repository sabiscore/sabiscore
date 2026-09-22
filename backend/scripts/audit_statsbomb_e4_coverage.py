"""Experiment E4 / Portfolio C+D — StatsBomb Open Data source qualification.

Directive v5 §15 (Coverage Gates G1-G6), §23 (Event Data Research Programme,
gates D1-D2), §40 (Gate R1 - Source Qualification), §42 (reopening criteria).

WHY THIS EXISTS ALONGSIDE audit_statsbomb_coverage.py
-----------------------------------------------------
``audit_statsbomb_coverage.py`` measures StatsBomb against the **Understat**
parquet corpus, to decide Path A/B for two ``PHASE7_FEATURES_ALWAYS_DATA_GAP``
slots. E4's registry entry (``reports/research/experiment_registry.yaml``)
records that it reused that number rather than measuring its own:

    "Blocked at Gate G1 by a coverage ceiling this codebase had already
     measured for a different feature ... No new audit was run because the
     existing measurement already answers it."

That is a borrowed denominator. E4's question is about the corpus SabiScore
actually trains and serves on -- ``backend/data/cache/fd_*.csv`` -- and about
prediction-time availability (Gate G5), which no StatsBomb audit in this repo
has ever measured. §42 clause 6 ("corrected methodological defect") is the
grounds for measuring it properly here. The Understat audit is left untouched:
it decides a different, live question.

This script writes NO production code paths and changes no feature contract.

Usage
-----
    PYTHONPATH=. python scripts/audit_statsbomb_e4_coverage.py [--events-sample N]

Exit codes
----------
0   Audit complete (JSON written to reports/evaluation/).
1   Fetch error (network or JSON parse failure).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# One normaliser, not a third copy. audit_statsbomb_coverage is stdlib-only at
# import time, so this pulls in no DB/app import chain.
from audit_statsbomb_coverage import (  # noqa: E402
    _SB_COMPETITIONS_URL,
    _SB_GITHUB_BASE,
    _fetch_json,
    _identity_key,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORPUS_DIR = _REPO_ROOT / "data" / "cache"
_REPORT_DIR = _REPO_ROOT / "reports" / "evaluation"

# football-data.co.uk division code -> SabiScore canonical league id.
_DIV_TO_LEAGUE: dict[str, str] = {
    "E0": "EPL",
    "SP1": "LA_LIGA",
    "I1": "SERIE_A",
    "D1": "BUNDESLIGA",
    "F1": "LIGUE_1",
    "N1": "EREDIVISIE",
}

# StatsBomb competition_id -> SabiScore canonical league id.
# Derived by reading competitions.json, not from memory. EREDIVISIE is absent
# from StatsBomb Open Data entirely -- that absence is a measurement, recorded
# in the report rather than silently omitted.
_SB_COMP_TO_LEAGUE: dict[int, str] = {
    2: "EPL",
    7: "LIGUE_1",
    9: "BUNDESLIGA",
    11: "LA_LIGA",
    12: "SERIE_A",
    16: "UCL",
}

_SABISCORE_LEAGUES = [
    "EPL",
    "LA_LIGA",
    "SERIE_A",
    "BUNDESLIGA",
    "LIGUE_1",
    "EREDIVISIE",
]

# §15 G1 bar. Same constant the sibling audit already established for this
# source; not re-derived post-hoc after seeing this result.
COVERAGE_THRESHOLD_PCT = 85.0

# Kickoffs are recorded in local time by football-data and as a UTC date by
# StatsBomb; a one-day window absorbs that without loosening identity.
_DATE_TOLERANCE_DAYS = 1


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------


def _parse_corpus_date(raw: str) -> date | None:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _season_label(stem: str) -> str:
    """fd_E0_2324 -> '2023/2024'."""
    code = stem.rsplit("_", 1)[-1]
    if len(code) != 4 or not code.isdigit():
        return code
    return f"20{code[:2]}/20{code[2:]}"


def load_corpus() -> list[dict[str, Any]]:
    """Every fixture SabiScore actually trains on, from fd_*.csv.

    Handles both column vocabularies present in data/cache: the normalised
    (``date``/``home_team``) form and the raw football-data (``Date``/
    ``HomeTeam``) form. A row whose date or team names cannot be read is
    dropped and counted, never defaulted.
    """
    rows: list[dict[str, Any]] = []
    malformed = 0
    files = sorted(_CORPUS_DIR.glob("fd_*.csv"))
    if not files:
        raise FileNotFoundError(f"No fd_*.csv corpus files under {_CORPUS_DIR}")

    for path in files:
        div = path.stem.split("_")[1]
        league = _DIV_TO_LEAGUE.get(div)
        if league is None:
            continue
        season = _season_label(path.stem)
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for rec in csv.DictReader(fh):
                raw_date = rec.get("date") or rec.get("Date") or ""
                home = rec.get("home_team") or rec.get("HomeTeam") or ""
                away = rec.get("away_team") or rec.get("AwayTeam") or ""
                parsed = _parse_corpus_date(raw_date)
                if not parsed or not home.strip() or not away.strip():
                    malformed += 1
                    continue
                rows.append(
                    {
                        "league": league,
                        "season": season,
                        "date": parsed,
                        "home_key": _identity_key(home),
                        "away_key": _identity_key(away),
                        "home_raw": home.strip(),
                        "away_raw": away.strip(),
                    }
                )
    log.info("Corpus: %d fixtures (%d malformed rows dropped)", len(rows), malformed)
    return rows


# ---------------------------------------------------------------------------
# StatsBomb fetching (with dates -- the sibling audit discards them)
# ---------------------------------------------------------------------------


def fetch_sb_matches() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (matches, competition_index) for every SabiScore-relevant comp."""
    comps = _fetch_json(_SB_COMPETITIONS_URL)
    if not isinstance(comps, list):
        raise TypeError(f"competitions.json: expected list, got {type(comps).__name__}")

    index = [
        {
            "competition_id": c["competition_id"],
            "competition_name": c["competition_name"],
            "country_name": c["country_name"],
            "season_id": c["season_id"],
            "season_name": c["season_name"],
            "league": _SB_COMP_TO_LEAGUE.get(c["competition_id"]),
        }
        for c in comps
    ]

    matches: list[dict[str, Any]] = []
    for entry in index:
        if entry["league"] is None:
            continue
        cid, sid = entry["competition_id"], entry["season_id"]
        url = f"{_SB_GITHUB_BASE}/matches/{cid}/{sid}.json"
        try:
            payload = _fetch_json(url)
            if not isinstance(payload, list):
                raise TypeError(f"expected list, got {type(payload).__name__}")
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Could not fetch %s %s: %s",
                entry["league"],
                entry["season_name"],
                exc,
            )
            continue

        for match in payload:
            parsed = _parse_corpus_date((match.get("match_date") or "")[:10])
            home = (match.get("home_team") or {}).get("home_team_name", "")
            away = (match.get("away_team") or {}).get("away_team_name", "")
            if not parsed or not home or not away:
                continue
            matches.append(
                {
                    "league": entry["league"],
                    "season": entry["season_name"],
                    "season_id": sid,
                    "competition_id": cid,
                    "match_id": match.get("match_id"),
                    "date": parsed,
                    "home_key": _identity_key(home),
                    "away_key": _identity_key(away),
                    "home_raw": home,
                    "away_raw": away,
                }
            )
        log.info(
            "  SB %s %s: %d matches",
            entry["league"],
            entry["season_name"],
            len(payload),
        )
        time.sleep(0.05)

    return matches, index


# ---------------------------------------------------------------------------
# Gate D1 -- identity crosswalk (fail-closed, staged, uniqueness-guarded)
# ---------------------------------------------------------------------------


def _tokens_equivalent(corpus_token: str, sb_run: list[str]) -> bool:
    """Does one corpus token stand for this run of StatsBomb tokens?

    Three relations, all abbreviation-shaped and all seen in the real corpus:
      exact          'lyon'    == ['lyon']
      prefix (>=2)   'st'      -> ['saint']        (corpus 'st etienne')
      initials       'sg'      -> ['saint','germain']  (corpus 'paris sg')
    """
    if len(sb_run) == 1:
        other = sb_run[0]
        if corpus_token == other:
            return True
        return (
            len(corpus_token) >= 2
            and len(other) >= 2
            and (other.startswith(corpus_token) or corpus_token.startswith(other))
        )
    return len(sb_run) > 1 and corpus_token == "".join(t[0] for t in sb_run)


def _containment_score(corpus_key: str, sb_key: str) -> int | None:
    """StatsBomb tokens consumed by corpus_key, or None if it does not fit.

    Walks both token lists left to right, letting one corpus token absorb a
    contiguous run of StatsBomb tokens. Returns None unless every corpus token
    is accounted for -- a corpus name carrying a token the StatsBomb name has
    no counterpart for is a different club, not a weaker match.
    """
    corpus_tokens = corpus_key.split()
    sb_tokens = sb_key.split()
    if not corpus_tokens or not sb_tokens:
        return None

    ci = si = consumed = 0
    while ci < len(corpus_tokens) and si < len(sb_tokens):
        matched = False
        for run_len in (2, 1):  # prefer the abbreviation reading
            run = sb_tokens[si : si + run_len]
            if len(run) == run_len and _tokens_equivalent(corpus_tokens[ci], run):
                consumed += run_len
                si += run_len
                ci += 1
                matched = True
                break
        if not matched:
            si += 1  # a StatsBomb-only token (legal form, city suffix)
    return consumed if ci == len(corpus_tokens) else None


def build_crosswalk(
    sb_matches: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str], str], dict[str, Any]]:
    """StatsBomb team key -> corpus team key, per league.

    Stage 1 exact key. Stage 2 scores every corpus candidate by how much of the
    StatsBomb name it accounts for and requires a unique strict maximum.

    The scoring stage exists because a bare-subset test silently mis-resolves:
    'paris saint germain' contains corpus key 'paris' (Paris FC) as a subset,
    so a subset rule hands PSG's fixtures to a different club. Scoring makes
    'paris sg' win outright (3 tokens consumed vs 1). A tie is left UNRESOLVED
    -- never guessed, never substituted with a neutral.
    """
    corpus_keys: dict[str, set[str]] = defaultdict(set)
    for row in corpus:
        corpus_keys[row["league"]].add(row["home_key"])
        corpus_keys[row["league"]].add(row["away_key"])

    sb_keys: dict[str, set[str]] = defaultdict(set)
    sb_raw: dict[tuple[str, str], str] = {}
    for match in sb_matches:
        sb_keys[match["league"]].add(match["home_key"])
        sb_keys[match["league"]].add(match["away_key"])
        sb_raw[(match["league"], match["home_key"])] = match["home_raw"]
        sb_raw[(match["league"], match["away_key"])] = match["away_raw"]

    mapping: dict[tuple[str, str], str] = {}
    unresolved: dict[str, list[str]] = defaultdict(list)
    ambiguous: dict[str, list[str]] = defaultdict(list)

    for league, keys in sb_keys.items():
        targets = corpus_keys.get(league, set())
        for key in sorted(keys):
            if key in targets:
                mapping[(league, key)] = key
                continue
            scored = [
                (score, target)
                for target in targets
                if (score := _containment_score(target, key)) is not None
            ]
            if not scored:
                unresolved[league].append(sb_raw.get((league, key), key))
                continue
            best = max(s for s, _ in scored)
            winners = sorted(t for s, t in scored if s == best)
            if len(winners) == 1:
                mapping[(league, key)] = winners[0]
            else:
                ambiguous[league].append(
                    f"{sb_raw.get((league, key), key)} -> {winners}"
                )

    total = sum(len(v) for v in sb_keys.values())
    resolved = len(mapping)
    stats = {
        "statsbomb_team_keys_total": total,
        "resolved": resolved,
        "resolution_rate_pct": round(100.0 * resolved / total, 2) if total else 0.0,
        "unresolved_by_league": {k: sorted(v) for k, v in unresolved.items()},
        "ambiguous_by_league": {k: sorted(v) for k, v in ambiguous.items()},
    }
    return mapping, stats


# ---------------------------------------------------------------------------
# Gates G1-G6
# ---------------------------------------------------------------------------


def run_gates(
    sb_matches: list[dict[str, Any]],
    corpus: list[dict[str, Any]],
    crosswalk: dict[tuple[str, str], str],
) -> dict[str, Any]:
    corpus_seasons: dict[str, set[str]] = defaultdict(set)
    corpus_by_league: dict[str, int] = defaultdict(int)
    corpus_index: dict[tuple[str, str, str], list[date]] = defaultdict(list)
    servable_by_key: dict[tuple[str, str, str, date], str] = {}
    for row in corpus:
        corpus_seasons[row["league"]].add(row["season"])
        corpus_by_league[row["league"]] += 1
        corpus_index[(row["league"], row["home_key"], row["away_key"])].append(
            row["date"]
        )
        servable_by_key[
            (row["league"], row["home_key"], row["away_key"], row["date"])
        ] = row["season"]

    corpus_season_set = {s for ss in corpus_seasons.values() for s in ss}

    matched: set[tuple[str, str, str, date]] = set()
    sb_in_window = 0
    per_league_sb_in_window: dict[str, int] = defaultdict(int)
    per_season_matched: dict[str, int] = defaultdict(int)

    for match in sb_matches:
        if match["league"] not in _SABISCORE_LEAGUES:
            continue
        if match["season"] not in corpus_season_set:
            continue
        sb_in_window += 1
        per_league_sb_in_window[match["league"]] += 1
        home = crosswalk.get((match["league"], match["home_key"]))
        away = crosswalk.get((match["league"], match["away_key"]))
        if home is None or away is None:
            continue
        for corpus_date in corpus_index.get((match["league"], home, away), []):
            if abs((corpus_date - match["date"]).days) <= _DATE_TOLERANCE_DAYS:
                matched.add((match["league"], home, away, corpus_date))
                per_season_matched[f"{match['league']}::{match['season']}"] += 1
                break

    per_league_matched: dict[str, int] = defaultdict(int)
    for league, _home, _away, _dt in matched:
        per_league_matched[league] += 1

    total_corpus = sum(corpus_by_league.values())
    g1_overall = round(100.0 * len(matched) / total_corpus, 2) if total_corpus else 0.0

    per_league = {}
    for league in _SABISCORE_LEAGUES:
        denom = corpus_by_league.get(league, 0)
        num = per_league_matched.get(league, 0)
        per_league[league] = {
            "corpus_fixtures": denom,
            "statsbomb_fixtures_in_window": per_league_sb_in_window.get(league, 0),
            "matched_fixtures": num,
            "coverage_pct": round(100.0 * num / denom, 2) if denom else 0.0,
        }

    # G2 historical depth: which corpus seasons StatsBomb touches at all.
    sb_seasons_by_league: dict[str, set[str]] = defaultdict(set)
    for match in sb_matches:
        sb_seasons_by_league[match["league"]].add(match["season"])
    g2 = {
        league: {
            "corpus_seasons": sorted(corpus_seasons.get(league, set())),
            "statsbomb_seasons_all_time": sorted(
                sb_seasons_by_league.get(league, set())
            ),
            "statsbomb_seasons_inside_corpus_window": sorted(
                sb_seasons_by_league.get(league, set())
                & corpus_seasons.get(league, set())
            ),
        }
        for league in _SABISCORE_LEAGUES
    }

    # G3 cross-season stability: matched fixtures per league-season.
    g3 = dict(sorted(per_season_matched.items()))

    # G4 cross-league portability.
    leagues_clearing = [
        lg
        for lg, v in per_league.items()
        if v["coverage_pct"] >= COVERAGE_THRESHOLD_PCT
    ]
    leagues_zero = [lg for lg, v in per_league.items() if v["matched_fixtures"] == 0]

    # G5 prediction-time availability. SabiScore serves the season at the corpus
    # tail; the servable-fixture numerator is measured against the crosswalk
    # result, not assumed from the season list.
    serving_season = max(corpus_season_set)
    sb_newest_by_league = {
        league: (
            max(sb_seasons_by_league[league])
            if sb_seasons_by_league.get(league)
            else None
        )
        for league in _SABISCORE_LEAGUES
    }
    servable_total = sum(
        1 for season in servable_by_key.values() if season == serving_season
    )
    servable_matched = sum(
        1 for key in matched if servable_by_key.get(key) == serving_season
    )
    g5 = {
        "serving_season": serving_season,
        "servable_fixtures": servable_total,
        "servable_fixtures_with_statsbomb_events": servable_matched,
        "prediction_time_availability_pct": (
            round(100.0 * servable_matched / servable_total, 2)
            if servable_total
            else 0.0
        ),
        "statsbomb_newest_season_by_league": sb_newest_by_league,
    }

    g6_default_rate = round(100.0 - g5["prediction_time_availability_pct"], 2)

    return {
        "G1_fixture_coverage": {
            "threshold_pct": COVERAGE_THRESHOLD_PCT,
            "corpus_fixtures_total": total_corpus,
            "statsbomb_fixtures_inside_corpus_window": sb_in_window,
            "matched_fixtures_total": len(matched),
            "coverage_pct": g1_overall,
            "verdict": "PASS" if g1_overall >= COVERAGE_THRESHOLD_PCT else "FAIL",
            "per_league": per_league,
        },
        "G2_historical_depth": g2,
        "G3_cross_season_stability": g3,
        "G4_cross_league_portability": {
            "leagues_total": len(_SABISCORE_LEAGUES),
            "leagues_clearing_threshold": leagues_clearing,
            "leagues_with_zero_coverage": leagues_zero,
            "verdict": (
                "PASS" if len(leagues_clearing) == len(_SABISCORE_LEAGUES) else "FAIL"
            ),
        },
        "G5_prediction_time_availability": {
            **g5,
            "verdict": (
                "PASS"
                if g5["prediction_time_availability_pct"] >= COVERAGE_THRESHOLD_PCT
                else "FAIL"
            ),
        },
        "G6_production_default_rate": {
            "implied_default_rate_pct": g6_default_rate,
            "verdict": (
                "PASS"
                if g6_default_rate <= (100.0 - COVERAGE_THRESHOLD_PCT)
                else "FAIL"
            ),
        },
    }


# ---------------------------------------------------------------------------
# Gate D2 -- event completeness on a bounded sample
# ---------------------------------------------------------------------------


def audit_event_completeness(
    sb_matches: list[dict[str, Any]],
    corpus_seasons: set[str],
    sample: int,
) -> dict[str, Any]:
    """Fetch a bounded sample of event streams and measure completeness.

    Only samples matches inside SabiScore's corpus window -- event quality on a
    2003/04 season SabiScore cannot train on is not evidence about E4.
    """
    eligible = [
        m
        for m in sb_matches
        if m["league"] in _SABISCORE_LEAGUES and m["season"] in corpus_seasons
    ]
    if not eligible:
        return {
            "eligible_matches_in_corpus_window": 0,
            "sampled": 0,
            "note": (
                "No StatsBomb match falls inside the corpus window; "
                "D2 is not measurable for E4."
            ),
        }

    eligible.sort(key=lambda m: (m["league"], m["date"]))
    step = max(1, len(eligible) // sample)
    chosen = eligible[::step][:sample]

    results: list[dict[str, Any]] = []
    for match in chosen:
        url = f"{_SB_GITHUB_BASE}/events/{match['match_id']}.json"
        try:
            events = _fetch_json(url)
        except Exception as exc:  # noqa: BLE001
            results.append({"match_id": match["match_id"], "error": str(exc)[:120]})
            continue
        if not isinstance(events, list):
            results.append(
                {"match_id": match["match_id"], "error": "payload not a list"}
            )
            continue
        malformed = sum(1 for e in events if not isinstance(e, dict) or "type" not in e)
        types = {
            (e.get("type") or {}).get("name") for e in events if isinstance(e, dict)
        }
        with_location = sum(
            1 for e in events if isinstance(e, dict) and e.get("location")
        )
        teams = {
            (e.get("team") or {}).get("name")
            for e in events
            if isinstance(e, dict) and e.get("team")
        }
        players = {
            (e.get("player") or {}).get("id")
            for e in events
            if isinstance(e, dict) and e.get("player")
        }
        results.append(
            {
                "match_id": match["match_id"],
                "league": match["league"],
                "season": match["season"],
                "events": len(events),
                "malformed_events": malformed,
                "distinct_event_types": len(types),
                "events_with_location": with_location,
                "distinct_teams": len(teams),
                "distinct_players": len(players),
                "has_pressure_events": "Pressure" in types,
                "has_carry_events": "Carry" in types,
                "has_shot_events": "Shot" in types,
            }
        )
        time.sleep(0.05)

    ok = [r for r in results if "error" not in r]
    return {
        "eligible_matches_in_corpus_window": len(eligible),
        "sampled": len(results),
        "fetch_failures": len(results) - len(ok),
        "mean_events_per_match": (
            round(sum(r["events"] for r in ok) / len(ok), 1) if ok else 0
        ),
        "total_malformed_events": sum(r["malformed_events"] for r in ok),
        "matches_with_pressure_events": sum(1 for r in ok if r["has_pressure_events"]),
        "matches_with_carry_events": sum(1 for r in ok if r["has_carry_events"]),
        "matches_not_reporting_exactly_two_teams": sum(
            1 for r in ok if r["distinct_teams"] != 2
        ),
        "detail": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events-sample", type=int, default=12)
    args = parser.parse_args()

    corpus = load_corpus()
    sb_matches, sb_index = fetch_sb_matches()
    crosswalk, crosswalk_stats = build_crosswalk(sb_matches, corpus)
    gates = run_gates(sb_matches, corpus, crosswalk)
    corpus_seasons = {r["season"] for r in corpus}
    d2 = audit_event_completeness(sb_matches, corpus_seasons, args.events_sample)

    report = {
        "experiment_id": "E4",
        "audit_date": date.today().isoformat(),
        "directive": "v5 §15 G1-G6, §23 D1-D2, §40 R1",
        "source": "StatsBomb Open Data (github.com/statsbomb/open-data)",
        "source_license_class": "L0",
        "corpus": {
            "path": str(_CORPUS_DIR.relative_to(_REPO_ROOT)),
            "fixtures": len(corpus),
            "seasons": sorted(corpus_seasons),
            "leagues": _SABISCORE_LEAGUES,
        },
        "statsbomb_competition_index": sb_index,
        "D1_identity_crosswalk": crosswalk_stats,
        "D2_event_completeness": d2,
        "gates": gates,
    }

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = _REPORT_DIR / "e4-statsbomb-source-qualification.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    log.info("Report written: %s", out)

    print(
        json.dumps(
            {
                "G1_pct": gates["G1_fixture_coverage"]["coverage_pct"],
                "G1_verdict": gates["G1_fixture_coverage"]["verdict"],
                "G4_verdict": gates["G4_cross_league_portability"]["verdict"],
                "G4_zero_coverage_leagues": gates["G4_cross_league_portability"][
                    "leagues_with_zero_coverage"
                ],
                "G5_pct": gates["G5_prediction_time_availability"][
                    "prediction_time_availability_pct"
                ],
                "G5_verdict": gates["G5_prediction_time_availability"]["verdict"],
                "D1_resolution_rate_pct": crosswalk_stats["resolution_rate_pct"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        log.error("Audit failed: %s", exc, exc_info=True)
        sys.exit(1)
