"""Feature schema bridge for live inference paths.

The feature projector returns a rich dictionary that can outlive multiple
schema revisions. Inference, however, consumes a positional vector and must
therefore bind explicitly to the active generation's declared schema order.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence, Tuple

import numpy as np

from ..core.exceptions import FeatureContractViolationError
from .active_generation import ActiveGenerationError, active_feature_schema_version
from .feature_registry import UnknownFeatureSchemaError, resolve_feature_schema


def resolve_active_bridge_schema() -> Tuple[str, Sequence[str]]:
    """Resolve the active generation's schema version and ordered feature list."""
    try:
        schema_version = active_feature_schema_version()
        schema = tuple(resolve_feature_schema(schema_version))
    except (ActiveGenerationError, UnknownFeatureSchemaError) as exc:
        raise FeatureContractViolationError(
            f"active feature schema is unavailable for live inference: {exc}",
            context="feature_bridge",
        ) from exc
    return schema_version, schema


def bridge_feature_vector(
    features_result: Mapping[str, Any],
    *,
    schema: Sequence[str],
    schema_version: str,
    context: str,
) -> np.ndarray:
    """Build a finite float32 vector in exact schema order.

    Preferred path is name-based assembly from ``features_dict``. A positional
    legacy vector is accepted only as compatibility fallback when its width
    exactly matches the schema.
    """
    if not schema:
        raise FeatureContractViolationError(
            "resolved feature schema is empty",
            schema_version=schema_version,
            context=context,
        )

    features_dict = features_result.get("features_dict")
    if (
        isinstance(features_dict, Mapping)
        and features_dict
        and all(name in features_dict for name in schema)
    ):
        values = np.empty(len(schema), dtype=np.float32)
        for index, name in enumerate(schema):
            raw = features_dict[name]
            try:
                numeric = float(raw)
            except (TypeError, ValueError) as exc:
                raise FeatureContractViolationError(
                    f"feature {name!r} is non-numeric: {raw!r}",
                    schema_version=schema_version,
                    expected_dim=len(schema),
                    context=context,
                ) from exc
            if not np.isfinite(numeric):
                raise FeatureContractViolationError(
                    f"feature {name!r} is not finite: {raw!r}",
                    schema_version=schema_version,
                    expected_dim=len(schema),
                    context=context,
                )
            values[index] = numeric
        return values

    observed_dims = []
    for key in ("features", "features_68", "features_58"):
        raw = features_result.get(key)
        if raw is None:
            continue
        vector = np.asarray(raw, dtype=np.float32)
        if vector.ndim != 1:
            raise FeatureContractViolationError(
                f"{key} must be a 1D vector, got shape {tuple(vector.shape)}",
                schema_version=schema_version,
                expected_dim=len(schema),
                context=context,
            )
        observed_dims.append(int(vector.shape[0]))
        if vector.shape[0] != len(schema):
            continue
        if not np.isfinite(vector).all():
            raise FeatureContractViolationError(
                f"{key} contains non-finite values",
                schema_version=schema_version,
                expected_dim=len(schema),
                actual_dim=int(vector.shape[0]),
                context=context,
            )
        return vector

    if observed_dims:
        raise FeatureContractViolationError(
            f"no positional vector matched schema width {len(schema)} (observed: {observed_dims})",
            schema_version=schema_version,
            expected_dim=len(schema),
            actual_dim=max(observed_dims),
            context=context,
        )
    if isinstance(features_dict, Mapping) and features_dict:
        missing = [name for name in schema if name not in features_dict]
        raise FeatureContractViolationError(
            f"features_dict is missing {len(missing)} schema keys: "
            f"{', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}",
            schema_version=schema_version,
            expected_dim=len(schema),
            actual_dim=len(features_dict),
            context=context,
        )
    raise FeatureContractViolationError(
        "projection result has neither features_dict nor positional feature vector",
        schema_version=schema_version,
        expected_dim=len(schema),
        context=context,
    )
