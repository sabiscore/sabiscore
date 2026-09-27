from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from src.services import google_oauth
from src.services.google_oauth import GoogleOAuthError, verify_google_id_token


@pytest.mark.asyncio
async def test_google_id_token_requires_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "false")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)

    with pytest.raises(GoogleOAuthError, match="not configured"):
        await verify_google_id_token("x" * 200, "nonce-value")


@pytest.mark.asyncio
async def test_google_id_token_verifies_signature_audience_issuer_and_nonce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_numbers = private_key.public_key().public_numbers()

    def b64url(value: int) -> str:
        import base64

        size = (value.bit_length() + 7) // 8
        raw = value.to_bytes(size, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    kid = "sabiscore-test-google-key"
    jwk = {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": b64url(public_numbers.n),
        "e": b64url(public_numbers.e),
    }
    client_id = "google-client-id.apps.googleusercontent.com"
    nonce = "test-nonce-123456789"
    from cryptography.hazmat.primitives import serialization

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    now = datetime.now(timezone.utc)
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PrivateFormat,
        NoEncryption,
    )

    private_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    )

    token = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": client_id,
            "sub": "google-subject-123",
            "email": "Analyst@Example.com",
            "email_verified": True,
            "name": "Sabi Analyst",
            "nonce": nonce,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        private_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )

    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", client_id)
    monkeypatch.setattr(google_oauth, "_get_google_jwks", lambda: _resolved(jwk))

    claims = await verify_google_id_token(token, nonce)
    assert claims["sub"] == "google-subject-123"
    assert claims["email"] == "analyst@example.com"
    assert claims["email_verified"] is True
    assert claims["name"] == "Sabi Analyst"


async def _resolved(value: dict) -> dict:
    return {value["kid"]: value}


# --- 2026-09-27: production 401s gave one reason for every claim failure --------

CLIENT_ID = "117-web-client.apps.googleusercontent.com"
NONCE = "nonce-value-1234567890"


def _signed(**overrides):
    """A Google-shaped ID token signed by a local key, and that key as a JWK."""
    import base64

    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    numbers = key.public_key().public_numbers()

    def b64(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    now = datetime.now(timezone.utc)
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-subject-123",
        "email": "analyst@example.com",
        "email_verified": True,
        "nonce": NONCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        **overrides,
    }
    jwk = {"kty": "RSA", "kid": "k1", "use": "sig", "alg": "RS256", "n": b64(numbers.n), "e": b64(numbers.e)}
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": "k1"}), jwk


def _configure(monkeypatch: pytest.MonkeyPatch, jwk: dict, client_id: str = CLIENT_ID) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", client_id)
    monkeypatch.setattr(google_oauth, "_get_google_jwks", lambda: _resolved(jwk))


@pytest.mark.asyncio
async def test_a_client_id_mismatch_is_named_not_a_generic_failure(monkeypatch) -> None:
    # Web and backend configured with different client IDs: the token's audience is
    # the web's id. The 401 must say so, or no log can tell the operator what to fix.
    token, jwk = _signed(aud="999-other-client.apps.googleusercontent.com")
    _configure(monkeypatch, jwk)
    with pytest.raises(GoogleOAuthError, match="audience does not match GOOGLE_OAUTH_CLIENT_ID"):
        await verify_google_id_token(token, NONCE)


@pytest.mark.asyncio
async def test_the_bare_issuer_google_documents_is_accepted(monkeypatch) -> None:
    token, jwk = _signed(iss="accounts.google.com")
    _configure(monkeypatch, jwk)
    assert (await verify_google_id_token(token, NONCE))["sub"] == "google-subject-123"


@pytest.mark.asyncio
async def test_a_quoted_client_id_from_a_dashboard_paste_still_matches(monkeypatch) -> None:
    token, jwk = _signed()
    _configure(monkeypatch, jwk, client_id=f'"{CLIENT_ID}"')
    assert (await verify_google_id_token(token, NONCE))["email"] == "analyst@example.com"


@pytest.mark.asyncio
async def test_an_expired_token_says_expired(monkeypatch) -> None:
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    token, jwk = _signed(iat=int(past.timestamp()), exp=int((past + timedelta(minutes=5)).timestamp()))
    _configure(monkeypatch, jwk)
    with pytest.raises(GoogleOAuthError, match="expired"):
        await verify_google_id_token(token, NONCE)


@pytest.mark.asyncio
async def test_a_token_from_another_issuer_is_named(monkeypatch) -> None:
    token, jwk = _signed(iss="https://evil.example.com")
    _configure(monkeypatch, jwk)
    with pytest.raises(GoogleOAuthError, match="issuer is not Google"):
        await verify_google_id_token(token, NONCE)


@pytest.mark.asyncio
async def test_any_other_claim_failure_stays_generic(monkeypatch) -> None:
    token, jwk = _signed(iat="not-a-number")
    _configure(monkeypatch, jwk)
    with pytest.raises(GoogleOAuthError, match="^Google identity verification failed$"):
        await verify_google_id_token(token, NONCE)


@pytest.mark.asyncio
async def test_the_endpoint_logs_the_reason_it_answers_401(monkeypatch, caplog) -> None:
    # The web callback turns the detail into a code; this log line is what names it.
    import logging

    from fastapi import HTTPException
    from starlette.requests import Request

    from src.api.endpoints import auth
    from src.schemas.auth import GoogleOAuthRequest

    async def reject(_token, _nonce):
        raise GoogleOAuthError("Google token audience does not match GOOGLE_OAUTH_CLIENT_ID")

    monkeypatch.setattr(auth, "verify_google_id_token", reject)
    request = Request({"type": "http", "headers": [], "client": ("203.0.113.9", 1)})
    payload = GoogleOAuthRequest(id_token="x" * 120, nonce="n" * 16)

    with caplog.at_level(logging.WARNING, logger=auth.logger.name), pytest.raises(HTTPException) as exc:
        await auth.login_with_google(payload, request, None, None)  # type: ignore[arg-type]

    assert exc.value.status_code == 401
    assert "google_oauth_rejected reason=Google token audience does not match" in caplog.text
