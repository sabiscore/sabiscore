"""Unit tests for src/features/draw_recalibration.py."""

from __future__ import annotations

import numpy as np
import pytest

from src.features.draw_recalibration import DrawRecalibrator


# ── fit ───────────────────────────────────────────────────────────────────────


def test_fit_empty_returns_identity():
    cal = DrawRecalibrator.fit(np.array([]), np.zeros((0, 3)))
    assert cal.factor == 1.0


def test_fit_zero_modeled_draw_rate_returns_identity():
    y_cal = np.array([0, 0, 2])
    y_proba = np.array([[0.6, 0.0, 0.4], [0.7, 0.0, 0.3], [0.3, 0.0, 0.7]])
    cal = DrawRecalibrator.fit(y_cal, y_proba)
    assert cal.factor == 1.0


def test_fit_computes_factor():
    # 50% actual draws, 25% modeled → factor = 2.0
    y_cal = np.array([1, 1, 0, 0])  # 50% draws (label=1 is draw here per docstring)
    # Actually the module says 0=home, 1=draw, 2=away
    y_cal = np.array([1, 1, 0, 2])  # 2 draws out of 4 → 50%
    y_proba = np.array(
        [
            [0.5, 0.25, 0.25],
            [0.5, 0.25, 0.25],
            [0.7, 0.15, 0.15],
            [0.4, 0.25, 0.35],
        ]
    )
    cal = DrawRecalibrator.fit(y_cal, y_proba)
    actual_draw_rate = 0.5
    modeled_draw_rate = (0.25 + 0.25 + 0.15 + 0.25) / 4
    expected_factor = round(actual_draw_rate / modeled_draw_rate, 4)
    assert cal.factor == pytest.approx(expected_factor, abs=0.001)


def test_fit_factor_gt_1_when_model_underpredicts_draws():
    # Model says 10% draws, actual 30% → factor > 1
    y_cal = np.array([1, 1, 1, 0, 2, 0, 2, 2, 2, 2])
    y_proba = np.zeros((10, 3))
    y_proba[:, 0] = 0.8
    y_proba[:, 1] = 0.1
    y_proba[:, 2] = 0.1
    cal = DrawRecalibrator.fit(y_cal, y_proba)
    assert cal.factor > 1.0


# ── recalibrate ───────────────────────────────────────────────────────────────


def test_recalibrate_identity_factor():
    cal = DrawRecalibrator(factor=1.0)
    h, d, a = cal.recalibrate(0.5, 0.25, 0.25)
    assert h + d + a == pytest.approx(1.0, abs=1e-5)


def test_recalibrate_sums_to_one():
    cal = DrawRecalibrator(factor=1.2)
    h, d, a = cal.recalibrate(0.45, 0.28, 0.27)
    assert h + d + a == pytest.approx(1.0, abs=1e-5)


def test_recalibrate_caps_draw_at_0_60():
    cal = DrawRecalibrator(factor=5.0)
    h, d, a = cal.recalibrate(0.35, 0.35, 0.30)
    assert d <= 0.60 + 1e-6


def test_recalibrate_zero_remaining_uses_scale_one():
    # home=0, away=0 → remaining=0 → scale=1 → new_home=new_away=0 → renorm
    cal = DrawRecalibrator(factor=1.0)
    h, d, a = cal.recalibrate(0.0, 0.5, 0.0)
    assert h + d + a == pytest.approx(1.0, abs=1e-5)


def test_recalibrate_degenerate_total_near_zero():
    cal = DrawRecalibrator(factor=0.0)
    h, d, a = cal.recalibrate(0.0, 0.0, 0.0)
    assert h == pytest.approx(1 / 3, abs=1e-5)
    assert d == pytest.approx(1 / 3, abs=1e-5)
    assert a == pytest.approx(1 / 3, abs=1e-5)


def test_recalibrate_increases_draw_with_factor_gt_1():
    cal = DrawRecalibrator(factor=1.5)
    _, d_inflated, _ = cal.recalibrate(0.45, 0.20, 0.35)
    _, d_baseline, _ = DrawRecalibrator(factor=1.0).recalibrate(0.45, 0.20, 0.35)
    assert d_inflated > d_baseline


def test_recalibrate_result_values_rounded_to_6dp():
    cal = DrawRecalibrator(factor=1.1)
    h, d, a = cal.recalibrate(0.40, 0.30, 0.30)
    assert round(h, 6) == h
    assert round(d, 6) == d
    assert round(a, 6) == a
