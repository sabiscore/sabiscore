"""Unit tests for src/features/pi_ratings.py — no parquet I/O."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from src.features.pi_ratings import PiContext, PiRatingSystem, _DEFAULT_RATING


@pytest.fixture()
def sys() -> PiRatingSystem:
    return PiRatingSystem(parquet_path=None)


_DT = datetime(2024, 9, 14, 15, 0)


# ── get_context defaults ──────────────────────────────────────────────────────


def test_get_context_fresh_returns_defaults(sys):
    ctx = sys.get_context("Arsenal", "Chelsea")
    assert isinstance(ctx, PiContext)
    assert ctx.home_pi_attack == pytest.approx(_DEFAULT_RATING, abs=0.001)
    assert ctx.home_pi_defense == pytest.approx(_DEFAULT_RATING, abs=0.001)
    assert ctx.away_pi_attack == pytest.approx(_DEFAULT_RATING, abs=0.001)
    assert ctx.away_pi_defense == pytest.approx(_DEFAULT_RATING, abs=0.001)
    assert ctx.pi_attack_diff == pytest.approx(0.0, abs=0.001)
    assert ctx.pi_defense_diff == pytest.approx(0.0, abs=0.001)


def test_get_context_does_not_mutate(sys):
    sys.get_context("Arsenal", "Chelsea")
    assert sys._attack["Arsenal"] == _DEFAULT_RATING


# ── update ────────────────────────────────────────────────────────────────────


def test_update_with_goals_changes_ratings(sys):
    sys.update(
        "m1",
        "Arsenal",
        "Chelsea",
        home_goals=3,
        away_goals=1,
        league="EPL",
        match_date=_DT,
    )
    assert (
        sys._attack["Arsenal"] != _DEFAULT_RATING
        or sys._defense["Arsenal"] != _DEFAULT_RATING
    )


def test_update_goalless_draw_no_rating_change(sys):
    sys.update(
        "m0",
        "Arsenal",
        "Chelsea",
        home_goals=0,
        away_goals=0,
        league="EPL",
        match_date=_DT,
    )
    assert sys._attack["Arsenal"] == pytest.approx(_DEFAULT_RATING, abs=0.001)
    assert sys._defense["Arsenal"] == pytest.approx(_DEFAULT_RATING, abs=0.001)


def test_update_idempotent_by_match_id(tmp_path):
    parquet_file = tmp_path / "pi.parquet"
    s = PiRatingSystem(parquet_path=parquet_file)
    s.update(
        "m2",
        "Arsenal",
        "Chelsea",
        home_goals=2,
        away_goals=0,
        league="EPL",
        match_date=_DT,
    )
    attack_after_first = s._attack["Arsenal"]
    s._cache = None  # force table reload from parquet
    s.update(
        "m2",
        "Arsenal",
        "Chelsea",
        home_goals=2,
        away_goals=0,
        league="EPL",
        match_date=_DT,
    )
    assert s._attack["Arsenal"] == pytest.approx(attack_after_first, abs=0.001)


def test_context_after_update_reflects_new_ratings(sys):
    sys.update(
        "m3",
        "Arsenal",
        "Chelsea",
        home_goals=3,
        away_goals=0,
        league="EPL",
        match_date=_DT,
    )
    ctx = sys.get_context("Arsenal", "Chelsea")
    assert ctx.home_pi_attack > ctx.away_pi_attack


def test_sequential_wins_increase_attack(sys):
    for i in range(5):
        sys.update(
            f"g{i}",
            "Arsenal",
            f"Opp{i}",
            home_goals=2,
            away_goals=0,
            league="EPL",
            match_date=_DT,
        )
    assert sys._attack["Arsenal"] > _DEFAULT_RATING


def test_load_table_returns_empty_df_without_parquet(sys):
    df = sys._load_table()
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_replay_empty_noop(sys):
    sys._replay_to_current(pd.DataFrame())
    assert sys._attack["X"] == _DEFAULT_RATING


def test_persist_noop_without_parquet(sys):
    df = pd.DataFrame(columns=sys._COLUMNS)
    sys._persist(df)


# ── PiContext frozen dataclass ─────────────────────────────────────────────────


def test_pi_context_frozen():
    ctx = PiContext(
        home_pi_attack=0.1,
        home_pi_defense=-0.05,
        away_pi_attack=0.0,
        away_pi_defense=0.0,
        pi_attack_diff=0.1,
        pi_defense_diff=0.05,
    )
    with pytest.raises((AttributeError, TypeError)):
        ctx.home_pi_attack = 999.0  # type: ignore[misc]
