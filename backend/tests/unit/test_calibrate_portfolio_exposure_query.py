"""Pins the four defects that made `calibrate_portfolio_exposure.py` unrunnable.

The script shipped 2026-09-04 and was never executed against a real database.
Every one of these assertions corresponds to something that was wrong and would
have produced either a hard error or — worse — a plausible-looking number
derived from a biased statistic. See `docs/DEBT.md` item 9.

No database is required: the SQL is asserted as a contract, and the calibration
math is exercised directly on synthetic groups.
"""

from __future__ import annotations

import re

import pytest

from scripts.calibrate_portfolio_exposure import (
    _QUERY,
    _actual_outcome,
    _calibrate,
    _pairwise_agreement,
)


# --- the SQL contract ----------------------------------------------------


def test_query_does_not_name_columns_that_do_not_exist() -> None:
    """`match_prediction_logs` has neither a `league` nor `predicted_outcome`.

    Both were in the original query. Either one raises
    `UndefinedColumn` on the first real run.
    """
    assert "mpl.league" not in _QUERY
    assert "mpl.predicted_outcome" not in _QUERY


def test_league_comes_from_the_matches_table() -> None:
    assert "m.league_id AS league" in _QUERY


def test_predicted_outcome_is_derived_from_the_probability_columns() -> None:
    for column in ("home_probability", "draw_probability", "away_probability"):
        assert column in _QUERY
    for outcome in ("'home_win'", "'draw'", "'away_win'"):
        assert outcome in _QUERY


def test_status_match_is_case_insensitive() -> None:
    """Production writes 'finished' lower-case.

    The original `IN ('FINISHED', 'SETTLED')` matched zero rows — a silent
    empty result, not an error, which is the harder failure to notice.
    """
    assert "lower(m.status)" in _QUERY
    assert "'finished'" in _QUERY
    assert not re.search(r"IN \(\s*'FINISHED'", _QUERY)


def test_query_deduplicates_to_one_row_per_match() -> None:
    """Without this a match contributes several rows to the same group."""
    assert "DISTINCT ON (mpl.match_id)" in _QUERY
    assert "ORDER BY mpl.match_id" in _QUERY


def test_query_is_scoped_to_one_model_generation() -> None:
    """Cross-generation pooling was already fixed once, in
    `build_settled_predictions_query` (2026-08-17). Same rule here."""
    assert "mpl.model_version = %(model_version)s" in _QUERY


def test_model_version_is_bound_as_a_parameter_not_interpolated() -> None:
    assert "%(model_version)s" in _QUERY
    assert "v5_phase7" not in _QUERY, "the serving generation must not be hardcoded"


# --- the statistical consequence ----------------------------------------


def _member(match_id: str, actual: str) -> dict:
    return {
        "match_id": match_id,
        "predicted": actual,
        "actual": actual,
        "correct": True,
    }


def test_a_match_always_agrees_with_itself() -> None:
    """The mechanism behind the bias, stated directly.

    Duplicate rows for one match are the *same* result, so every self-pair
    agrees. Feeding them into the pairwise statistic inflates it toward 1.0.
    """
    duplicated = [_member("m1", "home_win"), _member("m1", "home_win")]
    assert _pairwise_agreement(duplicated) == 1.0


def test_duplicate_rows_inflate_measured_agreement() -> None:
    """Reproduces the real production effect in miniature.

    Live figures when this was found: 110 naive pairs at 0.6818 agreement, of
    which 43 were same-match self-pairs agreeing at exactly 1.0; deduplicated
    it is 30 pairs at 0.4333. Against the 1/3 chance baseline that is an excess
    of 0.3485 rather than 0.1000 — a 3.5x overstatement of the very
    correlation the haircut is derived from.
    """
    deduped = [
        _member("m1", "home_win"),
        _member("m2", "draw"),
        _member("m3", "away_win"),
    ]
    with_duplicates = deduped + [_member("m1", "home_win"), _member("m2", "draw")]

    assert _pairwise_agreement(deduped) == 0.0
    assert _pairwise_agreement(with_duplicates) > _pairwise_agreement(deduped)


def test_higher_measured_correlation_produces_a_harsher_haircut() -> None:
    """Why the bias matters rather than being cosmetic.

    An inflated agreement means a larger haircut and a smaller aggregate cap —
    the script would systematically under-stake on evidence that does not
    support it.
    """
    uncorrelated = {
        ("EPL", f"2026-09-0{i}"): [
            _member(f"a{i}", "home_win"),
            _member(f"b{i}", "draw"),
        ]
        for i in range(1, 10)
    }
    correlated = {
        ("EPL", f"2026-09-0{i}"): [
            _member(f"a{i}", "home_win"),
            _member(f"b{i}", "home_win"),
        ]
        for i in range(1, 10)
    }

    low = _calibrate(uncorrelated)["proposed_constants"]
    high = _calibrate(correlated)["proposed_constants"]

    assert (
        high["HAIRCUT_PER_ADDITIONAL_FIXTURE"] >= low["HAIRCUT_PER_ADDITIONAL_FIXTURE"]
    )
    assert high["AGGREGATE_CAP_MULTIPLIER"] <= low["AGGREGATE_CAP_MULTIPLIER"]


# --- reported fields -----------------------------------------------------


def test_group_and_pair_counts_are_reported_separately() -> None:
    """`n_pairs_measured` previously reported the number of groups.

    A human reads these two numbers to judge whether the estimate is thin, so
    labelling one as the other is a real reporting defect.
    """
    groups = {
        ("EPL", "2026-09-01"): [
            _member("a", "home_win"),
            _member("b", "draw"),
            _member("c", "draw"),
        ],
        ("SERIE_A", "2026-09-01"): [_member("d", "home_win"), _member("e", "home_win")],
    }
    result = _calibrate(groups)
    assert result["n_groups_measured"] == 2
    assert result["n_pairs_measured"] == 4  # C(3,2) + C(2,2) = 3 + 1


def test_low_volume_is_reported_and_blocks_apply() -> None:
    groups = {("EPL", "2026-09-01"): [_member("a", "home_win"), _member("b", "draw")]}
    result = _calibrate(groups)
    assert result["status"] == "LOW_VOLUME"
    assert result["recommendation"].startswith("DEFER")


@pytest.mark.parametrize(
    ("home", "away", "expected"),
    [(2, 1, "home_win"), (0, 3, "away_win"), (1, 1, "draw")],
)
def test_actual_outcome(home: int, away: int, expected: str) -> None:
    assert _actual_outcome(home, away) == expected
