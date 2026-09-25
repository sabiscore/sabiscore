"""Directive v8 D1: a job past its memory ceiling is stopped and reports its peak."""

from __future__ import annotations

import pytest

from scripts._resource_guard import ResourceCeilingExceeded, ResourceGuard


def test_allocation_past_the_ceiling_is_stopped_with_its_peak() -> None:
    held = []
    with pytest.raises(ResourceCeilingExceeded) as info:
        with ResourceGuard(max_mb=_current_mb() + 200, interval_s=0.05):
            for _ in range(2000):  # ~2 GB if never stopped
                held.append(bytearray(1024 * 1024))
                held[-1][::4096] = b"x" * len(held[-1][::4096])  # touch the pages
    held.clear()
    assert info.value.peak_mb > info.value.ceiling_mb


def test_a_job_under_the_ceiling_reports_peak_and_runtime() -> None:
    with ResourceGuard(max_mb=_current_mb() + 1024, interval_s=0.05) as guard:
        sum(range(10_000))
    summary = guard.summary()
    assert summary["peak_rss_mb"] > 0
    assert summary["runtime_s"] >= 0
    assert guard.exceeded is False


def _current_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / (1024 * 1024)
