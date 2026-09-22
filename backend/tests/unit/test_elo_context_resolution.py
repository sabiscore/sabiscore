"""Regression: an unresolved Elo rating must be reported, never published silently.

`EloEngine._get_pre_and_trend()` falls back to `_DEFAULT_BASE_ELO` (1500.0) for a
team it has no prior rating for. Both sides unresolved therefore yields
`elo_difference == 0.0` and zero trends — numerically identical to two genuinely
equal, well-measured teams.

`EloContext` previously carried no signal distinguishing the two, and
`build_live_feature_vector*` writes those values straight into the canonical
vector. Because `_CALLER_RESOLVED_FEATURES` deliberately excludes the Elo
features from `project_match_features()`'s own gap tracking (on the assumption
the caller resolves them), an absent rating was reported nowhere at all: not as
a gap, not in `feature_defaulted_ratio`, and not in the completeness term of
`_compute_edge_quality_score`. That is the vΩ.24 "neutral default rendered as a
measurement" class, on the highest-ATE feature in the registry.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from src.data.elo_engine import EloEngine

MATCH_DATE = datetime(2026, 8, 15)


def _engine_with(tmp_path, rows) -> EloEngine:
    path = tmp_path / "elo.parquet"
    pd.DataFrame(
        rows,
        columns=[
            "match_id",
            "team_id",
            "pre_match_elo",
            "post_match_elo",
            "league",
            "season",
            "match_date",
        ],
    ).to_parquet(path)
    return EloEngine(parquet_path=path)


def test_unknown_teams_report_unresolved(tmp_path):
    """No rows at all — the 1500/1500 baseline must not claim to be measured."""
    engine = _engine_with(tmp_path, [])
    ctx = engine.get_context(
        home_team_id="nobody",
        away_team_id="nowhere",
        league="EPL",
        season="2026/2027",
        match_date=MATCH_DATE,
    )

    assert ctx.elo_difference == 0.0  # the trap: looks like an even matchup
    assert ctx.home_resolved is False
    assert ctx.away_resolved is False
    assert ctx.resolved is False


def test_one_sided_history_is_not_fully_resolved(tmp_path):
    """A rating for only one side still can't support a real elo_difference."""
    engine = _engine_with(
        tmp_path,
        [
            (
                "m1",
                "team-home",
                1500.0,
                1540.0,
                "EPL",
                "2026/2027",
                datetime(2026, 8, 1),
            ),
        ],
    )
    ctx = engine.get_context(
        home_team_id="team-home",
        away_team_id="team-away",
        league="EPL",
        season="2026/2027",
        match_date=MATCH_DATE,
    )

    assert ctx.home_resolved is True
    assert ctx.away_resolved is False
    assert ctx.resolved is False


def test_both_sides_with_history_resolve(tmp_path):
    engine = _engine_with(
        tmp_path,
        [
            (
                "m1",
                "team-home",
                1500.0,
                1540.0,
                "EPL",
                "2026/2027",
                datetime(2026, 8, 1),
            ),
            (
                "m2",
                "team-away",
                1500.0,
                1470.0,
                "EPL",
                "2026/2027",
                datetime(2026, 8, 2),
            ),
        ],
    )
    ctx = engine.get_context(
        home_team_id="team-home",
        away_team_id="team-away",
        league="EPL",
        season="2026/2027",
        match_date=MATCH_DATE,
    )

    assert ctx.resolved is True
    assert ctx.elo_difference == pytest.approx(70.0)


def test_committed_elo_artifact_cannot_resolve_real_team_ids():
    """Documents the live production state, so it is not re-diagnosed as a bug.

    The committed Elo parquet is keyed by synthetic slot ids ("bundesliga_home_0"),
    not real Team.id values, so no live fixture can ever resolve against it. This
    test asserts the *honest reporting* of that, not that resolution succeeds —
    flip it once a real Elo replay lands (docs/DEBT.md item 10).
    """
    ctx = EloEngine().get_context(
        home_team_id="arsenal-fc",
        away_team_id="chelsea-fc",
        league="EPL",
        season="2026/2027",
        match_date=MATCH_DATE,
    )
    assert ctx.resolved is False, (
        "Elo now resolves real team ids — the replay landed; update docs/DEBT.md "
        "item 10 and this test's expectation."
    )
