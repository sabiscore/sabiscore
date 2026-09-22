"""Backfill V4/Phase 9 source artefacts without touching production models.

This script fetches from football-data.org and Understat/soccerdata and writes
Parquet + JSON artefacts for offline feature research and walk-forward retraining.
It does NOT modify any live model, config, or database.

Examples
--------
# Single league, dry run (prints what would run, touches nothing):
cd backend
python scripts/backfill_v4_data_sources.py --league epl --season 2025 --dry-run

# Full EPL season:
FOOTBALL_DATA_API_KEY=your_key python scripts/backfill_v4_data_sources.py \
    --league epl --season 2025 --out ../data/processed/v4_sources

# All 5 leagues, Understat only:
python scripts/backfill_v4_data_sources.py \
    --all-leagues --season 2025 --skip-football-data \
    --out ../data/processed/v4_sources

# Read API key from env; skip Understat (no soccerdata installed):
FOOTBALL_DATA_API_KEY=xxx python scripts/backfill_v4_data_sources.py \
    --league bundesliga --season 2025 --skip-understat

Notes
-----
- The default output directory matches ``settings.phase9_sources_path``
  (``data/processed/v4_sources``) when run from the repo root via
  ``PHASE9_SOURCES_PATH``, but this script has no hard dependency on
  ``src.core.config`` — it reads the env var directly so it can run before
  the full settings stack (DB, Redis, etc.) is configured.
- Artefacts produced here are NOT automatically picked up by
  ``DataAggregator`` or ``PredictionService``. They are inputs to the
  Stage 4 offline retraining / SHAP-ablation workflow described in
  ``docs/V4_PHASE9_SHADOW_MODE.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Allow execution from both repo root and backend/.
# ---------------------------------------------------------------------------

_CURRENT = Path(__file__).resolve()
_BACKEND_ROOT = _CURRENT.parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# noqa: E402 — must be after sys.path manipulation
from src.connectors.football_data_org import FootballDataOrgClient  # noqa: E402
from src.connectors.understat_source import UnderstatTeamXGSource  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_LEAGUES: list[str] = ["epl", "la_liga", "serie_a", "bundesliga", "ligue_1"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("backfill_v4")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _season_window(season: int) -> tuple[date, date]:
    """Return the (start, end) date range for a given season start year."""
    return date(season, 7, 1), date(season + 1, 6, 30)


def _elapsed(start: float) -> str:
    return f"{time.perf_counter() - start:.1f}s"


# ---------------------------------------------------------------------------
# Per-league backfill
# ---------------------------------------------------------------------------


async def backfill_league(
    *,
    league: str,
    season: int,
    out_dir: Path,
    football_data_key: str | None,
    skip_football_data: bool,
    skip_understat: bool,
    dry_run: bool,
) -> dict[str, Any]:
    """Backfill one league/season and return a manifest entry."""
    manifest: dict[str, Any] = {
        "league": league,
        "season": season,
        "artefacts": [],
        "warnings": [],
    }
    date_from, date_to = _season_window(season)

    # ------------------------------------------------------------------
    # football-data.org
    # ------------------------------------------------------------------
    if not skip_football_data:
        logger.info("[%s/%s] football-data.org - fetching...", league, season)
        if dry_run:
            logger.info("[DRY-RUN] Would fetch football-data.org %s %s", league, season)
            manifest["artefacts"].append(
                {"source": "football-data.org", "status": "dry-run-skipped"}
            )
        else:
            t0 = time.perf_counter()
            try:
                fd_client = FootballDataOrgClient(api_key=football_data_key)
                matches, fd_meta = await fd_client.matches(
                    league=league,
                    season=season,
                    date_from=date_from,
                    date_to=date_to,
                )
                parquet_path = out_dir / f"football_data_org_{league}_{season}.parquet"
                meta_path = out_dir / f"football_data_org_{league}_{season}.json"
                matches.to_parquet(parquet_path, index=False)
                _write_json(meta_path, fd_meta)
                logger.info(
                    "[%s/%s] football-data.org OK %d rows in %s",
                    league,
                    season,
                    len(matches),
                    _elapsed(t0),
                )
                manifest["artefacts"].append(
                    {
                        "source": "football-data.org",
                        "parquet": str(parquet_path),
                        "meta": str(meta_path),
                        "rows": int(len(matches)),
                        "elapsed_s": round(time.perf_counter() - t0, 2),
                    }
                )
            except Exception as exc:
                logger.error("[%s/%s] football-data.org FAILED %s", league, season, exc)
                manifest["warnings"].append(f"football-data.org error: {exc}")

    # ------------------------------------------------------------------
    # Understat / soccerdata
    # ------------------------------------------------------------------
    if not skip_understat:
        logger.info("[%s/%s] Understat - fetching via soccerdata...", league, season)
        if dry_run:
            logger.info("[DRY-RUN] Would fetch Understat %s %s", league, season)
            manifest["artefacts"].append(
                {"source": "understat", "status": "dry-run-skipped"}
            )
        else:
            t0 = time.perf_counter()
            try:
                soccerdata_cache = str(out_dir / ".soccerdata")
                understat = UnderstatTeamXGSource(cache_dir=soccerdata_cache)
                understat_matches, us_meta = understat.team_match_xg(
                    league=league, season=season
                )
                rollups = understat.rolling_xg_features(understat_matches)

                matches_path = out_dir / f"understat_matches_{league}_{season}.parquet"
                rollups_path = out_dir / f"understat_rollups_{league}_{season}.parquet"
                meta_path = out_dir / f"understat_{league}_{season}.json"

                understat_matches.to_parquet(matches_path, index=False)
                rollups.to_parquet(rollups_path, index=False)
                _write_json(meta_path, us_meta)

                logger.info(
                    "[%s/%s] Understat OK %d matches / %d rollup rows in %s",
                    league,
                    season,
                    len(understat_matches),
                    len(rollups),
                    _elapsed(t0),
                )
                manifest["artefacts"].append(
                    {
                        "source": "understat",
                        "matches": str(matches_path),
                        "rollups": str(rollups_path),
                        "meta": str(meta_path),
                        "match_rows": int(len(understat_matches)),
                        "rollup_rows": int(len(rollups)),
                        "elapsed_s": round(time.perf_counter() - t0, 2),
                    }
                )
            except ImportError as exc:
                msg = f"Understat skipped (soccerdata not installed): {exc}"
                logger.warning("[%s/%s] %s", league, season, msg)
                manifest["warnings"].append(msg)
            except Exception as exc:
                logger.error("[%s/%s] Understat FAILED %s", league, season, exc)
                manifest["warnings"].append(f"Understat error: {exc}")

    return manifest


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill SabiScore V4/Phase 9 source artefacts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--league",
        default="epl",
        help=(
            "League slug: epl, la_liga, serie_a, bundesliga, ligue_1. "
            "Ignored when --all-leagues is set."
        ),
    )
    parser.add_argument(
        "--all-leagues",
        action="store_true",
        help="Run all 5 top leagues. Overrides --league.",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=2025,
        help="Season start year (e.g. 2025 for 2025/26).",
    )
    parser.add_argument(
        "--football-data-key",
        default=os.getenv("FOOTBALL_DATA_API_KEY"),
        help="football-data.org API key (or set FOOTBALL_DATA_API_KEY env).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(os.getenv("PHASE9_SOURCES_PATH", "data/processed/v4_sources")),
        help="Output directory for Parquet artefacts and JSON metadata.",
    )
    parser.add_argument(
        "--skip-football-data",
        action="store_true",
        help="Skip football-data.org ingestion.",
    )
    parser.add_argument(
        "--skip-understat",
        action="store_true",
        help="Skip Understat/soccerdata ingestion.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run without writing any files.",
    )
    args = parser.parse_args()

    leagues: list[str] = ALL_LEAGUES if args.all_leagues else [args.league]

    if not args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)

    global_manifest: dict[str, Any] = {
        "season": args.season,
        "leagues": leagues,
        "dry_run": args.dry_run,
        "results": [],
    }

    run_start = time.perf_counter()
    for league in leagues:
        entry = await backfill_league(
            league=league,
            season=args.season,
            out_dir=args.out,
            football_data_key=args.football_data_key,
            skip_football_data=args.skip_football_data,
            skip_understat=args.skip_understat,
            dry_run=args.dry_run,
        )
        global_manifest["results"].append(entry)

    global_manifest["total_elapsed_s"] = round(time.perf_counter() - run_start, 2)

    # Write global manifest.
    manifest_path = args.out / f"manifest_{args.season}.json"
    if not args.dry_run:
        _write_json(manifest_path, global_manifest)
        logger.info("Manifest written to %s", manifest_path)
    else:
        logger.info("[DRY-RUN] Manifest not written.")

    print(json.dumps(global_manifest, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
