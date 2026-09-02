"""Unit tests for web_push_delivery (VAPID + RFC 8291 aes128gcm, config-gated).

The first test is the one that matters most: because this module composes the
web-push content-encoding itself rather than importing `pywebpush`, correctness
has to be *proved*, not assumed. RFC 8291 section 5 publishes a complete worked
example with fixed keys and a fixed expected body, so the encryption is pinned
byte for byte against the specification's own output.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric import utils as asym_utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.core.config import settings
from src.services.web_push_delivery import (
    _shared_client,
    aclose,
    build_vapid_headers,
    encrypt_payload,
    is_web_push_configured,
    send_web_push,
    vapid_public_key,
)


def _d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


# Generated per test run rather than pasted as a literal. The VAPID assertions
# verify a signature against the same key that produced it, so a fresh keypair
# is exactly as good — and a hardcoded 32-byte base64url scalar beside an
# identifier containing "PRIVATE_KEY" is indistinguishable from a real
# credential to a secret scanner.
_VAPID_PRIVATE_KEY_OBJ = ec.generate_private_key(ec.SECP256R1())
_VAPID_PRIVATE_SCALAR = _VAPID_PRIVATE_KEY_OBJ.private_numbers().private_value.to_bytes(32, "big")
_VAPID_PUBLIC_RAW = _VAPID_PRIVATE_KEY_OBJ.public_key().public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint,
)


def _configure(monkeypatch, *, enabled: bool = True) -> None:
    monkeypatch.setattr(settings, "enable_web_push_notifications", enabled)
    monkeypatch.setattr(settings, "vapid_public_key", _e(_VAPID_PUBLIC_RAW))
    monkeypatch.setattr(settings, "vapid_private_key", _e(_VAPID_PRIVATE_SCALAR))
    monkeypatch.setattr(settings, "vapid_claims_sub", "mailto:ops@sabiscore.com")
    monkeypatch.setattr(settings, "web_push_ttl_seconds", 86400)


# ── RFC 8291 §5 conformance ───────────────────────────────────────────────────


def test_encryption_matches_the_rfc_8291_published_test_vector() -> None:
    """RFC 8291 section 5, byte for byte.

    If this fails, the HKDF chain or the record header is wrong and no browser
    on earth would be able to decrypt what we send — a failure mode that is
    completely invisible from our side, because the push service accepts and
    forwards an undecryptable body with a 201.
    """
    body = encrypt_payload(
        b"When I grow up, I want to be a watermelon",
        ua_public=_d(
            "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
        ),
        auth_secret=_d("BTBZMqHH6r4Tts7J_aSIgg"),
        as_private=ec.derive_private_key(
            int.from_bytes(_d("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"),
            ec.SECP256R1(),
        ),
        salt=_d("DGv6ra1nlYgDCS1FRnbzlw"),
    )

    assert _e(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
        "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
        "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    )


def test_a_browser_can_actually_decrypt_a_freshly_generated_payload() -> None:
    """Round-trip with a random salt and ephemeral key, decrypting the way a
    user agent would. The RFC vector proves one fixed case; this proves the
    non-deterministic production path produces something readable."""
    ua_private = ec.generate_private_key(ec.SECP256R1())
    ua_public = ua_private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    auth_secret = b"0123456789abcdef"
    plaintext = b'{"title":"Kickoff reminder","body":"Match starts soon."}'

    body = encrypt_payload(plaintext, ua_public=ua_public, auth_secret=auth_secret)

    salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    as_public = body[21 : 21 + idlen]
    ciphertext = body[21 + idlen :]
    assert rs == 4096
    assert idlen == 65

    shared = ua_private.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    )
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=b"WebPush: info\x00" + ua_public + as_public,
    ).derive(shared)
    content_key = HKDF(
        algorithm=hashes.SHA256(),
        length=16,
        salt=salt,
        info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(),
        length=12,
        salt=salt,
        info=b"Content-Encoding: nonce\x00",
    ).derive(ikm)

    decrypted = AESGCM(content_key).decrypt(nonce, ciphertext, None)
    assert decrypted.rstrip(b"\x02") == plaintext


# ── Configuration gate ────────────────────────────────────────────────────────


def test_not_configured_by_default(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_web_push_notifications", False)
    assert is_web_push_configured() is False
    assert vapid_public_key() is None


def test_public_key_is_exposed_once_configured(monkeypatch) -> None:
    _configure(monkeypatch)
    assert is_web_push_configured() is True
    assert vapid_public_key() == _e(_VAPID_PUBLIC_RAW)


def test_enabled_without_a_keypair_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_web_push_notifications", True)
    monkeypatch.setattr(settings, "vapid_public_key", None)
    monkeypatch.setattr(settings, "vapid_private_key", None)
    monkeypatch.setattr(settings, "vapid_claims_sub", None)
    assert is_web_push_configured() is False
    assert vapid_public_key() is None


async def test_send_is_a_no_op_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_web_push_notifications", False)
    result = await send_web_push(
        endpoint="https://fcm.googleapis.com/fcm/send/abc",
        p256dh=_e(_VAPID_PUBLIC_RAW),
        auth=_e(b"0123456789abcdef"),
        title="t",
        body="b",
    )
    assert result.sent is False
    assert result.reason == "not_configured"


# ── VAPID (RFC 8292) ──────────────────────────────────────────────────────────


def test_vapid_authorization_is_a_verifiable_es256_token(monkeypatch) -> None:
    _configure(monkeypatch)
    headers = build_vapid_headers("https://fcm.googleapis.com/fcm/send/abc123?x=1")
    authorization = headers["Authorization"]
    assert authorization.startswith("vapid t=")
    assert f", k={_e(_VAPID_PUBLIC_RAW)}" in authorization

    token = authorization[len("vapid t=") :].split(",")[0]
    header_b64, claims_b64, signature_b64 = token.split(".")

    assert json.loads(_d(header_b64)) == {"typ": "JWT", "alg": "ES256"}
    claims = json.loads(_d(claims_b64))
    # The audience is the push service ORIGIN. Signing the full endpoint would
    # put the subscription URL inside a token any intermediary can read.
    assert claims["aud"] == "https://fcm.googleapis.com"
    assert claims["sub"] == "mailto:ops@sabiscore.com"
    assert claims["exp"] > 0

    signature = _d(signature_b64)
    assert len(signature) == 64, "JOSE requires fixed-width r||s, not DER"
    _VAPID_PRIVATE_KEY_OBJ.public_key().verify(
        asym_utils.encode_dss_signature(
            int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
        ),
        f"{header_b64}.{claims_b64}".encode("ascii"),
        ec.ECDSA(hashes.SHA256()),
    )


# ── Transport behaviour ───────────────────────────────────────────────────────


def _client_returning(status_code: int, captured: dict | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["headers"] = dict(request.headers)
            captured["content"] = request.content
            captured["url"] = str(request.url)
        return httpx.Response(status_code)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _send(monkeypatch, client: httpx.AsyncClient):
    _configure(monkeypatch)
    ua_private = ec.generate_private_key(ec.SECP256R1())
    ua_public = ua_private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    async with client:
        return await send_web_push(
            endpoint="https://fcm.googleapis.com/fcm/send/abc123",
            p256dh=_e(ua_public),
            auth=_e(b"0123456789abcdef"),
            title="Kickoff reminder",
            body="Match starts in about 60 minutes.",
            url="/match/fd-559696",
            client=client,
        )


async def test_successful_send_sets_the_aes128gcm_transport_headers(monkeypatch) -> None:
    captured: dict = {}
    result = await _send(monkeypatch, _client_returning(201, captured))

    assert result.sent is True
    assert result.reason == "ok"
    assert result.expired is False
    assert captured["headers"]["content-encoding"] == "aes128gcm"
    assert captured["headers"]["content-type"] == "application/octet-stream"
    assert captured["headers"]["ttl"] == "86400"
    assert captured["headers"]["authorization"].startswith("vapid t=")
    # Header is salt(16) + rs(4) + idlen(1) + 65-byte key, so anything shorter
    # than 86 bytes cannot be a well-formed record.
    assert len(captured["content"]) > 86


@pytest.mark.parametrize("status_code", [404, 410])
async def test_a_gone_subscription_is_reported_as_expired(monkeypatch, status_code: int) -> None:
    result = await _send(monkeypatch, _client_returning(status_code))
    assert result.sent is False
    assert result.expired is True
    assert result.reason == "subscription_expired"


async def test_a_server_error_is_not_treated_as_expired(monkeypatch) -> None:
    """A 500 from the push service is their problem, not a dead subscription.
    Deactivating the device here would silently lose a real reader."""
    result = await _send(monkeypatch, _client_returning(500))
    assert result.sent is False
    assert result.expired is False
    assert result.reason == "http_500"


async def test_transport_failure_never_raises(monkeypatch) -> None:
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await _send(monkeypatch, client)
    assert result.sent is False
    assert result.reason == "send_failed"


async def test_malformed_subscription_keys_never_raise(monkeypatch) -> None:
    _configure(monkeypatch)
    result = await send_web_push(
        endpoint="https://fcm.googleapis.com/fcm/send/abc",
        p256dh="not-a-real-key",
        auth="also-not-real",
        title="t",
        body="b",
        client=_client_returning(201),
    )
    assert result.sent is False
    assert result.reason == "encryption_failed"


def test_a_pem_private_key_is_accepted_as_well_as_the_base64url_scalar(monkeypatch) -> None:
    """`npx web-push generate-vapid-keys` emits a base64url scalar, but an
    operator arriving from another toolchain may hold a PEM block."""
    _configure(monkeypatch)
    pem = _VAPID_PRIVATE_KEY_OBJ.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    monkeypatch.setattr(settings, "vapid_private_key", pem)

    token = build_vapid_headers("https://push.example/x")["Authorization"]
    header_b64, claims_b64, signature_b64 = token[len("vapid t=") :].split(",")[0].split(".")
    signature = _d(signature_b64)
    _VAPID_PRIVATE_KEY_OBJ.public_key().verify(
        asym_utils.encode_dss_signature(
            int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
        ),
        f"{header_b64}.{claims_b64}".encode("ascii"),
        ec.ECDSA(hashes.SHA256()),
    )


def test_a_non_ec_pem_is_rejected_rather_than_used(monkeypatch) -> None:
    _configure(monkeypatch)
    rsa_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode("ascii")
    )
    monkeypatch.setattr(settings, "vapid_private_key", rsa_pem)

    with pytest.raises(ValueError, match="EC P-256"):
        build_vapid_headers("https://push.example/x")


def test_missing_vapid_settings_raise_rather_than_signing_with_nothing(monkeypatch) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "vapid_claims_sub", None)
    with pytest.raises(ValueError, match="VAPID keypair and subject"):
        build_vapid_headers("https://push.example/x")


async def test_the_http_client_is_shared_and_closable() -> None:
    """One module-scoped client, not one per send — the same rule the provider
    gateway follows for its lifespan client."""
    first = _shared_client()
    assert _shared_client() is first
    await aclose()
    assert first.is_closed
    # A send after shutdown must rebuild rather than reuse a closed client.
    assert _shared_client() is not first
    await aclose()


async def test_incomplete_subscription_is_rejected_before_any_request(monkeypatch) -> None:
    _configure(monkeypatch)
    result = await send_web_push(
        endpoint="", p256dh="", auth="", title="t", body="b", client=_client_returning(201)
    )
    assert result.sent is False
    assert result.reason == "incomplete_subscription"
