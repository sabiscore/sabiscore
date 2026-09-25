"""Memory ceiling for heavy offline jobs (directive v8 D1).

On the 8 GB development machine one heavy job gets a 3 GB budget (training,
full pytest, next build, HPO). ``ResourceGuard`` samples RSS of this process and
every child (loky/joblib workers each hold their own copy of the design matrix)
twice a second, records the peak, and stops the job past the ceiling.

    with ResourceGuard() as guard:
        train()
    manifest["resources"] = guard.summary()

The ceiling is ``SABISCORE_MAX_RSS_MB`` (default 3072). Stopping kills child
processes first, then interrupts the main thread; a main thread busy inside one
long C call (a single xgboost fit) is interrupted when that call returns.
# ponytail: interrupt_main is cooperative; a hard kill (os._exit) would lose the
# structured error. Upgrade only if a C-level fit is observed blowing past it.
"""

from __future__ import annotations

import _thread
import os
import threading
import time

import psutil

_MB = 1024 * 1024


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
    def __init__(self, max_mb: float | None = None, interval_s: float = 0.5) -> None:
        self.max_mb = (
            float(max_mb)
            if max_mb is not None
            else float(os.environ.get("SABISCORE_MAX_RSS_MB", "3072"))
        )
        self.interval_s = interval_s
        self.peak_mb = 0.0
        self.runtime_s = 0.0
        self.exceeded = False
        self._stop = threading.Event()
        self._started = 0.0

    def _sample(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.peak_mb = max(self.peak_mb, _tree_rss_mb())
            if self.peak_mb > self.max_mb:
                self.exceeded = True
                for child in psutil.Process().children(recursive=True):
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
                _thread.interrupt_main()
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
        if self.exceeded:
            raise ResourceCeilingExceeded(self.peak_mb, self.max_mb) from exc
        return False

    def summary(self) -> dict:
        return {
            "peak_rss_mb": round(self.peak_mb, 1),
            "runtime_s": round(self.runtime_s, 1),
            "rss_ceiling_mb": self.max_mb,
        }
