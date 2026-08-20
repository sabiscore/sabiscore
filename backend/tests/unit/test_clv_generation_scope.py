"""CLV evidence must be scoped to one immutable model generation."""

from __future__ import annotations

from src.repositories.fixtures import build_clv_records_query


def test_clv_query_scopes_generation_before_and_after_latest_selection() -> None:
    statement = build_clv_records_query(model_version="v5_phase7")
    sql = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()

    # One predicate belongs inside latest_prediction; another belongs on the
    # selected row.  Filtering only outside would let a newer foreign generation
    # hide a valid older prediction for the requested generation.
    assert sql.count("match_prediction_logs.model_version = 'v5_phase7'") >= 2


def test_clv_query_preserves_unscoped_research_mode() -> None:
    statement = build_clv_records_query()
    sql = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()

    assert "match_prediction_logs.model_version =" not in sql
