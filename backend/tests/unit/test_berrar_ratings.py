"""Unit tests for src/features/berrar_ratings.py — no parquet I/O."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from src.features.berrar_ratings import (
    BerrarContext,
    BerrarRatingSystem,
    _DEFAULT_RATING,
)


@pytest.fixture()
def sys() -> BerrarRatingSystem:
    return BerrarRatingSystem(parquet_path=None)


# ── get_context defaults ──────────────────────────────────────────────────────


def test_get_context_fresh_system_default_ratings(sys):
    ctx = sys.get_context("TeamA", "TeamB")
    assert isinstance(ctx, BerrarContext)
    assert ctx.home_berrar_rating == pytest.approx(_DEFAULT_RATING, abs=0.01)
    assert ctx.away_berrar_rating == pytest.approx(_DEFAULT_RATING, abs=0.01)
    assert ctx.berrar_rating_diff == pytest.approx(0.0, abs=0.01)


def test_get_context_does_not_mutate_ratings(sys):
    sys.get_context("Arsenal", "Chelsea")
    sys.get_context("Arsenal", "Chelsea")
    assert sys._ratings["Arsenal"] == _DEFAULT_RATING


# ── update ────────────────────────────────────────────────────────────────────

_DT = datetime(2024, 9, 14, 15, 0)


def test_update_home_win_raises_home_rating(sys):
    sys.update("m1", "Arsenal", "Chelsea", result=1, league="EPL", match_date=_DT)
    assert sys._ratings["Arsenal"] > _DEFAULT_RATING
    assert sys._ratings["Chelsea"] < _DEFAULT_RATING


def test_update_away_win_raises_away_rating(sys):
    sys.update("m2", "Arsenal", "Chelsea", result=-1, league="EPL", match_date=_DT)
    assert sys._ratings["Chelsea"] > _DEFAULT_RATING
    assert sys._ratings["Arsenal"] < _DEFAULT_RATING


def test_update_draw_symmetric_from_equal_start(sys):
    sys.update("m3", "Arsenal", "Chelsea", result=0, league="EPL", match_date=_DT)
    # From equal starting ratings, draw is symmetric: both stay at _DEFAULT_RATING
    assert sys._ratings["Arsenal"] == pytest.approx(sys._ratings["Chelsea"], abs=0.01)


def test_update_idempotent_by_match_id(tmp_path):
    parquet_file = tmp_path / "berrar.parquet"
    s = BerrarRatingSystem(parquet_path=parquet_file)
    s.update("m4", "Arsenal", "Chelsea", result=1, league="EPL", match_date=_DT)
    rating_after_first = s._ratings["Arsenal"]
    s._cache = None  # force table reload from parquet
    s.update("m4", "Arsenal", "Chelsea", result=1, league="EPL", match_date=_DT)
    assert s._ratings["Arsenal"] == pytest.approx(rating_after_first, abs=0.01)


def test_context_reflects_updated_ratings(sys):
    sys.update("m5", "Arsenal", "Chelsea", result=1, league="EPL", match_date=_DT)
    ctx = sys.get_context("Arsenal", "Chelsea")
    assert ctx.home_berrar_rating > ctx.away_berrar_rating
    assert ctx.berrar_rating_diff > 0.0


def test_sequential_wins_increase_rating(sys):
    for i in range(5):
        sys.update(
            f"m{i}", "Arsenal", "Chelsea", result=1, league="EPL", match_date=_DT
        )
    assert sys._ratings["Arsenal"] > _DEFAULT_RATING + 5


def test_load_table_returns_empty_df_without_parquet(sys):
    df = sys._load_table()
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_replay_to_current_empty_noop(sys):
    sys._replay_to_current(pd.DataFrame())
    assert sys._ratings["SomeTeam"] == _DEFAULT_RATING


def test_persist_noop_without_parquet(sys):
    df = pd.DataFrame(columns=sys._COLUMNS)
    sys._persist(df)


# ── BerrarContext dataclass ───────────────────────────────────────────────────


def test_berrar_context_frozen():
    ctx = BerrarContext(
        home_berrar_rating=1520.0,
        away_berrar_rating=1500.0,
        berrar_rating_diff=20.0,
    )
    with pytest.raises((AttributeError, TypeError)):
        ctx.home_berrar_rating = 9999.0  # type: ignore[misc]
