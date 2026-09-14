"""Google OpenID Connect token verification for SabiScore browser authentication."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
from jose import JWTError, jwt

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
JWKS_CACHE_TTL_SECONDS = 3600

_jwks_cache: dict[str, Any] | None = None
_jwks_expires_at = 0.0
_jwks_lock = asyncio.Lock()


class GoogleOAuthError(ValueError):
    """Raised when a Google identity token cannot be trusted."""


async def _get_google_jwks() -> dict[str, Any]:
    global _jwks_cache, _jwks_expires_at

    now = time.monotonic()
    if _jwks_cache is not None and now < _jwks_expires_at:
        return _jwks_cache

    async with _jwks_lock:
        now = time.monotonic()
        if _jwks_cache is not None and now < _jwks_expires_at:
            return _jwks_cache

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(GOOGLE_JWKS_URL)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GoogleOAuthError("Unable to verify Google identity right now") from exc

        keys = payload.get("keys") if isinstance(payload, dict) else None
        if not isinstance(keys, list) or not keys:
            raise GoogleOAuthError("Google signing keys are unavailable")

        _jwks_cache = {str(key.get("kid")): key for key in keys if isinstance(key, dict) and key.get("kid")}
        _jwks_expires_at = time.monotonic() + JWKS_CACHE_TTL_SECONDS
        return _jwks_cache


async def verify_google_id_token(id_token: str, expected_nonce: str) -> dict[str, Any]:
    """Validate Google's signed OIDC ID token and return trusted claims."""
    enabled = os.getenv("GOOGLE_OAUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    if not enabled or not client_id:
        raise GoogleOAuthError("Google authentication is not configured")
    if not id_token or len(id_token) > 8192:
        raise GoogleOAuthError("Invalid Google identity token")
    if not expected_nonce or len(expected_nonce) > 256:
        raise GoogleOAuthError("Invalid OAuth nonce")

    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise GoogleOAuthError("Invalid Google identity token") from exc

    if header.get("alg") != "RS256":
        raise GoogleOAuthError("Unsupported Google signing algorithm")

    kid = header.get("kid")
    if not kid:
        raise GoogleOAuthError("Google signing key identifier is missing")

    jwks = await _get_google_jwks()
    key = jwks.get(str(kid))
    if key is None:
        global _jwks_expires_at
        _jwks_expires_at = 0.0
        jwks = await _get_google_jwks()
        key = jwks.get(str(kid))

    if key is None:
        raise GoogleOAuthError("Google signing key is unavailable")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=GOOGLE_ISSUER,
            options={"require_sub": True, "require_exp": True, "require_iat": True},
        )
    except JWTError as exc:
        raise GoogleOAuthError("Google identity verification failed") from exc

    if claims.get("nonce") != expected_nonce:
        raise GoogleOAuthError("Google OAuth nonce verification failed")
    if claims.get("azp") and claims.get("azp") != client_id:
        raise GoogleOAuthError("Google authorized party does not match this application")

    email = str(claims.get("email") or "").strip().lower()
    subject = str(claims.get("sub") or "").strip()
    if not subject or not email or claims.get("email_verified") is not True:
        raise GoogleOAuthError("Google account email could not be verified")

    return {
        "sub": subject,
        "email": email,
        "email_verified": True,
        "name": str(claims.get("name") or "").strip()[:200] or None,
        "picture": str(claims.get("picture") or "").strip()[:1000] or None,
    }


__all__ = ["GoogleOAuthError", "verify_google_id_token"]
