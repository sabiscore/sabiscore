from src.core.redaction import redact_mapping, redact_text, redact_url, safe_endpoint


def test_redacts_credentials_from_stack_trace_text() -> None:
    value = (
        "ValueError redis://operator:super-secret-password@cache.example:6379/0 "
        "Authorization: Bearer abc.def.ghi?api_key=visible-token"
    )

    redacted = redact_text(value)

    assert "super-secret-password" not in redacted
    assert "visible-token" not in redacted
    assert "abc.def.ghi" not in redacted
    assert "[REDACTED]" in redacted


def test_redacts_nested_mapping_and_url_query() -> None:
    payload = {
        "request": {
            "authorization": "Bearer secret-token",
            "url": "https://example.test/data?token=secret&league=EPL",
        },
        "events": [
            {"database_dsn": "postgresql://user:password@example.test/db"},
        ],
    }

    redacted = redact_mapping(payload)

    assert redacted["request"]["authorization"] == "[REDACTED]"
    assert "secret" not in redacted["request"]["url"]
    assert redacted["events"][0]["database_dsn"] == "[REDACTED]"
    assert "token=%5BREDACTED%5D" in redact_url(payload["request"]["url"])


def test_invalid_url_diagnostics_never_raise_or_echo_input() -> None:
    malformed = "rediss://user:secret@example.invalid:not-a-port/0?api_key=secret"
    assert safe_endpoint(malformed) == "invalid://[REDACTED]"
    assert redact_url(malformed) == "[REDACTED_INVALID_URL]"
    assert "secret" not in safe_endpoint(malformed)
