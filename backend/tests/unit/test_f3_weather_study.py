"""Tests for the F3 weather incremental-value study's pure logic.

Covers the two things whose failure would be silent and would misreport a
research result: the dual-vocabulary corpus loader (a reader that speaks only
one vocabulary sees an empty season, not an error) and the §51 verdict rule
(the difference between "no measurable effect" and "measurably worse" is the
whole finding).

Matches the precedent in `test_incremental_value_harness.py`: pure functions
only. The pipeline itself is exercised by running it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _incremental_value_harness import load_fixtures_with_market  # noqa: E402
from study_f3_weather_incremental_value import _favourable, verdict  # noqa: E402

_MODERN = (
    "Div,Date,Time,HomeTeam,AwayTeam,FTR,B365H,B365D,B365A\n"
    "E0,15/04/2023,15:00,Arsenal,Chelsea,H,2.00,3.40,4.00\n"
)
_LEGACY = (
    "Div,date,Time,home_team,away_team,result,bet365_home,bet365_draw,bet365_away\n"
    "E0,15/04/2023,15:00,Arsenal,Chelsea,H,2.00,3.40,4.00\n"
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_loader_reads_both_corpus_vocabularies_identically(tmp_path: Path):
    """The 2025/26 files renamed every column; both must yield the same row."""
    modern = load_fixtures_with_market(_write(tmp_path, "fd_E0_2526.csv", _MODERN))
    legacy = load_fixtures_with_market(_write(tmp_path, "fd_E0_2223.csv", _LEGACY))

    assert len(modern) == len(legacy) == 1
    assert modern[0] == legacy[0]
    assert modern[0]["home_team"] == "Arsenal"
    assert modern[0]["outcome"] == 0  # H -> 0, the RPS convention


def test_loader_drops_a_fixture_whose_price_implies_certainty(tmp_path: Path):
    """A quoted price at or below 1.0 is corrupt input, not a long shot."""
    body = _MODERN.replace("2.00,3.40,4.00", "1.00,3.40,4.00")
    assert load_fixtures_with_market(_write(tmp_path, "fd_E0_2526.csv", body)) == []


def test_loader_returns_nothing_when_a_required_column_is_absent(tmp_path: Path):
    """Fails closed on an unrecognised vocabulary rather than half-reading it."""
    body = _MODERN.replace("B365H", "PinnacleH")
    assert load_fixtures_with_market(_write(tmp_path, "fd_E0_2526.csv", body)) == []


def _fold(lower: float, upper: float) -> dict:
    return {
        "pooled": {
            "n": 500,
            "candidate_minus_baseline_bootstrap": {"ci_lower": lower, "ci_upper": upper},
        }
    }


def _arm(*folds) -> dict:
    return {"learner": "test", "folds": {f"test_{i}": f for i, f in enumerate(folds)}}


def test_favourable_requires_the_interval_to_exclude_zero():
    assert _favourable(_fold(-0.004, -0.001)["pooled"]) is True   # wholly better
    assert _favourable(_fold(0.001, 0.004)["pooled"]) is False    # wholly worse
    assert _favourable(_fold(-0.002, 0.003)["pooled"]) is None    # straddles zero


def test_promoted_only_when_every_pooled_fold_excludes_zero_favourably():
    result = verdict({"a": _arm(_fold(-0.004, -0.001), _fold(-0.003, -0.002))})
    assert result["label"] == "PROMOTED"
    assert result["pooled_folds_improving"] == 2


def test_one_improving_fold_among_several_does_not_promote():
    """The bar is every fold. A single favourable origin is not a result."""
    result = verdict({"a": _arm(_fold(-0.004, -0.001), _fold(-0.002, 0.003))})
    assert result["label"] == "DEGRADES_BASELINE"
    assert result["pooled_folds_improving"] == 1


def test_no_effect_is_reported_as_no_effect_not_as_worse():
    """The operator label is binary; the precise reading must not be."""
    result = verdict({"a": _arm(_fold(-0.002, 0.003), _fold(-0.001, 0.002))})
    assert result["label"] == "DEGRADES_BASELINE"
    assert result["pooled_folds_degrading"] == 0
    assert result["pooled_folds_indistinguishable"] == 2
    assert "NO MEASURABLE EFFECT" in result["precise_reading"]


def test_genuinely_worse_is_distinguished_from_no_effect():
    result = verdict({"a": _arm(_fold(0.001, 0.004), _fold(-0.001, 0.002))})
    assert result["label"] == "DEGRADES_BASELINE"
    assert result["pooled_folds_degrading"] == 1
    assert "measurably WORSE" in result["precise_reading"]


def test_verdict_is_inconclusive_when_no_fold_scored():
    assert verdict({"a": _arm({"error": "insufficient_train_or_test_rows"})})["label"] == (
        "INCONCLUSIVE"
    )
