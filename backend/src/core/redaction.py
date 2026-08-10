"""Central secret redaction helpers for logs, traces, and error envelopes."""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_QUERY_KEYS = {
    "api_key",
    "apikey",
    "api_token",
    "key",
    "token",
    "auth",
    "authorization",
    "password",
}

_SENSITIVE_PARAM_RE = re.compile(
    r"\b(" + "|".join(SENSITIVE_QUERY_KEYS) + r")=([^&\s'\"]+)",
    re.IGNORECASE,
)
_URL_USERINFO_RE = re.compile(
    r"(?P<scheme>\b[a-z][a-z0-9+.-]*://)(?P<userinfo>[^/@\s]+)@",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def redact_text(value: object) -> str:
    """Remove credentials embedded in arbitrary exception or log text."""

    text = str(value)
    text = _URL_USERINFO_RE.sub(r"\g<scheme>[REDACTED]@", text)
    text = _SENSITIVE_PARAM_RE.sub(r"\1=[REDACTED]", text)
    return _BEARER_RE.sub("Bearer [REDACTED]", text)


def redact_url(url: str) -> str:
    """Return a usable URL with userinfo and sensitive query values removed."""

    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"
    except ValueError:
        return "[REDACTED_INVALID_URL]"
    pairs = [
        (key, "[REDACTED]" if key.lower() in SENSITIVE_QUERY_KEYS else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, host, parts.path, urlencode(pairs), parts.fragment))


def safe_endpoint(url: str) -> str:
    """Return only scheme and host for dependency diagnostics."""

    try:
        parts = urlsplit(url)
        host = parts.hostname or "unconfigured"
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        return f"{parts.scheme or 'unknown'}://{host}"
    except ValueError:
        return "invalid://[REDACTED]"


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    """Redact secret-valued mapping fields while preserving status metadata."""

    redacted: dict[str, Any] = {}
    for key, value in values.items():
        lowered = key.lower()
        metadata_field = lowered in {"requires_key", "api_key_configured"}
        sensitive = any(
            marker in lowered
            for marker in ("api_key", "token", "secret", "password", "authorization", "dsn")
        )
        if sensitive and not metadata_field:
            redacted[key] = "[REDACTED]" if value else None
        elif isinstance(value, Mapping):
            redacted[key] = redact_mapping(value)
        elif isinstance(value, (list, tuple)):
            redacted[key] = [
                redact_mapping(item) if isinstance(item, Mapping) else redact_text(item)
                if isinstance(item, str)
                else item
                for item in value
            ]
        elif isinstance(value, str):
            redacted[key] = redact_text(value)
        else:
            redacted[key] = value
    return redacted


__all__ = [
    "SENSITIVE_QUERY_KEYS",
    "redact_mapping",
    "redact_text",
    "redact_url",
    "safe_endpoint",
]
