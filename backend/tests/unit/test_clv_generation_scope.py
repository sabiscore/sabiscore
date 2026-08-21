"""CLV evidence must be scoped to one immutable model generation."""

from __future__ import annotations

import pytest

from src.repositories.fixtures import build_clv_records_query


def test_clv_query_scopes_generation_before_and_after_latest_selection() -> None:
    statement = build_clv_records_query(model_version="v5_phase7")
    sql = str(statement.compile(compile_kwargs={"literal_binds": True})).lower()

    # One predicate belongs inside latest_prediction; another belongs on the
    # selected row.  Filtering only outside would let a newer foreign generation
    # hide a valid older prediction for the requested generation.
    assert sql.count("match_prediction_logs.model_version = 'v5_phase7'") >= 2


def test_clv_query_requires_explicit_generation_scope() -> None:
    with pytest.raises(TypeError, match="model_version"):
        build_clv_records_query()  # type: ignore[call-arg]


def test_clv_query_rejects_blank_generation_scope() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        build_clv_records_query(model_version="  ")
