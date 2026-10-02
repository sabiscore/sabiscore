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
