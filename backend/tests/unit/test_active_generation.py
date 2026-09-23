from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from src.models.active_generation import (
    ActiveGenerationError,
    load_active_generation,
    verify_feature_contract_freshness,
)
from src.models.feature_registry import build_feature_contract


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Sentinel rather than None: the absent-field case is a distinct rejection path
# from an explicitly-null one, and both must fail closed.
_OMIT = object()


def _write_generation(
    root: Path,
    *,
    feature_schema_version: object = "phase7_68",
    metadata_body: bytes = b'{"feature_count": 68}',
    feature_contract: object = _OMIT,
) -> None:
    artifact = b"model-bytes"
    metadata = metadata_body
    (root / "epl.pkl").write_bytes(artifact)
    (root / "epl.json").write_bytes(metadata)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "generation": "test-generation",
        "active_version": "test",
        "served_head": "test-head",
        "certification_state": "UNVERIFIED",
        "promotion_state": "ACTIVE_FAIL_CLOSED",
        "artifacts": {
            "epl": {
                "artifact": "epl.pkl",
                "artifact_sha256": _hash(artifact),
                "metadata": "epl.json",
                "metadata_sha256": _hash(metadata),
                "required": True,
            }
        },
    }
    if feature_schema_version is not _OMIT:
        manifest["feature_schema_version"] = feature_schema_version
    (root / "active_generation.json").write_text(json.dumps(manifest), encoding="utf-8")

    if feature_contract is not _OMIT:
        (root / "feature_contract.json").write_text(
            json.dumps(feature_contract), encoding="utf-8"
        )


def test_active_generation_verifies_hashes(tmp_path: Path) -> None:
    _write_generation(tmp_path)

    result = load_active_generation(tmp_path)

    assert result["generation"] == "test-generation"
    assert result["artifacts"]["epl"]["artifact_path"] == tmp_path / "epl.pkl"
    assert len(result["manifest_sha256"]) == 64


def test_active_generation_rejects_tampered_artifact(tmp_path: Path) -> None:
    _write_generation(tmp_path)
    (tmp_path / "epl.pkl").write_bytes(b"tampered")

    with pytest.raises(ActiveGenerationError, match="hash mismatch"):
        load_active_generation(tmp_path)


# ── Feature-contract identity ────────────────────────────────────────────────
# The artifacts are tamper-evident, but `feature_schema_version` used to be
# unvalidated free text that six public consumers republish as provenance.
# prediction.py answers a width mismatch with a fallback result rather than
# raising, so a relabel degrades every prediction silently. These pin the gate.


@pytest.mark.parametrize("declared", ["test-68", "phase7_99", "", "   "])
def test_rejects_unknown_feature_schema_version(tmp_path: Path, declared: str) -> None:
    _write_generation(tmp_path, feature_schema_version=declared)

    with pytest.raises(ActiveGenerationError, match="feature_schema_version"):
        load_active_generation(tmp_path)


def test_rejects_absent_feature_schema_version(tmp_path: Path) -> None:
    _write_generation(tmp_path, feature_schema_version=_OMIT)

    with pytest.raises(ActiveGenerationError, match="feature_schema_version"):
        load_active_generation(tmp_path)


def test_rejects_null_feature_schema_version(tmp_path: Path) -> None:
    _write_generation(tmp_path, feature_schema_version=None)

    with pytest.raises(ActiveGenerationError, match="feature_schema_version"):
        load_active_generation(tmp_path)


def test_rejects_schema_relabelled_over_narrower_artifacts(tmp_path: Path) -> None:
    """The exact silent-degradation case: claim 89 features over 68-wide artifacts."""

    _write_generation(tmp_path, feature_schema_version="phase8_89")

    with pytest.raises(ActiveGenerationError, match="Feature contract mismatch"):
        load_active_generation(tmp_path)


@pytest.mark.parametrize(
    "body",
    [
        b"{}",  # no feature_count at all
        b'{"feature_count": "68"}',  # string, not int
        b'{"feature_count": true}',  # bool is an int subclass — must not pass
        b'{"feature_count": null}',
    ],
)
def test_rejects_metadata_without_a_usable_feature_count(
    tmp_path: Path, body: bytes
) -> None:
    _write_generation(tmp_path, metadata_body=body)

    with pytest.raises(ActiveGenerationError, match="feature_count"):
        load_active_generation(tmp_path)


