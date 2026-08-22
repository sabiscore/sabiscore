"""core.database must not connect at import time, but must still fail
closed the moment anything actually asks for a session/engine.

Runs in real subprocesses (not just patched in-process) because the
regression this guards is specifically about *module import*, which an
in-process test can't isolate once `src.core.database` is already cached in
`sys.modules` by the rest of the suite. See docs/DEBT.md item 7 and
docs/adr/0007-lazy-database-engine-init.md.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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
