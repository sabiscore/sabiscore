from __future__ import annotations

import numpy as np
import pytest

from src.core.exceptions import FeatureContractViolationError
from src.models.feature_bridge import (
    bridge_feature_vector,
    resolve_active_bridge_schema,
)


def test_resolve_active_bridge_schema_returns_declared_contract() -> None:
    schema_version, schema = resolve_active_bridge_schema()
    assert isinstance(schema_version, str)
    assert schema_version
    assert len(schema) > 0


def test_bridge_feature_vector_uses_schema_order_from_features_dict() -> None:
    schema = ("a", "b", "c")
    payload = {
        "features_dict": {
            "b": 2.0,
            "c": 3.0,
            "a": 1.0,
        }
    }

    vector = bridge_feature_vector(
        payload,
        schema=schema,
        schema_version="test_schema",
        context="unit_test",
    )

    assert vector.tolist() == [1.0, 2.0, 3.0]


def test_bridge_feature_vector_rejects_missing_schema_keys() -> None:
    with pytest.raises(FeatureContractViolationError, match="missing"):
        bridge_feature_vector(
            {"features_dict": {"a": 1.0}},
            schema=("a", "b"),
            schema_version="test_schema",
            context="unit_test",
        )


def test_bridge_feature_vector_rejects_non_finite_values() -> None:
    with pytest.raises(FeatureContractViolationError, match="not finite"):
        bridge_feature_vector(
            {"features_dict": {"a": float("nan")}},
            schema=("a",),
            schema_version="test_schema",
            context="unit_test",
        )


def test_bridge_feature_vector_uses_legacy_positional_vector_when_width_matches() -> None:
    vector = bridge_feature_vector(
        {"features_68": np.array([1.0, 2.0], dtype=np.float32)},
        schema=("x", "y"),
        schema_version="legacy_schema",
        context="unit_test",
    )
    assert vector.tolist() == [1.0, 2.0]


def test_bridge_feature_vector_rejects_legacy_vector_width_mismatch() -> None:
    with pytest.raises(FeatureContractViolationError, match="matched schema width"):
        bridge_feature_vector(
            {"features_68": np.array([1.0], dtype=np.float32)},
            schema=("x", "y"),
            schema_version="legacy_schema",
            context="unit_test",
        )


def test_feature_contract_violation_error_attributes() -> None:
    err = FeatureContractViolationError(
        "test violation",
        schema_version="schema_v1",
        expected_dim=68,
        actual_dim=58,
        context="unit_test_context",
    )
    assert str(err) == "test violation"
    assert err.schema_version == "schema_v1"
    assert err.expected_dim == 68
    assert err.actual_dim == 58
    assert err.context == "unit_test_context"
    assert err.provider == "unit_test_context"
    assert err.evidence_type == "feature_contract_violation"


def test_resolve_active_bridge_schema_active_generation_error(monkeypatch) -> None:
    from src.models import feature_bridge
    from src.models.active_generation import ActiveGenerationError

    def _fail_active():
        raise ActiveGenerationError("active generation manifest missing")

    monkeypatch.setattr(feature_bridge, "active_feature_schema_version", _fail_active)
    with pytest.raises(FeatureContractViolationError) as exc_info:
        resolve_active_bridge_schema()
    assert "active feature schema is unavailable" in str(exc_info.value)
    assert exc_info.value.context == "feature_bridge"


def test_resolve_active_bridge_schema_unknown_schema_error(monkeypatch) -> None:
    from src.models import feature_bridge
    from src.models.feature_registry import UnknownFeatureSchemaError

    def _fail_resolve(_version):
        raise UnknownFeatureSchemaError("schema apex_v999 unknown")

    monkeypatch.setattr(feature_bridge, "resolve_feature_schema", _fail_resolve)
    with pytest.raises(FeatureContractViolationError) as exc_info:
        resolve_active_bridge_schema()
    assert "active feature schema is unavailable" in str(exc_info.value)
    assert exc_info.value.context == "feature_bridge"


def test_bridge_feature_vector_empty_schema() -> None:
    with pytest.raises(FeatureContractViolationError, match="resolved feature schema is empty"):
        bridge_feature_vector(
            {"features_dict": {"a": 1.0}},
            schema=(),
            schema_version="empty_v1",
            context="unit_test",
        )


def test_bridge_feature_vector_non_numeric_dict_value() -> None:
    with pytest.raises(FeatureContractViolationError, match="is non-numeric"):
        bridge_feature_vector(
            {"features_dict": {"a": "not_a_number"}},
            schema=("a",),
            schema_version="test_schema",
            context="unit_test",
        )


