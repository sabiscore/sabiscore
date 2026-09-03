"""The committed Understat corpus must stay complete and byte-loadable.

``backend/data/processed/v4_sources`` is tracked (not gitignored) because a
corpus CI cannot reach is a corpus no training run can reproduce — re-acquiring
it means a 35-league-season Understat backfill. Tracking it creates a new failure
mode the repository did not have before: the corpus can be silently truncated by
a partial commit, or corrupted by line-ending normalisation of a parquet file.

Both failures are quiet. A short corpus still loads, still trains, and produces
a candidate whose numbers nobody can reproduce. This test is the tripwire: it
asserts the corpus matches the row counts its own acquisition manifests recorded
at fetch time, so a missing season fails here rather than in a training report
six steps later.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

CORPUS = Path(__file__).resolve().parents[2] / "data" / "processed" / "v4_sources"

# Recorded by scripts/backfill_v4_data_sources.py at acquisition time and
# reproduced by scripts/measure_xg_feature_ate.py on 2026-09-03.
EXPECTED_LEAGUE_SEASONS = 35
EXPECTED_MATCH_ROWS = 12_560
EXPECTED_LEAGUES = {"epl", "la_liga", "serie_a", "bundesliga", "ligue_1"}


def _manifest_artefacts() -> list[dict]:
    """Every artefact entry across every season manifest."""
    artefacts = []
    for path in sorted(CORPUS.glob("manifest_*.json")):
        for result in json.loads(path.read_text(encoding="utf-8"))["results"]:
            for artefact in result["artefacts"]:
                artefacts.append({**artefact, "league": result["league"], "season": result["season"]})
    return artefacts


def test_corpus_directory_is_committed() -> None:
    assert CORPUS.is_dir(), (
        f"{CORPUS} is absent. It is tracked in git — an absent corpus means a "
        "bad checkout or a reverted .gitignore negation, not a missing backfill."
    )


def test_manifests_describe_the_expected_league_seasons() -> None:
    artefacts = _manifest_artefacts()
    assert len(artefacts) == EXPECTED_LEAGUE_SEASONS
    assert {a["league"] for a in artefacts} == EXPECTED_LEAGUES
    assert sum(a["match_rows"] for a in artefacts) == EXPECTED_MATCH_ROWS


@pytest.mark.parametrize("artefact", _manifest_artefacts(), ids=lambda a: f"{a['league']}_{a['season']}")
def test_each_parquet_matches_the_rows_its_manifest_recorded(artefact: dict) -> None:
    """Row-count parity is what catches a truncated or normalised parquet.

    Reading the file also proves it survived `* text=auto` — a CRLF-mangled
    parquet raises here rather than yielding short reads downstream.
    """
    path = CORPUS / f"understat_matches_{artefact['league']}_{artefact['season']}.parquet"
    assert path.is_file(), f"{path.name} is missing from the committed corpus"

    frame = pd.read_parquet(path)
    assert len(frame) == artefact["match_rows"], (
        f"{path.name} holds {len(frame)} rows; its manifest recorded "
        f"{artefact['match_rows']}. The corpus was truncated or rewritten."
    )
    for column in ("home_team", "away_team", "home_xg", "away_xg", "date"):
        assert column in frame.columns, f"{path.name} lost the {column!r} column"


def test_corpus_carries_real_xg_not_zero_fill() -> None:
    """A zero-filled corpus would pass every count assertion above.

    ATE measurement on a constant column is meaningless, so the thing worth
    asserting is variance, not presence — the same reasoning the feature
    registry applies to `training_defaulted_slots`.
    """
    frame = pd.concat(
        [pd.read_parquet(p) for p in sorted(CORPUS.glob("understat_matches_*.parquet"))],
        ignore_index=True,
    )
    played = frame[frame["home_xg"].notna() & frame["away_xg"].notna()]

    # 101 Ligue 1 2019/20 fixtures France cancelled for COVID are legitimately
    # null (docs/DEBT.md item 56) — they are unplayed matches, not gaps.
    assert len(played) == EXPECTED_MATCH_ROWS - 101
    assert played["home_xg"].std() > 0.5, "home_xg has no variance — corpus is defaulted, not observed"
    assert played["away_xg"].std() > 0.5, "away_xg has no variance — corpus is defaulted, not observed"
