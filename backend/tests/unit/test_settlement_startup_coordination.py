from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


async def test_initial_settlement_waits_for_fixture_sync_then_runs_without_hour_delay(monkeypatch) -> None:
    from src.api import main

    completed = asyncio.Event()
    completed.set()
    monkeypatch.setattr(main, "_FIXTURE_SYNC_COMPLETED", completed)
    monkeypatch.setattr(main, "_INITIAL_SETTLEMENT_DELAY_SECONDS", 0)
    run_pass = AsyncMock(return_value={"outcome": "ok"})
    sleep_calls = 0

    async def controlled_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise asyncio.CancelledError

    with patch("src.services.settlement_service.run_settlement_pass", run_pass), patch(
        "src.api.main.asyncio.sleep", new=controlled_sleep
    ):
        with pytest.raises(asyncio.CancelledError):
            await main._background_settlement_sync()

    run_pass.assert_awaited_once()
