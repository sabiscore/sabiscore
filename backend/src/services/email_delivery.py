"""EMAIL notification transport (stdlib SMTP, config-gated, fail-closed).

Deliberately not a vendor SDK — `smtplib` speaks to any SMTP-compatible
provider (SES, Resend, Brevo, Gmail, ...) an operator points it at, so no new
dependency and no vendor lock-in. Disabled by default (`ENABLE_EMAIL_NOTIFICATIONS`);
until an operator supplies real SMTP credentials, `send_notification_email`
is a no-op that reports "not configured" rather than raising or crashing the
dispatch loop.
"""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from ..core.config import settings
from ..core.redaction import redact_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailSendResult:
    sent: bool
    reason: str


def is_email_configured() -> bool:
    return bool(
        settings.enable_email_notifications
        and settings.smtp_host
        and settings.smtp_from_address
    )


def send_notification_email(*, to_address: str, subject: str, body: str) -> EmailSendResult:
    """Best-effort SMTP send. Never raises — callers must not let a transport
    failure block writing the in-app notification log row."""
    host = settings.smtp_host
    from_address = settings.smtp_from_address
    if not is_email_configured() or not host or not from_address:
        return EmailSendResult(sent=False, reason="not_configured")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = to_address
    message.set_content(body)

    try:
        with smtplib.SMTP(host, settings.smtp_port, timeout=10) as client:
            if settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_username and settings.smtp_password:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
        return EmailSendResult(sent=True, reason="ok")
    except Exception as exc:  # noqa: BLE001 - transport failure must never propagate
        logger.warning("email_delivery: send failed: %s", redact_text(exc))
        return EmailSendResult(sent=False, reason="send_failed")


__all__ = ["EmailSendResult", "is_email_configured", "send_notification_email"]
