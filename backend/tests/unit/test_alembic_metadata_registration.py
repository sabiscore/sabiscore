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

⚠️ AND THE REPLAY RUNS IN A FRESH INTERPRETER, WHICH IS LOAD-BEARING

An in-process replay cannot prove env.py's imports are sufficient, because
`Base.metadata` is process-global and any other test module can populate it
first. `tests/unit/test_adversarial_m2_m3.py` imports `src.api.main` ->
`auth.py` -> `social_auth_models`, and "adversarial" sorts before "alembic", so
in the full-suite collection CI actually runs, the mapper is already registered
before a single assertion here executes.

Measured, with the `env.py` import reverted:

    pytest <this file>                       ->  3 failed, 2 passed
    pytest test_adversarial_m2_m3.py <this>  -> 16 passed   <- wrong reason

The first reading is what made an earlier session trust this guard. The second
is the run that matters. Capturing the metadata in a subprocess makes the two
agree.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC = BACKEND_ROOT / "src"
ENV_PY = BACKEND_ROOT / "alembic" / "env.py"

#: Runs in a fresh interpreter with nothing imported but what env.py imports.
#: Emits the parts of `Base.metadata` that `alembic check` compares, as JSON.
_SNAPSHOT_SCRIPT = """
import importlib, json, sys

modules = json.loads(sys.argv[1])
from src.core.database import Base

for module in modules:
    try:
        importlib.import_module(module)
    except ImportError:
        # `from src.db import models` yields "src.db.models.<name>" for a
        # symbol import; fall back to the module itself.
        importlib.import_module(module.rsplit(".", 1)[0])

columns = {}
indexes = {}
for name, table in Base.metadata.tables.items():
    columns[name] = {
        column.name: {
            "nullable": bool(column.nullable),
            "length": getattr(column.type, "length", None),
            "type": type(column.type).__name__,
        }
        for column in table.columns
    }
    indexes[name] = sorted(index.name for index in table.indexes if index.name)

unique_constraints = sorted(
    str(constraint.name)
    for table in Base.metadata.tables.values()
    for constraint in table.constraints
    if constraint.name and str(constraint.name).startswith("uq_")
)

json.dump(
    {
        "tables": sorted(Base.metadata.tables),
        "columns": columns,
        "indexes": indexes,
        "unique_constraints": unique_constraints,
    },
    sys.stdout,
)
"""


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
def metadata() -> dict[str, Any]:
    """`Base.metadata` as alembic sees it, captured in a FRESH interpreter.

    See this module's docstring for why in-process is not good enough.
    """
    env = dict(os.environ)
    # Mirror backend/conftest.py, which this subprocess never loads.
    env.setdefault("APP_ENV", "test")
    env.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./sabiscore_test.db")
    env.setdefault("ALLOW_SQLITE_FALLBACK", "true")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(BACKEND_ROOT), str(SRC), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    completed = subprocess.run(
        [sys.executable, "-c", _SNAPSHOT_SCRIPT, json.dumps(_env_model_modules())],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        pytest.fail(
            "metadata snapshot subprocess failed - alembic/env.py may not be "
            f"importable on its own:\n{completed.stderr[-4000:]}"
        )
    return json.loads(completed.stdout)


def test_the_scan_finds_something(metadata: dict[str, Any]) -> None:
    """Guard the guard: an empty scan would make every assertion below vacuous."""
    declared = _declared_tablenames()
    assert len(declared) > 10, f"AST scan found only {len(declared)} tables - scan is broken"
    assert metadata["tables"], "no tables registered - env.py import replay is broken"


def test_every_mapped_table_is_reachable_from_alembic_env(
    metadata: dict[str, Any],
) -> None:
    """A mapped table alembic cannot see is one autogenerate proposes dropping."""
    registered = set(metadata["tables"])
    missing = {
        table: source
        for table, source in _declared_tablenames().items()
        if table not in registered
    }
    assert not missing, (
        "These tables are declared under src/ but are NOT on Base.metadata when "
        "alembic/env.py runs, so `alembic check` will propose DROPPING them:\n"
        + "\n".join(f"  {table}  <- {source}" for table, source in sorted(missing.items()))
        + "\n\nFix: import the defining module in alembic/env.py."
    )


def test_social_auth_columns_are_installed_on_the_users_mapper(
    metadata: dict[str, Any],
) -> None:
    """The specific regression, pinned separately.

    `install_social_user_fields()` adds columns to an EXISTING mapper, so the
    table-level scan above cannot see it - a table named `users` is registered
    either way. Without this, the columns could silently vanish again.
    """
    assert "users" in metadata["tables"]
    columns = set(metadata["columns"]["users"])
    assert {"username", "avatar_url", "email_verified"} <= columns, (
        f"social columns missing from the users mapper: got {sorted(columns)}"
    )
    assert "ix_users_username" in metadata["indexes"]["users"]


def test_hashed_password_is_nullable_matching_migration_0014(
    metadata: dict[str, Any],
) -> None:
    """Migration 0014 makes it nullable; an OAuth account has no password.

    `auth.py` creates OAuth users with `hashed_password=None` and login fails
    closed on a null value before any hash comparison, so NOT NULL here was
    simply a stale declaration contradicting both.
    """
    assert metadata["columns"]["users"]["hashed_password"]["nullable"] is True


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
    metadata: dict[str, Any],
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
    declared = set(metadata["unique_constraints"])
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


def _string_length(node: ast.AST) -> int | None:
    """N from `sa.String(length=N)` or `String(N)`; None for anything else."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name != "String":
        return None
    for keyword in node.keywords:
        if keyword.arg == "length" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    if node.args and isinstance(node.args[0], ast.Constant):
        return node.args[0].value
    return None


def _column_length(node: ast.AST) -> tuple[str, int] | None:
    """(column, length) from `sa.Column("x", sa.String(length=N), ...)`."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name != "Column" or not node.args:
        return None
    first = node.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return None
    for arg in node.args[1:]:
        length = _string_length(arg)
        if length is not None:
            return first.value, length
    return None


def _migration_string_lengths() -> dict[tuple[str, str], tuple[int, str]]:
    """{(table, column): (length, migration file)} for bounded String columns."""
    versions = BACKEND_ROOT / "alembic" / "versions"
    found: dict[tuple[str, str], tuple[int, str]] = {}
    for path in sorted(versions.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            op = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if op not in {"create_table", "add_column"} or not node.args:
                continue
            table_node = node.args[0]
            if not (
                isinstance(table_node, ast.Constant)
                and isinstance(table_node.value, str)
            ):
                continue
            for arg in node.args[1:]:
                column = _column_length(arg)
                if column:
                    found.setdefault((table_node.value, column[0]), (column[1], path.name))
    return found


def test_migration_declared_string_lengths_match_the_orm(
    metadata: dict[str, Any],
) -> None:
    """A bounded VARCHAR in a migration must be bounded the same way in the ORM.

    ⚠️ This one does NOT fail `alembic check`, which is exactly why it needs a
    test. Alembic's default type comparator reduces to
    `t1.length is not None and t1.length != t2.length`, so a metadata type with
    no length reads as "don't care" and the gate stays green. The cost is
    silent: the ORM declines to enforce a limit the database does enforce, so an
    over-long value surfaces as a driver-level DataError at INSERT rather than
    as a clean application-level rejection.

    `user_identities.provider/provider_subject/provider_email` were unbounded
    against migration 0014's VARCHAR(32)/(255)/(320).
    """
    mismatches: list[str] = []
    for (table, column), (expected, source) in sorted(_migration_string_lengths().items()):
        declared = metadata["columns"].get(table, {}).get(column)
        if declared is None:  # dropped later, or not a mapped table
            continue
        if declared["length"] != expected:
            mismatches.append(
                f"  {table}.{column}: migration says String({expected}), "
                f"ORM says {declared['type']}(length={declared['length']})  <- {source}"
            )
    assert not mismatches, (
        "These columns are bounded in a migration but not identically in the "
        "ORM. `alembic check` will NOT catch this - an unbounded metadata type "
        "compares as 'don't care':\n" + "\n".join(mismatches)
    )
