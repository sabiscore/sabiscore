import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

# Alembic's own bookkeeping table (alembic_version.version_num) defaults to
# VARCHAR(32). SQLite doesn't enforce VARCHAR length, so a revision id over
# this ceiling passes every local/SQLite gate and only fails on real
# PostgreSQL, at the very last statement of `alembic upgrade head` — see
# 0011_user_identity_dev_platform.py's docstring for the incident this pins.
ALEMBIC_VERSION_NUM_MAX_LENGTH = 32

SCAN_ROOTS = [
    BACKEND / "src",
    BACKEND / "scripts",
    BACKEND / "alembic",
]
SCAN_FILES = [
    ROOT / ".env.example",
    ROOT / ".env.production.example",
    BACKEND / ".env.example",
]
FORBIDDEN_SCHEMA_PATTERNS = [
    "Base.metadata." + "create_all",
    "Base.metadata." + "drop_all",
    "AUTO_CREATE" + "_TABLES",
]
TEXT_SUFFIXES = {".py", ".sh", ".ini", ".env", ".example", ".toml", ".yml", ".yaml"}


def _tracked_hardening_files():
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                yield path
    for path in SCAN_FILES:
        if path.exists():
            yield path


def test_no_runtime_script_or_alembic_file_contains_direct_schema_creation():
    for path in _tracked_hardening_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in FORBIDDEN_SCHEMA_PATTERNS:
            assert pattern not in text, (
                f"Retired schema-management path found in {path.relative_to(ROOT)}"
            )


def test_baseline_migration_is_explicit_and_orm_free():
    migration = BACKEND / "alembic" / "versions" / "0001_baseline_schema.py"
    text = migration.read_text(encoding="utf-8")

    assert "from src.core.database import Base" not in text
    assert "import Base" not in text
    assert "Base.metadata" not in text
    assert "op.create_table(" in text
    assert "op.create_index(" in text
    assert "op.drop_index(" in text
    assert "op.drop_table(" in text


def test_every_alembic_revision_id_fits_the_version_num_column():
    versions_dir = BACKEND / "alembic" / "versions"
    migration_files = sorted(versions_dir.glob("*.py"))
    assert migration_files, "expected at least one Alembic migration file"

    for path in migration_files:
        spec = importlib.util.spec_from_file_location(path.stem, str(path))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        revision = getattr(module, "revision", None)
        assert revision, f"{path.name} has no `revision` attribute"
        assert len(revision) <= ALEMBIC_VERSION_NUM_MAX_LENGTH, (
            f"{path.name}: revision id {revision!r} is {len(revision)} chars, "
            f"exceeds alembic_version.version_num's {ALEMBIC_VERSION_NUM_MAX_LENGTH}-char "
            "column width — `alembic upgrade head` will fail on PostgreSQL with "
            "StringDataRightTruncation on its final version-stamp UPDATE"
        )

        down_revision = getattr(module, "down_revision", None)
        if down_revision:
            assert len(down_revision) <= ALEMBIC_VERSION_NUM_MAX_LENGTH, (
                f"{path.name}: down_revision {down_revision!r} exceeds "
                f"{ALEMBIC_VERSION_NUM_MAX_LENGTH} chars"
            )


def test_sqlite_fallback_requires_explicit_opt_in_outside_tests(monkeypatch):
    from src.core.config import Settings

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./local.db")
    monkeypatch.setenv("ALLOW_SQLITE_FALLBACK", "false")

    settings = Settings()

    assert settings.app_env == "development"
    assert settings.database_url.startswith("sqlite")
    assert settings.allow_sqlite_fallback is False


# ── Migration target guard ───────────────────────────────────────────────────
#
# `alembic upgrade head` applies DDL, and every route to it — a developer's
# shell, make, scripts/ci_local_enforcer.sh, Render's startCommand — passes
# through alembic/env.py. That makes env.py the one place this guard cannot be
# bypassed by forgetting to add it somewhere else.
#
# It exists because it already happened: a local pre-commit gate ran
# `alembic upgrade head` against the Render production instance purely because
# DATABASE_URL was exported in that shell. It was a no-op (production was
# already at head), but "happened to be a no-op" is not a safety property.


def _load_migration_guard():
    """Extract env.py's guard without alembic's runtime context.

    Importing alembic/env.py outright executes migrations against whatever
    context is configured, which a test must never do.
    """
    from urllib.parse import urlsplit

    from src.core.config import settings

    source = (BACKEND / "alembic" / "env.py").read_text(encoding="utf-8")
    start = source.index("_DEPLOY_ENVIRONMENTS")
    end = source.index("def _sync_database_url")
    namespace: dict = {"urlsplit": urlsplit, "settings": settings}
    exec(compile(source[start:end], "env.py-guard", "exec"), namespace)  # noqa: S102
    return namespace["_guard_migration_target"], settings


_PROD_URL = (
    "postgresql+psycopg://u:p@"
    "dpg-da3p8qv10e5c738vls1g-a.oregon-postgres.render.com/sabiscore_db_v3"
)
_LOCAL_URL = "postgresql+psycopg://postgres@localhost:5432/sabiscore_verify"


def _verdict(guard, settings, url: str, app_env: str) -> str:
    original = settings.app_env
    try:
        settings.app_env = app_env
        guard(url)
        return "ALLOW"
    except RuntimeError:
        return "REFUSE"
    finally:
        settings.app_env = original


def test_a_local_shell_cannot_migrate_a_remote_database() -> None:
    """The incident, pinned. APP_ENV defaults to development."""
    guard, settings = _load_migration_guard()
    for env in ("development", "test", "", "DEVELOPMENT"):
        assert _verdict(guard, settings, _PROD_URL, env) == "REFUSE", env


def test_a_declared_deploy_environment_may_still_migrate() -> None:
    """Render's startCommand runs `alembic upgrade head` with APP_ENV=production.

    The guard must not break deployment — that would trade one outage for
    another.
    """
    guard, settings = _load_migration_guard()
    for env in ("production", "staging", "Production"):
        assert _verdict(guard, settings, _PROD_URL, env) == "ALLOW", env


def test_local_and_sqlite_targets_are_always_permitted() -> None:
    guard, settings = _load_migration_guard()
    for url in (
        _LOCAL_URL,
        "postgresql+psycopg://u:p@127.0.0.1:5432/db",
        "sqlite:///./sabiscore.db",
    ):
        assert _verdict(guard, settings, url, "development") == "ALLOW", url


def test_both_migration_paths_route_through_the_guard() -> None:
    """Offline and online migrations must both be covered.

    Guarding only `run_migrations_online` would leave `--sql` mode open, and
    the two are easy to change independently.
    """
    source = (BACKEND / "alembic" / "env.py").read_text(encoding="utf-8")
    offline = source.index("def run_migrations_offline")
    online = source.index("def run_migrations_online")
    assert "_guard_migration_target" in source[offline:online], "offline path unguarded"
    assert "_guard_migration_target" in source[online:], "online path unguarded"
