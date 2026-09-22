#!/usr/bin/env python3
"""Export real served-prediction / market evidence for the G11 and G18
certification harnesses (``evaluate_g11_ece.py``, ``evaluate_g18_bootstrap.py``).

Corrections applied relative to the original request, recorded here rather
than silently:

1. **No mock/offline fallback that produces usable evidence.** The request
   asked for "fallback to SQLite/S3 mock if offline". Silently substituting
   synthetic rows into ``artifacts/evidence/*.csv`` -- the exact path the real
   certification harnesses read -- is a fabrication risk: nothing downstream
   could tell a mocked file from a real one. Per INV-02 ("missing... evidence
   fails closed"), this script FAILS CLOSED with a clear error when the real
   database is unreachable. ``--dry-run`` instead exercises the query/export
   logic against an in-memory synthetic fixture and refuses to write to the
   real evidence path -- see ``_dry_run_records()``.
2. **Output schema matches what the harnesses actually parse**, not an
   invented schema. Read directly from ``evaluate_g11_ece.py``'s ``load()``
   and ``evaluate_g18_bootstrap.py``'s ``load()``:
   - G11 needs flat columns ``home_win_prob,draw_prob,away_win_prob,result``
     (+ optional ``league``, ``generation_id``). No ``raw_probs``/
     ``calibrated_probs`` split exists in either the harness or the schema --
     ``MatchPredictionLog`` logs one set of probabilities per row, honestly
     labelled by ``calibration_method`` (see prediction.py, commit 808a42e).
   - G18 needs ``date,home_win_prob,draw_prob,away_win_prob,result`` plus
     either Bet365/Pinnacle-tier odds columns or generic
     ``home_odds,draw_odds,away_odds,bookmaker``.
3. **Reuses the existing repository layer**, not a hand-rolled query, for
   G11: ``repositories.fixtures.get_settled_predictions()`` already does the
   latest-prediction-per-match join, scoped to one ``model_version`` to avoid
   the cross-generation pooling bug its own docstring documents (production
   match ``fd-564632`` carries both a ``v5_phase7`` and ``v6_phase8`` row).
   G18 needs prediction + market + outcome joined on the *same* match in one
   row, which no existing function returns (``get_settled_predictions``
   omits market data, ``get_clv_records`` omits the outcome and returns
   already-devigged probabilities rather than raw odds). Rather than extend
   the shared, tested query builders in ``repositories/fixtures.py``, the
   join lives in ``_g18_query()`` below, built from the *same* proven
   filters (``is_closing_line``, ``coherent``, ``captured_at < match_date``,
   ``created_at < match_date``, single ``model_version``) so the risk stays
   contained to this new, non-serving-path file.
4. Deterministic evidence lineage (a new script, not a certification-policy
   change -- no OG-06 needed): every export writes a companion
   ``<output>.manifest.json`` with generated_at (UTC), git SHA, model_version,
   league filter, row count, and the exact query parameters used.

Usage (matches the repository's PYTHONPATH convention for backend scripts):

    cd backend
    PYTHONPATH=. python scripts/export_production_evidence.py \\
        --model-version v5_phase7 [--league EPL] \\
        --output-dir ../artifacts/evidence

    PYTHONPATH=. python scripts/export_production_evidence.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

G11_FIELDS = [
    "home_win_prob",
    "draw_prob",
    "away_win_prob",
    "result",
    "league",
    "generation_id",
]
G18_FIELDS = [
    "date",
    "home_win_prob",
    "draw_prob",
    "away_win_prob",
    "home_odds",
    "draw_odds",
    "away_odds",
    "bookmaker",
    "result",
    "league",
]
_OUTCOME_LABEL = {0: "H", 1: "D", 2: "A"}


def git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except Exception:
        return os.getenv("SABISCORE_GIT_SHA")


def _write_csv(rows: list[dict[str, Any]], fields: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_manifest(
    path: Path,
    *,
    kind: str,
    model_version: str,
    league: str | None,
    row_count: int,
    query_params: dict[str, Any],
) -> None:
    manifest = {
        "kind": kind,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit_sha": git_sha(),
        "model_version": model_version,
        "league_filter": league,
        "row_count": row_count,
        "query_params": query_params,
        "output_file": path.name,
        "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest()
        if path.exists()
        else None,
    }
    path.with_suffix(path.suffix + ".manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _dry_run_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Synthetic, clearly-fake fixture for exercising the export/write path
    with no database. Never written to the real evidence path -- see main()."""
    g11_rows = [
        {
            "home_win_prob": 0.45,
            "draw_prob": 0.28,
            "away_win_prob": 0.27,
            "result": "H",
            "league": "EPL",
            "generation_id": "dry_run_synthetic",
        },
        {
            "home_win_prob": 0.31,
            "draw_prob": 0.30,
            "away_win_prob": 0.39,
            "result": "A",
            "league": "EPL",
            "generation_id": "dry_run_synthetic",
        },
    ]
    g18_rows = [
        {
            "date": "2026-01-05",
            "home_win_prob": 0.45,
            "draw_prob": 0.28,
            "away_win_prob": 0.27,
            "home_odds": 2.10,
            "draw_odds": 3.40,
            "away_odds": 3.60,
            "bookmaker": "dry_run_synthetic",
            "result": "H",
            "league": "EPL",
        },
    ]
    return g11_rows, g18_rows


