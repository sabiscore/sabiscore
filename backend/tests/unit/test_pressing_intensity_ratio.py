"""Regression guard for the home_pressing_intensity PPDA-inversion bug.

Found by GitHub Copilot's automated review of PR #153: the gated
home_pressing_intensity calculation used the raw ppda_ratio ratio
(home/away), contradicting both the docstring in
scripts/populate_statsbomb_cache.py ("pressing_intensity ~= 1/ppda_ratio")
and the feature's own name — a home side with LOWER (better) PPDA than its
opponent produced a ratio BELOW 1, i.e. the arithmetic said the harder-pressing
team was pressing less. Fixed by extracting the one-line formula into
_pressing_intensity_ratio() so both call sites in
UpcomingMatchFeatureProjector share it and it is unit-testable without
mocking the full async pipeline.
"""

from __future__ import annotations

import pytest

from src.services.upcoming_match_feature_service import _pressing_intensity_ratio


def test_home_pressing_harder_scores_above_one() -> None:
    """Home PPDA=8 (more pressing) vs away PPDA=12 (less pressing)."""
    ratio = _pressing_intensity_ratio(home_ppda_ratio=8.0, away_ppda_ratio=12.0)
    assert ratio > 1.0
    assert ratio == pytest.approx(12.0 / 8.0)


def test_away_pressing_harder_scores_below_one() -> None:
    """Home PPDA=12 (less pressing) vs away PPDA=8 (more pressing)."""
    ratio = _pressing_intensity_ratio(home_ppda_ratio=12.0, away_ppda_ratio=8.0)
    assert ratio < 1.0
    assert ratio == pytest.approx(8.0 / 12.0)


def test_equal_pressing_scores_one() -> None:
    assert _pressing_intensity_ratio(10.0, 10.0) == pytest.approx(1.0)


def test_zero_home_ppda_does_not_raise() -> None:
    """A degenerate zero/negative PPDA reading must not divide by zero."""
    ratio = _pressing_intensity_ratio(home_ppda_ratio=0.0, away_ppda_ratio=10.0)
    assert ratio > 0.0
    assert ratio < float("inf")
