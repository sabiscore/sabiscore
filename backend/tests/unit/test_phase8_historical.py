"""Guards for the Phase 8 historical replay (docs/DEBT.md item 29).

The defect these exist to prevent is specific: a training run whose 21 Phase 8
columns are *constant*, producing a model that learned nothing from them while
its metadata claims ``feature_count: 89``. Shape-only assertions ("21 columns
present") would have passed under exactly that bug, so the load-bearing tests
here are the ones asserting the values genuinely vary, and that a row never
reflects its own match's result.
"""

from datetime import datetime

import pytest

from src.features.phase8_historical import (
    RESOLVED_FEATURES,
    UNRESOLVED_FEATURES,
    compute_phase8_training_columns,
)
from src.models.feature_registry import DEFAULT_FEATURE_VALUES_89, PHASE8_FEATURES_21


def _match(day: int, home: str, away: str, hg: int, ag: int, league: str = "EPL") -> dict:
    return {
        "league": league,
        "season": "2324",
        "date": datetime(2024, 1, day),
        "home": home,
        "away": away,
        "hg": hg,
        "ag": ag,
    }


def test_resolved_and_unresolved_partition_the_registry_exactly():
    """Adding a Phase 8 feature without classifying it must fail here.

    This is the drift guard: the module hardcodes 15 resolvable names, and the
    registry owns the canonical 21. If those two ever disagree, a column would
    silently ship unlisted and unclassified.
    """
    assert set(RESOLVED_FEATURES).isdisjoint(UNRESOLVED_FEATURES)
    assert set(RESOLVED_FEATURES) | set(UNRESOLVED_FEATURES) == set(PHASE8_FEATURES_21)
    assert len(RESOLVED_FEATURES) == 15
    assert len(UNRESOLVED_FEATURES) == 6


def test_first_match_is_neutral_cold_start():
    """No prior history means neutral ratings — matching serving's behaviour
    for an unseen team, not a fabricated value."""
    result = compute_phase8_training_columns([_match(1, "A", "B", 2, 0)])

    row = result.rows[0]
    assert row["home_pi_attack"] == 0.0
    assert row["away_pi_attack"] == 0.0
    assert row["pi_attack_diff"] == 0.0
    assert row["home_berrar_rating"] == 1500.0
    assert row["berrar_rating_diff"] == 0.0


def test_ratings_vary_across_matches():
    """THE test. A constant column is the defect; this proves variance."""
    matches = [
        _match(1, "A", "B", 3, 0),
        _match(2, "A", "C", 2, 0),
        _match(3, "A", "D", 1, 0),
        _match(4, "A", "E", 4, 1),
    ]
    result = compute_phase8_training_columns(matches)

    # A has won everything, so its attack rating and Berrar rating must climb
    # monotonically across the four rows.
    attacks = [row["home_pi_attack"] for row in result.rows]
    berrars = [row["home_berrar_rating"] for row in result.rows]
    assert attacks == sorted(attacks) and len(set(attacks)) == 4, attacks
    assert berrars == sorted(berrars) and len(set(berrars)) == 4, berrars

    # Form must move off the cold-start prior too, once results exist.
    ppgs = [row["home_weighted_ppg"] for row in result.rows]
    assert len(set(ppgs)) > 1, ppgs
    assert ppgs[-1] == pytest.approx(3.0), "four straight wins should reach max PPG"


def test_row_never_reflects_its_own_result():
    """No-leakage invariant: the row for match N is the state BEFORE match N."""
    matches = [_match(1, "A", "B", 5, 0), _match(2, "A", "B", 5, 0)]
    result = compute_phase8_training_columns(matches)

    # Row 0 is pre-any-history, so it must still be neutral despite A winning 5-0.
    assert result.rows[0]["home_pi_attack"] == 0.0
    assert result.rows[0]["home_berrar_rating"] == 1500.0
    # Row 1 sees match 0's result, and only match 0's.
    assert result.rows[1]["home_pi_attack"] > 0.0
    assert result.rows[1]["home_berrar_rating"] > 1500.0


def test_self_play_is_skipped_without_wedging_the_batch():
    """docs/DEBT.md item 23: 26 production rows have home_team_id == away_team_id,
    and in Elo they aborted the entire batch flush. Here the neighbours survive."""
    matches = [
        _match(1, "A", "B", 2, 0),
        _match(2, "A", "A", 1, 1),  # poison
        _match(3, "A", "C", 3, 1),
    ]
    result = compute_phase8_training_columns(matches)

    assert result.skipped_self_play == 1
    assert result.rows[1] == {}, "skipped match must yield no fabricated values"
    assert result.rows[0] and result.rows[2], "neighbours must still resolve"
    assert result.rows_resolved == 2


def test_malformed_record_is_skipped_without_wedging_the_batch():
    matches = [
        _match(1, "A", "B", 2, 0),
        {"league": "EPL", "date": "not-a-datetime", "home": "A", "away": "C", "hg": 1, "ag": 0},
        {"league": "EPL", "date": datetime(2024, 1, 3), "home": "A"},  # missing keys
        _match(4, "A", "D", 3, 1),
    ]
    result = compute_phase8_training_columns(matches)

    assert result.skipped_malformed == 2
    assert result.rows[1] == {} and result.rows[2] == {}
    assert result.rows[0] and result.rows[3]


def test_rows_align_to_input_order_even_when_unsorted():
    """The engines require chronological order but the caller indexes by
    position, so the replay must sort internally and realign."""
    early = _match(1, "A", "B", 3, 0)
    late = _match(9, "A", "C", 0, 3)
    forward = compute_phase8_training_columns([early, late])
    reversed_input = compute_phase8_training_columns([late, early])

    # Same match, same chronological position, therefore same values —
    # regardless of the order it was handed to us in.
    assert reversed_input.rows[1] == forward.rows[0]
    assert reversed_input.rows[0] == forward.rows[1]


def test_leagues_do_not_share_rating_state():
    """Team-name keys are only unique within a league in this corpus."""
    matches = [
        _match(1, "A", "B", 5, 0, league="EPL"),
        _match(2, "A", "B", 0, 0, league="LA_LIGA"),
    ]
    result = compute_phase8_training_columns(matches)

    assert result.rows[1]["home_pi_attack"] == 0.0, "La Liga 'A' must start neutral"
    assert result.rows[1]["home_berrar_rating"] == 1500.0


def test_unresolved_columns_are_never_emitted():
    """Market drift and match importance cannot be honestly derived here, so
    they must be absent — leaving the caller's registry default in place —
    rather than present-and-invented."""
    result = compute_phase8_training_columns([_match(1, "A", "B", 2, 0)])

    for name in UNRESOLVED_FEATURES:
        assert name not in result.rows[0]
    for name in RESOLVED_FEATURES:
        assert name in result.rows[0]


def test_merging_onto_registry_defaults_yields_a_complete_phase8_block():
    """The documented integration contract: merge onto DEFAULT_FEATURE_VALUES_89
    and every one of the 21 columns is populated, 15 real and 6 defaulted."""
    result = compute_phase8_training_columns([_match(1, "A", "B", 2, 0)])
    features = dict(DEFAULT_FEATURE_VALUES_89)
    features.update(result.rows[0])

    assert all(name in features for name in PHASE8_FEATURES_21)
    for name in UNRESOLVED_FEATURES:
        assert features[name] == DEFAULT_FEATURE_VALUES_89[name]


def test_empty_input_is_not_an_error():
    result = compute_phase8_training_columns([])
    assert result.rows == []
    assert result.matches_seen == 0
    assert result.rows_resolved == 0