def _g18_query(*, model_version: str, league: str | None, limit: int):
    """Prediction + closing-line + outcome, joined on one match, one row per
    match. Mirrors the window-function pattern of
    repositories.fixtures.build_settled_predictions_query /
    build_clv_records_query -- not a copy of either, since neither returns
    this combined shape -- kept local to this script rather than added to
    the shared repository module (see module docstring, point 3)."""
    from sqlalchemy import func, select

    from src.core.database import Match
    from src.db.models import MarketSnapshot, MatchPredictionLog

    ranked_prediction = (
        select(
            MatchPredictionLog.match_id,
            MatchPredictionLog.home_probability,
            MatchPredictionLog.draw_probability,
            MatchPredictionLog.away_probability,
            func.row_number()
            .over(
                partition_by=MatchPredictionLog.match_id,
                order_by=(
                    MatchPredictionLog.created_at.desc(),
                    MatchPredictionLog.id.desc(),
                ),
            )
            .label("rank"),
        )
        .join(Match, MatchPredictionLog.match_id == Match.id)
        .where(
            MatchPredictionLog.model_version == model_version,
            MatchPredictionLog.created_at < Match.match_date,
        )
        .subquery()
    )
    ranked_closing = (
        select(
            MarketSnapshot.match_id,
            MarketSnapshot.home_odds,
            MarketSnapshot.draw_odds,
            MarketSnapshot.away_odds,
            MarketSnapshot.bookmaker,
            func.row_number()
            .over(
                partition_by=MarketSnapshot.match_id,
                order_by=(MarketSnapshot.captured_at.desc(), MarketSnapshot.id.desc()),
            )
            .label("rank"),
        )
        .join(Match, MarketSnapshot.match_id == Match.id)
        .where(
            MarketSnapshot.is_closing_line.is_(True),
            MarketSnapshot.coherent.is_(True),
            MarketSnapshot.captured_at < Match.match_date,
        )
        .subquery()
    )
    query = (
        select(
            Match.match_date,
            Match.league_id,
            Match.home_score,
            Match.away_score,
            ranked_prediction.c.home_probability,
            ranked_prediction.c.draw_probability,
            ranked_prediction.c.away_probability,
            ranked_closing.c.home_odds,
            ranked_closing.c.draw_odds,
            ranked_closing.c.away_odds,
            ranked_closing.c.bookmaker,
        )
        .select_from(Match)
        .join(
            ranked_prediction,
            (ranked_prediction.c.match_id == Match.id)
            & (ranked_prediction.c.rank == 1),
        )
        .join(
            ranked_closing,
            (ranked_closing.c.match_id == Match.id) & (ranked_closing.c.rank == 1),
        )
        .where(
            Match.status == "finished",
            Match.home_score.is_not(None),
            Match.away_score.is_not(None),
        )
        .order_by(Match.match_date.asc())
        .limit(limit)
    )
    if league:
        query = query.where(Match.league_id == league)
    return query