def test_rejects_same_width_schema_relabel(tmp_path: Path) -> None:
    """The live 2026-09-23 defect: phase7_68 declared over apex_v1_68 artifacts.

    Both schemas are 68 wide, so the width check alone passes — but they
    disagree in 11 market slots (20-30), and serving builds whichever block the
    manifest names. The artifact's hash-verified metadata records the schema it
    was trained on, so a disagreement is detectable without loading a pickle.
    """

    _write_generation(
        tmp_path,
        feature_schema_version="phase7_68",
        metadata_body=b'{"feature_count": 68, "feature_schema_version": "apex_v1_68"}',
    )

    with pytest.raises(ActiveGenerationError, match="apex_v1_68"):
        load_active_generation(tmp_path)


def test_accepts_matching_declared_training_schema(tmp_path: Path) -> None:
    _write_generation(
        tmp_path,
        feature_schema_version="apex_v1_68",
        metadata_body=b'{"feature_count": 68, "feature_schema_version": "apex_v1_68"}',
    )

    assert load_active_generation(tmp_path)["feature_schema_version"] == "apex_v1_68"


def test_metadata_without_a_training_schema_still_loads_on_width(tmp_path: Path) -> None:
    """Older artifacts never recorded their schema; width stays the only check."""

    _write_generation(tmp_path, metadata_body=b'{"feature_count": 68}')

    assert load_active_generation(tmp_path)["feature_schema_version"] == "phase7_68"


def test_accepts_a_coherent_phase8_generation(tmp_path: Path) -> None:
    """The gate checks agreement, not a hardcoded 68 — 89 over 89 must load."""

    _write_generation(
        tmp_path,
        feature_schema_version="phase8_89",
        metadata_body=b'{"feature_count": 89}',
    )

    result = load_active_generation(tmp_path)

    assert result["feature_schema_version"] == "phase8_89"


def test_committed_manifest_satisfies_its_own_declared_contract() -> None:
    """The real shipped manifest must pass the gate that guards the deploy.

    verify_active_artifacts.py runs load_active_generation() in Render's
    buildCommand, so a mismatch here fails the build rather than production.
    """

    # No schema literal: this used to pin "phase7_68", which certified the
    # manifest/artifact mismatch in docs/DEBT.md item 141. The loader itself now
    # requires the declared schema to match each artifact's training record.
    result = load_active_generation()

    assert result["artifacts"], "committed manifest declares no artifacts"


# ── Feature-contract freshness (docs/DEBT.md item 36) ────────────────────────
# The three-artifact drift this item describes happened because a producer
# changed shape and nobody regenerated (or deleted) its stale consumers. These
# pin the guard that prevents backend/models/feature_contract.json from rotting
# the same way.
#
# Deliberately a build-time gate, NOT part of load_active_generation: that
# function runs at startup and on the staking path, so a stale derived doc
# must never be able to make the API unbootable. See the function's docstring.


def test_freshness_check_rejects_a_missing_contract(tmp_path: Path) -> None:
    _write_generation(tmp_path, feature_contract=_OMIT)

    with pytest.raises(ActiveGenerationError, match="feature_contract.json is missing"):
        verify_feature_contract_freshness(tmp_path)


def test_freshness_check_rejects_a_stale_contract(tmp_path: Path) -> None:
    """A hand-edited or un-regenerated contract must fail the build, not pass silently."""

    _write_generation(
        tmp_path,
        feature_contract={
            "schema": "sabiscore_feature_contract_v1",
            "feature_count": 0,
            "features": [],
        },
    )

    with pytest.raises(ActiveGenerationError, match="feature_contract.json is stale"):
        verify_feature_contract_freshness(tmp_path)


def test_freshness_check_accepts_a_freshly_generated_contract(tmp_path: Path) -> None:
    _write_generation(tmp_path, feature_contract=build_feature_contract("phase7_68"))

    verify_feature_contract_freshness(tmp_path)  # must not raise


def test_a_missing_contract_does_not_block_loading_the_generation(
    tmp_path: Path,
) -> None:
    """The startup/staking path must stay independent of the derived doc.

    This is the guard against re-coupling them: a generation with no
    feature_contract.json at all still loads, so a regeneration someone forgot
    can fail the deploy without being able to crash-loop a running service.
    """

    _write_generation(tmp_path, feature_contract=_OMIT)

    assert load_active_generation(tmp_path)["feature_schema_version"] == "phase7_68"


# ── Operator override (ADR-0011) ─────────────────────────────────────────────
#
# The override exists so "ship despite failing gates" has an honest
# representation. These tests pin the two properties that make it honest:
# it must be attributable (no anonymous state flip), and it must never be
# mistakable for a certification.


def _valid_override() -> dict[str, object]:
    return {
        "authorizing_identity": "ops@example.com",
        "rationale": "Accepting 0/6 market baseline for a limited beta.",
        "authorized_at": "2026-09-19T00:00:00Z",
        "acknowledged_failures": ["market_baseline", "error_association"],
    }


