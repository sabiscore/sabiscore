"""One lane for CPU- and memory-heavy work run off the event loop (directive v8 S3).

``asyncio.to_thread`` keeps a 10,000-replicate bootstrap off the event loop
(docs/DEBT.md item 144) but not off another bootstrap: the hourly settlement
pass and a cold ``/model-performance`` cache miss could overlap and stack their
peaks on a 512 MB instance with ~129 MB of headroom (item 152, live
2026-09-24). The lock is taken inside the worker thread, so waiting never
blocks the event loop, and a ``threading.Lock`` is not bound to any one event
loop the way an ``asyncio.Semaphore`` is.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_lane = threading.Lock()


def _serialized(func: Callable[..., T], args: tuple, kwargs: dict) -> T:
    with _lane:
        return func(*args, **kwargs)


async def run_heavy(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """``asyncio.to_thread``, but at most one heavy job runs at a time."""
    return await asyncio.to_thread(_serialized, func, args, kwargs)