async def _export_real(
    *, model_version: str, league: str | None, limit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from src.db.session import AsyncSessionLocal
    from src.repositories.fixtures import get_settled_predictions

    if AsyncSessionLocal is None:
        raise RuntimeError(
            "DATABASE_URL is not configured / the DB session factory is unavailable. "
            "Failing closed per INV-02 rather than substituting mock evidence -- use --dry-run "
            "to exercise the export logic without a database."
        )

    g11_rows: list[dict[str, Any]] = []
    g18_rows: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as session:
        settled = await get_settled_predictions(
            session, model_version=model_version, league=league, limit=limit
        )
        for record in settled:
            probs = record["probs"]
            g11_rows.append(
                {
                    "home_win_prob": probs[0],
                    "draw_prob": probs[1],
                    "away_win_prob": probs[2],
                    "result": _OUTCOME_LABEL[record["outcome"]],
                    "league": league or "",
                    "generation_id": model_version,
                }
            )

        result = await session.execute(
            _g18_query(model_version=model_version, league=league, limit=limit)
        )
        for row in result.all():
            (
                match_date,
                league_id,
                home_score,
                away_score,
                hp,
                dp,
                ap,
                ho,
                do,
                ao,
                bookmaker,
            ) = row
            outcome = (
                0 if home_score > away_score else (1 if home_score == away_score else 2)
            )
            g18_rows.append(
                {
                    "date": match_date.strftime("%Y-%m-%d"),
                    "home_win_prob": hp,
                    "draw_prob": dp,
                    "away_win_prob": ap,
                    "home_odds": ho,
                    "draw_odds": do,
                    "away_odds": ao,
                    "bookmaker": bookmaker,
                    "result": _OUTCOME_LABEL[outcome],
                    "league": league_id,
                }
            )
    return g11_rows, g18_rows


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Export served-prediction/market evidence for G11 and G18"
    )
    ap.add_argument(
        "--model-version",
        help="Required unless --dry-run; e.g. v5_phase7. Scoping avoids cross-generation pooling (see module docstring).",
    )
    ap.add_argument(
        "--league",
        default=None,
        help="Canonical league id filter, e.g. EPL. Omit for all leagues.",
    )
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument(
        "--output-dir", type=Path, default=REPO_ROOT / "artifacts" / "evidence"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Exercise export/write logic on a synthetic fixture; never writes to --output-dir.",
    )
    args = ap.parse_args()

    if args.dry_run:
        g11_rows, g18_rows = _dry_run_records()
        out_dir = REPO_ROOT / "artifacts" / "evidence" / "_dry_run"
        model_version = "dry_run_synthetic"
    else:
        if not args.model_version:
            print(
                "ERROR: --model-version is required for a real export (omit only with --dry-run).",
                file=sys.stderr,
            )
            return 2
        try:
            g11_rows, g18_rows = asyncio.run(
                _export_real(
                    model_version=args.model_version,
                    league=args.league,
                    limit=args.limit,
                )
            )
        except Exception as exc:
            print(f"BLOCKED: {exc}", file=sys.stderr)
            return 1
        out_dir = args.output_dir
        model_version = args.model_version

    g11_path = out_dir / f"g11_predictions_{model_version}.csv"
    g18_path = out_dir / f"g18_candidate_market_{model_version}.csv"
    _write_csv(g11_rows, G11_FIELDS, g11_path)
    _write_csv(g18_rows, G18_FIELDS, g18_path)
    _write_manifest(
        g11_path,
        kind="g11_settled_predictions",
        model_version=model_version,
        league=args.league,
        row_count=len(g11_rows),
        query_params={"limit": args.limit, "dry_run": args.dry_run},
    )
    _write_manifest(
        g18_path,
        kind="g18_candidate_market",
        model_version=model_version,
        league=args.league,
        row_count=len(g18_rows),
        query_params={"limit": args.limit, "dry_run": args.dry_run},
    )

    print(
        json.dumps(
            {
                "g11_rows": len(g11_rows),
                "g18_rows": len(g18_rows),
                "g11_path": str(g11_path),
                "g18_path": str(g18_path),
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    if not args.dry_run and (len(g11_rows) < 50 or len(g18_rows) < 50):
        print(
            "NOTE: below the 50-row floor both harnesses require; they will report BLOCKED, not a fabricated pass.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
