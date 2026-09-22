"""Unit tests for backend.src.core.portfolio_exposure (ADR-0005 / WP-17).

Stateless, advisory-only policy: grouping/haircut/aggregate-cap math, the
vΩ.26 league-vocabulary regression, mutation safety, and the honest
drawdown stub. See docs/adr/0005-portfolio-exposure-policy.md.
"""

from __future__ import annotations

import pytest

from src.core.portfolio_exposure import compute_portfolio_exposure, haircut_multiplier


def _match(
    match_id="m1",
    league="EREDIVISIE",
    match_date="2026-08-07T15:00:00Z",
    has_value=True,
    kelly_stake_pct=2.0,
    edge_pct=5.0,
):
    best_value_bet = (
        {
            "kelly_stake_pct": kelly_stake_pct,
            "edge_pct": edge_pct,
            "outcome": "home_win",
        }
        if has_value
        else None
    )
    return {
        "match_id": match_id,
        "league": league,
        "match_date": match_date,
        "has_value": has_value,
        "best_value_bet": best_value_bet,
    }


def test_haircut_multiplier_pure_function():
    assert haircut_multiplier(1) == 1.0
    assert haircut_multiplier(2) == 0.9
    assert haircut_multiplier(100) == 0.50  # floored


def test_single_flagged_fixture_gets_no_haircut():
    matches = [_match()]
    compute_portfolio_exposure(matches)
    assert matches[0]["portfolio"]["correlation_haircut_multiplier"] == 1.0
    assert (
        matches[0]["portfolio"]["adjusted_kelly_stake_pct"]
        == matches[0]["portfolio"]["raw_kelly_stake_pct"]
    )


def test_two_same_league_same_day_fixtures_get_haircut():
    matches = [_match(match_id="m1"), _match(match_id="m2")]
    compute_portfolio_exposure(matches)
    for m in matches:
        assert m["portfolio"]["correlation_group_size"] == 2
        assert m["portfolio"]["correlation_haircut_multiplier"] == 0.9


def test_haircut_floors_at_configured_minimum():
    matches = [_match(match_id=f"m{i}") for i in range(20)]
    compute_portfolio_exposure(matches)
    for m in matches:
        assert m["portfolio"]["correlation_haircut_multiplier"] == 0.50


def test_different_leagues_same_day_are_not_grouped_together():
    matches = [
        _match(match_id="m1", league="EREDIVISIE"),
        _match(match_id="m2", league="EPL"),
    ]
    compute_portfolio_exposure(matches)
    for m in matches:
        assert m["portfolio"]["correlation_group_size"] == 1
        assert m["portfolio"]["correlation_haircut_multiplier"] == 1.0


def test_same_league_different_day_are_not_grouped_together():
    matches = [
        _match(match_id="m1", match_date="2026-08-07T15:00:00Z"),
        _match(match_id="m2", match_date="2026-08-14T15:00:00Z"),
    ]
    compute_portfolio_exposure(matches)
    for m in matches:
        assert m["portfolio"]["correlation_group_size"] == 1


def test_display_form_and_canonical_form_league_strings_group_together():
    """Regression for the vΩ.26 defect class: "Eredivisie" (display form) and
    "EREDIVISIE" (canonical form) must group as one N=2 pair, not silently
    split into two N=1 groups."""
    matches = [
        _match(match_id="m1", league="Eredivisie"),
        _match(match_id="m2", league="EREDIVISIE"),
    ]
    compute_portfolio_exposure(matches)
    for m in matches:
        assert m["portfolio"]["correlation_group_size"] == 2


def test_non_flagged_fixtures_excluded_from_grouping_and_get_null_portfolio():
    matches = [
        _match(match_id="m1", has_value=True),
        _match(match_id="m2", has_value=False),
    ]
    compute_portfolio_exposure(matches)
    assert matches[0]["portfolio"]["correlation_group_size"] == 1
    assert matches[1]["portfolio"] is None


def test_aggregate_cap_uses_max_kelly_cap_among_flagged_leagues():
    # EREDIVISIE kelly_cap=0.025, EPL kelly_cap=0.04 (CALIBRATED) -> basis uses 0.04
    matches = [
        _match(match_id="m1", league="EREDIVISIE"),
        _match(match_id="m2", league="EPL", match_date="2026-08-22T15:00:00Z"),
    ]
    summary = compute_portfolio_exposure(matches)
    assert summary["aggregate_cap_pct"] == pytest.approx(3.0 * 0.04 * 100)


def test_aggregate_cap_falls_back_to_default_when_no_league_resolves():
    matches = [_match(match_id="m1", league="NOT_A_REAL_LEAGUE")]
    summary = compute_portfolio_exposure(matches)
    assert summary["aggregate_cap_pct"] == pytest.approx(3.0 * 0.05 * 100)


def test_exceeds_aggregate_cap_flags_only_fixtures_that_push_running_total_over_cap_ranked_by_edge():
    # Different days -> no haircut interaction; isolates the aggregate-cap math.
    # EREDIVISIE aggregate_cap_pct = 3.0 * 0.025 * 100 = 7.5
    matches = [
        _match(
            match_id="m1",
            match_date="2026-08-07T15:00:00Z",
            edge_pct=10.0,
            kelly_stake_pct=3.0,
        ),
        _match(
            match_id="m2",
            match_date="2026-08-08T15:00:00Z",
            edge_pct=8.0,
            kelly_stake_pct=3.0,
        ),
        _match(
            match_id="m3",
            match_date="2026-08-09T15:00:00Z",
            edge_pct=5.0,
            kelly_stake_pct=3.0,
        ),
    ]
    summary = compute_portfolio_exposure(matches)

    by_id = {m["match_id"]: m for m in matches}
    assert (
        by_id["m1"]["portfolio"]["exceeds_aggregate_cap"] is False
    )  # running 3.0 <= 7.5
    assert (
        by_id["m2"]["portfolio"]["exceeds_aggregate_cap"] is False
    )  # running 6.0 <= 7.5
    assert (
        by_id["m3"]["portfolio"]["exceeds_aggregate_cap"] is True
    )  # running 9.0 > 7.5
    assert summary["exceeds_aggregate_cap"] is True


def test_exceeds_aggregate_cap_never_true_when_total_under_cap():
    matches = [_match(match_id="m1", kelly_stake_pct=1.0, edge_pct=5.0)]
    summary = compute_portfolio_exposure(matches)
    assert matches[0]["portfolio"]["exceeds_aggregate_cap"] is False
    assert summary["exceeds_aggregate_cap"] is False


def test_drawdown_status_reports_insufficient_data_never_fabricates_zero():
    summary = compute_portfolio_exposure([_match()])
    assert summary["drawdown"]["status"] == "insufficient_settled_predictions"
    assert summary["drawdown"]["realized_drawdown_pct"] is None


def test_compute_portfolio_exposure_does_not_mutate_value_bets_or_best_value_bet():
    match = _match()
    original_best_value_bet = dict(match["best_value_bet"])
    compute_portfolio_exposure([match])
    assert match["best_value_bet"] == original_best_value_bet


def test_compute_portfolio_exposure_handles_empty_batch():
    summary = compute_portfolio_exposure([])
    assert summary["aggregate_recommended_pct"] == 0.0
    assert summary["exceeds_aggregate_cap"] is False
