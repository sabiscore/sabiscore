"""Fail-closed bridge for candidate feature vectors.

The V21 candidate contract is intentionally stricter than a width check. The
incumbent generation remains served independently while candidate vectors are
admitted only when their declared schema and per-feature provenance are
complete and point-in-time safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

try:  # Container runtime exposes backend/src as the top-level ``src`` package.
    from src.models.feature_registry import build_feature_contract
except ModuleNotFoundError:  # Repository tests import through ``backend.src``.
    from backend.src.models.feature_registry import build_feature_contract


class FeatureBridgeRejected(ValueError):
    """Candidate input failed its schema or provenance contract."""


@dataclass(frozen=True)
class BridgedFeatures:
    schema_id: str
    schema_hash: str
    feature_order: tuple[str, ...]
    values: tuple[float, ...]
    provenance: Mapping[str, Any]


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise FeatureBridgeRejected(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FeatureBridgeRejected(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise FeatureBridgeRejected(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


class FeatureBridge:
    """Validate and order a candidate vector against the canonical registry."""

    def __init__(self, redis_client: Any = None, *, schema_id: str = "apex_v1_89"):
        self.redis = redis_client
        self.schema_id = schema_id
        self.contract = build_feature_contract(schema_id)
        self.feature_order = tuple(
            str(item["feature_name"]) for item in self.contract["features"]
        )
        # The registry digest covers the ordered full contract, including
        # semantics, units, serving lineage, freshness disposition, and dtype.
        self.schema_hash = str(self.contract["feature_contract_sha256"])
        self.feature_dim = len(self.feature_order)
        self.market_derived_features = tuple(
            name for name in self.feature_order
            if any(token in name.casefold() for token in (
                "odds", "market", "implied_prob", "closing", "devig", "sharp_money"
            ))
        )

    def validate(
        self,
        *,
        features: Mapping[str, Any],
        feature_schema_id: str,
        schema_hash: str,
        feature_evidence: Mapping[str, Mapping[str, Any]],
        feature_cutoff: str,
        expected_schema_hash: str | None = None,
    ) -> BridgedFeatures:
        if feature_schema_id != self.schema_id:
            raise FeatureBridgeRejected("feature_schema_id does not match candidate")
        if self.market_derived_features:
            raise FeatureBridgeRejected(
                "candidate schema contains market-derived inputs: "
                + ", ".join(self.market_derived_features)
            )
        if schema_hash != self.schema_hash or (
            expected_schema_hash is not None and expected_schema_hash != self.schema_hash
        ):
            raise FeatureBridgeRejected("feature_schema_hash does not match candidate")
        if tuple(features.keys()) != self.feature_order:
            raise FeatureBridgeRejected("feature_order does not match candidate schema")
        if set(feature_evidence) != set(self.feature_order):
            raise FeatureBridgeRejected("feature evidence is incomplete or contains unknown fields")

        cutoff = _utc(feature_cutoff, "feature_cutoff")
        values: list[float] = []
        for contract_item, name in zip(self.contract["features"], self.feature_order):
            for field in ("semantic_definition", "unit", "serving_source"):
                if contract_item.get(field) in (None, "UNDECLARED", ""):
                    raise FeatureBridgeRejected(
                        f"registered feature contract leaves {field} undeclared: {name}"
                    )
            evidence = feature_evidence[name]
            if evidence.get("feature_name") != name:
                raise FeatureBridgeRejected(f"feature name mismatch: {name}")
            for field in ("source", "semantics", "unit"):
                if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                    raise FeatureBridgeRejected(f"{field} is missing for {name}")
            if evidence["source"] != contract_item["serving_source"]:
                raise FeatureBridgeRejected(f"feature lineage mismatch: {name}")
            if evidence["semantics"] != contract_item["semantic_definition"]:
                raise FeatureBridgeRejected(f"feature semantics mismatch: {name}")
            if evidence["unit"] != contract_item["unit"]:
                raise FeatureBridgeRejected(f"feature unit mismatch: {name}")
            observed = _utc(evidence.get("feature_timestamp"), f"feature_timestamp[{name}]")
            effective = _utc(evidence.get("effective_at"), f"effective_at[{name}]")
            if observed > cutoff or effective > cutoff:
                raise FeatureBridgeRejected(f"point-in-time cutoff violated: {name}")
            max_age = evidence.get("max_age_seconds")
            if (
                isinstance(max_age, bool)
                or not isinstance(max_age, (int, float))
                or max_age <= 0
            ):
                raise FeatureBridgeRejected(f"freshness policy is missing: {name}")
            age = (cutoff - observed).total_seconds()
            if age < 0 or age > max_age:
                raise FeatureBridgeRejected(f"feature is stale: {name}")
            try:
                value = float(features[name])
            except (TypeError, ValueError) as exc:
                raise FeatureBridgeRejected(f"feature value is invalid: {name}") from exc
            if not isfinite(value):
                raise FeatureBridgeRejected(f"feature value is non-finite: {name}")
            values.append(value)

        return BridgedFeatures(
            schema_id=self.schema_id,
            schema_hash=self.schema_hash,
            feature_order=self.feature_order,
            values=tuple(values),
            provenance={"feature_cutoff": cutoff.isoformat(), "source": "validated_live_evidence"},
        )

    def get_serving_features(self, match_id: str, parent_baseline: Sequence[float]) -> list[float]:
        """Legacy adapter now rejects unproven fallbacks instead of returning them."""
        del match_id
        if len(parent_baseline) != self.feature_dim:
            raise FeatureBridgeRejected("fallback vector dimension does not match candidate")
        raise FeatureBridgeRejected("fallback vector has no semantic evidence or lineage")


__all__ = ["BridgedFeatures", "FeatureBridge", "FeatureBridgeRejected"]
