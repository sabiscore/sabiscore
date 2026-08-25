"""Shared boilerplate for Class-C repair/rebind CLI scripts.

Extracted after ``repair_fixture_identity_rebind.py`` duplicated
``repair_orphan_team_identities.py``'s review/apply argument shape,
SHA-256 validation, DSN redaction, and session-bootstrap sequence
byte-for-byte. Both scripts genuinely need identical behavior here (same
production-safety contract: PostgreSQL-only, redacted target logging, a
64-hex-char manifest digest, review/apply as a mutually exclusive pair) --
this is the second occurrence of the pattern, not a speculative abstraction.

Nothing here is domain-specific to any one repair; each script still owns its
own manifest-building, apply call, and result-printing.
"""

from __future__ import annotations

import argparse
import re

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def redact_database_url(url: str) -> str:
    """Mask credentials in a DSN before it is ever printed."""
    return re.sub(r"(://[^:/@]+:)[^@]*(@)", r"\1***\2", url)


def validate_sha256(value: str, *, field: str) -> str:
    """Normalize and enforce a 64-hex-char SHA-256 digest argument."""
    normalized = (value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return normalized


def build_review_apply_parser(description: str) -> argparse.ArgumentParser:
    """The common --review/--apply argument shape every Class-C repair CLI uses."""
    parser = argparse.ArgumentParser(description=description)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--review",
        action="store_true",
        help="Read-only: print the manifest and its SHA-256",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Mutate only after the reviewed hash and explicit authorization are supplied",
    )
    parser.add_argument("--manifest-sha256", default="")
    parser.add_argument("--authorization-id", default="")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--lock-timeout-seconds", type=int, default=5)
    return parser


async def open_class_c_session(database_url: str):
    """Point the app's async engine at ``database_url`` (if given) and open a
    session factory, mirroring what every Class-C repair script's ``_run``
    otherwise duplicated inline. Caller is responsible for ``close_db()``.
    """
    import os

    if database_url:
        os.environ["DATABASE_URL"] = str(database_url)

    from src.core.config import settings
    from src.db.session import init_db

    print(f"target={redact_database_url(settings.database_url)}")
    await init_db()
    from src.db import session as db_session

    factory = db_session.AsyncSessionLocal
    if factory is None:
        raise RuntimeError("Async database session is unavailable")
    return factory


__all__ = [
    "build_review_apply_parser",
    "open_class_c_session",
    "redact_database_url",
    "validate_sha256",
]
