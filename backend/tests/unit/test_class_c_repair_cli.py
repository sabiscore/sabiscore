"""Shared boilerplate used by every Class-C repair CLI (docs/DEBT.md items
34/35/39): redaction, digest validation, and the common review/apply argument
shape.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _class_c_repair_cli import (  # noqa: E402
    build_review_apply_parser,
    redact_database_url,
    validate_sha256,
)


def test_redact_database_url_masks_the_password_only() -> None:
    url = "postgresql://sabiscore_user:s3cr3t@dpg-example-a.oregon-postgres.render.com/sabiscore"
    redacted = redact_database_url(url)
    assert "s3cr3t" not in redacted
    assert redacted.startswith("postgresql://sabiscore_user:***@")
    assert redacted.endswith("/sabiscore")


def test_redact_database_url_leaves_a_credential_free_url_unchanged() -> None:
    url = "sqlite+aiosqlite:///:memory:"
    assert redact_database_url(url) == url


def test_validate_sha256_normalizes_case_and_strips_whitespace() -> None:
    digest = " " + ("A1" * 32) + " "
    assert validate_sha256(digest, field="--x") == ("a1" * 32)


@pytest.mark.parametrize("bad", ["", "not-a-digest", "a" * 63, "g" * 64])
def test_validate_sha256_rejects_anything_not_64_hex_chars(bad: str) -> None:
    with pytest.raises(ValueError, match="64-character SHA-256"):
        validate_sha256(bad, field="--manifest-sha256")


def test_review_apply_parser_requires_exactly_one_mode() -> None:
    parser = build_review_apply_parser("test")
    with pytest.raises(SystemExit):
        parser.parse_args([])
    with pytest.raises(SystemExit):
        parser.parse_args(["--review", "--apply"])


def test_review_apply_parser_review_mode_defaults() -> None:
    parser = build_review_apply_parser("test")
    args = parser.parse_args(["--review"])
    assert args.review is True
    assert args.apply is False
    assert args.lock_timeout_seconds == 5


def test_review_apply_parser_apply_mode_accepts_all_flags() -> None:
    parser = build_review_apply_parser("test")
    args = parser.parse_args(
        [
            "--apply",
            "--manifest-sha256",
            "a" * 64,
            "--authorization-id",
            "change-123",
            "--confirm",
            "APPLY_X",
            "--database-url",
            "postgresql://x",
            "--lock-timeout-seconds",
            "10",
        ]
    )
    assert args.apply is True
    assert args.manifest_sha256 == "a" * 64
    assert args.authorization_id == "change-123"
    assert args.confirm == "APPLY_X"
    assert args.lock_timeout_seconds == 10
