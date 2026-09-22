"""`src/features/dynamic_team_state.py` — directive Experiment E6.

The properties pinned here are the ones that make this model a genuine test of
E6's hypothesis rather than a reparameterised Elo:

* the update gain GROWS with the gap since a team last played (fixed-K Elo has
  no such mechanism — this is the whole experiment);
* uncertainty shrinks with observation and is capped, so a long-absent club
  cannot have its estimate overwritten by one result;
* the expectation function is numerically identical to `FastEloReplay`'s, so
  any measured difference comes from the gain and not from a second, subtly
  different link function;
* a match never informs its own row.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.features.dynamic_team_state import (
    DynamicTeamStateReplay,
    calibrate_observation_noise_scale,
    compute_dynamic_state_columns,
    default_dynamic_state_replay,
)
from src.features.elo_replay import (
    SEASON_CARRYOVER_RETENTION,
    apply_season_carryover,
    default_fast_elo_replay,
)

_HOME_ADVANTAGE = 60.0


def _replay() -> DynamicTeamStateReplay:
    return DynamicTeamStateReplay(home_advantage=_HOME_ADVANTAGE)


def _play(
    replay: DynamicTeamStateReplay,
    home: str,
    away: str,
    when: date,
    hg: int = 1,
    ag: int = 0,
    league: str = "EPL",
) -> None:
    replay.get_context(home, away, league, when)
    replay.update(home, away, league, when, hg, ag)


# ── The distinguishing property: adaptivity to staleness ────────────────────


def test_a_longer_layoff_produces_a_larger_rating_update() -> None:
    """E6's hypothesis, made falsifiable.

    Two identical teams play an identical result; the only difference is how
    long each has been idle. The staler estimate must move further. Fixed-K
    Elo moves both by exactly the same amount — that contrast is the entire
    point of the experiment, so if this test fails the model is not testing
    what E6 asks.
    """
    start = date(2023, 1, 1)

    def strength_after_gap(gap_days: int) -> float:
        replay = _replay()
        # Burn in: several matches so the variance settles well below RD0.
        for i in range(8):
            _play(replay, "Alpha", f"Filler{i}", start + timedelta(days=i * 7))
        resume = start + timedelta(days=8 * 7 + gap_days)
        before = replay.get_context("Alpha", "Beta", "EPL", resume).home_strength
        replay.update("Alpha", "Beta", "EPL", resume, 0, 3)  # heavy defeat
        after = replay.get_context("Alpha", "Beta", "EPL", resume).home_strength
        return abs(after - before)

    short_gap_move = strength_after_gap(3)
    long_gap_move = strength_after_gap(120)

    assert long_gap_move > short_gap_move, (
        f"a 120-day layoff moved the rating {long_gap_move:.3f} points but a "
        f"3-day gap moved it {short_gap_move:.3f} — the state-space model is "
        "not adapting to staleness, so it is only Elo with extra steps"
    )


def test_uncertainty_grows_with_elapsed_time() -> None:
    replay = _replay()
    start = date(2023, 1, 1)
    _play(replay, "Alpha", "Beta", start)

    soon = replay.get_context(
        "Alpha", "Gamma", "EPL", start + timedelta(days=1)
    ).home_rd
    later = replay.get_context(
        "Alpha", "Gamma", "EPL", start + timedelta(days=90)
    ).home_rd

    assert later > soon


def test_uncertainty_shrinks_when_a_team_is_observed() -> None:
    replay = _replay()
    start = date(2023, 1, 1)
    first = replay.get_context("Alpha", "Beta", "EPL", start).home_rd
    replay.update("Alpha", "Beta", "EPL", start, 2, 1)
    second = replay.get_context("Alpha", "Beta", "EPL", start).home_rd

    assert second < first


def test_accumulated_uncertainty_is_capped_at_the_initial_deviation() -> None:
    """A club absent for five years must not return so uncertain that one
    result overwrites its estimate. Glicko caps RD at RD0 for this reason."""
    replay = _replay()
    start = date(2019, 1, 1)
    _play(replay, "Alpha", "Beta", start)

    far_future = replay.get_context(
        "Alpha", "Gamma", "EPL", start + timedelta(days=5 * 365)
    )
    assert far_future.home_rd <= 350.0 + 1e-9


# ── Same link function as the incumbent ────────────────────────────────────


@pytest.mark.parametrize(
    "home_strength,away_strength",
    [(1500.0, 1500.0), (1600.0, 1400.0), (1400.0, 1650.0), (1500.0, 1512.5)],
)
def test_expectation_matches_the_incumbent_elo_formula(
    home_strength: float, away_strength: float
) -> None:
    """The comparison isolates the update gain, so the two models must agree
    exactly on what a given pair of ratings predicts."""
    elo = default_fast_elo_replay()
    replay = DynamicTeamStateReplay(home_advantage=elo._home_advantage)

    adjusted = home_strength + elo._home_advantage
    expected_elo = 1.0 / (1.0 + 10 ** ((away_strength - adjusted) / 400.0))

    assert replay.expected_home_score(home_strength, away_strength) == pytest.approx(
        expected_elo
    )


# ── The experiment's control: matched steady-state learning rate ───────────


def test_calibrated_steady_state_gain_matches_the_incumbent_k() -> None:
    """The control that makes E6 a test of adaptivity rather than of K.

    Run a long weekly-cadence sequence between evenly-matched teams — the
    exact regime the closed form solves for — and confirm the realised gain
    (points moved per unit of prediction error) converges on Elo's own K. If
    it did not, a difference in the study's headline could just as easily
    come from the candidate learning faster as from it adapting better.
    """
    k_elo = 20.0
    replay = DynamicTeamStateReplay(
        home_advantage=0.0,  # symmetric: keeps the steady state at p = 0.5
        observation_noise_scale=calibrate_observation_noise_scale(k_elo=k_elo),
    )
    start = date(2023, 1, 1)
    # Alternate results so neither side runs away; ratings stay near parity
    # and the variance recursion settles at its fixed point.
    for i in range(200):
        when = start + timedelta(days=7 * i)
        replay.get_context("Alpha", "Beta", "EPL", when)
        replay.update("Alpha", "Beta", "EPL", when, 1, 0) if i % 2 else replay.update(
            "Alpha", "Beta", "EPL", when, 0, 1
        )

    when = start + timedelta(days=7 * 200)
    before = replay.get_context("Alpha", "Beta", "EPL", when)
    expected = replay.expected_home_score(before.home_strength, before.away_strength)
    replay.update("Alpha", "Beta", "EPL", when, 1, 0)
    after = replay.get_context("Alpha", "Beta", "EPL", when)

    realised_gain = (after.home_strength - before.home_strength) / (1.0 - expected)
    assert realised_gain == pytest.approx(k_elo, rel=0.05), (
        f"steady-state gain {realised_gain:.2f} != incumbent K {k_elo}; the two "
        "arms are no longer matched on learning rate, so the study would be "
        "confounded"
    )


def test_calibration_rejects_a_gain_it_cannot_reproduce() -> None:
    """Fails closed rather than returning a negative observation variance."""
    with pytest.raises(ValueError):
        calibrate_observation_noise_scale(k_elo=10_000.0)


def test_default_replay_matches_the_incumbent_home_advantage() -> None:
    """Both arms must read the same settings, or the comparison drifts."""
    assert default_dynamic_state_replay()._home_advantage == (
        default_fast_elo_replay()._home_advantage
    )


# ── Leakage ────────────────────────────────────────────────────────────────


def test_a_match_never_informs_its_own_row() -> None:
    """Emitted context must reflect only strictly-earlier matches.

    Watched failing by moving the `replay.update(...)` call in
    `compute_dynamic_state_columns` above the `get_context(...)` line: the
    first row then carries a non-zero strength_diff instead of 0.0.
    """
    matches = [
        {
            "league": "EPL",
            "date": date(2023, 1, 1),
            "home": "Alpha",
            "away": "Beta",
            "hg": 5,
            "ag": 0,
        },
        {
            "league": "EPL",
            "date": date(2023, 1, 8),
            "home": "Alpha",
            "away": "Beta",
            "hg": 0,
            "ag": 0,
        },
    ]
    rows = compute_dynamic_state_columns(matches, home_advantage=_HOME_ADVANTAGE)

    # Row 0: neither team has any history, so both sit at the base strength.
    assert rows[0]["dynamic_strength_diff"] == pytest.approx(0.0)
    assert rows[0]["dynamic_resolved"] == 0.0
    # Row 1: the 5-0 is now in the past, so Alpha leads and both are resolved.
    assert rows[1]["dynamic_strength_diff"] > 0.0
    assert rows[1]["dynamic_resolved"] == 1.0


def test_self_play_rows_are_skipped_not_rated() -> None:
    """docs/DEBT.md item 23: 26 rows in the production twin of this corpus
    record a team playing itself. They must yield no rating, not a zero one."""
    matches = [
        {
            "league": "EPL",
            "date": date(2023, 1, 1),
            "home": "Alpha",
            "away": "Alpha",
            "hg": 1,
            "ag": 1,
        },
    ]
    rows = compute_dynamic_state_columns(matches, home_advantage=_HOME_ADVANTAGE)
    assert rows[0] == {}


def test_replay_is_deterministic() -> None:
    matches = [
        {
            "league": "EPL",
            "date": date(2023, 1, 1) + timedelta(days=7 * i),
            "home": f"T{i % 5}",
            "away": f"T{(i + 2) % 5}",
            "hg": i % 3,
            "ag": (i + 1) % 3,
        }
        for i in range(40)
    ]
    first = compute_dynamic_state_columns(matches, home_advantage=_HOME_ADVANTAGE)
    second = compute_dynamic_state_columns(matches, home_advantage=_HOME_ADVANTAGE)
    assert first == second


# ── Season carryover: the second factor in the item-72 2x2 ablation ────────


def _dominant_team_strength(*, season_carryover: bool) -> float:
    """Build one dominant team over season A, then read it entering season B."""
    replay = DynamicTeamStateReplay(
        home_advantage=_HOME_ADVANTAGE, season_carryover=season_carryover
    )
    start = date(2023, 8, 1)
    # Alpha beats a rotating cast all of season A; the rest beat each other,
    # so the league mean stays near the base while Alpha climbs away from it.
    for i in range(20):
        when = start + timedelta(days=7 * i)
        replay.get_context("Alpha", f"Rival{i % 4}", "EPL", when, season="2324")
        replay.update("Alpha", f"Rival{i % 4}", "EPL", when, 3, 0, season="2324")
    next_season = start + timedelta(days=365)
    return replay.get_context(
        "Alpha", "Rival0", "EPL", next_season, season="2425"
    ).home_strength


def test_carryover_off_by_default_leaves_the_rating_untouched_across_seasons() -> None:
    """E6's tested configuration: elapsed-time process noise is the principled
    replacement for the incumbent's blanket regression, not a supplement."""
    replay = DynamicTeamStateReplay(home_advantage=_HOME_ADVANTAGE)
    start = date(2023, 8, 1)
    for i in range(10):
        when = start + timedelta(days=7 * i)
        replay.get_context("Alpha", "Beta", "EPL", when, season="2324")
        replay.update("Alpha", "Beta", "EPL", when, 2, 0, season="2324")

    end_of_season = replay.get_context(
        "Alpha", "Beta", "EPL", start + timedelta(days=7 * 10), season="2324"
    ).home_strength
    new_season = replay.get_context(
        "Alpha", "Beta", "EPL", start + timedelta(days=365), season="2425"
    ).home_strength

    assert new_season == pytest.approx(end_of_season)


