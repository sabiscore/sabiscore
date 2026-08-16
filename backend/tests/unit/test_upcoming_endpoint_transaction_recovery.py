"""Regression test for endpoint-level swallowed DB failures."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_upcoming_endpoint_rolls_back_before_returning_degraded_response() -> None:
    from src.api.endpoints.upcoming_matches import get_upcoming_matches

    db = AsyncMock(name="db")
    odds_service = MagicMock(name="odds_service")

    with patch(
        "src.api.endpoints.upcoming_matches.UpcomingMatchService"
    ) as MockService:
        MockService.return_value.get_upcoming_matches = AsyncMock(
            side_effect=RuntimeError("database execute failed")
        )

        response = await get_upcoming_matches(
            league="EPL",
            days_ahead=7,
            limit=20,
            include_predictions=False,
            include_value_bets=False,
            db=db,
            odds_service=odds_service,
        )

    db.rollback.assert_awaited_once()
    assert response.source == "error"
    assert response.data_gap is True
    assert "EXC:RuntimeError" in response.unavailable_reasons
