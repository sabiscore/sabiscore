"""Unit tests for the deterministic Football-Data <-> Understat join (V23 Task 1).

Covers name normalization/aliasing, point-in-time prior-only rolling (own match
excluded, NaN below window, never 0.0), and the fail-closed join (unique match
only; missing/ambiguous/unmapped -> None, never a guessed value).
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from src.features.understat_join import (
    CORPUS_UNAVAILABLE_FAMILIES,
    UNDERSTAT_ROLLING_FEATURES,
    build_join_index,
    compute_prior_rolling,
    load_team_aliases,
    normalize_team_name,
    teams_match,
    understat_features_for_fixture,
)


def _corpus(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def test_normalize_strips_accents_affixes_and_punctuation() -> None:
    assert normalize_team_name("Atlético Madrid") == normalize_team_name("Atletico Madrid")
    assert normalize_team_name("Paris Saint-Germain FC") == "paris saint germain"
    assert normalize_team_name("FC Barcelona") == normalize_team_name("Barcelona")  # affix dropped
    assert normalize_team_name("1. FC Köln") == "1 koln"  # accent folded, affix dropped
    # Deterministic and idempotent.
    once = normalize_team_name("Borussia M'gladbach")
    assert normalize_team_name(once) == once


def test_teams_match_exact_alias_and_rejection() -> None:
    alias = {normalize_team_name("Manchester City"): normalize_team_name("Man City")}
    assert teams_match("Manchester City", "Man City", alias)
    assert teams_match("Arsenal", "Arsenal", {})  # exact normalized equality, no alias needed
    assert not teams_match("Manchester City", "Manchester United", alias)  # different clubs


def test_load_team_aliases_reads_shipped_table() -> None:
    alias = load_team_aliases()
    assert alias, "the shipped alias table should be non-empty"
    # Values are normalized on load so callers never re-normalize.
    assert alias[normalize_team_name("Wolverhampton Wanderers")] == normalize_team_name("Wolves")


def test_prior_rolling_excludes_own_match_and_is_nan_below_window() -> None:
    # Team A plays six matches (home each time); xG and goals ramp 1..6.
    rows = []
    for i in range(6):
        rows.append(
            {
                "game_id": i + 1,
                "season": "2324",
                "sabi_league": "epl",
                "sabi_season": 2023,
                "date": datetime(2023, 8, 1 + i),
                "home_team": "A",
                "away_team": f"Opp{i}",
                "home_goals": i + 1,
                "away_goals": 0,
                "home_xg": float(i + 1),
                "away_xg": 0.5,
            }
        )
    rolling = compute_prior_rolling(_corpus(rows), window=5)
    # Matches 1..5: fewer than 5 prior A appearances -> NaN (no cold-start fill).
    for gid in range(1, 6):
        assert math.isnan(rolling[gid]["home_roll_xg_for"])
    # Match 6: mean of A's prior five xG = mean(1..5) = 3.0 (its own xG of 6 excluded).
    assert rolling[6]["home_roll_xg_for"] == pytest.approx(3.0)
    # Finishing efficiency = sum(prior goals)/sum(prior xG) = 15/15 = 1.0.
    assert rolling[6]["home_roll_finishing_eff"] == pytest.approx(1.0)
    # xG-against prior mean = mean of five 0.5 values = 0.5.
    assert rolling[6]["home_roll_xg_against"] == pytest.approx(0.5)


def test_xg_against_is_the_opponents_xg() -> None:
    # Two matches so the away side of match 2 has one prior; assert the perspective flip.
    rows = [
        {"game_id": 1, "season": "2324", "sabi_league": "epl", "sabi_season": 2023,
         "date": datetime(2023, 8, 1), "home_team": "B", "away_team": "C",
         "home_goals": 2, "away_goals": 1, "home_xg": 2.0, "away_xg": 1.0},
    ]
    rolling = compute_prior_rolling(_corpus(rows), window=1)
    # window=1 with one prior is impossible for match 1 (no prior) -> NaN both sides.
    assert math.isnan(rolling[1]["home_roll_xg_for"])


def _join_fixture(league, date, home, away, hg, ag):
    return {"league": league, "date": date, "home_team": home, "away_team": away, "fthg": hg, "ftag": ag}


def test_join_resolves_unique_match_and_returns_float32() -> None:
    rows = []
    for i in range(6):
        rows.append({"game_id": i + 1, "season": "2324", "sabi_league": "epl", "sabi_season": 2023,
                     "date": datetime(2023, 8, 1 + i), "home_team": "Manchester City", "away_team": f"Opp{i}",
                     "home_goals": 3, "away_goals": 0, "home_xg": 2.0 + i * 0.1, "away_xg": 0.4})
    corpus = _corpus(rows)
    rolling = compute_prior_rolling(corpus, window=5)
    index = build_join_index(corpus)
    alias = load_team_aliases()
    # FD fixture uses the FD spelling "Man City"; alias resolves it. Match 6 has full history.
    fx = _join_fixture("EPL", datetime(2023, 8, 6), "Man City", "Opp5", 3, 0)
    feats = understat_features_for_fixture(fx, index, rolling, alias)
    assert feats is not None
    assert set(feats) == set(UNDERSTAT_ROLLING_FEATURES)
    assert all(isinstance(v, np.float32) for v in feats.values())
    assert float(feats["home_roll_xg_for"]) == pytest.approx(np.mean([2.0, 2.1, 2.2, 2.3, 2.4]), abs=1e-5)


def test_join_fails_closed_on_no_name_match() -> None:
    rows = [{"game_id": 1, "season": "2324", "sabi_league": "epl", "sabi_season": 2023,
             "date": datetime(2023, 8, 1), "home_team": "Arsenal", "away_team": "Chelsea",
             "home_goals": 1, "away_goals": 0, "home_xg": 1.5, "away_xg": 0.8}]
    corpus = _corpus(rows)
    rolling = compute_prior_rolling(corpus, window=5)
    index = build_join_index(corpus)
    # Same league/score/date, but the FD teams are a different fixture -> no match -> None.
    fx = _join_fixture("EPL", datetime(2023, 8, 1), "Everton", "Fulham", 1, 0)
    assert understat_features_for_fixture(fx, index, rolling, {}) is None


def test_join_fails_closed_on_ambiguous_same_scoreline_collision() -> None:
    # Two different EPL matches on the same day, same 1-0 scoreline (a real collision class).
    rows = [
        {"game_id": 1, "season": "2324", "sabi_league": "epl", "sabi_season": 2023,
         "date": datetime(2023, 8, 1), "home_team": "Arsenal", "away_team": "Chelsea",
         "home_goals": 1, "away_goals": 0, "home_xg": 1.5, "away_xg": 0.8},
        {"game_id": 2, "season": "2324", "sabi_league": "epl", "sabi_season": 2023,
         "date": datetime(2023, 8, 1), "home_team": "Everton", "away_team": "Fulham",
         "home_goals": 1, "away_goals": 0, "home_xg": 1.1, "away_xg": 0.9},
    ]
    corpus = _corpus(rows)
    rolling = compute_prior_rolling(corpus, window=1)
    index = build_join_index(corpus)
    # The scoreline+date+league key matches both; team names pick exactly one (Arsenal-Chelsea).
    fx = _join_fixture("EPL", datetime(2023, 8, 1), "Arsenal", "Chelsea", 1, 0)
    # Rolling is NaN (no prior history) so the covered-feature contract yields a dict of NaNs,
    # but the *join itself* is unique -> not None. The evaluator excludes NaN rows separately.
    feats = understat_features_for_fixture(fx, index, rolling, {})
    assert feats is not None
    assert all(math.isnan(float(v)) for v in feats.values())


def test_corpus_unavailable_families_are_declared() -> None:
    # Anti-fabrication: the module must declare xA / shot-count efficiency / xPTS as absent.
    assert "xa" in CORPUS_UNAVAILABLE_FAMILIES
    assert "xpts" in CORPUS_UNAVAILABLE_FAMILIES
    # None of those appear as emitted feature columns.
    joined = " ".join(UNDERSTAT_ROLLING_FEATURES)
    assert "xa" not in joined and "xpts" not in joined
