"""Safety and completeness checks for the psql-free verification runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_verification_sql import (
    _DEFAULT_FILES,
    _normalize_postgres_url,
    split_sql_statements,
    validate_read_only_statements,
)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_CANONICAL_AUDITS = (
    _BACKEND_DIR / "scripts" / "verify_elo.sql",
    _BACKEND_DIR / "scripts" / "verify_semantic_identity.sql",
    _BACKEND_DIR / "scripts" / "verify_clv_settlement.sql",
    _BACKEND_DIR / "scripts" / "verify_clv_by_generation.sql",
)
_LOCAL_COMPAT_RUNNER = _BACKEND_DIR / "scripts" / "run_verification_sql_local.py"


def test_normalize_postgres_url_requires_postgres() -> None:
    assert _normalize_postgres_url("postgres://u:p@host/db") == (
        "postgresql+asyncpg://u:p@host/db"
    )
    assert _normalize_postgres_url("postgresql://u:p@host/db") == (
        "postgresql+asyncpg://u:p@host/db"
    )
    assert _normalize_postgres_url("postgresql+asyncpg://u:p@host/db") == (
        "postgresql+asyncpg://u:p@host/db"
    )
    with pytest.raises(ValueError, match="PostgreSQL"):
        _normalize_postgres_url("sqlite:///local.db")


def test_splitter_ignores_semicolons_inside_quotes_and_comments() -> None:
    sql = """
    -- comment with ; delimiter
    SELECT 'a;b' AS value;
    /* block ; comment */
    WITH x AS (SELECT \"semi;colon\" AS value) SELECT * FROM x;
    """
    statements = split_sql_statements(sql)
    assert len(statements) == 2
    assert "'a;b'" in statements[0]
    assert '"semi;colon"' in statements[1]


def test_validator_skips_transaction_wrappers_and_rejects_writes() -> None:
    statements = split_sql_statements(
        "BEGIN TRANSACTION READ ONLY; SELECT 1; WITH x AS (SELECT 2) SELECT * FROM x; ROLLBACK;"
    )
    executable = validate_read_only_statements(statements)
    assert len(executable) == 2

    for unsafe in (
        "UPDATE matches SET status='x'",
        "DELETE FROM matches",
        "INSERT INTO matches(id) VALUES('x')",
    ):
        with pytest.raises(ValueError, match="non-read-only"):
            validate_read_only_statements([unsafe])


def test_default_runner_includes_every_canonical_audit() -> None:
    assert tuple(_DEFAULT_FILES) == _CANONICAL_AUDITS


def test_canonical_verification_files_are_nonempty_and_read_only() -> None:
    for path in _CANONICAL_AUDITS:
        sql = path.read_text(encoding="utf-8")
        assert sql.strip(), f"{path.name} must never be committed empty"
        executable = validate_read_only_statements(split_sql_statements(sql))
        assert executable, f"{path.name} must contain at least one read-only query"


def test_canonical_verification_files_have_one_transaction_wrapper() -> None:
    for path in _CANONICAL_AUDITS:
        sql = path.read_text(encoding="utf-8").upper()
        assert sql.count("BEGIN TRANSACTION READ ONLY;") == 1, (
            f"{path.name} must contain exactly one BEGIN TRANSACTION READ ONLY wrapper"
        )
        assert sql.count("ROLLBACK;") == 1, (
            f"{path.name} must contain exactly one ROLLBACK wrapper"
        )


def test_elo_audit_distinguishes_residual_from_new_self_play_writers() -> None:
    sql = (_BACKEND_DIR / "scripts" / "verify_elo.sql").read_text(encoding="utf-8")
    assert "historical_fdco_self_play_matches" in sql
    assert "non_historical_self_play_matches" in sql
    assert "post_pr25_self_play_matches" in sql
    assert "scheduled_self_play_matches" in sql
    assert "HISTORICAL_FDCO_RESIDUAL" in sql
    assert "POST_PR25_OR_NON_HISTORICAL_WRITER" in sql
    assert "m.id LIKE 'fdco-%'" in sql
    assert "TIMESTAMP '2026-08-17 08:47:46'" in sql
    assert "COALESCE(m.updated_at, m.created_at)" in sql


def test_elo_audit_has_fail_closed_post_pr25_self_play_gate() -> None:
    sql = (_BACKEND_DIR / "scripts" / "verify_elo.sql").read_text(encoding="utf-8")
    assert "self_play_post_pr25_integrity" in sql
    assert "violation_count = 0" in sql
    assert "violation_count::integer" in sql
    assert "(violation_count - violation_count)::integer" in sql


def test_semantic_identity_audit_has_fail_closed_gate() -> None:
    sql = (_BACKEND_DIR / "scripts" / "verify_semantic_identity.sql").read_text(
        encoding="utf-8"
    )
    assert "semantic_historical_identity_integrity" in sql
    assert "historical_matches_with_semantic_identity_mismatch" in sql
    assert "elo_snapshot_team_league_mismatch" in sql
    assert "violation_count = 0" in sql
    assert "violation_count::integer" in sql
    assert "(violation_count - violation_count)::integer" in sql


def test_clv_audits_select_one_chain_per_match_and_generation() -> None:
    generation_sql = (
        _BACKEND_DIR / "scripts" / "verify_clv_by_generation.sql"
    ).read_text(encoding="utf-8").lower()
    settlement_sql = (
        _BACKEND_DIR / "scripts" / "verify_clv_settlement.sql"
    ).read_text(encoding="utf-8").lower()

    assert "partition by p.match_id, p.model_version" in generation_sql
    assert "where prediction_rank = 1" in generation_sql
    assert "where closing_rank = 1" in generation_sql
    assert "p.created_at < c.captured_at" in generation_sql
    assert "group by model_version" in generation_sql

    assert "partition by p.match_id, p.model_version" in settlement_sql
    assert "where e.prediction_rank = 1" in settlement_sql
    assert "clv_mean_diagnostic_only" not in settlement_sql
    assert "'clv_sample_size'" not in settlement_sql


def test_local_compat_runner_cannot_restore_sqlite_fallback() -> None:
    source = _LOCAL_COMPAT_RUNNER.read_text(encoding="utf-8")
    assert "from run_verification_sql import main" in source
    assert "sqlite+aiosqlite" not in source
    assert "SABISCORE_ALLOW_INSECURE_FALLBACK" not in source
    assert "src.db.session" not in source
