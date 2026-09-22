"""Compatibility shim for the canonical ESPN provider.

The production ESPN implementation lives in ``src.providers.espn``. This
module remains only for legacy imports and does not promise real-time latency,
polling, odds, or predictions.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ...core.config import settings
from ...providers.espn import ESPNProvider, ESPN_LEAGUE_SLUGS


class ESPNConnector:
    """Legacy wrapper around the keyless supplementary ESPN provider."""

    LEAGUE_IDS = ESPN_LEAGUE_SLUGS

    def __init__(self, poll_interval: int = 300) -> None:
        self.poll_interval = max(int(poll_interval), 300)
        self.provider = ESPNProvider(
            enabled=settings.enable_espn_provider,
            live_tests=settings.provider_live_tests,
        )
        self._running = False

    async def __aenter__(self) -> "ESPNConnector":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self._running = False

    async def fetch_scoreboard(
        self, league: str, date: str | None = None
    ) -> list[dict[str, Any]]:
        result = await self.provider.scoreboard(league.upper(), date=date)
        return result.records

    async def poll_live_matches(self, league: str, callback=None) -> None:
        """Legacy conservative polling loop.

        Polling is bounded to at least five minutes and only runs when
        PROVIDER_LIVE_TESTS=true; otherwise the provider returns PARTIAL.
        """
        self._running = True
        while self._running:
            matches = await self.fetch_scoreboard(league)
            if callback:
                for match in matches:
                    await callback(match)
            await asyncio.sleep(self.poll_interval)

    async def update_match_from_espn(self, match_id: str, espn_id: str) -> bool:
        del match_id, espn_id
        return False

    def stop_polling(self) -> None:
        self._running = False
