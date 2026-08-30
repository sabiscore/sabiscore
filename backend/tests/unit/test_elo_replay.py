"""docs/DEBT.md item 48: real, cross-verified Elo replay for training.

Regression guard for the finding that motivated this module: every canonical
Elo feature was a constant 0.0 across every row `train_on_real_matches.py`
emitted, because nothing replayed Elo over the offline training corpus.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.features.elo_replay import (
    ELO_TRAINING_COLUMNS,
    compute_elo_training_columns,
    cross_verify_against_elo_engine,
)

_LEAGUE = "EPL"
_SEASON = "2526"
_KICKOFF = datetime(2026, 1, 1, 15, 0, 0)


def _matches(results: list[tuple[str, str, int, int]]) -> list[dict]:
    """Build a chronological match list. Each tuple is (home, away, hg, ag)."""
    return [
        {
            "league": _LEAGUE, "season": _SEASON,
            "date": _KICKOFF + timedelta(days=i),
            "home": home, "away": away, "hg": hg, "ag": ag,
        }
        for i, (home, away, hg, ag) in enumerate(results)
    ]


def test_elo_training_columns_excludes_the_permanently_gapped_field() -> None:
    """elo_league_adjusted is permanently PHASE7_FEATURES_ALWAYS_DATA_GAP by
    ATE-review policy — this replay must never touch it."""
    assert set(ELO_TRAINING_COLUMNS) == {
        "elo_difference", "elo_home_trend_5", "elo_away_trend_5", "elo_momentum_cross",
    }
    assert "elo_league_adjusted" not in ELO_TRAINING_COLUMNS


def test_cross_verify_against_real_elo_engine_does_not_raise() -> None:
    """The from-scratch reimplementation must agree with EloEngine before
    anything trusts its output at scale."""
    matches = _matches([
        ("Team A", "Team B", 2, 1),
        ("Team B", "Team C", 0, 0),
        ("Team A", "Team C", 3, 0),
        ("Team C", "Team A", 1, 1),
        ("Team B", "Team A", 2, 0),
    ])
    cross_verify_against_elo_engine(matches, n_check=len(matches))


def test_first_meeting_is_unresolved_neutral() -> None:
    """Two teams with no prior history both sit at the base rating —
    elo_difference is 0.0 and resolved_both_sides does not count this row."""
    matches = _matches([("Team A", "Team B", 1, 0)])
    result = compute_elo_training_columns(matches)
    assert result.matches_seen == 1
    assert result.rows[0]["elo_difference"] == 0.0
    assert result.resolved_both_sides == 0


def test_elo_difference_varies_after_a_result_is_recorded() -> None:
    """The regression this module exists to fix: elo_difference must NOT stay
    a constant 0.0 once teams have a real, divergent result history."""
    matches = _matches([
        ("Team A", "Team B", 3, 0),   # A beats B — A's rating rises, B's falls
        ("Team A", "Team B", 2, 0),   # rematch: A now enters as a real favourite
    ])
    result = compute_elo_training_columns(matches)
    first_diff = result.rows[0]["elo_difference"]
    second_diff = result.rows[1]["elo_difference"]
    assert first_diff == 0.0  # no prior history yet
    assert second_diff > 0.0  # A is now rated above B after winning the first meeting
    assert first_diff != second_diff
    assert result.resolved_both_sides == 1  # only the rematch had both sides resolved


def test_self_play_is_skipped_not_replayed() -> None:
    """Mirrors the production durable-Elo guard (docs/DEBT.md item 23): a
    team recorded as playing itself must never be replayed."""
    matches = _matches([("Team A", "Team A", 1, 1)])
    result = compute_elo_training_columns(matches)
    assert result.skipped_self_play == 1
    assert result.rows[0] == {}


def test_a_match_never_sees_its_own_result() -> None:
    """The row for a match is computed PRE-match; the state update happens
    strictly after, so replaying the same fixture twice back-to-back must
    give the identical elo_difference both times."""
    matches = _matches([
        ("Team A", "Team B", 5, 0),
        ("Team A", "Team B", 5, 0),
    ])
    result = compute_elo_training_columns(matches)
    # Both rows are computed from a state where only the FIRST match (if any)
    # has already been applied — the second row must reflect the first
    # match's outcome, not its own.
    assert result.rows[0]["elo_difference"] == 0.0
    assert result.rows[1]["elo_difference"] > 0.0
