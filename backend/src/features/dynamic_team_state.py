"""Local-level state-space team-strength rating — directive Experiment E6.

WHY THIS EXISTS
---------------
`PRODUCTION_EXECUTIVE_DIRECTIVE.md` §43 Experiment E6: *"latent team strength
changes faster than current Elo/rating representation. Candidate: lightweight
state-space model."*

The incumbent representation is `features/elo_replay.py::FastEloReplay` — Elo
with a **fixed** K-factor. A fixed K encodes one specific assumption: that
every observation carries the same amount of information about a team's
current strength, regardless of how stale the prior estimate is. A team
returning from a 90-day summer break and a team playing its third match in
eight days both move by exactly K·(actual − expected).

This module keeps Elo's expectation function **byte-for-byte identical** and
changes only that assumption. Each team carries a variance `P` alongside its
strength `θ`:

    time update (θ unchanged, uncertainty grows with the gap):
        P ← P + q · Δt_days
    measurement update (EKF linearisation of the logistic link):
        g  = ∂p/∂θ = p(1−p)·ln(10)/400
        S  = g²(P_h + P_a) + p(1−p)        # innovation variance
        K_i = P_i · g / S                   # Kalman gain, POINTS per unit prob error
        θ_h += K_h·(y − p) ;  θ_a −= K_a·(y − p)
        P_i ← (1 − K_i·g)·P_i

The gain is therefore time-varying and team-specific: a stale estimate (large
P) moves further on the next result than a well-observed one. That *is* the
E6 hypothesis, expressed as a model rather than a slogan.

NOT A NEW IDEA, AND SAID SO
---------------------------
This is the Glicko/Kalman family — Glickman's rating deviation is the same
`P`, grown by elapsed time and shrunk by observations. The defaults below are
Glicko's own published conventions (RD₀ = 350; c chosen so an unobserved
rating decays back toward RD 350 over roughly two years), **not** values tuned
on this corpus. Tuning them against the evaluation window would be the
test-set-informed selection item 64 already had to fix once.

DELIBERATE DIFFERENCES FROM `FastEloReplay`, AND WHY
----------------------------------------------------
* **No 50% season-carryover regression toward the league mean.** Elo needs
  that ad-hoc rule precisely because a fixed K has no notion of staleness.
  Here the summer gap is already ~90 days of accumulated process noise, so
  applying the regression too would double-count the same effect. The
  time-driven variance IS the principled replacement — and testing whether it
  is a *better* replacement is the experiment.
* **No per-league K multiplier.** `FastEloReplay` scales K by
  `EloEngine.LEAGUE_IMPORTANCE`; here the innovation variance already adapts
  per team, and adding a second, hand-set multiplier on top would confound
  which mechanism produced any difference.

Both differences are choices under test, not oversights. If E6 fails, "the
state-space parameterisation as specified" is what failed — reopening under
§42 would need a materially different formulation, not a re-run.

LEAKAGE
-------
`get_context()` reads state accumulated strictly *before* the match; `update()`
is called strictly *after*. A match can never inform its own row. The same
contract `compute_elo_training_columns` documents, pinned by
`tests/unit/test_dynamic_team_state.py`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Mapping, Sequence, Tuple

from .elo_replay import apply_season_carryover

_BASE_STRENGTH = 1500.0

#: Glicko's RD₀. A never-seen team is maximally uncertain.
_INITIAL_RD = 350.0

#: Glicko's c², in points² per day: an unobserved rating's RD climbs from 50
#: back to 350 over ~2 years. (350² − 50²) / 730 ≈ 164.4.
_PROCESS_VARIANCE_PER_DAY = (_INITIAL_RD**2 - 50.0**2) / 730.0

#: Elo's logistic link is base-10 over 400 points; this is d(p)/d(θ) / (p(1−p)).
_LINK_SLOPE = math.log(10.0) / 400.0

#: Floor on the innovation variance so a near-certain prediction (p→0 or 1)
#: cannot produce an unbounded gain. p(1−p) ≥ this.
_MIN_OBSERVATION_VARIANCE = 1e-4

#: Cadence the steady-state calibration below is solved at: one match a week.
_TYPICAL_CADENCE_DAYS = 7.0

#: Cap on accumulated uncertainty. Without it a club absent for several
#: seasons (relegated out of the corpus, then promoted back) returns with a
#: variance so large its first result nearly overwrites the estimate — a
#: single match is not that informative, and Glicko caps RD at RD₀ for the
#: same reason.
_MAX_VARIANCE = _INITIAL_RD**2

#: The columns this replay contributes, mirroring `ELO_TRAINING_COLUMNS`.
DYNAMIC_STATE_COLUMNS: Tuple[str, ...] = (
    "dynamic_strength_diff",
    "dynamic_uncertainty",
)


def calibrate_observation_noise_scale(
    *,
    k_elo: float,
    process_variance_per_day: float = _PROCESS_VARIANCE_PER_DAY,
    cadence_days: float = _TYPICAL_CADENCE_DAYS,
) -> float:
    """Observation-noise inflation that makes the STEADY-STATE gain equal `k_elo`.

    WHY THIS EXISTS — it is the experiment's control, not a tuning knob.

    E6 asks whether latent strength changes *faster* than a fixed-K rating
    assumes. That is a question about **adaptivity**, not about learning rate:
    a state-space model that simply moves ratings further per match would beat
    or lose to Elo for a reason having nothing to do with the hypothesis. So
    the two arms are matched on the nuisance parameter — identical expectation
    function, identical steady-state gain — leaving staleness-adaptivity as
    the only difference between them.

    Solved in closed form, touching **no data at all** (so it cannot be
    test-set-informed selection, the defect item 64 had to fix). At the
    steady state of the variance recursion with both teams symmetric at
    ``p = 0.5`` and a `cadence_days` gap:

        P⁻ = (1 − K·g)·P⁻ + q·Δt        ⟹  K = q·Δt / (g·P⁻)
        K  = P⁻·g / (2g²P⁻ + R)

    Eliminating ``P⁻`` between the two and solving for ``R`` gives the
    expression below; ``R`` is then reported as a multiple of the naive
    Bernoulli variance ``p(1−p) = 0.25``.

    The resulting multiple is ≈11× for this corpus's cadence, which is a
    physically sensible reading rather than a fudge: one football match is
    about an order of magnitude less informative about latent strength than a
    clean coin-flip observation would be, because match-level noise dominates.
    """
    if k_elo <= 0:
        raise ValueError("k_elo must be positive")
    slope = 0.25 * _LINK_SLOPE
    drift = cadence_days * process_variance_per_day
    prior_variance = drift / (slope * k_elo)
    observation_variance = (
        slope * slope * prior_variance * (prior_variance - 2.0 * drift) / drift
    )
    if observation_variance <= 0:
        raise ValueError(
            "no positive observation noise reproduces this steady-state gain; "
            f"k_elo={k_elo} is too large for q={process_variance_per_day}"
        )
    return observation_variance / 0.25


@dataclass
class _TeamState:
    strength: float = _BASE_STRENGTH
    variance: float = _INITIAL_RD**2
    last_played: date | None = None
    last_season: str | None = None


@dataclass(frozen=True)
class DynamicStateContext:
    """Pre-match state for one fixture.

    `strength_diff` is the direct analogue of `EloContext.elo_difference`.
    `uncertainty` is information Elo structurally cannot express: the standard
    deviation of the *difference* estimate, in rating points.
    """

    home_strength: float
    away_strength: float
    strength_diff: float
    home_rd: float
    away_rd: float
    uncertainty: float
    home_resolved: bool
    away_resolved: bool

    @property
    def resolved(self) -> bool:
        return self.home_resolved and self.away_resolved


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


class DynamicTeamStateReplay:
    """Chronological replay of the local-level state-space rating.

    API deliberately mirrors `FastEloReplay` (`get_context` / `update`) so a
    caller can run both over one loop and compare like with like, rather than
    two loops whose subtle ordering differences become part of the result.
    """

    def __init__(
        self,
        *,
        home_advantage: float,
        initial_rd: float = _INITIAL_RD,
        process_variance_per_day: float = _PROCESS_VARIANCE_PER_DAY,
        observation_noise_scale: float = 1.0,
        season_carryover: bool = False,
    ) -> None:
        """
        Args:
            season_carryover: Apply the incumbent's 50% regression toward the
                league mean at a season boundary, on top of the state-space
                gain. Defaults to False — the configuration E6 tested, where
                elapsed-time process noise is the principled *replacement* for
                that ad-hoc rule. Set True only for the item-72 ablation's
                cell B, which asks whether the two mechanisms are complements
                rather than alternatives. Only the RATING is regressed; the
                variance is left to the time update, so the flag varies one
                factor rather than smuggling a variance change in with it.
        """
        self._home_advantage = float(home_advantage)
        self._initial_variance = float(initial_rd) ** 2
        self._process_variance_per_day = float(process_variance_per_day)
        self._observation_noise_scale = float(observation_noise_scale)
        self._season_carryover = bool(season_carryover)
        self._states: Dict[Tuple[str, str], _TeamState] = {}
        self._league_season_sum: Dict[Tuple[str, str], float] = {}
        self._league_season_n: Dict[Tuple[str, str], int] = {}

    # ── state access ──────────────────────────────────────────────────────

    def _state(self, team: str, league: str) -> _TeamState:
        key = (team, league)
        state = self._states.get(key)
        if state is None:
            state = _TeamState(strength=_BASE_STRENGTH, variance=self._initial_variance)
            self._states[key] = state
        return state

    def _projected_variance(self, state: _TeamState, match_date: date) -> float:
        """Variance after the time update — grown by the gap since last seen.

        A team with no history is already at the initial variance; growing it
        further would be adding uncertainty about an estimate that carries
        none of its own.
        """
        if state.last_played is None:
            return state.variance
        elapsed_days = max((match_date - state.last_played).days, 0)
        grown = state.variance + self._process_variance_per_day * elapsed_days
        return min(grown, _MAX_VARIANCE)

    def _carried_strength(
        self, state: _TeamState, league: str, season: str | None
    ) -> float:
        """Rating entering this match, after the optional carryover rule.

        With `season_carryover=False` (E6's tested configuration) this is the
        identity — the time update already prices staleness. With it True, the
        incumbent's own rule is borrowed verbatim from `elo_replay`, not
        re-derived, so the ablation's two arms cannot drift apart.
        """
        if not self._season_carryover or season is None:
            return state.strength
        if state.last_season is None or state.last_season == season:
            return state.strength
        key = (league, season)
        n = self._league_season_n.get(key, 0)
        league_mean = (self._league_season_sum[key] / n) if n else _BASE_STRENGTH
        return apply_season_carryover(state.strength, league_mean)

    def get_context(
        self,
        home: str,
        away: str,
        league: str,
        match_date: date | datetime,
        season: str | None = None,
    ) -> DynamicStateContext:
        """Pre-match context. Reads state only; never mutates it.

        `season` is required only when `season_carryover=True`; the default
        configuration ignores it entirely.
        """
        when = _as_date(match_date)
        home_state, away_state = self._state(home, league), self._state(away, league)
        home_var = self._projected_variance(home_state, when)
        away_var = self._projected_variance(away_state, when)
        home_strength = self._carried_strength(home_state, league, season)
        away_strength = self._carried_strength(away_state, league, season)
        return DynamicStateContext(
            home_strength=home_strength,
            away_strength=away_strength,
            strength_diff=home_strength - away_strength,
            home_rd=math.sqrt(home_var),
            away_rd=math.sqrt(away_var),
            uncertainty=math.sqrt(home_var + away_var),
            home_resolved=home_state.last_played is not None,
            away_resolved=away_state.last_played is not None,
        )

    def expected_home_score(self, home_strength: float, away_strength: float) -> float:
        """Elo's own expectation, unchanged — see the module docstring.

        Identical to `FastEloReplay.update`'s formula, so any difference this
        experiment measures comes from the update gain, not from a second,
        subtly different link function.
        """
        adjusted_home = home_strength + self._home_advantage
        return 1.0 / (1.0 + 10 ** ((away_strength - adjusted_home) / 400.0))

    # ── measurement update ────────────────────────────────────────────────

    def update(
        self,
        home: str,
        away: str,
        league: str,
        match_date: date | datetime,
        home_goals: int,
        away_goals: int,
        season: str | None = None,
    ) -> None:
        """EKF measurement update. Call strictly AFTER `get_context`."""
        when = _as_date(match_date)
        home_state, away_state = self._state(home, league), self._state(away, league)

        home_var = self._projected_variance(home_state, when)
        away_var = self._projected_variance(away_state, when)

        # Same carried rating `get_context` just reported, so the update acts
        # on the estimate the prediction was made from.
        home_state.strength = self._carried_strength(home_state, league, season)
        away_state.strength = self._carried_strength(away_state, league, season)

        expected = self.expected_home_score(home_state.strength, away_state.strength)
        if home_goals > away_goals:
            actual = 1.0
        elif home_goals < away_goals:
            actual = 0.0
        else:
            actual = 0.5

        # EKF linearisation of the logistic link at the current estimate.
        bernoulli_variance = max(expected * (1.0 - expected), _MIN_OBSERVATION_VARIANCE)
        slope = bernoulli_variance * _LINK_SLOPE
        observation_variance = bernoulli_variance * self._observation_noise_scale
        innovation_variance = slope**2 * (home_var + away_var) + observation_variance

        home_gain = home_var * slope / innovation_variance
        away_gain = away_var * slope / innovation_variance
        innovation = actual - expected

        home_state.strength += home_gain * innovation
        away_state.strength -= away_gain * innovation
        # Joseph-free simple form: valid because the gain is the optimal one
        # for this linearisation, so P⁻ − K·g·P⁻ is already the posterior.
        home_state.variance = max((1.0 - home_gain * slope) * home_var, 1.0)
        away_state.variance = max((1.0 - away_gain * slope) * away_var, 1.0)
        home_state.last_played = when
        away_state.last_played = when

        if season is not None:
            home_state.last_season = season
            away_state.last_season = season
            # Running league-season mean, for the carryover rule to regress
            # toward. Accumulated from POST-match ratings, matching
            # FastEloReplay's own bookkeeping.
            key = (league, season)
            self._league_season_sum[key] = (
                self._league_season_sum.get(key, 0.0)
                + home_state.strength
                + away_state.strength
            )
            self._league_season_n[key] = self._league_season_n.get(key, 0) + 2


def default_dynamic_state_replay() -> DynamicTeamStateReplay:
    """Construct the replay from the same settings the incumbent Elo uses.

    Mirrors `elo_replay.default_fast_elo_replay()` so the two arms cannot
    silently drift apart on home advantage, and calibrates the observation
    noise off the SAME `settings.elo_k_base` the incumbent's fixed K comes
    from — matching their steady-state learning rates by construction.
    """
    from ..core.config import settings

    k_base = float(settings.elo_k_base)
    return DynamicTeamStateReplay(
        home_advantage=float(settings.elo_home_advantage),
        observation_noise_scale=calibrate_observation_noise_scale(k_elo=k_base),
    )


def compute_dynamic_state_columns(
    matches: Sequence[Mapping[str, object]],
    *,
    home_advantage: float,
    observation_noise_scale: float | None = None,
) -> List[Dict[str, float]]:
    """Replay the state-space rating over matches in the order given.

    Mirrors `elo_replay.compute_elo_training_columns`: `rows[i]` holds the
    columns for `matches[i]`, or an empty dict for a self-play record (the
    same guard docs/DEBT.md item 23 added to the production Elo backfill —
    26 such rows exist in this corpus's production twin).

    Args:
        matches: Records as `train_on_real_matches.load_matches` emits them —
            `league`, `date`, `home`, `away`, `hg`, `ag`. Extra keys ignored.
    """
    rows: List[Dict[str, float]] = [{} for _ in matches]
    replay = DynamicTeamStateReplay(
        home_advantage=home_advantage,
        observation_noise_scale=(
            1.0 if observation_noise_scale is None else observation_noise_scale
        ),
    )

    for index, match in enumerate(matches):
        home = str(match["home"])
        away = str(match["away"])
        league = str(match["league"])
        when = match["date"]
        if home == away:
            continue

        context = replay.get_context(home, away, league, when)  # type: ignore[arg-type]
        rows[index] = {
            "dynamic_strength_diff": context.strength_diff,
            "dynamic_uncertainty": context.uncertainty,
            "dynamic_home_rd": context.home_rd,
            "dynamic_away_rd": context.away_rd,
            "dynamic_resolved": float(context.resolved),
        }
        # Update AFTER emitting — a match never informs its own row.
        replay.update(
            home,
            away,
            league,
            when,
            int(match["hg"]),
            int(match["ag"]),  # type: ignore[arg-type]
        )

    return rows
