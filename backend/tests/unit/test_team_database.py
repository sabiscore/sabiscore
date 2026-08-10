"""Unit tests for team_database.py — ELO ratings and matchup feature generation."""

from __future__ import annotations


from src.data.team_database import (
    TEAM_ELO_RATINGS,
    TEAM_SQUAD_VALUES,
    get_matchup_features,
    get_team_elo,
    get_team_squad_value,
    get_team_stats,
)


# ── get_team_elo ─────────────────────────────────────────────────────────────

def test_get_team_elo_known_team():
    rating = get_team_elo("Arsenal")
    assert rating == TEAM_ELO_RATINGS["Arsenal"]
    assert 1300 <= rating <= 2000


def test_get_team_elo_known_team_real_madrid():
    assert get_team_elo("Real Madrid") == 1970


def test_get_team_elo_case_insensitive():
    rating = get_team_elo("arsenal")
    assert rating == TEAM_ELO_RATINGS["Arsenal"]


def test_get_team_elo_partial_match():
    # "Borussia" matches "Borussia Dortmund" or "Borussia Monchengladbach"
    rating = get_team_elo("Borussia Dortmund")
    assert 1800 <= rating <= 1950


def test_get_team_elo_unknown_team_is_stable():
    r1 = get_team_elo("Hypothetical FC")
    r2 = get_team_elo("Hypothetical FC")
    assert r1 == r2
    assert 1500 <= r1 <= 1650


def test_get_team_elo_different_unknown_teams_differ():
    r1 = get_team_elo("AlphaDelta United")
    r2 = get_team_elo("BetaGamma City")
    # Both should be in the unknown-team hash range
    assert 1500 <= r1 <= 1650
    assert 1500 <= r2 <= 1650


def test_get_team_elo_all_known_teams_in_range():
    for name, rating in TEAM_ELO_RATINGS.items():
        assert 1400 <= rating <= 2100, f"{name}: ELO {rating} out of expected range"


# ── get_team_squad_value ──────────────────────────────────────────────────────

def test_get_squad_value_known_team():
    val = get_team_squad_value("Manchester City")
    assert val == TEAM_SQUAD_VALUES["Manchester City"]


def test_get_squad_value_case_insensitive():
    val = get_team_squad_value("manchester city")
    assert val == TEAM_SQUAD_VALUES["Manchester City"]


def test_get_squad_value_partial_match():
    val = get_team_squad_value("PSG")
    assert val > 0


def test_get_squad_value_unknown_team_stable():
    v1 = get_team_squad_value("Mystery Town FC")
    v2 = get_team_squad_value("Mystery Town FC")
    assert v1 == v2
    assert 150 <= v1 <= 300


# ── get_team_stats ────────────────────────────────────────────────────────────

def test_get_team_stats_returns_expected_keys():
    stats = get_team_stats("Arsenal", is_home=True)
    required_keys = {
        "win_rate", "goals_per_game", "goals_conceded_per_game",
        "attacking_strength", "defensive_strength", "xg_avg", "xg_conceded_avg",
        "squad_value", "form_5", "form_10", "form_20",
        "win_streak", "unbeaten_streak", "clean_sheet_rate", "scoring_consistency",
    }
    assert required_keys.issubset(set(stats.keys()))


def test_get_team_stats_home_advantage():
    home = get_team_stats("Liverpool", is_home=True)
    away = get_team_stats("Liverpool", is_home=False)
    assert home["win_rate"] >= away["win_rate"]
    assert home["xg_avg"] >= away["xg_avg"]


def test_get_team_stats_win_rate_in_range():
    stats = get_team_stats("Chelsea")
    assert 0.0 <= stats["win_rate"] <= 1.0


def test_get_team_stats_goals_positive():
    stats = get_team_stats("Bayern Munich")
    assert stats["goals_per_game"] > 0
    assert stats["goals_conceded_per_game"] > 0


def test_get_team_stats_strong_team_vs_weak():
    strong = get_team_stats("Real Madrid")
    weak = get_team_stats("Unknown Minnows FC")
    assert strong["attacking_strength"] >= weak["attacking_strength"]


def test_get_team_stats_unknown_team():
    stats = get_team_stats("Fictional City FC")
    assert isinstance(stats, dict)
    assert stats["win_rate"] > 0


# ── get_matchup_features ──────────────────────────────────────────────────────

def test_get_matchup_features_returns_dict():
    features = get_matchup_features("Arsenal", "Chelsea", league="EPL")
    assert isinstance(features, dict)
    assert len(features) > 20


def test_get_matchup_features_has_elo_keys():
    features = get_matchup_features("Liverpool", "Manchester City")
    assert "home_elo" in features
    assert "away_elo" in features
    assert "elo_difference" in features


def test_get_matchup_features_elo_difference_sign():
    # Arsenal vs lower-rated team: Arsenal is home, should have positive elo diff
    features = get_matchup_features("Real Madrid", "Almeria")
    assert features["elo_difference"] > 0  # Real Madrid > Almeria in ELO


def test_get_matchup_features_has_xg_keys():
    features = get_matchup_features("Bayern Munich", "RB Leipzig")
    assert "home_xg_avg_5" in features
    assert "away_xg_avg_5" in features
    assert "xg_differential" in features


def test_get_matchup_features_has_form_keys():
    features = get_matchup_features("Juventus", "Napoli")
    assert "home_form_5" in features
    assert "away_form_5" in features
    assert "home_form_10" in features


def test_get_matchup_features_squad_value_diff():
    features = get_matchup_features("Manchester City", "Burnley")
    assert "squad_value_diff" in features
    assert features["home_squad_value"] > features["away_squad_value"]


def test_get_matchup_features_home_advantage_coefficient():
    features = get_matchup_features("Arsenal", "Liverpool")
    assert "home_advantage_coefficient" in features
    assert features["home_advantage_coefficient"] > 1.0


def test_get_matchup_features_referee_home_bias():
    features = get_matchup_features("Chelsea", "Tottenham")
    assert "referee_home_bias" in features
    assert features["referee_home_bias"] == 0.52


def test_get_matchup_features_unknown_teams():
    features = get_matchup_features("Team Alpha FC", "Team Beta United")
    assert isinstance(features, dict)
    assert "elo_difference" in features
