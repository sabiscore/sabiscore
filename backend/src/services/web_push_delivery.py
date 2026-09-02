"""WEB_PUSH notification transport — VAPID (RFC 8292) + aes128gcm (RFC 8291).

Deliberately not ``pywebpush``. That library pulls ``py-vapid`` and
``http-ece``, which in turn sit on ``cryptography`` — already a runtime
dependency here. The whole content-encoding is a fully specified HKDF chain
plus one AES-128-GCM seal, so composing it directly costs ~80 lines, adds
nothing to ``requirements.runtime.txt`` (kept deliberately lean to shorten
Render deploy windows), and — unlike a vendored black box — is pinned against
the RFC's own published test vector in ``test_web_push_delivery.py``.

This is not hand-rolled cryptography: every primitive (ECDH P-256,
HKDF-SHA256, AES-128-GCM, ECDSA P-256) comes from ``cryptography``, and the
key-derivation order is transcribed from RFC 8291 section 3.4 and RFC 8188
section 2.

Disabled by default (``ENABLE_WEB_PUSH_NOTIFICATIONS``). Until an operator
supplies a VAPID keypair, ``send_web_push`` is a no-op reporting
``not_configured`` rather than raising or crashing the dispatch loop — the
same fail-closed contract ``email_delivery.send_notification_email`` honours.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import utils as asym_utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..core.config import settings
from ..core.redaction import redact_text

logger = logging.getLogger(__name__)

# RFC 8291 §3.4 / RFC 8188 §2 — fixed context strings. The trailing NUL and the
# 0x01 counter byte are part of the HKDF-Expand input, not decoration.
_KEY_INFO_PREFIX = b"WebPush: info\x00"
_CEK_INFO = b"Content-Encoding: aes128gcm\x00\x01"
_NONCE_INFO = b"Content-Encoding: nonce\x00\x01"
_RECORD_SIZE = 4096
# A push service answers 404/410 when the subscription is gone for good. Any
# other status is transient from our side and must not deactivate a device.
_GONE_STATUSES = (404, 410)
_VAPID_TOKEN_LIFETIME_SECONDS = 12 * 60 * 60

_client: Optional[httpx.AsyncClient] = None


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def is_web_push_configured() -> bool:
    return bool(
        settings.enable_web_push_notifications
        and settings.vapid_public_key
        and settings.vapid_private_key
        and settings.vapid_claims_sub
    )


def vapid_public_key() -> Optional[str]:
    """The application-server public key browsers pass to ``PushManager.subscribe``.

    Public by design (RFC 8292 §2) — it identifies the sender, it does not
    authorise anything. Served over the API instead of a ``NEXT_PUBLIC_*``
    build variable so a rotation is a restart, not a frontend redeploy.
    """
    return settings.vapid_public_key if is_web_push_configured() else None


def encrypt_payload(
    plaintext: bytes,
    *,
    ua_public: bytes,
    auth_secret: bytes,
    as_private: Optional[ec.EllipticCurvePrivateKey] = None,
    salt: Optional[bytes] = None,
) -> bytes:
    """Seal ``plaintext`` into an RFC 8291 ``aes128gcm`` body.

    ``as_private``/``salt`` are injectable purely so the RFC 8291 §5 test
    vector can be reproduced byte for byte; production always generates both
    fresh.
    """
    if as_private is None:
        as_private = ec.generate_private_key(ec.SECP256R1())
    if salt is None:
        salt = os.urandom(16)

    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    as_public = as_private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    shared_secret = as_private.exchange(ec.ECDH(), ua_key)

    # RFC 8291 §3.4: the auth secret is the HKDF *salt* for this first stage,
    # and the resulting 32 bytes become the IKM for the RFC 8188 stage below.
    prk_key = _hmac_sha256(auth_secret, shared_secret)
    ikm = _hmac_sha256(prk_key, _KEY_INFO_PREFIX + ua_public + as_public + b"\x01")

    # RFC 8188 §2: the record salt is the HKDF salt for the content keys.
    prk = _hmac_sha256(salt, ikm)
    content_key = _hmac_sha256(prk, _CEK_INFO)[:16]
    nonce = _hmac_sha256(prk, _NONCE_INFO)[:12]

    # 0x02 is the last-record delimiter; this transport never splits records.
    ciphertext = AESGCM(content_key).encrypt(nonce, plaintext + b"\x02", None)

    header = (
        salt
        + _RECORD_SIZE.to_bytes(4, "big")
        + len(as_public).to_bytes(1, "big")
        + as_public
    )
    return header + ciphertext


def _load_vapid_private_key(raw: str) -> ec.EllipticCurvePrivateKey:
    """Accept the base64url 32-byte scalar ``npx web-push generate-vapid-keys``
    emits, or a PEM block if an operator supplies one instead."""
    stripped = raw.strip()
    if "BEGIN" in stripped:
        key = serialization.load_pem_private_key(stripped.encode("utf-8"), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError("VAPID private key must be an EC P-256 key")
        return key
    return ec.derive_private_key(
        int.from_bytes(_b64url_decode(stripped), "big"), ec.SECP256R1()
    )


def build_vapid_headers(endpoint: str) -> Dict[str, str]:
    """RFC 8292 §3 ``Authorization: vapid t=<jwt>, k=<public key>``.

    The audience is the push service's *origin*, never the full endpoint —
    including the subscription path would leak it into a signed token that
    intermediaries can read.
    """
    private_key_raw = settings.vapid_private_key
    public_key_raw = settings.vapid_public_key
    subject = settings.vapid_claims_sub
    if not private_key_raw or not public_key_raw or not subject:
        raise ValueError("VAPID keypair and subject are required")

    split = urlsplit(endpoint)
    audience = f"{split.scheme}://{split.netloc}"
    header = _b64url_encode(
        json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()
    )
    claims = _b64url_encode(
        json.dumps(
            {
                "aud": audience,
                "exp": int(time.time()) + _VAPID_TOKEN_LIFETIME_SECONDS,
                "sub": subject,
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{claims}".encode("ascii")
    der_signature = _load_vapid_private_key(private_key_raw).sign(
        signing_input, ec.ECDSA(hashes.SHA256())
    )
    r, s = asym_utils.decode_dss_signature(der_signature)
    # JOSE wants fixed-width r||s, not the variable-length DER the signer emits.
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    token = f"{header}.{claims}.{_b64url_encode(raw_signature)}"
    return {"Authorization": f"vapid t={token}, k={public_key_raw}"}


@dataclass(frozen=True)
class WebPushSendResult:
    sent: bool
    reason: str
    #: True only when the push service says the subscription is permanently
    #: gone, which is the caller's signal to deactivate the stored device.
    expired: bool = False


def _shared_client() -> httpx.AsyncClient:
    """One module-scoped client, not one per send — the same rule the provider
    gateway follows for its lifespan client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=10.0)
    return _client


