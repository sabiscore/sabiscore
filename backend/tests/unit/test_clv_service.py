"""Unit tests for services.clv_service.compute_clv_summary().

Contracts verified:
  1. Below the n>=10 floor -> skipped: True with the true count in the reason.
  2. mean_clv is model_probs[argmax] - closing_probs[argmax], averaged.
  3. positive_rate is the fraction of records with CLV > 0.
  4. A record whose model_probs don't sum to ~1.0 is excluded from n itself,
     not merely from the mean — this can flip skipped from True to False if
     gotten wrong, which is what the test below actually pins.
"""

from __future__ import annotations

import pytest

from src.services.clv_service import compute_clv_summary


def _record(model_probs: list[float], closing_probs: list[float]) -> dict:
    return {"model_probs": model_probs, "closing_probs": closing_probs}


def test_below_floor_is_skipped_with_true_count() -> None:
    records = [_record([0.5, 0.3, 0.2], [0.4, 0.35, 0.25]) for _ in range(3)]

    result = compute_clv_summary(records)

    assert result["skipped"] is True
    assert result["n"] == 3
    assert "3" in result["reason"]


def test_mean_clv_and_positive_rate_hand_computed() -> None:
    # argmax(model_probs) is index 0 in every record below.
    positive = [
        _record([0.6, 0.25, 0.15], [0.5, 0.3, 0.2]) for _ in range(6)
    ]  # CLV = 0.6 - 0.5 = +0.1
    negative = [
        _record([0.6, 0.25, 0.15], [0.7, 0.2, 0.1]) for _ in range(4)
    ]  # CLV = 0.6 - 0.7 = -0.1

    result = compute_clv_summary(positive + negative)

    assert result["skipped"] is False
    assert result["n"] == 10
    # (6 * 0.1 + 4 * -0.1) / 10 = 0.02
    assert result["mean_clv"] == pytest.approx(0.02)
    assert result["positive_rate"] == pytest.approx(0.6)


def test_malformed_probability_sum_excluded_from_n_not_just_the_mean() -> None:
    """9 valid records + 3 with model_probs summing to 1.5 (not ~1.0). If the
    malformed rows leaked into n, this would read n=12 and skipped=False —
    the wrong side of the floor. Excluding them from n correctly keeps it at
    9, below the floor."""
    valid = [_record([0.6, 0.25, 0.15], [0.5, 0.3, 0.2]) for _ in range(9)]
    malformed = [_record([0.5, 0.5, 0.5], [0.4, 0.3, 0.3]) for _ in range(3)]

    result = compute_clv_summary(valid + malformed)

    assert result["skipped"] is True
    assert result["n"] == 9
