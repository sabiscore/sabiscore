from __future__ import annotations

import httpx
import pytest

from src.services.alerting import trigger_slack_drift_alert


@pytest.mark.asyncio
async def test_alerting_uses_injected_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SLACK_DRIFT_WEBHOOK_URL", "https://hooks.slack.test/services/example"
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        delivered = await trigger_slack_drift_alert(
            http_client=client,
            affected_features=["home_form", "away_xg"],
            batch_size=120,
            drift_share=0.25,
            correlation_id="eval-1",
        )

    assert delivered is True
    assert len(requests) == 1
    assert requests[0].url.host == "hooks.slack.test"
    assert b"Benjamini" in requests[0].content


@pytest.mark.asyncio
async def test_alerting_skips_when_webhook_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SLACK_DRIFT_WEBHOOK_URL", raising=False)

    async with httpx.AsyncClient() as client:
        delivered = await trigger_slack_drift_alert(
            http_client=client,
            affected_features=["home_form"],
            batch_size=120,
        )

    assert delivered is False
