"""Directive v8 D1: a job past its memory ceiling is stopped and reports its peak.

Ceilings sit below current RSS, so every reading is over them: the tests then
exercise the guard, not how an allocator happens to grow RSS.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts._resource_guard import EXIT_CODE, ResourceCeilingExceeded, ResourceGuard


def _current_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / (1024 * 1024)


def test_a_script_over_the_ceiling_is_killed_with_a_structured_error() -> None:
    """The default (scripts) mode stops the process itself, from the sampler."""
    code = (
        "import time, psutil\n"
        "from scripts._resource_guard import ResourceGuard\n"
        "cur = psutil.Process().memory_info().rss / 2**20\n"
        "with ResourceGuard(max_mb=cur - 1, interval_s=0.05):\n"
        "    time.sleep(30)\n"
        "print('ran to completion')\n"
    )
    backend = Path(__file__).resolve().parents[2]
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=backend, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == EXIT_CODE
    assert "ran to completion" not in done.stdout
    error = json.loads(done.stderr.strip().splitlines()[-1])
    assert error["error"] == "rss_ceiling_exceeded"
    assert error["peak_rss_mb"] > error["rss_ceiling_mb"]


def test_in_process_mode_raises_on_exit_and_never_signals() -> None:
    """hard_exit=False must raise only from __exit__. The earlier version sent
    an asynchronous KeyboardInterrupt that could land after the block ended; in
    CI it aborted pytest itself."""
    with pytest.raises(ResourceCeilingExceeded) as info:
        with ResourceGuard(max_mb=_current_mb() - 1, interval_s=0.01, hard_exit=False):
            sum(range(200_000))
    assert info.value.peak_mb > info.value.ceiling_mb
    import time

    time.sleep(0.1)  # a stray KeyboardInterrupt would surface here


def test_exit_reading_catches_an_overrun_the_sampler_never_saw() -> None:
    """A sampler that never fires (60 s interval) must not let the job pass."""
    with pytest.raises(ResourceCeilingExceeded):
        with ResourceGuard(max_mb=_current_mb() - 1, interval_s=60, hard_exit=False):
            pass


def test_a_job_under_the_ceiling_reports_peak_and_runtime() -> None:
    with ResourceGuard(max_mb=_current_mb() + 1024, interval_s=0.05) as guard:
        sum(range(10_000))
    summary = guard.summary()
    assert summary["peak_rss_mb"] > 0
    assert summary["runtime_s"] >= 0
    assert guard.exceeded is False