def _write_override_generation(root: Path, override: object = _OMIT) -> None:
    _write_generation(root)
    path = root / "active_generation.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["certification_state"] = "OPERATOR_OVERRIDE_UNCERTIFIED"
    if override is not _OMIT:
        manifest["operator_override"] = override
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_override_permits_staking_but_is_never_certified(tmp_path: Path) -> None:
    """The whole point: staking on, certification claim still off."""
    from src.models.active_generation import (
        active_generation_is_certified,
        staking_authorization,
    )

    _write_override_generation(tmp_path, _valid_override())

    auth = staking_authorization(tmp_path)
    assert auth.permitted is True
    assert auth.basis == "OPERATOR_OVERRIDE"
    assert auth.is_override is True
    assert auth.certification_state == "OPERATOR_OVERRIDE_UNCERTIFIED"
    # The load-bearing assertion. If this ever returns True, an override has
    # laundered itself into a certification claim.
    assert active_generation_is_certified(tmp_path) is False


def test_override_carries_the_disclosure_to_its_consumers(tmp_path: Path) -> None:
    from src.models.active_generation import staking_authorization

    _write_override_generation(tmp_path, _valid_override())
    payload = staking_authorization(tmp_path).as_dict()

    assert payload["authorizing_identity"] == "ops@example.com"
    assert "limited beta" in payload["rationale"]
    assert payload["acknowledged_failures"] == ["market_baseline", "error_association"]


def test_override_without_a_block_is_rejected(tmp_path: Path) -> None:
    _write_override_generation(tmp_path, _OMIT)

    with pytest.raises(ActiveGenerationError, match="no operator_override block"):
        load_active_generation(tmp_path)


@pytest.mark.parametrize(
    "field",
    ["authorizing_identity", "rationale", "authorized_at", "acknowledged_failures"],
)
def test_override_missing_any_required_field_is_rejected(
    tmp_path: Path, field: str
) -> None:
    """An override that does not say who, why, when, or what-was-overridden is
    indistinguishable from one taken in ignorance."""
    override = _valid_override()
    del override[field]
    _write_override_generation(tmp_path, override)

    with pytest.raises(ActiveGenerationError, match="missing required field"):
        load_active_generation(tmp_path)


def test_override_with_empty_acknowledged_failures_is_rejected(tmp_path: Path) -> None:
    override = _valid_override()
    override["acknowledged_failures"] = []
    _write_override_generation(tmp_path, override)

    with pytest.raises(ActiveGenerationError, match="missing required field"):
        load_active_generation(tmp_path)


def test_override_with_blank_rationale_is_rejected(tmp_path: Path) -> None:
    override = _valid_override()
    override["rationale"] = "   "
    _write_override_generation(tmp_path, override)

    with pytest.raises(ActiveGenerationError, match="non-empty string"):
        load_active_generation(tmp_path)


def test_unknown_certification_state_still_fails_closed(tmp_path: Path) -> None:
    """Adding a third valid state must not turn the allowlist into a passthrough."""
    _write_generation(tmp_path)
    path = tmp_path / "active_generation.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["certification_state"] = "DEFINITELY_CERTIFIED_TRUST_ME"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ActiveGenerationError, match="Unknown certification_state"):
        load_active_generation(tmp_path)


def test_unverified_generation_permits_no_staking(tmp_path: Path) -> None:
    from src.models.active_generation import staking_authorization

    _write_generation(tmp_path)
    auth = staking_authorization(tmp_path)

    assert auth.permitted is False
    assert auth.basis == "NONE"
    assert auth.is_override is False


def test_build_gate_script_loads_this_module_standalone(tmp_path: Path) -> None:
    """`scripts/verify_active_artifacts.py` is the Render buildCommand gate and
    loads `active_generation.py` via `spec_from_file_location`, deliberately
    avoiding the app import chain (which opens a DB connection at module
    scope). That load path is NOT exercised by importing this module normally,
    so a construct that works in the app can still break the deploy.

    It happened: adding `@dataclass` here raised
    ``AttributeError: 'NoneType' object has no attribute '__dict__'`` inside
    `dataclasses._is_type`, because the module was absent from `sys.modules`
    while its own top level ran. Every unit test still passed; only running the
    gate script caught it.

    Running the real script as a subprocess is the only honest coverage —
    re-implementing its loader here would test the copy, not the gate.
    """
    import subprocess
    import sys as _sys

    backend_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [_sys.executable, "scripts/verify_active_artifacts.py"],
        cwd=backend_root,
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "PYTHONPATH": "."},
    )

    assert result.returncode == 0, (
        "the Render build gate failed to load active_generation.py standalone:\n"
        f"{result.stdout}\n{result.stderr}"
    )
