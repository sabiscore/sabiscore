"""Alembic environment for the canonical SabiScore backend schema."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from urllib.parse import urlsplit

from src.core.config import settings
from src.core.database import Base
from src.db import models as _db_models  # noqa: F401
from src.db import provider_elo_team_mapping as _provider_elo_team_mapping  # noqa: F401

# Mapped tables live outside `src/db/` too. `social_auth_models` defines
# `user_identities` and installs the social columns on `users`; without this
# import they are absent from `Base.metadata` and autogenerate proposes
# dropping what migration 0014 created. `test_alembic_metadata_registration.py`
# fails if any mapped table is missing from the set imported here.
from src.services import social_auth_models as _social_auth_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


#: Environments that legitimately migrate a remote database. A deploy context
#: declares itself; a developer's shell does not. `APP_ENV` defaults to
#: "development" (core/config.py), so a local shell is structurally incapable of
#: reaching production no matter what DATABASE_URL happens to hold.
_DEPLOY_ENVIRONMENTS = frozenset({"production", "staging"})

_LOCAL_HOSTS = frozenset({None, "", "localhost", "127.0.0.1", "::1"})


def _guard_migration_target(url: str) -> str:
    """Refuse to migrate a remote database from a non-deploy environment.

    `alembic upgrade head` applies DDL. Every route to it — a developer's
    shell, `make`, scripts/ci_local_enforcer.sh, and Render's own startCommand
    — passes through this module, which makes it the one place a guard cannot
    be bypassed by forgetting to add it somewhere.

    This exists because it already happened: a local pre-commit gate ran
    `alembic upgrade head` against the Render production instance purely
    because DATABASE_URL was exported in that shell. It was a no-op (production
    was already at head), but "happened to be a no-op" is not a safety
    property.

    The discriminator is deliberately `APP_ENV`, not the variable's *name*.
    Renaming production's variable to PROD_DATABASE_URL would break Render's
    startCommand — which supplies DATABASE_URL (render.yaml) — while doing
    nothing to stop a developer who also has the renamed variable exported. The
    operation needs the guard, not the spelling.
    """
    host = urlsplit(url).hostname
    if host in _LOCAL_HOSTS:
        return url

    env = (settings.app_env or "").strip().lower()
    if env in _DEPLOY_ENVIRONMENTS:
        return url

    raise RuntimeError(
        "Refusing to run migrations against a remote database.\n"
        f"  target host : {host}\n"
        f"  APP_ENV     : {env or '(unset -> development)'}\n"
        "\n"
        "Migrations alter schema. Only a declared deploy environment "
        f"({', '.join(sorted(_DEPLOY_ENVIRONMENTS))}) may target a non-local "
        "database.\n"
        "\n"
        "If you meant to migrate a local database, point DATABASE_URL at "
        "localhost.\n"
        "If you are deploying, set APP_ENV explicitly in the deploy "
        "environment (render.yaml already does)."
    )


def _sync_database_url(url: str) -> str:
    if "+aiosqlite" in url:
        return url.replace("+aiosqlite", "")
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg")
    # Render provides plain postgresql:// / postgres:// — route to psycopg3 (installed)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    url = _guard_migration_target(_sync_database_url(settings.database_url))
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _guard_migration_target(
        _sync_database_url(settings.database_url)
    )

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
