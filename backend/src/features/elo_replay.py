"""Historical Elo replay, shared by M2 Family A's ablation and real training.

WHY THIS EXISTS
---------------
``docs/DEBT.md`` item 48: ``elo_difference`` and its 3 resolvable siblings
(``elo_home_trend_5``, ``elo_away_trend_5``, ``elo_momentum_cross`` —
``elo_league_adjusted`` is permanently ``DATA_GAP`` by ATE-review policy, see
``feature_registry.PHASE7_FEATURES_ALWAYS_DATA_GAP``) were a CONSTANT 0.0
across every row ``train_on_real_matches.build_dataset()`` emitted, because
nothing replayed Elo over the offline training corpus. The ablation
(``backend/scripts/m2_family_a_elo_ablation.py``) measured that adding real
Elo to a form/recency BASE improves out-of-sample RPS
(``backend/reports/evaluation/m2-family-a-elo-ablation.json``). This module is
the follow-up the ablation's own report named as "not done here": wiring a
real, cross-verified replay into the actual training pipeline.

ONE IMPLEMENTATION, NOT TWO
---------------------------
The rating math (home-advantage-adjusted expected score, per-league K-factor,
5-game post-minus-pre trend, season-carryover regression to the league mean)
mirrors ``backend.src.data.elo_engine.EloEngine`` — the offline research
engine, explicitly not the production Postgres authority
(``services.elo_state_service.DurableEloContext`` serves live requests). It is
reimplemented as ``FastEloReplay``, a dict-based O(1)-amortized accumulator,
because ``EloEngine``'s per-call DataFrame filter-and-copy does not finish a
~12,260-match bulk replay in reasonable time — it is built for occasional
single-match lookups, not one bulk pass. ``cross_verify_against_elo_engine``
proves the two agree on a real subset before either caller trusts the fast
path at scale.

Both ``m2_family_a_elo_ablation.py`` and ``train_on_real_matches.py`` import
this module rather than keeping their own copies of the replay class — a
second, independently-maintained implementation is exactly the class of defect
Phase 3's feature-registry work spent several PRs eliminating.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Mapping, Sequence, Tuple

import numpy as np

from ..core.config import settings
from ..data.elo_engine import EloEngine

_DEFAULT_BASE_ELO = 1500.0

#: The 4 canonical Elo slots this replay can honestly populate.
#: ``elo_league_adjusted`` is deliberately excluded — see the module docstring.
ELO_TRAINING_COLUMNS: Tuple[str, ...] = (
    "elo_difference",
    "elo_home_trend_5",
    "elo_away_trend_5",
    "elo_momentum_cross",
)


class FastEloReplay:
    """Same rating math as ``EloEngine``, O(1)-amortized per match instead of
    ``EloEngine``'s O(n) DataFrame filter-and-copy. Replicates, not reinvents:
    home-advantage-adjusted expected score, per-league K-factor, 5-game
    post-minus-pre delta trend, and the 50% season-carryover regression toward
    the league mean when a team's last rating predates the current season.
    """

    def __init__(self, home_advantage: float, k_base: float, league_importance: Dict[str, float]) -> None:
        self._home_advantage = home_advantage
        self._k_base = k_base
        self._league_importance = league_importance
        self._history: Dict[Tuple[str, str], List[Tuple[str, float]]] = defaultdict(list)
        self._deltas: Dict[Tuple[str, str], Deque[float]] = defaultdict(lambda: deque(maxlen=5))
        self._league_season_sum: Dict[Tuple[str, str], float] = defaultdict(float)
        self._league_season_n: Dict[Tuple[str, str], int] = defaultdict(int)

    def get_pre_and_trend(self, team: str, league: str, season: str) -> Tuple[float, float, bool]:
        key = (team, league)
        hist = self._history[key]
        if not hist:
            return _DEFAULT_BASE_ELO, 0.0, False
        last_season, last_post = hist[-1]
        deltas = self._deltas[key]
        trend = float(np.mean(deltas)) if deltas else 0.0
        if last_season != season:
            ls_key = (league, season)
            n = self._league_season_n[ls_key]
            league_mean = (self._league_season_sum[ls_key] / n) if n else _DEFAULT_BASE_ELO
            last_post = league_mean + 0.5 * (last_post - league_mean)
        return last_post, trend, True

    def get_context(self, home: str, away: str, league: str, season: str) -> Dict[str, object]:
        home_pre, home_trend, home_found = self.get_pre_and_trend(home, league, season)
        away_pre, away_trend, away_found = self.get_pre_and_trend(away, league, season)
        return {
            "home_elo": home_pre, "away_elo": away_pre,
            "elo_difference": home_pre - away_pre,
            "home_elo_trend_5": home_trend, "away_elo_trend_5": away_trend,
            "elo_momentum_cross": home_trend - away_trend,
            "resolved": home_found and away_found,
        }

    def update(self, home: str, away: str, league: str, season: str, home_goals: int, away_goals: int) -> None:
        home_pre, _, _ = self.get_pre_and_trend(home, league, season)
        away_pre, _, _ = self.get_pre_and_trend(away, league, season)
        adjusted_home = home_pre + self._home_advantage
        home_expected = 1.0 / (1.0 + 10 ** ((away_pre - adjusted_home) / 400.0))
        away_expected = 1.0 - home_expected
        if home_goals > away_goals:
            home_actual, away_actual = 1.0, 0.0
        elif home_goals < away_goals:
            home_actual, away_actual = 0.0, 1.0
        else:
            home_actual, away_actual = 0.5, 0.5
        k = self._k_base * self._league_importance.get(league.lower(), 1.0)
        home_post = home_pre + k * (home_actual - home_expected)
        away_post = away_pre + k * (away_actual - away_expected)
        for team, pre, post in ((home, home_pre, home_post), (away, away_pre, away_post)):
            key = (team, league)
            self._deltas[key].append(post - pre)
            self._history[key].append((season, post))
            ls_key = (league, season)
            self._league_season_sum[ls_key] += post
            self._league_season_n[ls_key] += 1


def default_fast_elo_replay() -> FastEloReplay:
    """Construct a replay using the same settings/importance table EloEngine
    itself uses, so a caller cannot accidentally drift the two apart."""
    return FastEloReplay(
        home_advantage=float(settings.elo_home_advantage),
        k_base=float(settings.elo_k_base),
        league_importance=EloEngine.LEAGUE_IMPORTANCE,
    )


def cross_verify_against_elo_engine(matches: Sequence[Mapping[str, Any]], n_check: int = 300) -> None:
    """Run both engines over the first ``n_check`` matches and assert
    numerically identical pre-match context. Raises on mismatch; a caller must
    never trust ``FastEloReplay``'s output at scale without calling this
    first — the whole point of a from-scratch reimplementation is that it can
    silently diverge from the algorithm it is meant to replicate.
    """
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as scratch_dir:
        scratch = Path(scratch_dir) / "elo_cross_verify_scratch.parquet"
        real = EloEngine(parquet_path=scratch)
        fast = default_fast_elo_replay()
        mismatches = 0
        for i, m in enumerate(matches[:n_check]):
            league, season, date = m["league"], m["season"], m["date"]
            home, away, hg, ag = m["home"], m["away"], m["hg"], m["ag"]

            real_ctx = real.get_context(home, away, league, season, date)
            fast_ctx = fast.get_context(home, away, league, season)

            if not np.isclose(real_ctx.elo_difference, fast_ctx["elo_difference"], atol=1e-6) or (
                real_ctx.resolved != fast_ctx["resolved"]
            ):
                mismatches += 1

            real.update_after_match(
                match_id=f"verify_{i}", home_team_id=home, away_team_id=away,
                home_goals=hg, away_goals=ag, league=league, season=season,
                match_date=date, persist=False,
            )
            fast.update(home, away, league, season, hg, ag)

        if mismatches:
            raise RuntimeError(
                f"FastEloReplay diverged from EloEngine on {mismatches}/{n_check} matches — "
                "do not trust the fast replay's output until this is fixed."
            )


@dataclass(frozen=True)
class EloReplayResult:
    """Per-match Elo columns plus the counters needed to audit the run.

    ``rows`` is always the same length as the input and aligned to it by
    index — same shape as ``Phase8ReplayResult``. A skipped (self-play) match
    yields an empty dict, so a caller merging it onto the registry defaults
    leaves every Elo slot at its default rather than receiving a fabricated
    value.
    """

    rows: List[Dict[str, float]] = field(default_factory=list)
    matches_seen: int = 0
    skipped_self_play: int = 0
    resolved_both_sides: int = 0

    def summary(self) -> str:
        return (
            f"elo replay: {self.matches_seen} matches, "
            f"{self.resolved_both_sides}/{self.matches_seen} rows with both sides "
            f"resolved (>=1 prior match each), skipped_self_play={self.skipped_self_play}"
        )


def compute_elo_training_columns(matches: Sequence[Mapping[str, Any]]) -> EloReplayResult:
    """Replay real Elo over historical matches, in the order given.

    Unlike the Phase 8 replay, this does not need to internally re-sort:
    ``train_on_real_matches.load_matches`` already returns matches ascending
    by kickoff, and both this function's only caller and the ablation script
    feed it in that order. A row is computed PRE-match and the state update
    happens strictly AFTER — a match never informs its own row.

    Args:
        matches: Records shaped as ``train_on_real_matches.load_matches``
            emits them — ``league``, ``season``, ``date``, ``home``, ``away``,
            ``hg``, ``ag``. Extra keys are ignored.

    Returns:
        An :class:`EloReplayResult` whose ``rows[i]`` holds the 4
        :data:`ELO_TRAINING_COLUMNS` for ``matches[i]``, or an empty dict for
        a self-play record. Merge onto ``DEFAULT_FEATURE_VALUES_68``/``_89``
        to fill every other slot.
    """
    rows: List[Dict[str, float]] = [{} for _ in matches]
    replay = default_fast_elo_replay()
    skipped_self_play = 0
    resolved_both_sides = 0

    for index, m in enumerate(matches):
        league, season = m["league"], m["season"]
        home, away, hg, ag = m["home"], m["away"], m["hg"], m["ag"]

        if home == away:
            # Same defensive guard as the production durable-Elo backfill
            # (docs/DEBT.md item 23): a team recorded as playing itself must
            # never be replayed — it has no meaningful Elo update.
            skipped_self_play += 1
            continue

        ctx = replay.get_context(home, away, league, season)
        rows[index] = {
            "elo_difference": ctx["elo_difference"],
            "elo_home_trend_5": ctx["home_elo_trend_5"],
            "elo_away_trend_5": ctx["away_elo_trend_5"],
            "elo_momentum_cross": ctx["elo_momentum_cross"],
        }
        if ctx["resolved"]:
            resolved_both_sides += 1

        # Update AFTER emitting — a match never informs its own row.
        replay.update(home, away, league, season, hg, ag)

    return EloReplayResult(
        rows=rows,
        matches_seen=len(matches),
        skipped_self_play=skipped_self_play,
        resolved_both_sides=resolved_both_sides,
    )
