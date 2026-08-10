"""Unit tests for src/data/utils — normalize_team_name and calculate_season_string."""

from __future__ import annotations

from datetime import datetime


from src.data.utils.deduplication import calculate_season_string, normalize_team_name


# ── normalize_team_name ───────────────────────────────────────────────────────

def test_normalize_known_replacements():
    assert normalize_team_name("Manchester United") == "man united"
    assert normalize_team_name("Manchester City") == "man city"
    assert normalize_team_name("Tottenham Hotspur") == "tottenham"
    assert normalize_team_name("Wolverhampton Wanderers") == "wolves"
    assert normalize_team_name("Brighton & Hove Albion") == "brighton"
    assert normalize_team_name("Newcastle United") == "newcastle"
    assert normalize_team_name("Sheffield United") == "sheffield utd"
    assert normalize_team_name("West Ham United") == "west ham"
    assert normalize_team_name("Aston Villa") == "villa"
    assert normalize_team_name("Nottingham Forest") == "nott'm forest"


def test_normalize_unknown_team_returns_lowercased():
    assert normalize_team_name("Arsenal") == "arsenal"
    assert normalize_team_name("Chelsea FC") == "chelsea fc"


def test_normalize_strips_whitespace():
    assert normalize_team_name("  Arsenal  ") == "arsenal"


def test_normalize_already_lowercase():
    assert normalize_team_name("liverpool") == "liverpool"


# ── calculate_season_string ───────────────────────────────────────────────────

def test_season_august_starts_current_season():
    d = datetime(2024, 8, 1)
    assert calculate_season_string(d) == "2024/2025"


def test_season_january_is_previous_start():
    d = datetime(2025, 1, 15)
    assert calculate_season_string(d) == "2024/2025"


def test_season_may_is_previous_start():
    d = datetime(2025, 5, 31)
    assert calculate_season_string(d) == "2024/2025"


def test_season_july_is_previous_start():
    d = datetime(2025, 7, 31)
    assert calculate_season_string(d) == "2024/2025"


def test_season_august_next_year():
    d = datetime(2025, 8, 10)
    assert calculate_season_string(d) == "2025/2026"


def test_season_format():
    d = datetime(2023, 9, 1)
    season = calculate_season_string(d)
    assert "/" in season
    parts = season.split("/")
    assert len(parts) == 2
    assert all(p.isdigit() for p in parts)
