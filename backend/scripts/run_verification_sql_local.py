"""Backward-compatible entry point for the canonical SQL verifier.

This filename was briefly used as a Windows convenience script. Keep it as a
shim so existing terminal history continues to work, but centralize every
safety invariant in ``run_verification_sql.py``. In particular, this wrapper
must never install a SQLite fallback or relax the explicit PostgreSQL
``DATABASE_URL`` requirement.

Usage (from ``backend/``)::

    python scripts/run_verification_sql_local.py scripts/verify_elo.sql
"""

from __future__ import annotations

from run_verification_sql import main


if __name__ == "__main__":
    raise SystemExit(main())
