"""Memory ceiling for heavy offline jobs (directive v8 D1).

On the 8 GB development machine one heavy job gets a 3 GB budget (training,
full pytest, next build, HPO). ``ResourceGuard`` samples RSS of this process and
every child (loky/joblib workers each hold their own copy of the design matrix)
twice a second, records the peak, and stops the job past the ceiling.

    with ResourceGuard() as guard:
        train()
    manifest["resources"] = guard.summary()

The ceiling is ``SABISCORE_MAX_RSS_MB`` (default 3072). Past it, children are
killed and, with ``hard_exit=True`` (the default, for scripts), one JSON line is
written to stderr and the process exits 137: the point is to protect the
machine, and a job already past its budget has nothing left worth saving. With
``hard_exit=False`` the block runs to the end and ``__exit__`` raises
``ResourceCeilingExceeded``.

An earlier version used ``_thread.interrupt_main()``. That signal is delivered
asynchronously, so when the sampler fired as the block ended the
``KeyboardInterrupt`` landed in whatever ran next; in CI it aborted pytest itself.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

import psutil

_MB = 1024 * 1024
EXIT_CODE = 137  # conventional "killed for memory"


class ResourceCeilingExceeded(MemoryError):
    def __init__(self, peak_mb: float, ceiling_mb: float) -> None:
        super().__init__(
            f"RSS peaked at {peak_mb:.0f} MB, over the {ceiling_mb:.0f} MB ceiling"
        )
        self.peak_mb = peak_mb
        self.ceiling_mb = ceiling_mb


def _tree_rss_mb() -> float:
    proc = psutil.Process()
    total = proc.memory_info().rss
    for child in proc.children(recursive=True):
        try:
            total += child.memory_info().rss
        except psutil.Error:
            pass
    return total / _MB


class ResourceGuard:
    def __init__(
        self,
        max_mb: float | None = None,
        interval_s: float = 0.5,
        hard_exit: bool = True,
    ) -> None:
        self.max_mb = (
            float(max_mb)
            if max_mb is not None
            else float(os.environ.get("SABISCORE_MAX_RSS_MB", "3072"))
        )
        self.interval_s = interval_s
        self.hard_exit = hard_exit
        self.peak_mb = 0.0
        self.runtime_s = 0.0
        self.exceeded = False
        self._stop = threading.Event()
        self._started = 0.0

    def _record(self) -> bool:
        try:
            self.peak_mb = max(self.peak_mb, _tree_rss_mb())
        except psutil.Error:  # a child exiting mid-scan must not kill the sampler
            pass
        return self.peak_mb > self.max_mb

    def _stop_job(self) -> None:
        for child in psutil.Process().children(recursive=True):
            try:
                child.kill()
            except psutil.Error:
                pass
        if self.hard_exit:
            sys.stderr.write(
                json.dumps(
                    {
                        "error": "rss_ceiling_exceeded",
                        "peak_rss_mb": round(self.peak_mb, 1),
                        "rss_ceiling_mb": self.max_mb,
                    }
                )
                + "\n"
            )
            sys.stderr.flush()
            os._exit(EXIT_CODE)

    def _sample(self) -> None:
        while not self._stop.wait(self.interval_s):
            if self._record():
                self.exceeded = True
                self._stop_job()
                return

    def __enter__(self) -> "ResourceGuard":
        self._started = time.monotonic()
        self.peak_mb = _tree_rss_mb()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._stop.set()
        self._thread.join()
        self.runtime_s = time.monotonic() - self._started
        # A final reading: a peak between samples, or a sampler that never got
        # scheduled, must not let an over-ceiling job pass as within budget.
        if self._record():
            self.exceeded = True
        if self.exceeded:
            raise ResourceCeilingExceeded(self.peak_mb, self.max_mb) from exc
        return False

    def summary(self) -> dict:
        return {
            "peak_rss_mb": round(self.peak_mb, 1),
            "runtime_s": round(self.runtime_s, 1),
            "rss_ceiling_mb": self.max_mb,
        }
