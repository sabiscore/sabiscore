"""Walk-forward validation must not run on the event loop, and must be cached
on the exact records it scores.

Production regression (2026-09-23): the 10,000-replicate bootstrap ran inline
inside async handlers. `/api/v1/providers/health` took ~1.3 s alone and 11-25 s
while `/model-performance/summary` was in flight, because the summary froze the
single event loop. The web health route requests that summary on every page's
header refresh, so the header's provider pill routinely timed out to "Unknown".
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

import pytest

from src.api.endpoints import performance


class _DictCache:
    def __init__(self) -> None:
        self.store: Dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self.store.get(key)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self.store[key] = value


class _RecordingRegistry:
    def __init__(self) -> None:
        self.calls = 0
        self.thread_ids: List[int] = []

    def walk_forward_validate(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.calls += 1
        self.thread_ids.append(threading.get_ident())
        return {"skipped": False, "total_records": len(records)}


_RECORDS = [{"date": "2026-09-01", "outcome": 0, "probs": [0.5, 0.3, 0.2]}]


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> _RecordingRegistry:
    stub = _RecordingRegistry()
    settled: List[List[Dict[str, Any]]] = [_RECORDS]

    async def _settled(*_args: Any, **_kwargs: Any) -> List[Dict[str, Any]]:
        return list(settled[-1])

    monkeypatch.setattr(performance, "get_walk_forward_registry", lambda: stub)
    monkeypatch.setattr(performance, "get_settled_predictions", _settled)
    monkeypatch.setattr(performance, "active_served_identity", lambda: "v-test")
    monkeypatch.setattr(performance, "cache", _DictCache())
    stub.settled = settled  # type: ignore[attr-defined]
    return stub


async def _summary() -> Dict[str, Any]:
    # The shared path behind both /model-performance and its /summary.
    return await performance._walk_forward_summary(None, league=None, window=None)  # type: ignore[arg-type]


async def test_runs_off_the_event_loop_thread(registry: _RecordingRegistry) -> None:
    await _summary()

    assert len(registry.thread_ids) == 1
    assert registry.thread_ids[0] != threading.get_ident()


async def test_identical_records_are_served_from_cache(
    registry: _RecordingRegistry,
) -> None:
    first = await _summary()
    second = await _summary()

    assert registry.calls == 1
    assert second["validation"] == first["validation"]


async def test_new_settled_record_recomputes(registry: _RecordingRegistry) -> None:
    await _summary()
    registry.settled.append(  # type: ignore[attr-defined]
        _RECORDS + [{"date": "2026-09-08", "outcome": 2, "probs": [0.2, 0.3, 0.5]}]
    )

    result = await _summary()

    assert registry.calls == 2
    assert result["validation"]["total_records"] == 2
