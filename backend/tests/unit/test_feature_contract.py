"""The machine-readable feature contract (docs/DEBT.md item 36).

The debt item this closes is specifically about *fabrication*: three prior
artifacts described the contract in three incompatible shapes, and most of the
metadata the directive's §7.1 asks for exists nowhere in real code. These tests
therefore guard the honesty of the generator as hard as its correctness — a
future contributor "helpfully" filling in `unit` or `lookahead_risk` without a
real source must fail a test, not ship.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.feature_registry import (
    DEFAULT_FEATURE_VALUES_68,
    DEFAULT_FEATURE_VALUES_89,
    FEATURE_SCHEMA_VERSIONS,
    PHASE7_FEATURES_ALWAYS_DATA_GAP,
    UNDECLARED,
    UnknownFeatureSchemaError,
    _DEFAULT_VALUE_SOURCES,
    _UNDECLARED_FIELDS,
    build_feature_contract,
    contract_sha256,
    resolve_feature_schema,
)

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


@pytest.mark.parametrize("schema_version", sorted(FEATURE_SCHEMA_VERSIONS))
def test_contract_matches_its_declared_schema(schema_version: str) -> None:
    contract = build_feature_contract(schema_version)
    expected = resolve_feature_schema(schema_version)

    assert contract["feature_schema_version"] == schema_version
    assert contract["feature_count"] == len(expected)
    # Order is load-bearing: inference indexes positionally into the artifact.
    assert [f["feature_name"] for f in contract["features"]] == list(expected)
    assert [f["index"] for f in contract["features"]] == list(range(len(expected)))


def test_default_value_sources_cover_every_registered_schema() -> None:
    """Every schema needs a wired default-value source.

    Without this, adding a schema to FEATURE_SCHEMA_VERSIONS and forgetting
    _DEFAULT_VALUE_SOURCES reports every feature as having no default — and so
    an UNDECLARED disposition — purely because of the missing wiring, not
    because anything about the features is genuinely unknown.
    """

    assert set(_DEFAULT_VALUE_SOURCES) == set(FEATURE_SCHEMA_VERSIONS)


@pytest.mark.parametrize("bad", ["", "   ", "phase7_99", None, 68])
def test_rejects_unknown_schema_version(bad: object) -> None:
    with pytest.raises(UnknownFeatureSchemaError):
        build_feature_contract(bad)


def test_is_deterministic() -> None:
    """Same input, byte-identical output — the freshness gate depends on it."""

    first = build_feature_contract("phase7_68")
    second = build_feature_contract("phase7_68")

    assert first == second
    assert first["feature_contract_sha256"] == second["feature_contract_sha256"]


def test_hash_covers_more_than_the_name_list() -> None:
    """Unlike promotion_evidence._contract_hash, this must react to metadata.

    A hash over names alone cannot detect a changed default, disposition, or
    dtype — which is exactly the drift item 36 describes. Mutating one field
    of one record must change the digest.
    """

    records = build_feature_contract("phase7_68")["features"]
    mutated = [dict(record) for record in records]
    mutated[0]["default_value"] = 999.0

    assert contract_sha256(records) != contract_sha256(mutated)


# ── Disposition rule ─────────────────────────────────────────────────────────
# One explicit rule, not per-feature judgement. Anything the rule cannot
# decide stays UNDECLARED rather than being guessed into a category.


def test_always_data_gap_features_defer_until_data_exists() -> None:
    contract = build_feature_contract("phase7_68")
    by_name = {f["feature_name"]: f for f in contract["features"]}

    assert PHASE7_FEATURES_ALWAYS_DATA_GAP, "fixture assumption: the gap list is non-empty"
    for name in PHASE7_FEATURES_ALWAYS_DATA_GAP:
        assert by_name[name]["always_data_gap"] is True
        assert by_name[name]["disposition"] == "DEFER_UNTIL_DATA_EXISTS"


def test_defaulted_non_gap_features_are_aligned_observed() -> None:
    contract = build_feature_contract("phase7_68")

    for record in contract["features"]:
        name = record["feature_name"]
        if name in PHASE7_FEATURES_ALWAYS_DATA_GAP:
            continue
        if DEFAULT_FEATURE_VALUES_68.get(name) is None:
            continue
        assert record["disposition"] == "ALIGNED_OBSERVED", name


def test_features_without_a_registered_default_stay_undeclared() -> None:
    """The Apex market block has no entries in DEFAULT_FEATURE_VALUES_68.

    That is a real, currently-unanswerable question about those slots — the
    contract must say so rather than inventing a disposition for them.
    """

    contract = build_feature_contract("apex_v1_68")
    undeclared = [
        f["feature_name"] for f in contract["features"] if f["disposition"] == UNDECLARED
    ]

    assert undeclared, "expected the Apex market block to be genuinely undeclared"
    for name in undeclared:
        assert DEFAULT_FEATURE_VALUES_68.get(name) is None
        assert name not in PHASE7_FEATURES_ALWAYS_DATA_GAP


def test_phase8_defaults_resolve_under_the_89_schema() -> None:
    """phase8_89 must read DEFAULT_FEATURE_VALUES_89, not the 68 dict."""

    contract = build_feature_contract("phase8_89")
    by_name = {f["feature_name"]: f for f in contract["features"]}

    assert by_name["home_berrar_rating"]["default_value"] == (
        DEFAULT_FEATURE_VALUES_89["home_berrar_rating"]
    )
    assert by_name["match_importance_score"]["disposition"] == "ALIGNED_OBSERVED"


# ── Anti-fabrication ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("schema_version", sorted(FEATURE_SCHEMA_VERSIONS))
def test_unanswerable_fields_are_literally_undeclared(schema_version: str) -> None:
    """Nothing in this repo can answer these fields today.

    DEBT.md item 36 is explicit that inventing plausible values for
    lookahead_risk / availability_time / unit would be fabrication on the exact
    surface Phase 3 exists to make trustworthy. If a real derivation for one of
    these lands later, delete it from _UNDECLARED_FIELDS in the same change —
    do not weaken this assertion to accommodate a hand-written value.
    """

    contract = build_feature_contract(schema_version)

    assert _UNDECLARED_FIELDS, "fixture assumption: the undeclared field list is non-empty"
    for record in contract["features"]:
        for field in _UNDECLARED_FIELDS:
            assert record[field] == UNDECLARED, f"{record['feature_name']}.{field}"


def test_league_scope_is_derived_not_guessed() -> None:
    """Only the one-hot columns are league-scoped; everything else is ALL."""

    contract = build_feature_contract("phase7_68")
    scoped = {
        f["feature_name"]: f["league_scope"]
        for f in contract["features"]
        if f["league_scope"] != "ALL"
    }

    assert scoped == {
        "league_Bundesliga": "Bundesliga",
        "league_EPL": "EPL",
        "league_La_Liga": "La_Liga",
        "league_Ligue_1": "Ligue_1",
        "league_Serie_A": "Serie_A",
    }


def test_committed_contract_matches_a_fresh_rebuild() -> None:
    """backend/models/feature_contract.json must not rot.

    The same idiom as test_committed_manifest_satisfies_its_own_declared_contract:
    the checked-in artifact is verified against the real generator, so this file
    cannot drift from its producer the way the two artifacts item 36 describes
    did. Regenerate with scripts/generate_feature_contract.py.
    """

    manifest = json.loads(
        (MODELS_DIR / "active_generation.json").read_text(encoding="utf-8")
    )
    committed = json.loads(
        (MODELS_DIR / "feature_contract.json").read_text(encoding="utf-8")
    )

    assert committed == build_feature_contract(manifest["feature_schema_version"])
