"""Execute SabiScore production verification SQL without requiring ``psql``.

The runner is intentionally fail-closed:
- DATABASE_URL must be explicitly configured and must target PostgreSQL.
- SQL files may contain only SELECT/WITH statements plus the canonical
  BEGIN TRANSACTION READ ONLY / ROLLBACK wrappers.
- The runner opens its own server-side read-only transaction and always rolls
  it back, even on success.

Usage from backend/:
    python scripts/run_verification_sql.py
    python scripts/run_verification_sql.py scripts/verify_elo.sql
    python scripts/run_verification_sql.py \
        scripts/verify_clv_settlement.sql scripts/verify_clv_by_generation.sql
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from pathlib import Path
from typing import Iterable, Sequence

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_FILES = (
    _BACKEND_DIR / "scripts" / "verify_elo.sql",
    _BACKEND_DIR / "scripts" / "verify_clv_settlement.sql",
    _BACKEND_DIR / "scripts" / "verify_clv_by_generation.sql",
)
_READ_ONLY_WRAPPERS = {
    "begin transaction read only",
    "begin read only",
    "rollback",
}
_ALLOWED_KEYWORDS = {"select", "with"}


def _normalize_postgres_url(raw_url: str) -> str:
    value = raw_url.strip()
    if value.startswith("postgresql+asyncpg://"):
        return value
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+asyncpg://", 1)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    raise ValueError("DATABASE_URL must be a PostgreSQL URL")


def split_sql_statements(sql: str) -> list[str]:
    """Split SQL on statement semicolons while respecting comments/quotes."""

    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    single_quote = False
    double_quote = False
    line_comment = False
    block_comment = False
    dollar_tag: str | None = None

    while index < len(sql):
        char = sql[index]
        nxt = sql[index + 1] if index + 1 < len(sql) else ""

        if line_comment:
            buffer.append(char)
            if char == "\n":
                line_comment = False
            index += 1
            continue

        if block_comment:
            buffer.append(char)
            if char == "*" and nxt == "/":
                buffer.append(nxt)
                block_comment = False
                index += 2
            else:
                index += 1
            continue

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                buffer.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                buffer.append(char)
                index += 1
            continue

        if single_quote:
            buffer.append(char)
            if char == "'":
                if nxt == "'":
                    buffer.append(nxt)
                    index += 2
                    continue
                single_quote = False
            index += 1
            continue

        if double_quote:
            buffer.append(char)
            if char == '"':
                if nxt == '"':
                    buffer.append(nxt)
                    index += 2
                    continue
                double_quote = False
            index += 1
            continue

        if char == "-" and nxt == "-":
            buffer.extend((char, nxt))
            line_comment = True
            index += 2
            continue
        if char == "/" and nxt == "*":
            buffer.extend((char, nxt))
            block_comment = True
            index += 2
            continue
        if char == "'":
            buffer.append(char)
            single_quote = True
            index += 1
            continue
        if char == '"':
            buffer.append(char)
            double_quote = True
            index += 1
            continue
        if char == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[index:])
            if match:
                dollar_tag = match.group(0)
                buffer.append(dollar_tag)
                index += len(dollar_tag)
                continue
        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer.clear()
            index += 1
            continue

        buffer.append(char)
        index += 1

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _strip_leading_comments(statement: str) -> str:
    remaining = statement.lstrip()
    while remaining:
        if remaining.startswith("--"):
            newline = remaining.find("\n")
            if newline < 0:
                return ""
            remaining = remaining[newline + 1 :].lstrip()
            continue
        if remaining.startswith("/*"):
            end = remaining.find("*/", 2)
            if end < 0:
                raise ValueError("Unterminated SQL block comment")
            remaining = remaining[end + 2 :].lstrip()
            continue
        return remaining
    return ""


def validate_read_only_statements(statements: Iterable[str]) -> list[str]:
    """Return executable read-only statements or raise on anything unsafe."""

    executable: list[str] = []
    for statement in statements:
        stripped = _strip_leading_comments(statement)
        if not stripped:
            continue
        normalized = " ".join(stripped.lower().split())
        if normalized in _READ_ONLY_WRAPPERS:
            continue
        keyword = normalized.split(maxsplit=1)[0]
        if keyword not in _ALLOWED_KEYWORDS:
            raise ValueError(
                f"Verification SQL contains non-read-only statement starting with {keyword!r}"
            )
        executable.append(statement)
    return executable


def _display_value(value: object) -> str:
    if value is None:
        return "NULL"
    return str(value)


def _print_result(path: Path, index: int, statement: str, result: object) -> None:
    print(f"\n== {path.name} :: query {index} ==")
    keys = list(result.keys())  # type: ignore[attr-defined]
    rows = result.fetchall()  # type: ignore[attr-defined]
    if not keys:
        print("(no columns)")
        return
    print("\t".join(str(key) for key in keys))
    if not rows:
        print("(0 rows)")
        return
    for row in rows:
        print("\t".join(_display_value(value) for value in row))
    print(f"({len(rows)} rows)")


async def _run(files: Sequence[Path], database_url: str) -> int:
    normalized_url = _normalize_postgres_url(database_url)
    engine = create_async_engine(normalized_url, poolclass=NullPool, echo=False)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                for path in files:
                    sql = path.read_text(encoding="utf-8")
                    statements = validate_read_only_statements(split_sql_statements(sql))
                    if not statements:
                        raise ValueError(f"Verification file has no executable read-only queries: {path}")
                    for index, statement in enumerate(statements, start=1):
                        result = await connection.exec_driver_sql(statement)
                        _print_result(path, index, statement, result)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
    return 0


def _resolve_files(raw_files: Sequence[str]) -> list[Path]:
    candidates = [Path(value) for value in raw_files] if raw_files else list(_DEFAULT_FILES)
    resolved: list[Path] = []
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else (Path.cwd() / candidate)
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Verification SQL file not found: {path}")
        resolved.append(path)
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run read-only SabiScore verification SQL using SQLAlchemy/asyncpg"
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="SQL files to execute; defaults to all canonical Phase-2 verification files",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        parser.error("DATABASE_URL is required; refusing to fall back to a local database")

    try:
        files = _resolve_files(args.files)
        return asyncio.run(_run(files, database_url))
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
