"""core.database must not connect at import time, but must still fail
closed the moment anything actually asks for a session/engine.

The import-time regression itself can only be proven with real subprocesses
(not in-process patching), because it's specifically about *module import*,
which an in-process test can't isolate once `src.core.database` is already
cached in `sys.modules` by the rest of the suite. See docs/DEBT.md item 7 and
docs/adr/0008-lazy-database-engine-init.md.

The branch-level tests further down (TestInitEngine) run in-process instead,
monkeypatching _init_engine()'s collaborators directly -- subprocess tests
don't run under the parent pytest process's coverage instrumentation, so a
subprocess-only suite is invisible to coverage tooling despite genuinely
exercising the code.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import src.core.database as db

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# A host:port combination nothing listens on, with an explicit short libpq
# connect_timeout so the driver fails fast instead of riding the OS's own
# (much longer) TCP timeout -- psycopg honours connect_timeout as a URL
# query param and treats either outcome as a connection error.
_UNREACHABLE_DATABASE_URL = (
    "postgresql://baduser:badpass@127.0.0.1:1/nonexistent_db_xyz?connect_timeout=2"
)


def _run(script: str, *, extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    # Inherit the full parent environment (Windows needs SYSTEMROOT/WINDIR
    # etc. present for asyncio's Winsock init, not just PATH) and only
    # override the handful of vars this test actually cares about.
    env = {
        **os.environ,
        "APP_ENV": "production",
        "ALLOW_SQLITE_FALLBACK": "false",
        "DATABASE_URL": _UNREACHABLE_DATABASE_URL,
        "PYTHONPATH": ".",
        **extra_env,
    }
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_importing_for_base_and_models_does_not_require_a_live_database():
    """Alembic, tests, and IDE tooling only need Base/model classes -- this
    must succeed even against an unreachable database with no fallback."""
    result = _run(
        "import src.core.database as db\n"
        "assert db.Base is not None\n"
        "assert db.Match is not None\n"
        "print('IMPORT_OK')\n",
        extra_env={},
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stdout


def test_first_real_use_still_fails_closed_on_unreachable_database():
    """The fail-closed contract this module has always had -- PostgreSQL
    unreachable with no explicit SQLite fallback raises -- must survive the
    move from import-time to first-use-time."""
    result = _run(
        "import src.core.database as db\n"
        "try:\n"
        "    db.get_engine()\n"
        "    print('DID_NOT_RAISE')\n"
        "except Exception as exc:\n"
        "    print('RAISED:' + type(exc).__name__)\n",
        extra_env={},
    )
    assert result.returncode == 0, result.stderr
    assert "RAISED:" in result.stdout
    assert "DID_NOT_RAISE" not in result.stdout


def test_session_local_call_also_triggers_the_same_fail_closed_path():
    """SessionLocal() is the call surface ~30 callers already use -- it must
    raise the same way get_engine() does, not silently hand back a broken
    session."""
    result = _run(
        "import src.core.database as db\n"
        "try:\n"
        "    db.SessionLocal()\n"
        "    print('DID_NOT_RAISE')\n"
        "except Exception as exc:\n"
        "    print('RAISED:' + type(exc).__name__)\n",
        extra_env={},
    )
    assert result.returncode == 0, result.stderr
    assert "RAISED:" in result.stdout
    assert "DID_NOT_RAISE" not in result.stdout


def test_engine_is_memoized_across_calls():
    """get_engine() must not reconnect/re-test on every call once it has
    already succeeded once."""
    result = _run(
        "import src.core.database as db\n"
        "e1 = db.get_engine()\n"
        "e2 = db.get_engine()\n"
        "print('SAME' if e1 is e2 else 'DIFFERENT')\n",
        extra_env={
            "APP_ENV": "development",
            "ALLOW_SQLITE_FALLBACK": "true",
            "DATABASE_URL": "sqlite:///:memory:",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "SAME" in result.stdout


def test_session_local_returns_a_usable_session_on_the_success_path():
    """The other half of test_session_local_call_also_triggers_the_same_
    fail_closed_path: SessionLocal() must also still hand back a real,
    usable Session -- not just raise correctly on failure."""
    result = _run(
        "import src.core.database as db\n"
        "from sqlalchemy import text\n"
        "session = db.SessionLocal()\n"
        "try:\n"
        "    value = session.execute(text('SELECT 1')).scalar_one()\n"
        "    print('QUERY_OK:' + str(value))\n"
        "finally:\n"
        "    session.close()\n",
        extra_env={
            "APP_ENV": "development",
            "ALLOW_SQLITE_FALLBACK": "true",
            "DATABASE_URL": "sqlite:///:memory:",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "QUERY_OK:1" in result.stdout


def test_verify_database_connection_returns_the_same_engine_as_get_engine():
    """verify_database_connection() is the named entrypoint lifespan() calls
    -- confirm it actually does the same thing get_engine() does, not a
    parallel/divergent path."""
    result = _run(
        "import src.core.database as db\n"
        "e1 = db.verify_database_connection()\n"
        "e2 = db.get_engine()\n"
        "print('SAME' if e1 is e2 else 'DIFFERENT')\n",
        extra_env={
            "APP_ENV": "development",
            "ALLOW_SQLITE_FALLBACK": "true",
            "DATABASE_URL": "sqlite:///:memory:",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "SAME" in result.stdout


def test_status_helpers_reflect_reality_after_a_successful_lazy_init():
    """is_db_available()/is_using_fallback()/get_db_status() default to an
    honest 'unknown' (False) before anything triggers the engine, and must
    become accurate once get_engine() has actually run."""
    result = _run(
        "import src.core.database as db\n"
        "before = db.is_db_available()\n"
        "db.get_engine()\n"
        "after = db.is_db_available()\n"
        "status = db.get_db_status()\n"
        "print('BEFORE:' + str(before))\n"
        "print('AFTER:' + str(after))\n"
        "print('FALLBACK:' + str(db.is_using_fallback()))\n"
        "print('STATUS_AVAILABLE:' + str(status['available']))\n",
        extra_env={
            "APP_ENV": "development",
            "ALLOW_SQLITE_FALLBACK": "true",
            "DATABASE_URL": "sqlite:///:memory:",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "BEFORE:False" in result.stdout
    assert "AFTER:True" in result.stdout
    assert "STATUS_AVAILABLE:True" in result.stdout


def test_postgres_unreachable_falls_back_to_sqlite_when_explicitly_allowed():
    """The other half of the fail-closed test: when the fallback IS allowed,
    an unreachable primary must still succeed via SQLite, not raise."""
    result = _run(
        "import src.core.database as db\n"
        "engine = db.get_engine()\n"
        "print('ENGINE_OK:' + engine.dialect.name)\n"
        "print('USING_FALLBACK:' + str(db.is_using_fallback()))\n",
        extra_env={
            "APP_ENV": "development",
            "ALLOW_SQLITE_FALLBACK": "true",
            # Primary is Postgres and unreachable; fallback is allowed this time.
        },
    )
    assert result.returncode == 0, result.stderr
    assert "ENGINE_OK:sqlite" in result.stdout
    assert "USING_FALLBACK:True" in result.stdout


# ─── In-process branch coverage for _init_engine() ─────────────────────────
#
# The subprocess tests above are the trustworthy end-to-end proof, but a
# subprocess's coverage isn't visible to the parent pytest process's
# coverage.py run. These monkeypatch _init_engine()'s collaborators directly
# so every branch is both exercised AND counted.


@pytest.fixture(autouse=True)
def _reset_module_singletons(monkeypatch: pytest.MonkeyPatch):
    """_init_engine() mutates module-level globals (_db_available,
    _using_fallback); isolate each test from whatever the rest of the suite
    (or an earlier test in this file) already did to them."""
    monkeypatch.setattr(db, "_db_available", False)
    monkeypatch.setattr(db, "_using_fallback", False)
    yield


class _FakeEngine:
    def __init__(self, name: str):
        self.name = name


def test_init_engine_sqlite_primary_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "_sync_url", "sqlite:///:memory:")
    monkeypatch.setattr(db, "_sqlite_fallback_allowed", lambda: True)
    monkeypatch.setattr(db, "_create_sqlite_engine", lambda url: _FakeEngine("sqlite-primary"))
    monkeypatch.setattr(db, "_test_connection", lambda eng: True)

    engine = db._init_engine()

    assert engine.name == "sqlite-primary"
    assert db.is_db_available() is True
    assert db.is_using_fallback() is False


def test_init_engine_sqlite_primary_rejected_without_fallback_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "_sync_url", "sqlite:///:memory:")
    monkeypatch.setattr(db, "_sqlite_fallback_allowed", lambda: False)

    with pytest.raises(RuntimeError, match="ALLOW_INSECURE_FALLBACK"):
        db._init_engine()


def test_init_engine_postgres_success_never_touches_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "_sync_url", "postgresql+psycopg://irrelevant")
    monkeypatch.setattr(db, "_create_postgres_engine", lambda url: _FakeEngine("postgres"))

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *args, **kwargs):
            return None

    monkeypatch.setattr(_FakeEngine, "connect", lambda self: _FakeConn(), raising=False)

    engine = db._init_engine()

    assert engine.name == "postgres"
    assert db.is_db_available() is True
    assert db.is_using_fallback() is False


def test_init_engine_postgres_failure_falls_back_to_sqlite(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "_sync_url", "postgresql+psycopg://irrelevant")

    def _raise_postgres(url):
        raise ConnectionError("simulated postgres outage")

    monkeypatch.setattr(db, "_create_postgres_engine", _raise_postgres)
    monkeypatch.setattr(db, "_sqlite_fallback_allowed", lambda: True)
    monkeypatch.setattr(db, "_create_sqlite_engine", lambda url: _FakeEngine("sqlite-fallback"))
    monkeypatch.setattr(db, "_test_connection", lambda eng: True)

    engine = db._init_engine()

    assert engine.name == "sqlite-fallback"
    assert db.is_using_fallback() is True
    assert db.is_db_available() is True


def test_init_engine_postgres_failure_no_fallback_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(db, "_sync_url", "postgresql+psycopg://irrelevant")

    def _raise_postgres(url):
        raise ConnectionError("simulated postgres outage")

    monkeypatch.setattr(db, "_create_postgres_engine", _raise_postgres)
    monkeypatch.setattr(db, "_sqlite_fallback_allowed", lambda: False)

    with pytest.raises(ConnectionError, match="simulated postgres outage"):
        db._init_engine()

    assert db.is_using_fallback() is False


def test_init_engine_both_postgres_and_fallback_fail_reports_unavailable(monkeypatch: pytest.MonkeyPatch):
    """_init_engine() does not raise when the fallback engine itself fails
    its connection test -- it returns the (broken) engine and leaves
    is_db_available() False, matching the pre-refactor behaviour exactly."""
    monkeypatch.setattr(db, "_sync_url", "postgresql+psycopg://irrelevant")

    def _raise_postgres(url):
        raise ConnectionError("simulated postgres outage")

    monkeypatch.setattr(db, "_create_postgres_engine", _raise_postgres)
    monkeypatch.setattr(db, "_sqlite_fallback_allowed", lambda: True)
    monkeypatch.setattr(db, "_create_sqlite_engine", lambda url: _FakeEngine("sqlite-fallback"))
    monkeypatch.setattr(db, "_test_connection", lambda eng: False)

    engine = db._init_engine()

    assert engine.name == "sqlite-fallback"
    assert db.is_using_fallback() is True
    assert db.is_db_available() is False
