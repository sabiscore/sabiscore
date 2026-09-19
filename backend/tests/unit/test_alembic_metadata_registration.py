"""Every mapped table must be reachable from `alembic/env.py`'s imports.

⚠️ THE CLASS OF BUG THIS EXISTS FOR

`alembic check` compares the live database against `Base.metadata`. A mapper
that is never imported is absent from that metadata, so autogenerate concludes
the table/column exists in the database but not in the model and proposes
DROPPING it - failing the schema-drift gate with a diff that looks alarming and
has nothing to do with the commit that triggered it.

This happened: `src/services/social_auth_models.py` defines `user_identities`
and installs three columns on `users`, but `env.py` imported only `src.db.*`.
Migration 0014 created them, the ORM never declared them to Alembic, and the
gate failed on every commit from 2026-09-14 until this test was written -
invisible for five days because the CI runner could not boot during that window
(`docs/DEBT.md` item 16).

Pinning only those specific tables would guard one instance. The defect is
structural: `src/db/` is a convention, not an enforced location, and the next
model placed outside it fails exactly the same way. So this scans for the
declaration rather than listing known tables.

The scan is AST-based on purpose. Importing every module under `src/` to look
for mappers would execute arbitrary module-level code (`core/database.py`
historically opened a connection at import - `docs/DEBT.md` item 7), which is
both slow and a side effect a lint-style test has no business causing.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC = BACKEND_ROOT / "src"
ENV_PY = BACKEND_ROOT / "alembic" / "env.py"


def _env_model_modules() -> list[str]:
    """`src.*` modules that alembic/env.py imports, read from its source.

    Derived rather than hand-copied: a hand-copied list would drift from the
    file it is supposed to describe, which is the same failure mode one layer up.
    """
    tree = ast.parse(ENV_PY.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src."):
            modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _declared_tablenames() -> dict[str, str]:
    """{table_name: relative path} for every `__tablename__ = "..."` under src/."""
    found: dict[str, str] = {}
    for path in SRC.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a syntax error fails elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__tablename__"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    found.setdefault(
                        node.value.value, str(path.relative_to(BACKEND_ROOT))
                    )
    return found


@pytest.fixture(scope="module")
def registered_tables() -> set[str]:
    """Table names on Base.metadata after importing exactly env.py's set."""
    from src.core.database import Base

    for module in _env_model_modules():
        try:
            importlib.import_module(module)
        except ImportError:
            # `from src.db import models` yields "src.db.models.<name>" for a
            # symbol import; fall back to the module itself.
            importlib.import_module(module.rsplit(".", 1)[0])
    return set(Base.metadata.tables)


def test_the_scan_finds_something(registered_tables: set[str]) -> None:
    """Guard the guard: an empty scan would make every assertion below vacuous."""
    declared = _declared_tablenames()
    assert len(declared) > 10, f"AST scan found only {len(declared)} tables - scan is broken"
    assert registered_tables, "no tables registered - env.py import replay is broken"


def test_every_mapped_table_is_reachable_from_alembic_env(
    registered_tables: set[str],
) -> None:
    """A mapped table alembic cannot see is one autogenerate proposes dropping."""
    missing = {
        table: source
        for table, source in _declared_tablenames().items()
        if table not in registered_tables
    }
    assert not missing, (
        "These tables are declared under src/ but are NOT on Base.metadata when "
        "alembic/env.py runs, so `alembic check` will propose DROPPING them:\n"
        + "\n".join(f"  {table}  <- {source}" for table, source in sorted(missing.items()))
        + "\n\nFix: import the defining module in alembic/env.py."
    )


def test_social_auth_columns_are_installed_on_the_users_mapper(
    registered_tables: set[str],
) -> None:
    """The specific regression, pinned separately.

    `install_social_user_fields()` adds columns to an EXISTING mapper, so the
    table-level scan above cannot see it - a table named `users` is registered
    either way. Without this, the columns could silently vanish again.
    """
    from src.core.database import Base

    assert "users" in registered_tables
    users = Base.metadata.tables["users"]
    columns = {column.name for column in users.columns}
    assert {"username", "avatar_url", "email_verified"} <= columns, (
        f"social columns missing from the users mapper: got {sorted(columns)}"
    )
    assert any(index.name == "ix_users_username" for index in users.indexes)


def test_hashed_password_is_nullable_matching_migration_0014() -> None:
    """Migration 0014 makes it nullable; an OAuth account has no password.

    `auth.py` creates OAuth users with `hashed_password=None` and login fails
    closed on a null value before any hash comparison, so NOT NULL here was
    simply a stale declaration contradicting both.
    """
    from src.core.database import Base

    assert Base.metadata.tables["users"].columns["hashed_password"].nullable is True

def _migration_unique_constraint_names() -> dict[str, str]:
    """{constraint_name: migration file} for every named sa.UniqueConstraint."""
    versions = BACKEND_ROOT / "alembic" / "versions"
    found: dict[str, str] = {}
    for path in sorted(versions.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "UniqueConstraint":
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "name"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    found.setdefault(keyword.value.value, path.name)
    return found


def test_named_unique_constraints_in_migrations_exist_in_the_orm(
    registered_tables: set[str],
) -> None:
    """A UNIQUE CONSTRAINT and a unique INDEX are different objects.

    ⚠️ This is the defect the table-level scan above could NOT see, and it
    surfaced only after that scan's fix landed - the classic "fixing the first
    reveals the second" shape.

    `social_auth_models` declared
    `Index("ix_user_identities_provider_subject", ..., unique=True)` while
    migration 0014 creates
    `UniqueConstraint(..., name="uq_user_identities_provider_subject")`.
    PostgreSQL backs a unique constraint with an index, but alembic compares
    the two separately, so autogenerate proposed dropping the constraint and
    adding an index in its place - a one-item diff that failed the gate just as
    hard as the seven-item one.

    Name-level rather than full shape comparison: verifying column sets and
    deferrability faithfully needs a real database, which this environment does
    not have (`docs/DEBT.md` item 45). A missing NAME is the failure mode that
    actually occurred and is cheap to catch here; CI's `alembic check` remains
    the authority on the rest.
    """
    from src.core.database import Base

    declared = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.name and str(constraint.name).startswith("uq_")
    }
    missing = {
        name: source
        for name, source in _migration_unique_constraint_names().items()
        if name not in declared
    }
    assert not missing, (
        "These unique constraints are created by a migration but are absent "
        "from Base.metadata, so `alembic check` will propose dropping them:\n"
        + "\n".join(f"  {name}  <- {source}" for name, source in sorted(missing.items()))
        + "\n\nFix: declare sa.UniqueConstraint(..., name=...) in the model's "
        "__table_args__ - a unique Index is NOT the same object."
    )