def test_bridge_feature_vector_multidimensional_positional() -> None:
    with pytest.raises(FeatureContractViolationError, match="must be a 1D vector"):
        bridge_feature_vector(
            {"features": np.zeros((2, 2))},
            schema=("a", "b"),
            schema_version="test_schema",
            context="unit_test",
        )


def test_bridge_feature_vector_non_finite_positional() -> None:
    with pytest.raises(FeatureContractViolationError, match="contains non-finite values"):
        bridge_feature_vector(
            {"features": np.array([1.0, np.inf], dtype=np.float32)},
            schema=("a", "b"),
            schema_version="test_schema",
            context="unit_test",
        )


def test_bridge_feature_vector_empty_features_result() -> None:
    with pytest.raises(FeatureContractViolationError, match="neither features_dict nor positional"):
        bridge_feature_vector(
            {},
            schema=("a",),
            schema_version="test_schema",
            context="unit_test",
        )


@pytest.mark.asyncio
async def test_upcoming_match_service_feature_contract_violation_recovery(monkeypatch) -> None:
    from unittest.mock import AsyncMock
    from src.services.upcoming_match_service import UpcomingMatchService

    service = UpcomingMatchService()
    mock_db = AsyncMock()

    def _raise_bridge_error():
        raise FeatureContractViolationError("Schema missing", context="test")

    monkeypatch.setattr(
        "src.services.upcoming_match_service.resolve_active_bridge_schema",
        _raise_bridge_error,
    )
    monkeypatch.setattr(
        service,
        "get_upcoming_matches",
        AsyncMock(return_value={"matches": [{"match_id": "m1", "league": "EPL"}], "source": "test"}),
    )

    result = await service.get_upcoming_matches_with_predictions(mock_db, league="EPL")
    assert result["total"] == 1
    match = result["upcoming_matches"][0]
    assert "feature_contract_violation" in match["data_gaps"]
    assert match["value_bets"] == []


@pytest.mark.asyncio
async def test_full_analysis_feature_contract_violation_recovery(monkeypatch) -> None:
    from types import SimpleNamespace
    from src.api.endpoints import full_analysis as fa_endpoint

    class DummyProjector:
        def __init__(self, **_kwargs):
            pass

        async def build_live_feature_vector(self, **_kwargs):
            return {
                "match_id": "f1",
                "league": "EPL",
                "features_dict": {"elo_diff": 10.0},
                "data_gaps": [],
                "critical_gaps": [],
                "advisory_gaps": [],
            }

    class DummyPredictionEngine:
        async def predict(self, **_kwargs):
            return SimpleNamespace(
                to_dict=lambda: {
                    "home_win": 0.4,
                    "draw": 0.3,
                    "away_win": 0.3,
                    "model_version": "dummy",
                    "calibration_method": "raw",
                }
            )

    monkeypatch.setattr(fa_endpoint, "UpcomingMatchFeatureProjector", DummyProjector)
    monkeypatch.setattr(fa_endpoint, "PredictionEngine", DummyPredictionEngine)
    monkeypatch.setattr(fa_endpoint, "cache", None)

    # Branch A: resolve_active_bridge_schema fails
    def _raise_bridge_error():
        raise FeatureContractViolationError("Active schema unavailable", context="unit_test")

    monkeypatch.setattr(fa_endpoint, "resolve_active_bridge_schema", _raise_bridge_error)
    res = await fa_endpoint.get_full_analysis("f1", league="EPL", db=object())
    assert "FEATURE_CONTRACT_VIOLATION" in res["evidence_quality"]["critical_gaps"]

    # Branch B: bridge_feature_vector fails during prediction
    monkeypatch.undo()
    monkeypatch.setattr(fa_endpoint, "UpcomingMatchFeatureProjector", DummyProjector)
    monkeypatch.setattr(fa_endpoint, "PredictionEngine", DummyPredictionEngine)
    monkeypatch.setattr(fa_endpoint, "cache", None)

    def _fail_bridge(*_args, **_kwargs):
        raise FeatureContractViolationError("Vector mismatch", context="full_analysis")

    monkeypatch.setattr(fa_endpoint, "bridge_feature_vector", _fail_bridge)
    res2 = await fa_endpoint.get_full_analysis("f1", league="EPL", db=object())
    assert "FEATURE_CONTRACT_VIOLATION" in res2["evidence_quality"]["critical_gaps"]



