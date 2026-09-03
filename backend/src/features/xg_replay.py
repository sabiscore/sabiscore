"""Leak-free xG rolling replay over the offline training corpus.

WHY THIS EXISTS
---------------
``feature_registry.PHASE9_FEATURES_XG`` names three features
``scripts/measure_xg_feature_ate.py`` measured as CAUSAL_DRIVER on the real
Understat corpus, and ``upcoming_match_feature_service.project_xg_rolling_features``
already computes them at serving time. Nothing computed them at TRAINING time,
so the ``apex_v2_71`` candidate had no honest way to carry them. This module is
that half.

THE JOIN, AND WHY IT NEEDS A CROSSWALK
--------------------------------------
Training reads football-data.co.uk CSVs (``train_on_real_matches.load_matches``);
xG lives in the Understat parquet corpus. They are two different vocabularies,
and the bridge between them is deliberately split in two:

* the NORMALIZER is ``team_identity.market_identity_key`` — the single
  production identity algorithm, including its ``_AUDITED_ALIASES`` folding.
  CLAUDE.md is explicit that a second normalizer beside it has caused three
  production incidents; this module introduces none.
* the CROSSWALK below is a data table, not an algorithm, and maps
  already-normalized Understat keys onto already-normalized football-data keys.

The crosswalk is deliberately NOT merged into ``_AUDITED_ALIASES``. That table
maps a provider spelling onto the name stored in the production ``teams`` table
("atletico madrid" -> "club atletico de madrid"); this one maps onto
football-data.co.uk's CSV shorthand ("Ath Madrid"), which is a third vocabulary
that production identity resolution must never be pointed at. Merging them is
exactly the cross-context defect PR #145 recorded: one alias table consulted by
two call sites with different notions of "canonical".

TEMPORAL CONTRACT
-----------------
The rolling window is ``feature_registry.rolling_xg_mean`` itself — not a
pandas re-implementation of it — so training and serving cannot drift apart on
window size, minimum periods, or the below-minimum None. Each match's features
are computed from that team's previously-seen matches only; the match's own xG
is appended to both teams' history strictly AFTER its row is emitted.

Note one deliberate difference from ``measure_xg_feature_ate.build_features``,
which partitions its pandas rolling by ``(league, season)``: this replay does
NOT reset at a season boundary, because serving does not
(``_completed_matches_before`` applies no season bound). Parity with serving is
the binding constraint; the ATE population differs from the training population
by at most the first few fixtures of each season.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from ..core.league_policy import canonical_league_id
from ..data.understat_corpus import load_corpus_matches
from ..models.feature_registry import (
    PHASE9_FEATURES_XG,
    XG_ROLLING_WINDOW,
    derive_xg_rolling_features,
    rolling_xg_mean,
)
from ..services.team_identity import market_identity_key

#: The 3 slots this replay populates — the registry's own list, not a copy.
XG_TRAINING_COLUMNS: Tuple[str, ...] = tuple(PHASE9_FEATURES_XG)

#: Same 36 hours, same reasoning, as the match_stats reconciliation manifest:
#: wide enough to absorb a single-day timezone misalignment between the two
#: sources' recorded kickoff, far narrower than the months between two meetings
#: of the same home/away pairing.
_KICKOFF_TOLERANCE = timedelta(hours=36)

#: How many completed matches serving looks back over before filtering to the
#: ones that carry an observed xG — ``upcoming_match_feature_service
#: .project_xg_rolling_features`` passes 20 to ``_completed_matches_before``.
#: Mirrored here so the training window sees the same horizon.
_SERVING_LOOKBACK = 20

#: Normalized-Understat-key -> normalized-football-data-key, per canonical
#: league. Every entry was read out of the two committed corpora: after
#: ``market_identity_key`` folding, these are the COMPLETE set of club keys
#: present on one side and absent from the other across all 35 corpus files and
#: all seven football-data seasons. Without them La Liga joins at ~35% and
#: Bundesliga at ~51%.
#:
#: ⚠️ Adding a row here is an identity assertion about two offline corpora and
#: has no effect on live provider resolution. Adding one to
#: ``team_identity._AUDITED_ALIASES`` instead WOULD affect it — see the module
#: docstring.
_UNDERSTAT_TO_FOOTBALL_DATA: Dict[Tuple[str, str], str] = {
    ("BUNDESLIGA", "arminia bielefeld"): "bielefeld",
    ("BUNDESLIGA", "bayer leverkusen"): "leverkusen",
    ("BUNDESLIGA", "borussia dortmund"): "dortmund",
    ("BUNDESLIGA", "borussia m gladbach"): "m gladbach",
    ("BUNDESLIGA", "fortuna duesseldorf"): "fortuna dusseldorf",
    ("BUNDESLIGA", "hertha berlin"): "hertha",
    ("EPL", "manchester united"): "man united",
    ("EPL", "nottingham forest"): "nott m forest",
    ("LA_LIGA", "athletic"): "ath bilbao",
    ("LA_LIGA", "celta de vigo"): "celta",
    ("LA_LIGA", "club atletico de madrid"): "ath madrid",
    ("LA_LIGA", "espanyol"): "espanol",
    ("LA_LIGA", "rayo vallecano"): "vallecano",
    ("LA_LIGA", "real betis"): "betis",
    ("LA_LIGA", "real oviedo"): "oviedo",
    ("LA_LIGA", "real sociedad"): "sociedad",
    ("LA_LIGA", "real valladolid"): "valladolid",
    ("LA_LIGA", "sd huesca"): "huesca",
    ("LIGUE_1", "clermont foot"): "clermont",
    ("SERIE_A", "parma calcio"): "parma",
}


def corpus_team_key(name: str, league_id: str) -> str:
    """One club key, in football-data's vocabulary, for either corpus.

    Applied symmetrically to both sides so a club collapses onto one key
    regardless of which corpus the spelling came from.
    """
    key = market_identity_key(name, league_id)
    return _UNDERSTAT_TO_FOOTBALL_DATA.get((league_id, key), key)


def build_xg_index(
    sources_dir: Path,
) -> Dict[Tuple[str, str, str], List[Tuple[datetime, float, float]]]:
    """``(league, home_key, away_key)`` -> ``[(kickoff, home_xg, away_xg), ...]``."""
    corpus = load_corpus_matches(sources_dir)
    index: Dict[Tuple[str, str, str], List[Tuple[datetime, float, float]]] = {}
    for row in corpus.itertuples(index=False):
        league_id = canonical_league_id(str(row.sabi_league))
        key = (
            league_id,
            corpus_team_key(str(row.home_team), league_id),
            corpus_team_key(str(row.away_team), league_id),
        )
        kickoff = pd.Timestamp(row.date).to_pydatetime()
        index.setdefault(key, []).append(
            (kickoff, float(row.home_xg), float(row.away_xg))
        )
    return index


def _lookup(
    index: Mapping[Tuple[str, str, str], Sequence[Tuple[datetime, float, float]]],
    *,
    league_id: str,
    home_key: str,
    away_key: str,
    kickoff: datetime,
) -> Optional[Tuple[float, float]]:
    """The single corpus observation for this fixture, or None.

    More than one candidate inside the tolerance window fails closed rather
    than guessing — the same policy the match_stats manifest applies, and the
    reason the corpus loader deduplicates before this ever runs.
    """
    candidates = [
        (home_xg, away_xg)
        for observed_at, home_xg, away_xg in index.get((league_id, home_key, away_key), ())
        if abs(observed_at - kickoff) <= _KICKOFF_TOLERANCE
    ]
    return candidates[0] if len(candidates) == 1 else None


@dataclass(frozen=True)
class XgReplayResult:
    """Per-match xG columns plus the counters needed to audit the run.

    ``rows`` is always the same length as the input and aligned to it by index,
    matching ``EloReplayResult`` and ``Phase8ReplayResult``. A row with no
    honest answer yields an EMPTY dict — never a zero-filled one. A caller
    training on ``PHASE9_FEATURES_XG`` must DROP those rows rather than merge
    a default onto them: serving returns None for the same fixture, and a
    default here would be a feature the model learned from that serving can
    never reproduce.
    """

    rows: List[Dict[str, float]] = field(default_factory=list)
    matches_seen: int = 0
    #: Input matches for which the corpus held exactly one observation.
    observed: int = 0
    #: Input matches with an observation whose BOTH sides also had enough prior
    #: history for the rolling window — i.e. rows that actually get features.
    resolved_both_sides: int = 0

    def summary(self) -> str:
        return (
            f"xg replay: {self.matches_seen} matches, "
            f"{self.observed} with a corpus xG observation, "
            f"{self.resolved_both_sides} with both sides' rolling window filled "
            f"(window={XG_ROLLING_WINDOW})"
        )


def compute_xg_training_columns(
    matches: Sequence[Mapping[str, Any]],
    sources_dir: Path,
) -> XgReplayResult:
    """Replay leak-free rolling xG over historical matches, in the order given.

    Args:
        matches: Records shaped as ``train_on_real_matches.load_matches`` emits
            them — ``league``, ``date``, ``home``, ``away``. Must already be
            ascending by kickoff, which that loader guarantees. Extra keys are
            ignored.
        sources_dir: The tracked Understat parquet directory.

    Returns:
        An :class:`XgReplayResult` whose ``rows[i]`` holds the 3
        :data:`XG_TRAINING_COLUMNS` for ``matches[i]``, or an empty dict when
        the fixture has no corpus observation or either side is below the
        rolling minimum.
    """
    index = build_xg_index(sources_dir)

    # Most-recent-first, which is the order rolling_xg_mean documents.
    #
    # An UNOBSERVED match is recorded as None rather than skipped, and the deque
    # is bounded at _SERVING_LOOKBACK, not at the rolling window. That is exact
    # parity with serving, which reads the last _SERVING_LOOKBACK completed
    # matches, drops the ones with no match_stats row, and only then hands the
    # dense remainder to rolling_xg_mean. Keeping only observed values with no
    # lookback bound would instead reach arbitrarily far into the past for a
    # sparsely-covered team — a value serving could never reproduce.
    history: Dict[Tuple[str, str], Deque[Optional[Tuple[float, float]]]] = defaultdict(
        lambda: deque(maxlen=_SERVING_LOOKBACK)
    )

    rows: List[Dict[str, float]] = [{} for _ in matches]
    observed = 0
    resolved = 0

    for position, match in enumerate(matches):
        league_id = canonical_league_id(str(match["league"]))
        home_key = corpus_team_key(str(match["home"]), league_id)
        away_key = corpus_team_key(str(match["away"]), league_id)
        kickoff = match["date"]

        found = _lookup(
            index,
            league_id=league_id,
            home_key=home_key,
            away_key=away_key,
            kickoff=kickoff,
        )

        home_history = history[(league_id, home_key)]
        away_history = history[(league_id, away_key)]

        # Emit from history that predates this match, then update — a match
        # never informs its own row.
        home_seen = [pair for pair in home_history if pair is not None]
        away_seen = [pair for pair in away_history if pair is not None]
        features = derive_xg_rolling_features(
            home_xg_for=rolling_xg_mean([f for f, _ in home_seen]),
            home_xg_against=rolling_xg_mean([a for _, a in home_seen]),
            away_xg_for=rolling_xg_mean([f for f, _ in away_seen]),
            away_xg_against=rolling_xg_mean([a for _, a in away_seen]),
        )
        if features is not None:
            rows[position] = features
            resolved += 1

        if found is None:
            home_history.appendleft(None)
            away_history.appendleft(None)
        else:
            observed += 1
            home_xg, away_xg = found
            home_history.appendleft((home_xg, away_xg))
            away_history.appendleft((away_xg, home_xg))

    return XgReplayResult(
        rows=rows,
        matches_seen=len(matches),
        observed=observed,
        resolved_both_sides=resolved,
    )


__all__ = [
    "XG_TRAINING_COLUMNS",
    "XgReplayResult",
    "build_xg_index",
    "compute_xg_training_columns",
    "corpus_team_key",
]
