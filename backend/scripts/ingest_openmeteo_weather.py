"""Portfolio F — pre-match weather forecast acquisition (Open-Meteo).

Directive v5 §3 (Rule 3: pre-match information is the unit of truth),
§4 (Rule 4: historical availability must be reconstructable),
§5 (Rule 5: no fabricated data), §15 Gates G1/G5, §35 (compute policy).

WHAT THIS INGESTS, AND WHY IT IS NOT THE REANALYSIS ARCHIVE
-----------------------------------------------------------
Training on reanalysis (what the weather actually was, reconstructed
afterwards) and serving on forecasts is train/serve skew: the model learns to
lean on a precision serving can never supply. `src/providers/open_meteo.py`
read reanalysis for past kickoffs until 2026-09-26 (DEBT 155); it now reads the
same archived forecast at the same hour as this script, and this script imports
its cutoff, lead time, hour function and variable set so the two cannot drift.

This script therefore uses the **Historical Forecast API**
(`historical-forecast-api.open-meteo.com`), which archives the forecasts that
were actually published — Rule 4 Category A, historically reconstructable.

⚠️ MEASURED 2026-09-11: THAT API SILENTLY FALLS BACK TO REANALYSIS
-------------------------------------------------------------------
Before its own archive begins, the Historical Forecast API returns ERA5 values
with HTTP 200 and no warning. Probed at Liverpool (53.41/-2.98), comparing the
two endpoints hour by hour:

    2019-08-09  identical to ERA5   max diff 0.00 degC
    2021-08-01  identical to ERA5   max diff 0.00
    2021-12-01  identical to ERA5   max diff 0.00
    2022-01-01  identical to ERA5   max diff 0.00
    2022-03-01  DIFFERS             max diff 2.50
    2022-06-01  DIFFERS             max diff 3.60
    2024-08-17  DIFFERS             max diff 2.50
    2025-08-16  DIFFERS             max diff 3.10

So a naive backfill over the whole corpus would quietly train three of seven
seasons on post-hoc actuals — the exact leak Rule 3 exists to prevent, and
invisible because every response is a well-formed 200. `_FORECAST_ARCHIVE_START`
is a hard cutoff: a fixture before it is recorded as a gap with reason
`NO_ARCHIVED_FORECAST`, never filled from reanalysis.

VENUE COORDINATES ARE DERIVED, NEVER AUTHORED
----------------------------------------------
`docs/DEBT.md` item 44 rejected hand-entered stadium coordinates outright:
"Hand-entered or model-recalled coordinates are invented reference data, and
wrong ones produce *confidently wrong* weather, which is worse than no
weather." This script therefore reads the geocoded, auditable manifest that
`qualify_venue_locations.py` produced and uses **VERIFIED clubs only**.
`REQUIRES_REVIEW` and `UNKNOWN` clubs are skipped and counted, pending the
bounded operator review item 44 asks for.

Usage
-----
    cd backend && PYTHONPATH=. python scripts/ingest_openmeteo_weather.py --dry-run
    cd backend && PYTHONPATH=. python scripts/ingest_openmeteo_weather.py
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import polars as pl

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

from src.providers.open_meteo import (  # noqa: E402 - needs the sys.path insert above
    FORECAST_ARCHIVE_START,
    FORECAST_LEAD_HOURS,
    HISTORICAL_FORECAST_BASE,
    HOURLY_VARIABLES,
    forecast_valid_hour,
)

_HISTORICAL_FORECAST_BASE = HISTORICAL_FORECAST_BASE
_CORPUS_DIR = _BACKEND_ROOT / "data" / "cache"
_VENUE_MANIFEST = (
    _BACKEND_ROOT.parent
    / "reports"
    / "research"
    / "portfolio-f-venue-location-manifest.json"
)
_OUT_PARQUET = _BACKEND_ROOT / "data" / "cache" / "weather_forecasts_f1.parquet"
_REPORT_PATH = (
    _BACKEND_ROOT.parent
    / "reports"
    / "research"
    / "portfolio-f-weather-forecast-gates.json"
)

# Owned by the provider (DEBT 155); aliased here for this script's callers.
# 2022-03-01 is the conservative side of the measured reanalysis boundary.
_FORECAST_ARCHIVE_START = FORECAST_ARCHIVE_START
_CUTOFF_HOURS_PRE_KICKOFF = FORECAST_LEAD_HOURS
_HOURLY_VARIABLES = HOURLY_VARIABLES

# Parquet column per variable, unit in the name. F3's file predates wind,
# gusts and humidity; it is left untouched and new runs write a new file.
_COLUMN = {
    "temperature_2m": "temperature_2m_c",
    "precipitation": "precipitation_mm",
    "wind_speed_10m": "wind_speed_10m_kmh",
    "wind_gusts_10m": "wind_gusts_10m_kmh",
    "relative_humidity_2m": "relative_humidity_2m_pct",
}

_DIV_TO_LEAGUE: Dict[str, str] = {
    "E0": "EPL",
    "SP1": "LA_LIGA",
    "I1": "SERIE_A",
    "D1": "BUNDESLIGA",
    "F1": "LIGUE_1",
    "N1": "EREDIVISIE",
}

GAP_NO_VENUE = "VENUE_NOT_VERIFIED"
GAP_NO_ARCHIVE = "NO_ARCHIVED_FORECAST"
GAP_NO_KICKOFF_TIME = "KICKOFF_TIME_UNAVAILABLE"
GAP_FETCH_FAILED = "FETCH_FAILED"
GAP_HOUR_MISSING = "FORECAST_HOUR_MISSING"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def load_verified_venues() -> Dict[str, Tuple[float, float]]:
    """club name -> (lat, lon) for VERIFIED clubs only.

    Rule 5: a REQUIRES_REVIEW or UNKNOWN club yields no coordinate at all. It is
    never approximated from a neighbouring club, a league centroid, or memory.

    DEBT 101: reads the candidate `classify()` actually confirmed, never
    `candidates[0]`. Sheffield United was correct only by accident of geocoder
    response order -- "Sheffield" (confirmed) happened to arrive before
    "United Kingdom" (unconfirmed, from tokenising "united"). A reordered
    upstream response would have silently swapped in the country centroid
    while the manifest still said VERIFIED. A manifest generated before this
    field existed has no `confirmed` key on any candidate; that case falls
    back to `candidates[0]` with a logged warning naming the club, rather than
    failing closed on every venue at once for a schema difference alone.
    """
    manifest = json.loads(_VENUE_MANIFEST.read_text(encoding="utf-8"))
    venues: Dict[str, Tuple[float, float]] = {}
    stale_manifest_fallbacks: List[str] = []
    for entry in manifest["entries"]:
        if entry.get("verdict") != "VERIFIED":
            continue
        candidates = entry.get("candidates") or []
        if not candidates:
            continue
        chosen = next((c for c in candidates if c.get("confirmed") is True), None)
        if chosen is None:
            chosen = candidates[0]
            stale_manifest_fallbacks.append(entry["club"])
        lat, lon = chosen.get("latitude"), chosen.get("longitude")
        if lat is None or lon is None:
            continue
        venues[entry["club"]] = (float(lat), float(lon))
    if stale_manifest_fallbacks:
        logger.warning(
            "%d VERIFIED club(s) have no 'confirmed' candidate marker -- "
            "manifest predates DEBT 101; fell back to candidates[0]: %s",
            len(stale_manifest_fallbacks),
            ", ".join(stale_manifest_fallbacks),
        )
    logger.info(
        "Venue manifest: %d VERIFIED of %d clubs (%s)",
        len(venues),
        manifest["roster_size"],
        manifest["counts"],
    )
    return venues


def _parse_date(raw: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(raw: str) -> Tuple[int, int] | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parts = raw.split(":")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return None


def load_fixtures() -> List[Dict[str, Any]]:
    """Corpus fixtures with their kickoff CLOCK TIME, which load_matches drops.

    `train_on_real_matches.load_matches` parses only the date, but a T-2h
    forecast needs the hour. The `Time` column is real corpus data in both
    CSV vocabularies; a row without it is a gap, not a guessed 15:00 kickoff.
    """
    fixtures: List[Dict[str, Any]] = []
    for path in sorted(_CORPUS_DIR.glob("fd_*.csv")):
        div = path.stem.split("_")[1]
        league = _DIV_TO_LEAGUE.get(div)
        if league is None:
            continue
        code = path.stem.rsplit("_", 1)[-1]
        season = f"20{code[:2]}/20{code[2:]}" if len(code) == 4 else code
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                kickoff_date = _parse_date(row.get("date") or row.get("Date") or "")
                home = (row.get("home_team") or row.get("HomeTeam") or "").strip()
                away = (row.get("away_team") or row.get("AwayTeam") or "").strip()
                if not kickoff_date or not home:
                    continue
                fixtures.append(
                    {
                        "league": league,
                        "season": season,
                        "season_code": code,
                        "kickoff_date": kickoff_date,
                        "kickoff_clock": _parse_time(row.get("Time") or ""),
                        "home_team": home,
                        "away_team": away,
                    }
                )
    logger.info("Corpus: %d fixtures", len(fixtures))
    return fixtures


# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------


def fetch_venue_window(
    lat: float, lon: float, start: date, end: date, *, retries: int = 3
) -> Dict[str, Any]:
    """One request per venue per date-window, not one per fixture.

    116 venues instead of 12,765 fixtures. `timezone=auto` returns venue-local
    timestamps, which is the same clock the corpus `Time` column is stated in,
    so the two are compared without a timezone database.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(_HOURLY_VARIABLES),
        "timezone": "auto",
    }
    url = f"{_HISTORICAL_FORECAST_BASE}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=90) as response:
                return json.load(response)
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            logger.warning("retry %d for %.2f/%.2f: %s", attempt + 1, lat, lon, exc)
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def index_hourly(payload: Dict[str, Any]) -> Dict[str, Dict[str, float | None]]:
    """stamp -> {variable: value or None}. An absent series is None, never 0."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    series = {v: hourly.get(v) or [] for v in _HOURLY_VARIABLES}
    return {
        stamp: {v: (s[i] if i < len(s) else None) for v, s in series.items()}
        for i, stamp in enumerate(times)
    }


def build_rows(
    fixtures: List[Dict[str, Any]],
    venues: Dict[str, Tuple[float, float]],
    *,
    dry_run_limit: int | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Resolve each fixture to its T-2h forecast, or to an explicit gap."""
    gaps: Dict[str, int] = defaultdict(int)
    eligible: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for fixture in fixtures:
        if fixture["home_team"] not in venues:
            gaps[GAP_NO_VENUE] += 1
            continue
        if fixture["kickoff_date"] < _FORECAST_ARCHIVE_START:
            gaps[GAP_NO_ARCHIVE] += 1
            continue
        if fixture["kickoff_clock"] is None:
            gaps[GAP_NO_KICKOFF_TIME] += 1
            continue
        eligible[fixture["home_team"]].append(fixture)

    clubs = sorted(eligible)
    if dry_run_limit is not None:
        clubs = clubs[:dry_run_limit]

    rows: List[Dict[str, Any]] = []
    for position, club in enumerate(clubs, start=1):
        club_fixtures = eligible[club]
        lat, lon = venues[club]
        start = min(f["kickoff_date"] for f in club_fixtures) - timedelta(days=1)
        end = max(f["kickoff_date"] for f in club_fixtures) + timedelta(days=1)
        try:
            payload = fetch_venue_window(lat, lon, start, end)
        except Exception as exc:  # noqa: BLE001
            logger.error("%s: fetch failed — %s", club, exc)
            gaps[GAP_FETCH_FAILED] += len(club_fixtures)
            continue

        hourly = index_hourly(payload)
        for fixture in club_fixtures:
            hour, minute = fixture["kickoff_clock"]
            kickoff_local = datetime.combine(
                fixture["kickoff_date"], datetime.min.time()
            ).replace(hour=hour, minute=minute)
            cutoff = forecast_valid_hour(kickoff_local)
            key = cutoff.strftime("%Y-%m-%dT%H:00")
            observation = hourly.get(key)
            if observation is None or observation.get("temperature_2m") is None:
                gaps[GAP_HOUR_MISSING] += 1
                continue
            rows.append(
                {
                    "league": fixture["league"],
                    "season": fixture["season"],
                    "kickoff_date": fixture["kickoff_date"],
                    "kickoff_local": kickoff_local,
                    "forecast_valid_local": cutoff,
                    "cutoff_hours_pre_kickoff": _CUTOFF_HOURS_PRE_KICKOFF,
                    "home_team": fixture["home_team"],
                    "away_team": fixture["away_team"],
                    "latitude": lat,
                    "longitude": lon,
                    **{
                        _COLUMN[v]: (
                            float(observation[v]) if observation[v] is not None else None
                        )
                        for v in _HOURLY_VARIABLES
                    },
                    "source": "open-meteo historical-forecast-api",
                    "timezone_mode": "auto (venue-local); corpus Time assumed venue-local",
                }
            )
        logger.info(
            "  [%d/%d] %s: %d fixtures", position, len(clubs), club, len(club_fixtures)
        )
        time.sleep(0.2)

    return rows, dict(gaps)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch a single venue and write nothing"
    )
    parser.add_argument("--out", type=Path, default=_OUT_PARQUET)
    # A run for another experiment must not overwrite F3's evidence report.
    parser.add_argument("--report", type=Path, default=_REPORT_PATH)
    parser.add_argument("--experiment-id", default="F3")
    args = parser.parse_args()

    venues = load_verified_venues()
    fixtures = load_fixtures()
    rows, gaps = build_rows(fixtures, venues, dry_run_limit=1 if args.dry_run else None)

    frame = pl.DataFrame(rows) if rows else pl.DataFrame()
    total = len(fixtures)
    matched = len(rows)

    # Gate G1 over the whole corpus, and again over only the window where an
    # archived forecast can exist at all — the second is the number that says
    # whether the SOURCE is viable, as distinct from the corpus being older
    # than the archive.
    in_window = [f for f in fixtures if f["kickoff_date"] >= _FORECAST_ARCHIVE_START]
    report = {
        "experiment_id": args.experiment_id,
        "hourly_variables": list(_HOURLY_VARIABLES),
        "generated_at": datetime.now().astimezone().isoformat(),
        "source": "Open-Meteo Historical Forecast API",
        "source_license_class": "L0",
        "endpoint": _HISTORICAL_FORECAST_BASE,
        "rule_3_note": (
            "Archived FORECASTS, not ERA5 reanalysis. The endpoint silently "
            "falls back to reanalysis before its archive begins, so fixtures "
            f"before {_FORECAST_ARCHIVE_START.isoformat()} are refused rather "
            "than filled with post-hoc actuals."
        ),
        "forecast_archive_start": _FORECAST_ARCHIVE_START.isoformat(),
        "cutoff_hours_pre_kickoff": _CUTOFF_HOURS_PRE_KICKOFF,
        "corpus_fixtures": total,
        "fixtures_in_forecast_window": len(in_window),
        "matched_fixtures": matched,
        "gates": {
            "G1_whole_corpus_pct": round(100.0 * matched / total, 2) if total else 0.0,
            "G1_within_forecast_window_pct": (
                round(100.0 * matched / len(in_window), 2) if in_window else 0.0
            ),
            "threshold_pct": 85.0,
            "G5_prediction_time_availability": (
                "STRUCTURALLY SATISFIED — the same endpoint family serves a "
                "16-day forward forecast, so an upcoming fixture is answerable "
                "at the same T-2h cutoff. Not yet measured against live "
                "fixtures; that requires a prospective probe."
            ),
        },
        "gaps": gaps,
        "venues_verified": len(venues),
        "dry_run": bool(args.dry_run),
    }

    if args.dry_run:
        logger.info("DRY RUN — no parquet written")
        print(json.dumps(report, indent=2, default=str))
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(args.out)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote %s (%d rows) and %s", args.out, frame.height, args.report)
    print(json.dumps(report["gates"], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
