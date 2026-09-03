"""The one corpus definition shared by the match_stats manifest and xG training.

The deduplication is the load-bearing part: the committed corpus files overlap
(``understat_ligue_1_2020`` and ``understat_ligue_1_2021`` both carry the whole
2020/21 season), so 1,826 of the 12,459 rows are a second copy of a match
already present. Left in, one match contributes twice to a rolling xG mean and
the match_stats manifest proposes the same row twice.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from src.data.understat_corpus import load_corpus_matches


def _rows(**overrides) -> dict:
    row = {
        "game_id": 1,
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "date": datetime(2024, 8, 16, 19, 0),
        "home_xg": 1.5,
        "away_xg": 1.0,
        "has_data": True,
    }
    row.update(overrides)
    return row


def _write(tmp_path: Path, name: str, rows: list[dict]) -> Path:
    sources = tmp_path / "v4_sources"
    sources.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_parquet(sources / f"understat_matches_{name}.parquet")
    return sources


def test_missing_corpus_raises_rather_than_returning_empty(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_corpus_matches(tmp_path / "nothing")


def test_null_xg_and_cancelled_rows_are_dropped(tmp_path: Path) -> None:
    sources = _write(
        tmp_path,
        "epl_2024",
        [
            _rows(game_id=1),
            _rows(game_id=2, home_xg=None, away_xg=None, has_data=False),
            _rows(game_id=3, home_xg=None),
        ],
    )
    corpus = load_corpus_matches(sources)
    assert list(corpus["game_id"]) == [1]


def test_the_same_game_id_in_two_season_files_is_kept_once(tmp_path: Path) -> None:
    sources = tmp_path / "v4_sources"
    sources.mkdir()
    shared = _rows(game_id=13977, date=datetime(2020, 8, 21, 17, 0))
    pd.DataFrame([shared]).to_parquet(sources / "understat_matches_ligue_1_2020.parquet")
    pd.DataFrame([shared]).to_parquet(sources / "understat_matches_ligue_1_2021.parquet")

    corpus = load_corpus_matches(sources)
    assert len(corpus) == 1
    assert int(corpus.iloc[0]["game_id"]) == 13977


def test_distinct_games_survive_deduplication(tmp_path: Path) -> None:
    sources = _write(
        tmp_path,
        "epl_2024",
        [
            _rows(game_id=1, date=datetime(2024, 8, 16, 19, 0)),
            _rows(game_id=2, date=datetime(2024, 8, 17, 15, 0), home_team="Everton"),
        ],
    )
    corpus = load_corpus_matches(sources)
    assert sorted(corpus["game_id"]) == [1, 2]


def test_league_and_season_are_derived_from_the_filename(tmp_path: Path) -> None:
    sources = _write(tmp_path, "la_liga_2023", [_rows()])
    corpus = load_corpus_matches(sources)
    assert corpus.iloc[0]["sabi_league"] == "la_liga"
    assert int(corpus.iloc[0]["sabi_season"]) == 2023


def test_output_is_ascending_by_date(tmp_path: Path) -> None:
    sources = _write(
        tmp_path,
        "epl_2024",
        [
            _rows(game_id=2, date=datetime(2024, 9, 1, 15, 0)),
            _rows(game_id=1, date=datetime(2024, 8, 16, 19, 0)),
        ],
    )
    corpus = load_corpus_matches(sources)
    assert list(corpus["game_id"]) == [1, 2]
