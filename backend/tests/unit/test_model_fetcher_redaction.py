"""Regression tests for credential-safe model artifact diagnostics."""

from __future__ import annotations

import logging

import pytest

from src.core import model_fetcher


def test_signed_model_url_and_exception_are_redacted(monkeypatch, caplog) -> None:
    signed_url = (
        "https://models.example.test/model.pkl?token=super-secret&"
        "X-Amz-Credential=access-key%2Fscope&X-Amz-Signature=signed-secret&part=1"
    )

    def fail_request(*_args, **_kwargs):
        raise RuntimeError(f"request failed at {signed_url}")

    monkeypatch.setattr(model_fetcher.requests, "get", fail_request)
    caplog.set_level(logging.WARNING)

    with pytest.raises(RuntimeError):
        model_fetcher._download_bytes_with_requests(signed_url, {}, retries=1)

    rendered = caplog.text
    assert "super-secret" not in rendered
    assert "access-key" not in rendered
    assert "signed-secret" not in rendered
    assert "token=%5BREDACTED%5D" in rendered


def test_fetch_shell_does_not_echo_configured_urls() -> None:
    script = model_fetcher.Path(__file__).resolve().parents[3] / "scripts" / "fetch-models.sh"
    source = script.read_text(encoding="utf-8")
    assert 'echo "Fetching $url' not in source
    assert 'failed to fetch $url' not in source
    assert 'Got: $MODEL_BASE_URL' not in source
