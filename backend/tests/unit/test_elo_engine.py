"""Unit tests for EloEngine.seed_from_matches.

The load-bearing contract: without seeding, every team has zero rating
history, so get_context() always falls back to the neutral 1500/1500
baseline and elo_difference == 0.0 is indistinguishable from two genuinely
equal teams (see the *_resolved flags and the comment in
upcoming_match_feature_service.py). Seeding must produce real, non-neutral
ratings, must be idempotent, and must apply updates in chronological order
regardless of input order.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.data.elo_engine import EloEngine, EloSeedMatch


def _match(match_id: str, home: str, away: str, hg: int, ag: int, date: datetime) -> EloSeedMatch:
    return EloSeedMatch(
        match_id=match_id,
        home_team_id=home,
        away_team_id=away,
        home_goals=hg,
        away_goals=ag,
        league="EPL",
        season="2025/2026",
        match_date=date,
    )


def test_unseeded_team_is_unresolved_neutral_baseline(tmp_path: Path):
    engine = EloEngine(parquet_path=tmp_path / "elo.parquet")
    ctx = engine.get_context("t1", "t2", "EPL", "2025/2026", datetime(2026, 8, 20))
    assert ctx.home_resolved is False
    assert ctx.away_resolved is False
    assert ctx.elo_difference == 0.0


def test_seeding_produces_resolved_non_neutral_ratings(tmp_path: Path):
    engine = EloEngine(parquet_path=tmp_path / "elo.parquet")
    matches = [
        _match("m1", "t1", "t2", 3, 0, datetime(2026, 8, 1)),   # t1 dominant win
        _match("m2", "t2", "t1", 0, 2, datetime(2026, 8, 8)),   # t1 wins again
    ]
    applied = engine.seed_from_matches(matches)
    assert applied == 2

    ctx = engine.get_context("t1", "t2", "EPL", "2025/2026", datetime(2026, 8, 20))
    assert ctx.home_resolved is True
    assert ctx.away_resolved is True
    # t1 won both meetings — its rating must have risen above the 1500 baseline,
    # and above t2's.
    assert ctx.home_elo > 1500.0
    assert ctx.elo_difference > 0.0


def test_seeding_is_idempotent(tmp_path: Path):
    engine = EloEngine(parquet_path=tmp_path / "elo.parquet")
    matches = [_match("m1", "t1", "t2", 1, 0, datetime(2026, 8, 1))]

    first = engine.seed_from_matches(matches)
    ctx_after_first = engine.get_context("t1", "t2", "EPL", "2025/2026", datetime(2026, 8, 20))

    second = engine.seed_from_matches(matches)  # re-run, same data
    ctx_after_second = engine.get_context("t1", "t2", "EPL", "2025/2026", datetime(2026, 8, 20))

    assert first == 1
    assert second == 0  # nothing new applied
    assert ctx_after_first.home_elo == ctx_after_second.home_elo


def test_seeding_applies_chronologically_regardless_of_input_order(tmp_path: Path):
    """Feed the second match before the first — ratings must still reflect the
    real chronology, not the order the caller happened to supply."""
    engine_in_order = EloEngine(parquet_path=tmp_path / "in_order.parquet")
    engine_in_order.seed_from_matches([
        _match("m1", "t1", "t2", 2, 0, datetime(2026, 8, 1)),
        _match("m2", "t1", "t2", 2, 0, datetime(2026, 8, 8)),
    ])

    engine_reversed = EloEngine(parquet_path=tmp_path / "reversed.parquet")
    engine_reversed.seed_from_matches([
        _match("m2", "t1", "t2", 2, 0, datetime(2026, 8, 8)),
        _match("m1", "t1", "t2", 2, 0, datetime(2026, 8, 1)),
    ])

    ctx_ordered = engine_in_order.get_context("t1", "t2", "EPL", "2025/2026", datetime(2026, 8, 20))
    ctx_reversed = engine_reversed.get_context("t1", "t2", "EPL", "2025/2026", datetime(2026, 8, 20))
    assert ctx_ordered.home_elo == ctx_reversed.home_elo


if __name__ == "__main__":
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        test_unseeded_team_is_unresolved_neutral_baseline(p)
        test_seeding_produces_resolved_non_neutral_ratings(p)
        test_seeding_is_idempotent(p)
        test_seeding_applies_chronologically_regardless_of_input_order(p)
    print("elo_engine seeding: all checks passed")
    sys.exit(0)
