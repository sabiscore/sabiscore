"""Deterministic feature-contract evidence for candidate promotion gates.

This module turns the exact candidate matrices emitted by
``scripts.train_on_real_matches.build_dataset`` into a mechanically verifiable
train/serve contract. It is deliberately fail-closed: a report can describe a
blocked candidate, but it cannot self-assert PASS when its own evidence contains
schema mismatches, training-default-only positions, permanent serving gaps, or
no training rows.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from .active_generation import ActiveGenerationError, active_feature_schema_version
from .feature_registry import (
    APEX_FEATURES_68,
    CANONICAL_FEATURES_68,
    DEFAULT_FEATURE_VALUES_68,
    FEATURE_SCHEMA_VERSIONS,
    PHASE7_FEATURES_ALWAYS_DATA_GAP,
    UnknownFeatureSchemaError,
    resolve_feature_schema,
)

REPORT_SCHEMA = "apex_v1_68"
REPORT_SCHEMA_VERSION = 1
_CLASS_SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
_CLASS_ALWAYS_DATA_GAP = "ALWAYS_DATA_GAP"
_CLASS_TRAINING_DEFAULT_ONLY = "TRAINING_DEFAULT_ONLY"
_CLASS_ALIGNED_OBSERVED = "ALIGNED_OBSERVED_SIGNAL"
_ALLOWED_CLASSIFICATIONS = {
    _CLASS_SCHEMA_MISMATCH,
    _CLASS_ALWAYS_DATA_GAP,
    _CLASS_TRAINING_DEFAULT_ONLY,
    _CLASS_ALIGNED_OBSERVED,
}
_FLOAT_ATOL = 1e-8


def _contract_hash(features: Sequence[str]) -> str:
    payload = json.dumps(list(features), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _registered_schema_version(features: Sequence[str]) -> str | None:
    """The FEATURE_SCHEMA_VERSIONS key naming this exact contract, if any."""
    wanted = list(features)
    for version, contract in FEATURE_SCHEMA_VERSIONS.items():
        if wanted == list(contract):
            return version
    return None


def current_serving_contract() -> list[str]:
    """The column order live serving actually produces today.

    Was hardcoded to ``CANONICAL_FEATURES_68``. Since docs/DEBT.md item 37's
    serving wire-up, both serving implementations
    (``data/transformers.py``, ``services/upcoming_match_feature_service.py``)
    dispatch on the active generation's declared ``feature_schema_version``,
    so this gate must read the same source — otherwise
    ``serving_schema_misaligned_slots`` would keep reporting the 11-slot
    apex/legacy divergence even once serving genuinely produced Apex vectors,
    and the gate could never clear no matter what was fixed.

    Falls back to ``CANONICAL_FEATURES_68`` on any resolution failure, which
    is exactly what both serving implementations fall back to — the gate must
    describe serving's real behaviour, including its fallback.
    """
    try:
        return list(resolve_feature_schema(active_feature_schema_version()))
    except (ActiveGenerationError, UnknownFeatureSchemaError):
        return list(CANONICAL_FEATURES_68)


def _stack_candidate_rows(
    dataset: Mapping[str, Mapping[str, Any]], candidate_features: Sequence[str]
) -> tuple[np.ndarray, dict[str, int]]:
    matrices: list[np.ndarray] = []
    rows_by_league: dict[str, int] = {}
    expected_width = len(candidate_features)

    for league in sorted(dataset):
        raw = dataset[league].get("X", [])
        matrix = np.asarray(raw, dtype=np.float64)
        if matrix.size == 0:
            rows_by_league[league] = 0
            continue
        if matrix.ndim != 2 or matrix.shape[1] != expected_width:
            raise ValueError(
                f"candidate matrix for {league} must have shape (n, {expected_width}); "
                f"got {matrix.shape}"
            )
        if not np.all(np.isfinite(matrix)):
            raise ValueError(f"candidate matrix for {league} contains non-finite values")
        rows_by_league[league] = int(matrix.shape[0])
        matrices.append(matrix)

    if not matrices:
        return np.empty((0, expected_width), dtype=np.float64), rows_by_league
    return np.vstack(matrices), rows_by_league


def _column_is_default_only(feature: str, column: np.ndarray) -> tuple[bool, float]:
    default = DEFAULT_FEATURE_VALUES_68.get(feature)
    if default is None or column.size == 0:
        return False, 1.0 if column.size else 0.0
    observed = ~np.isclose(column, float(default), rtol=0.0, atol=_FLOAT_ATOL)
    coverage = float(np.mean(observed))
    return bool(not observed.any()), coverage


def _serving_feature_at(serving_contract: Sequence[str], index: int) -> str | None:
    """The serving contract's feature name at ``index``, or ``None`` past its end.

    A candidate wider than what is currently active in production (e.g. a
    71-wide xG candidate compared against today's 68-wide serving contract)
    has positions with nothing on the serving side at all. ``None`` — never an
    IndexError, and never silently reused from a shorter contract — makes that
    an explicit, mechanically-checkable SCHEMA_MISMATCH: `feature != None` is
    always true, so `_classification` classifies it correctly without special
    casing.
    """
    return serving_contract[index] if index < len(serving_contract) else None


def _classification(
    *,
    feature: str,
    serving_feature: str | None,
    defaulted_training_slot: bool,
) -> str:
    if feature != serving_feature:
        return _CLASS_SCHEMA_MISMATCH
    if feature in PHASE7_FEATURES_ALWAYS_DATA_GAP:
        return _CLASS_ALWAYS_DATA_GAP
    if defaulted_training_slot:
        return _CLASS_TRAINING_DEFAULT_ONLY
    return _CLASS_ALIGNED_OBSERVED


def _summary_from_features(features: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "features": len(features),
        # Policy-gapped slots are excluded here for the same reason item 38
        # excluded them from `always_data_gap_slots`' role as a blocker
        # (docs/DEBT.md item 49, authorized 2026-09-03). A feature in
        # PHASE7_FEATURES_ALWAYS_DATA_GAP is *by policy* constant at its
        # registry default in every candidate forever, so
        # `_column_is_default_only()` marks it defaulted unconditionally —
        # giving this counter a hard floor of 4 and making the gate
        # structurally unsatisfiable, the exact condition item 38 set out to
        # remove. This measures *unexpectedly* defaulted slots; the policy
        # gaps still surface in `always_data_gap_slots` and the markdown.
        #
        # Keyed on the feature NAME, not on the row's own `always_data_gap`
        # boolean: `_summary_from_features` also runs in the validator path
        # against stored report rows, and a report written before that key
        # existed would make `row.get(...)` return None, silently restoring
        # the old count on one side only. The name is validated present on
        # every row, so this agrees across both call sites by construction.
        "training_defaulted_slots": sum(
            bool(row.get("defaulted_training_slot"))
            and str(row.get("feature")) not in PHASE7_FEATURES_ALWAYS_DATA_GAP
            for row in features
        ),
        "non_variable_training_slots": sum(
            not bool(row.get("variable_in_training")) for row in features
        ),
        "serving_schema_misaligned_slots": sum(
            not bool(row.get("candidate_position_matches_current_serving_schema"))
            for row in features
        ),
        "always_data_gap_slots": sum(
            str(row.get("feature")) in PHASE7_FEATURES_ALWAYS_DATA_GAP
            for row in features
        ),
    }


def _expected_gate(summary: Mapping[str, Any], training_rows: int) -> str:
    # always_data_gap_slots is intentionally NOT a blocker (docs/DEBT.md item
    # 38, authorized 2026-08-22): PHASE7_FEATURES_ALWAYS_DATA_GAP is a
    # permanent, declared 4-slot gap present in every 68-wide schema by
    # design — counting it here made the gate structurally unsatisfiable for
    # any candidate, however good. The count still surfaces in `summary` and
    # the rendered markdown; it just stops disqualifying.
    blockers = (
        int(summary["training_defaulted_slots"]),
        int(summary["serving_schema_misaligned_slots"]),
    )
    return "PASS" if training_rows > 0 and all(value == 0 for value in blockers) else "FAIL"


def build_promotion_feature_evidence(
    dataset: Mapping[str, Mapping[str, Any]],
    *,
    candidate_features: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build rich promotion evidence from the exact candidate ``X`` matrices.

    ``dataset`` must be the object returned by ``build_dataset()``. The function
    never infers availability from filenames, family labels, or a hand-maintained
    report; every training statistic comes from those exact matrices and every
    serving alignment decision comes from the current positional registry.

    ``candidate_features`` names the ordered contract the candidate matrices
    were built against, defaulting to ``APEX_FEATURES_68`` — the only contract
    this function was originally exercised with. Pass an explicit,
    ``FEATURE_SCHEMA_VERSIONS``-registered contract (e.g. via
    ``resolve_feature_schema``) to evaluate a wider candidate, such as one that
    adds new features beyond today's active serving contract; positions past
    the end of the current serving contract classify as SCHEMA_MISMATCH rather
    than raising (see ``_serving_feature_at``).
    """

    candidate = list(candidate_features) if candidate_features is not None else list(APEX_FEATURES_68)
    matrix, rows_by_league = _stack_candidate_rows(dataset, candidate)
    training_rows = int(matrix.shape[0])
    features: list[dict[str, Any]] = []
    serving_contract = current_serving_contract()

    for index, feature in enumerate(candidate):
        serving_feature = _serving_feature_at(serving_contract, index)
        column = matrix[:, index] if training_rows else np.empty(0, dtype=np.float64)
        defaulted, training_coverage = _column_is_default_only(feature, column)
        variable = bool(column.size and not np.allclose(column, column[0], rtol=0.0, atol=_FLOAT_ATOL))
        classification = _classification(
            feature=feature,
            serving_feature=serving_feature,
            defaulted_training_slot=defaulted,
        )
        features.append(
            {
                "index": index,
                "feature": feature,
                "serving_feature": serving_feature,
                "classification": classification,
                "training_source": "exact build_dataset() candidate matrix",
                "serving_source": "active generation's positional serving contract",
                "training_rows": training_rows,
                "training_coverage": round(training_coverage, 6),
                "training_missingness": round(1.0 - training_coverage, 6),
                "variable_in_training": variable,
                "training_stddev": float(np.std(column)) if column.size else None,
                "training_min": float(np.min(column)) if column.size else None,
                "training_max": float(np.max(column)) if column.size else None,
                "defaulted_training_slot": defaulted,
                "always_data_gap": feature in PHASE7_FEATURES_ALWAYS_DATA_GAP,
                "candidate_position_matches_current_serving_schema": feature == serving_feature,
            }
        )

    summary = _summary_from_features(features)
    return {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "training_rows": training_rows,
        "rows_by_league": rows_by_league,
        # Self-description, so a consumer reading this file back does not have
        # to be told out-of-band which contract it was built from. None when the
        # caller passed an ad-hoc list that matches no registered schema —
        # absent beats a guessed label in evidence.
        "candidate_feature_schema_version": _registered_schema_version(candidate),
        "candidate_contract_hash": _contract_hash(candidate),
        "serving_contract_hash": _contract_hash(serving_contract),
        "summary": summary,
        "promotion_gate": _expected_gate(summary, training_rows),
        "features": features,
    }


def validate_promotion_feature_evidence(
    report: Mapping[str, Any],
    *,
    candidate_features: Sequence[str] | None = None,
) -> Mapping[str, Any]:
    """Validate a persisted promotion report against the current registry.

    The validator intentionally accepts the existing rich v1 report shape while
    enforcing its mechanically meaningful fields. New reports may include the
    additional ``schema_version``, ``serving_feature`` and ``classification``
    fields emitted above. This lets the repository close the producer/consumer
    gap without pretending the quarantined candidate has newer evidence than it
    actually does.

    ``candidate_features`` must match whatever ``build_promotion_feature_evidence``
    built ``report`` from. When omitted, the report's own
    ``candidate_feature_schema_version`` is used; only a report that declares
    nothing (every report written before that field existed) falls back to
    ``APEX_FEATURES_68``. Guessing 68 for a 71-wide report would fail with
    "must contain exactly 68 feature rows", which describes the validator's
    assumption rather than the report.
    """

    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError(f"unsupported promotion evidence schema: {report.get('schema')!r}")

    if candidate_features is not None:
        candidate = list(candidate_features)
    else:
        declared = report.get("candidate_feature_schema_version")
        candidate = (
            list(resolve_feature_schema(declared))
            if isinstance(declared, str) and declared
            else list(APEX_FEATURES_68)
        )
    raw_features = report.get("features")
    if not isinstance(raw_features, list) or len(raw_features) != len(candidate):
        raise ValueError(
            f"promotion evidence must contain exactly {len(candidate)} feature rows"
        )

    serving_contract = current_serving_contract()
    for index, candidate_feature in enumerate(candidate):
        serving_feature = _serving_feature_at(serving_contract, index)
        row = raw_features[index]
        if not isinstance(row, Mapping):
            raise ValueError(f"promotion feature row {index} is not an object")
        if row.get("index") != index:
            raise ValueError(f"promotion feature row {index} has an invalid index")
        if row.get("feature") != candidate_feature:
            raise ValueError(
                f"promotion feature order mismatch at {index}: "
                f"expected {candidate_feature!r}, got {row.get('feature')!r}"
            )
        expected_match = candidate_feature == serving_feature
        if row.get("candidate_position_matches_current_serving_schema") is not expected_match:
            raise ValueError(f"promotion serving alignment is stale at feature index {index}")
        if "serving_feature" in row and row.get("serving_feature") != serving_feature:
            raise ValueError(f"promotion serving feature is stale at feature index {index}")
        if "classification" in row:
            expected_class = _classification(
                feature=candidate_feature,
                serving_feature=serving_feature,
                defaulted_training_slot=bool(row.get("defaulted_training_slot")),
            )
            classification = row.get("classification")
            if classification not in _ALLOWED_CLASSIFICATIONS or classification != expected_class:
                raise ValueError(f"promotion classification is invalid at feature index {index}")

    summary = report.get("summary")
    if not isinstance(summary, Mapping):
        raise ValueError("promotion evidence summary is missing or malformed")
    expected_summary = _summary_from_features(raw_features)
    for key, expected_value in expected_summary.items():
        if summary.get(key) != expected_value:
            raise ValueError(
                f"promotion evidence summary mismatch for {key}: "
                f"expected {expected_value}, got {summary.get(key)!r}"
            )

    training_rows_raw = report.get("training_rows")
    if not isinstance(training_rows_raw, int) or isinstance(training_rows_raw, bool):
        raise ValueError("promotion evidence training_rows must be an integer")
    if training_rows_raw < 0:
        raise ValueError("promotion evidence training_rows cannot be negative")

    expected_gate = _expected_gate(expected_summary, training_rows_raw)
    gate = report.get("promotion_gate")
    if gate not in {"PASS", "FAIL"}:
        raise ValueError(f"promotion_gate must be PASS or FAIL, got {gate!r}")
    if gate != expected_gate:
        raise ValueError(
            f"promotion_gate={gate} contradicts mechanically derived gate={expected_gate}"
        )

    if "candidate_contract_hash" in report and report.get("candidate_contract_hash") != _contract_hash(candidate):
        raise ValueError("candidate feature-contract hash does not match the current registry")
    if "serving_contract_hash" in report and report.get("serving_contract_hash") != _contract_hash(serving_contract):
        raise ValueError("serving feature-contract hash does not match the current registry")

    return report


def render_promotion_feature_evidence_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact human-readable companion to the JSON evidence."""

    validated = validate_promotion_feature_evidence(report)
    summary = validated["summary"]
    rows_by_league = validated.get("rows_by_league", {})
    lines = [
        "# APEX Promotion Feature Evidence",
        "",
        f"Promotion gate: **{validated['promotion_gate']}**",
        f"Training rows: **{validated['training_rows']}**",
        "",
        "## Mechanical blockers",
        "",
        f"- Training-default-only slots: **{summary['training_defaulted_slots']}**",
        f"- Positional train/serve schema mismatches: **{summary['serving_schema_misaligned_slots']}**",
        f"- Permanent serving data-gap slots: **{summary['always_data_gap_slots']}**",
        "",
    ]
    if isinstance(rows_by_league, Mapping) and rows_by_league:
        lines.extend(["## Candidate rows by league", ""])
        for league in sorted(rows_by_league):
            lines.append(f"- {league}: {rows_by_league[league]}")
        lines.append("")
    lines.extend(
        [
            "This report is derived from the exact `build_dataset()` candidate matrices and a positional candidate-contract → active-serving-contract comparison (the schema live serving actually produces today). A FAIL is evidence, not an error to be thresholded away.",
            "",
        ]
    )
    return "\n".join(lines)
