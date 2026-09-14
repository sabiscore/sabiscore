from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from src.services import google_oauth
from src.services.google_oauth import GoogleOAuthError, verify_google_id_token


@pytest.mark.asyncio
async def test_google_id_token_requires_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
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

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
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
    now = datetime.now(timezone.utc)
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
        private_key,
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