def test_carryover_on_pulls_a_dominant_rating_back_toward_the_league_mean() -> None:
    with_carryover = _dominant_team_strength(season_carryover=True)
    without = _dominant_team_strength(season_carryover=False)

    assert with_carryover < without, (
        "carryover must regress a dominant team toward the league mean; "
        f"got {with_carryover:.2f} with vs {without:.2f} without"
    )


def test_state_space_carryover_borrows_the_incumbent_rule_verbatim() -> None:
    """One rule, one implementation — the ablation's two arms cannot drift."""
    assert apply_season_carryover(1700.0, 1500.0) == pytest.approx(
        1500.0 + SEASON_CARRYOVER_RETENTION * 200.0
    )


def test_carryover_regresses_the_rating_but_not_the_variance() -> None:
    """The flag varies ONE factor. Bundling a variance reset into it would
    make the ablation's 'carryover' cell also a 'more uncertainty' cell."""
    start = date(2023, 8, 1)
    readings = {}
    for carryover in (False, True):
        replay = DynamicTeamStateReplay(
            home_advantage=_HOME_ADVANTAGE, season_carryover=carryover
        )
        for i in range(10):
            when = start + timedelta(days=7 * i)
            replay.get_context("Alpha", "Beta", "EPL", when, season="2324")
            replay.update("Alpha", "Beta", "EPL", when, 2, 0, season="2324")
        readings[carryover] = replay.get_context(
            "Alpha", "Beta", "EPL", start + timedelta(days=365), season="2425"
        ).home_rd

    assert readings[True] == pytest.approx(readings[False])


def test_a_win_raises_the_winner_and_lowers_the_loser() -> None:
    replay = _replay()
    when = date(2023, 1, 1)
    replay.get_context("Alpha", "Beta", "EPL", when)
    replay.update("Alpha", "Beta", "EPL", when, 3, 0)
    after = replay.get_context("Alpha", "Beta", "EPL", when)

    assert after.home_strength > 1500.0
    assert after.away_strength < 1500.0