async def aclose() -> None:
    """Release the module-scoped client (FastAPI shutdown)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def send_web_push(
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    title: str,
    body: str,
    url: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> WebPushSendResult:
    """Best-effort push send. Never raises — a transport failure must not stop
    the dispatch loop from writing the in-app notification row."""
    if not is_web_push_configured():
        return WebPushSendResult(sent=False, reason="not_configured")
    if not endpoint or not p256dh or not auth:
        return WebPushSendResult(sent=False, reason="incomplete_subscription")

    payload: Dict[str, Any] = {"title": title, "body": body}
    if url:
        payload["url"] = url

    try:
        encrypted = encrypt_payload(
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            ua_public=_b64url_decode(p256dh),
            auth_secret=_b64url_decode(auth),
        )
        headers = build_vapid_headers(endpoint)
    except Exception as exc:  # noqa: BLE001 - a malformed key must not propagate
        logger.warning("web_push_delivery: encryption failed: %s", redact_text(exc))
        return WebPushSendResult(sent=False, reason="encryption_failed")

    headers.update(
        {
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(settings.web_push_ttl_seconds),
        }
    )

    try:
        response = await (client or _shared_client()).post(
            endpoint, content=encrypted, headers=headers
        )
    except Exception as exc:  # noqa: BLE001 - transport failure must never propagate
        logger.warning("web_push_delivery: send failed: %s", redact_text(exc))
        return WebPushSendResult(sent=False, reason="send_failed")

    if response.status_code in _GONE_STATUSES:
        return WebPushSendResult(sent=False, reason="subscription_expired", expired=True)
    if response.status_code >= 400:
        logger.warning("web_push_delivery: push service returned %s", response.status_code)
        return WebPushSendResult(sent=False, reason=f"http_{response.status_code}")
    return WebPushSendResult(sent=True, reason="ok")


__all__ = [
    "WebPushSendResult",
    "aclose",
    "build_vapid_headers",
    "encrypt_payload",
    "is_web_push_configured",
    "send_web_push",
    "vapid_public_key",
]
