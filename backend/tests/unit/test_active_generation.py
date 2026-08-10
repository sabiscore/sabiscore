from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.models.active_generation import ActiveGenerationError, load_active_generation


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_generation(root: Path) -> None:
    artifact = b"model-bytes"
    metadata = b'{"feature_count": 68}'
    (root / "epl.pkl").write_bytes(artifact)
    (root / "epl.json").write_bytes(metadata)
    (root / "active_generation.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation": "test-generation",
                "active_version": "test",
                "feature_schema_version": "test-68",
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
        ),
        encoding="utf-8",
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
