"""Unit tests for email_delivery (stdlib SMTP transport, config-gated)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.config import settings
from src.services.email_delivery import is_email_configured, send_notification_email


def _configure(monkeypatch, *, enabled: bool = True) -> None:
    monkeypatch.setattr(settings, "enable_email_notifications", enabled)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "user")
    monkeypatch.setattr(settings, "smtp_password", "pass")
    monkeypatch.setattr(settings, "smtp_from_address", "notifications@sabiscore.com")
    monkeypatch.setattr(settings, "smtp_use_tls", True)


def test_not_configured_by_default(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_email_notifications", False)
    assert is_email_configured() is False

    result = send_notification_email(to_address="fan@example.com", subject="s", body="b")
    assert result.sent is False
    assert result.reason == "not_configured"


def test_missing_host_or_from_address_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_email_notifications", True)
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "smtp_from_address", "notifications@sabiscore.com")
    assert is_email_configured() is False


def test_sends_via_smtp_with_tls_and_auth_when_configured(monkeypatch) -> None:
    _configure(monkeypatch)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("src.services.email_delivery.smtplib.SMTP", return_value=mock_client) as mock_smtp:
        result = send_notification_email(
            to_address="fan@example.com", subject="Kickoff reminder", body="Match starts soon."
        )

    assert result.sent is True
    assert result.reason == "ok"
    mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=10)
    mock_client.starttls.assert_called_once()
    mock_client.login.assert_called_once_with("user", "pass")
    mock_client.send_message.assert_called_once()
    sent_message = mock_client.send_message.call_args[0][0]
    assert sent_message["To"] == "fan@example.com"
    assert sent_message["From"] == "notifications@sabiscore.com"
    assert sent_message["Subject"] == "Kickoff reminder"


def test_transport_failure_never_raises(monkeypatch) -> None:
    _configure(monkeypatch)

    with patch("src.services.email_delivery.smtplib.SMTP", side_effect=OSError("connection refused")):
        result = send_notification_email(to_address="fan@example.com", subject="s", body="b")

    assert result.sent is False
    assert result.reason == "send_failed"


def test_no_credentials_skips_login(monkeypatch) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "smtp_username", None)
    monkeypatch.setattr(settings, "smtp_password", None)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("src.services.email_delivery.smtplib.SMTP", return_value=mock_client):
        result = send_notification_email(to_address="fan@example.com", subject="s", body="b")

    assert result.sent is True
    mock_client.login.assert_not_called()
