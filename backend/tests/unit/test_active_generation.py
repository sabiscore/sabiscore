from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.models.active_generation import ActiveGenerationError, load_active_generation


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
def test_rejects_metadata_without_a_usable_feature_count(tmp_path: Path, body: bytes) -> None:
    _write_generation(tmp_path, metadata_body=body)

    with pytest.raises(ActiveGenerationError, match="feature_count"):
        load_active_generation(tmp_path)


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

    result = load_active_generation()

    assert result["feature_schema_version"] == "phase7_68"
    assert result["artifacts"], "committed manifest declares no artifacts"
