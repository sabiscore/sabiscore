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
            assert pattern not in text, f"Retired schema-management path found in {path.relative_to(ROOT)}"


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
