#!/usr/bin/env python3
"""Populate Elo parquet snapshots from finished matches (Phase 7-A)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.src.core.database import Match, session_scope  # noqa: E402
from backend.src.data.elo_engine import EloEngine  # noqa: E402


def _build_from_db(engine: EloEngine, limit: int | None = None) -> int:
    updated = 0
    try:
        with session_scope() as db:
            query = (
                db.query(Match)
                .filter(Match.status == "finished")
                .filter(Match.home_score.isnot(None), Match.away_score.isnot(None))
                .order_by(Match.match_date.asc())
            )
            if limit:
                query = query.limit(limit)

            for match in query.all():
                league = str(match.league_id or "unknown")
                season = str(match.season or "unknown")
                match_date = match.match_date or datetime.utcnow()
                engine.update_after_match(
                    match_id=str(match.id),
                    home_team_id=str(match.home_team_id),
                    away_team_id=str(match.away_team_id),
                    home_goals=int(match.home_score),
                    away_goals=int(match.away_score),
                    league=league,
                    season=season,
                    match_date=match_date,
                )
                updated += 1
    except Exception:
        return 0
    return updated


def _build_from_training_csv(engine: EloEngine, data_dir: Path, limit: int | None = None) -> int:
    """Fallback when DB has no finished matches; uses CSV rows with synthetic team IDs."""
    csv_paths = sorted(data_dir.glob("*_training.csv"))
    updated = 0

    for csv_path in csv_paths:
        league = csv_path.stem.replace("_training", "")
        frame = pd.read_csv(csv_path)
        if "result" not in frame.columns:
            continue

        if "match_date" in frame.columns:
            frame["match_date"] = pd.to_datetime(frame["match_date"], errors="coerce")
            frame = frame.sort_values("match_date")
        else:
            frame["match_date"] = pd.Timestamp("2023-01-01") + pd.to_timedelta(frame.index, unit="D")

        for idx, row in frame.iterrows():
            if limit and updated >= limit:
                return updated
            result = row.get("result")
            label = str(result)
            if label in {"home_win", "H", "0", "0.0"}:
                home_goals, away_goals = 2, 1
            elif label in {"away_win", "A", "2", "2.0"}:
                home_goals, away_goals = 1, 2
            else:
                home_goals, away_goals = 1, 1

            match_date = row.get("match_date")
            if pd.isna(match_date):
                match_date = pd.Timestamp("2023-01-01") + pd.to_timedelta(idx, unit="D")

            match_id = str(row.get("match_id") or f"{league}-csv-{idx}")
            season = str(row.get("season") or "fallback")

            # Deterministic synthetic team IDs preserve idempotency for replayed runs.
            home_team_id = f"{league}_home_{idx % 20}"
            away_team_id = f"{league}_away_{(idx + 7) % 20}"

            engine.update_after_match(
                match_id=match_id,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                home_goals=home_goals,
                away_goals=away_goals,
                league=league,
                season=season,
                match_date=pd.Timestamp(match_date).to_pydatetime(),
            )
            updated += 1

    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Populate Elo parquet snapshots")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "elo_ratings.parquet",
        help="Destination Elo parquet path",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed",
        help="Training CSV directory for fallback generation",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of matches to process",
    )
    args = parser.parse_args()

    engine = EloEngine(parquet_path=args.output)

    updates = _build_from_db(engine, limit=args.limit)
    source = "database"
    if updates == 0:
        updates = _build_from_training_csv(engine, data_dir=args.data_dir, limit=args.limit)
        source = "training_csv_fallback"

    print(f"Populated {args.output} with {updates} updates (source={source})")
    return 0 if updates > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
