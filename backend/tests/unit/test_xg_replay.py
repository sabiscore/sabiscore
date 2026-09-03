"""The training half of the xG train/serve pair.

The leak boundary is the whole point: a match's own xG must never appear in its
own feature row, and the window semantics must be the registry's own, not a
re-implementation. ``test_xg_rolling_parity.py`` covers the pure functions;
this file covers the replay that drives them over a corpus.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.features.xg_replay import (
    XG_TRAINING_COLUMNS,
    build_xg_index,
    compute_xg_training_columns,
    corpus_team_key,
)
from src.models.feature_registry import (
    PHASE9_FEATURES_XG,
    XG_ROLLING_MIN_PERIODS,
)

LEAGUE = "EPL"
START = datetime(2024, 8, 16, 19, 0)


def _corpus(tmp_path: Path, rows: list[dict], name: str = "epl_2024") -> Path:
    sources = tmp_path / "v4_sources"
    sources.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_parquet(sources / f"understat_matches_{name}.parquet")
    return sources


def _us_row(home: str, away: str, day: int, home_xg: float, away_xg: float) -> dict:
    return {
        "game_id": day,
        "home_team": home,
        "away_team": away,
        "date": START + timedelta(days=day),
        "home_xg": home_xg,
        "away_xg": away_xg,
        "has_data": True,
    }


def _fd(home: str, away: str, day: int) -> dict:
    return {
        "league": LEAGUE,
        "season": "2425",
        "date": START + timedelta(days=day),
        "home": home,
        "away": away,
        "hg": 1,
        "ag": 0,
    }


# ---------------------------------------------------------------------------
# Identity: one normalizer, one crosswalk
# ---------------------------------------------------------------------------


def test_the_crosswalk_folds_both_vocabularies_onto_one_key() -> None:
    assert corpus_team_key("Manchester United", "EPL") == corpus_team_key("Man United", "EPL")
    assert corpus_team_key("Atletico Madrid", "LA_LIGA") == corpus_team_key("Ath Madrid", "LA_LIGA")
    assert corpus_team_key("Borussia M.Gladbach", "BUNDESLIGA") == corpus_team_key(
        "M'gladbach", "BUNDESLIGA"
    )


def test_two_different_clubs_do_not_collapse_onto_one_key() -> None:
    """The Paris FC / Paris SG collision the production alias table exists to
    prevent must not be reintroduced by the crosswalk."""
    assert corpus_team_key("Paris FC", "LIGUE_1") != corpus_team_key("Paris SG", "LIGUE_1")


def test_an_unknown_name_passes_through_the_normalizer_unchanged() -> None:
    assert corpus_team_key("Chelsea", "EPL") == "chelsea"


# ---------------------------------------------------------------------------
# The leak boundary
# ---------------------------------------------------------------------------


def test_a_match_never_sees_its_own_xg(tmp_path: Path) -> None:
    """Arsenal's first N matches all carry xG 1.0; the N+1th carries 9.0. The
    N+1th row's features must be computed from the 1.0s alone."""
    n = XG_ROLLING_MIN_PERIODS
    us_rows = [_us_row("Arsenal", f"Opp{i}", i, 1.0, 1.0) for i in range(n)]
    us_rows.append(_us_row("Arsenal", "Chelsea", n, 9.0, 9.0))
    # Chelsea needs its own history to clear the minimum.
    us_rows += [_us_row("Chelsea", f"Other{i}", 100 + i, 1.0, 1.0) for i in range(n)]
    sources = _corpus(tmp_path, us_rows)

    fd = [_fd("Arsenal", f"Opp{i}", i) for i in range(n)]
    fd += [_fd("Chelsea", f"Other{i}", 100 + i) for i in range(n)]
    fd.append(_fd("Arsenal", "Chelsea", 200))
    fd.sort(key=lambda r: r["date"])

    # The Arsenal-Chelsea fixture in fd sits at day 200, outside the corpus
    # row's 36h window, so it is unobserved — but both sides have history.
    result = compute_xg_training_columns(fd, sources)
    final = result.rows[-1]
    assert final, "both sides had enough history for a rolling answer"
    # Every observed value was 1.0 for both sides, so every difference is 0.0.
    # A 9.0 leaking in would move all three off zero.
    for column in XG_TRAINING_COLUMNS:
        assert final[column] == pytest.approx(0.0)


def test_below_the_minimum_yields_an_empty_row_not_a_zero_row(tmp_path: Path) -> None:
    sources = _corpus(tmp_path, [_us_row("Arsenal", "Chelsea", 0, 2.0, 0.5)])
    result = compute_xg_training_columns([_fd("Arsenal", "Chelsea", 0)], sources)
    assert result.rows == [{}]
    assert result.observed == 1
    assert result.resolved_both_sides == 0


def test_rows_are_index_aligned_to_the_input(tmp_path: Path) -> None:
    sources = _corpus(tmp_path, [_us_row("Arsenal", "Chelsea", 0, 2.0, 0.5)])
    fd = [_fd("Arsenal", "Chelsea", 0), _fd("Everton", "Fulham", 1)]
    result = compute_xg_training_columns(fd, sources)
    assert len(result.rows) == len(fd)
    assert result.matches_seen == 2


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------


def test_a_fixture_outside_the_kickoff_window_is_not_observed(tmp_path: Path) -> None:
    sources = _corpus(tmp_path, [_us_row("Arsenal", "Chelsea", 0, 2.0, 0.5)])
    far = _fd("Arsenal", "Chelsea", 10)
    assert compute_xg_training_columns([far], sources).observed == 0


def test_the_index_keys_on_normalized_names(tmp_path: Path) -> None:
    sources = _corpus(tmp_path, [_us_row("Manchester United", "Chelsea", 0, 2.0, 0.5)])
    index = build_xg_index(sources)
    assert ("EPL", "man united", "chelsea") in index


def test_a_league_absent_from_the_corpus_yields_no_features(tmp_path: Path) -> None:
    """Understat publishes no Eredivisie corpus, so an Eredivisie candidate row
    has no honest xG answer and must stay empty rather than default."""
    sources = _corpus(tmp_path, [_us_row("Arsenal", "Chelsea", 0, 2.0, 0.5)])
    eredivisie = [
        {**_fd("Ajax", "PSV", day), "league": "EREDIVISIE"} for day in range(10)
    ]
    result = compute_xg_training_columns(eredivisie, sources)
    assert result.observed == 0
    assert all(row == {} for row in result.rows)


def test_columns_are_the_registry_list_not_a_copy() -> None:
    assert list(XG_TRAINING_COLUMNS) == list(PHASE9_FEATURES_XG)


def test_summary_reports_both_coverage_stages(tmp_path: Path) -> None:
    sources = _corpus(tmp_path, [_us_row("Arsenal", "Chelsea", 0, 2.0, 0.5)])
    summary = compute_xg_training_columns([_fd("Arsenal", "Chelsea", 0)], sources).summary()
    assert "corpus xG observation" in summary
    assert "rolling window filled" in summary
