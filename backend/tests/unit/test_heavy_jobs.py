"""Directive v8 S3: heavy off-loop jobs never overlap (docs/DEBT.md item 152)."""

from __future__ import annotations

import asyncio
import threading
import time

from src.core.heavy_jobs import run_heavy


def test_concurrent_heavy_jobs_run_one_at_a_time() -> None:
    active = 0
    peak = 0
    guard = threading.Lock()

    def job() -> None:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with guard:
            active -= 1

    async def main() -> None:
        await asyncio.gather(*(run_heavy(job) for _ in range(4)))

    asyncio.run(main())
    assert peak == 1


def test_event_loop_stays_responsive_while_a_job_waits() -> None:
    async def main() -> float:
        heavy = [asyncio.create_task(run_heavy(time.sleep, 0.2)) for _ in range(2)]
        started = time.perf_counter()
        await asyncio.sleep(0.01)  # must not wait behind either job
        elapsed = time.perf_counter() - started
        await asyncio.gather(*heavy)
        return elapsed

    assert asyncio.run(main()) < 0.1
