"""The tracked Understat corpus, loaded once and filtered identically everywhere.

Three consumers need the same population or they silently describe different
things: ``understat_match_stats_reconciliation_service`` (which rows may be
written to ``match_stats``), ``features.xg_replay`` (which rows carry xG into
training), and ``scripts/measure_xg_feature_ate.py`` (which rows the measured
ATE was estimated on). This module is deliberately dependency-light — pandas
only, no SQLAlchemy, no ``src.models`` — so all three can import it.

Two filters and one deduplication define "a real observation":

* null ``home_xg``/``away_xg`` rows are dropped;
* ``has_data=False`` rows are dropped. The 101 Ligue 1 2019/20 fixtures France
  cancelled for COVID carry both flags. They are unplayed matches, not missing
  measurements — default-filling would fabricate xG for games that never
  happened (docs/DEBT.md item 56);
* duplicate ``game_id`` rows are dropped, keeping the first.

⚠️ The deduplication is not cosmetic. The committed corpus files are labelled by
Understat's own season id and their coverage OVERLAPS: ``understat_ligue_1_2020``
and ``understat_ligue_1_2021`` both contain the whole 2020/21 season, game ids
and all. Across the 35 committed files that is 1,826 matches present twice —
12,459 rows for 10,633 distinct matches. Left in, each duplicate:

* makes the reconciliation manifest propose the same ``(match_id, team_id)``
  ``match_stats`` row twice, which the backfill executor refuses outright; and
* lets one match contribute twice to a rolling xG mean, which is a quiet
  correctness bug rather than a loud one.

A consequence worth stating because it bounds every coverage number computed
from this corpus: the overlap means the 7 files per league cover 6 distinct
seasons, and 2021/22 is absent from all five leagues.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

import pandas as pd

#: Understat's own filename slug -> the value written to ``sabi_league``. The
#: canonical SabiScore league id is derived from it by the caller via
#: ``core.league_policy.canonical_league_id``; this module stays DB- and
#: policy-free.
_FILE_PREFIX = "understat_matches_"
_FILE_SUFFIX = ".parquet"


def load_corpus_matches(sources_dir: Path) -> pd.DataFrame:
    """Every played, distinct Understat match across the tracked corpus.

    Returns a frame carrying the parquet's own columns plus ``sabi_league`` and
    ``sabi_season``, sorted ascending by ``date`` with a reset index.
    """
    frames = []
    for path in sorted(glob.glob(str(sources_dir / f"{_FILE_PREFIX}*{_FILE_SUFFIX}"))):
        stem = os.path.basename(path)[len(_FILE_PREFIX) : -len(_FILE_SUFFIX)]
        league, season = stem.rsplit("_", 1)
        frame = pd.read_parquet(path)
        frame["sabi_league"] = league
        frame["sabi_season"] = int(season)
        frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"No Understat parquet found under {sources_dir}")

    corpus = pd.concat(frames, ignore_index=True)
    corpus = corpus[corpus["home_xg"].notna() & corpus["away_xg"].notna()]
    if "has_data" in corpus.columns:
        corpus = corpus[corpus["has_data"].astype(bool)]
    if "game_id" in corpus.columns:
        # Stable sort first so "keep first" is deterministic across runs rather
        # than dependent on glob order: the earliest-dated copy always wins.
        corpus = corpus.sort_values("date", kind="stable")
        corpus = corpus.drop_duplicates(subset="game_id", keep="first")
    return corpus.sort_values("date", kind="stable").reset_index(drop=True)


__all__ = ["load_corpus_matches"]
