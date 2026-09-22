"""Operational alert dispatchers.

Alerting is advisory and must never alter prediction, verdict, or stake state.
The caller supplies the application-lifespan ``httpx.AsyncClient`` so this
module never creates a per-call connection pool.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from urllib.parse import urlparse

import httpx
from httpx import AsyncClient

logger = logging.getLogger("sabiscore.alerts")


def _https_url_from_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        logger.error("%s must be an absolute HTTPS URL; alert skipped", name)
        return None
    return value


def _safe_feature_names(
    features: Sequence[str], *, limit: int = 5
) -> tuple[list[str], int]:
    cleaned: list[str] = []
    for feature in features:
        safe = "".join(
            char for char in str(feature) if char.isalnum() or char in "_-. "
        )
        if safe:
            cleaned.append(safe[:96])
    return cleaned[:limit], max(0, len(cleaned) - limit)


async def trigger_slack_drift_alert(
    *,
    http_client: AsyncClient,
    affected_features: Sequence[str],
    batch_size: int,
    drift_share: float | None = None,
    correlation_id: str | None = None,
) -> bool:
    """Send a structured, non-blocking drift advisory through Slack.

    Returns ``True`` only after Slack accepts the webhook. Delivery failure is
    logged without exposing the webhook URL and never raises into model logic.
    """

    webhook_url = _https_url_from_env("SLACK_DRIFT_WEBHOOK_URL")
    if webhook_url is None:
        logger.info(
            "Slack drift webhook is not configured; advisory retained in telemetry"
        )
        return False

    dashboard_url = _https_url_from_env("SABISCORE_MONITORING_URL")
    visible_features, hidden_count = _safe_feature_names(affected_features)
    feature_lines = [f"• `{name}`" for name in visible_features]
    if hidden_count:
        feature_lines.append(f"• …and {hidden_count} more")
    if not feature_lines:
        feature_lines.append(
            "• Dataset-level shift; no corrected column list available"
        )

    summary_parts = [f"*Batch size:* {max(0, int(batch_size))} fixtures"]
    if drift_share is not None:
        summary_parts.append(
            f"*Corrected drift share:* {max(0.0, min(1.0, drift_share)):.1%}"
        )
    if correlation_id:
        summary_parts.append(f"*Evaluation ID:* `{correlation_id[:64]}`")

    blocks: list[dict[str, object]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "SabiScore data drift advisory",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "\n".join(summary_parts)
                    + "\n\nA statistically corrected feature-distribution shift was detected. "
                    "This is advisory only: verdicts, stakes, and model promotion remain unchanged "
                    "until operator review."
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Benjamini–Hochberg corrected features:*\n"
                + "\n".join(feature_lines),
            },
        },
    ]
    if dashboard_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open monitoring"},
                        "url": dashboard_url,
                    }
                ],
            }
        )

    try:
        response = await http_client.post(
            webhook_url,
            json={"blocks": blocks},
            timeout=10.0,
        )
        response.raise_for_status()
        logger.info(
            "Drift advisory delivered",
            extra={
                "batch_size": batch_size,
                "affected_features": len(affected_features),
            },
        )
        return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Slack drift advisory rejected with HTTP %s",
            exc.response.status_code,
        )
    except (httpx.TimeoutException, httpx.NetworkError):
        logger.error("Slack drift advisory delivery failed due to network/timeout")
    except httpx.HTTPError:
        logger.error("Slack drift advisory delivery failed")
    return False


__all__ = ["trigger_slack_drift_alert"]
