"""Regression tests for the production Elo replay CLI safety boundary."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from uuid import uuid4


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "replay_elo_from_db.py"


def _load_module() -> ModuleType:
    module_name = f"replay_elo_from_db_test_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_does_not_inject_local_sqlite_database(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_DEV_DEFAULTS", raising=False)

    _load_module()

    assert "DATABASE_URL" not in os.environ
    assert "ALLOW_INSECURE_DEV_DEFAULTS" not in os.environ


def test_explicit_database_url_is_applied_before_replay(monkeypatch) -> None:
    module = _load_module()
    observed: dict[str, str | None] = {}

    async def fake_run(*, apply: bool) -> int:
        observed["database_url"] = os.environ.get("DATABASE_URL")
        observed["apply"] = str(apply)
        return 0

    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--dry-run",
            "--database-url",
            "postgresql+asyncpg://user:secret@example.invalid/sabiscore",
        ],
    )

    module.main()

    assert (
        observed["database_url"]
        == "postgresql+asyncpg://user:secret@example.invalid/sabiscore"
    )


def test_database_url_redaction_does_not_expose_password() -> None:
    module = _load_module()

    redacted = module._redact(
        "postgresql+asyncpg://user:super-secret@example.invalid/sabiscore"
    )

    assert "super-secret" not in redacted
    assert "user:***@" in redacted
