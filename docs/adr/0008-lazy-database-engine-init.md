# 0008 — Lazy sync database engine initialisation

**Status:** Accepted · implemented 2026-08-22

## Context

`docs/DEBT.md` item 7 documents this gap: `backend/src/core/database.py` ran
`_test_connection()` and raised at **module scope**, not inside a function.
Anything that imported the module therefore required a reachable PostgreSQL,
including tooling that has no business needing one:

- `alembic/env.py:11` does `from src.core.database import Base`, so `alembic
  upgrade head`, `alembic check`, and `alembic revision --autogenerate` all
  failed with a connection error before Alembic ran its own logic — the
  failure surfaced as a raw traceback from an import, not as a migration
  error.
- `src.api.main` could not be imported for inspection, linting, or an IDE
  language server without a database.
- `make verify` gate 4 and gate 14 both needed a live local PostgreSQL purely
  to import.
- In production, `render.yaml`'s `startCommand` is `alembic upgrade head &&
  uvicorn …`; when the import raised, the `&&` short-circuited, uvicorn never
  started, the container exited, Render restarted it, and the only public
  signal was the platform's own HTML 502. The service being down was
  *correct* (it cannot serve without its database) — being unable to say why
  was not.

**Why this was never simply "make it lazy" without a decision recorded
first:** the raise is load-bearing. It is what enforces "PostgreSQL
unavailable and SQLite fallback is not explicitly allowed" — the
`ALLOW_SQLITE_FALLBACK` invariant that must never activate silently.
Deferring the check has to preserve that exactly, and `db/session.py`'s
async `init_db()` reads `core.database.is_using_fallback()` to decide
whether the *async* engine should mirror the sync engine's fallback
decision — so simply deleting the check, or moving it somewhere that runs
too late, would silently change that coupling.

## Decision

Convert the eager, import-time engine + connection test into a lazily
initialised, memoized singleton:

- `_init_engine()` holds the exact same PostgreSQL-then-SQLite-fallback logic
  that used to run at import time, unchanged in substance.
- `get_engine()` calls `_init_engine()` exactly once (double-checked locking
  guards concurrent first callers) and memoizes the result; a failure is not
  cached or retried on a timer — the next call simply raises again.
- `verify_database_connection()` is a thin, explicitly-named wrapper around
  `get_engine()`, called once and unguarded (no try/except) as the first
  step of `api/main.py`'s `lifespan()`, before `await init_db()` — preserving
  the original fail-closed contract for the live app: an unreachable
  database with no explicit fallback still aborts startup, exactly as it
  always raised at import before, just with a dedicated log line instead of
  a bare import traceback. `is_using_fallback()` is guaranteed correct by
  the time `init_db()` reads it, because `verify_database_connection()` runs
  first.
- `SessionLocal` becomes a small class using `__new__` to preserve the exact
  `SessionLocal()` call surface every existing caller (~30 files: scripts,
  Celery-style workers, `db/session.py`'s async-session bridge) already
  uses, while deferring the bind to first call.
- The two direct consumers of the old module-level `engine` object
  (`api/endpoints/monitoring.py`, `services/orchestrator.py`) now call
  `get_engine()` instead — this was the one place the laziness could have
  been silently defeated, since `api/main.py` imports `monitoring.py`'s
  router at module scope (before `lifespan` ever runs), so a bare `engine`
  attribute there would have re-triggered eager connection exactly as
  before.
- Alembic's `env.py` needed no change beyond the module import becoming
  safe: it already builds its own independent engine via
  `engine_from_config()` and never touched `core.database`'s engine or
  fallback state, so it gets its own clear, Alembic-native connection error
  if the database is unreachable — no `verify_database_connection()` call
  added there, since nothing in Alembic's flow depends on it.

**Not changed:** the actual PostgreSQL-vs-SQLite decision logic, the
`ALLOW_SQLITE_FALLBACK`/`APP_ENV` gate, `check_database_health()`,
`session_scope()`, `get_db()`, or any model class.

## Consequences

- Importing `src.core.database` for `Base`/model classes (the overwhelming
  majority of its ~40 importers — tests, scripts, Alembic) no longer touches
  the database at all.
- A side benefit found while verifying this: `backend/conftest.py` sets
  `ALLOW_SQLITE_FALLBACK=true` for the whole test session, which meant the
  old eager import created a throwaway `sabiscore_fallback.db` SQLite engine
  on every single pytest run, even for tests that only needed `Base`/model
  classes and never touched it. That waste (and the stray gitignored file it
  left behind) is gone.
- Production fail-closed behaviour is unchanged: an unreachable database
  with no explicit fallback still aborts startup before serving any traffic
  — verified by two new regression tests that run real subprocesses against
  a genuinely unreachable address (`backend/tests/unit/test_lazy_database_engine.py`).
