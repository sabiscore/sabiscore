from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

import pytest

from src.services.manifest_ingestion import ManifestValidationError, validate_manifest


@pytest.fixture
def workspace_tmp() -> Path:
    root = Path.cwd() / ".pytest_tmp" / "manifest_ingestion" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        resolved = root.resolve()
        workspace_tmp_root = (Path.cwd() / ".pytest_tmp" / "manifest_ingestion").resolve()
        if workspace_tmp_root in resolved.parents or resolved == workspace_tmp_root:
            shutil.rmtree(resolved, ignore_errors=True)


def _write(path: Path, payload: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manifest(data_root: Path, payload: Path, *, status: str = "SUCCESS", hash_value: str | None = None) -> Path:
    manifest_path = data_root / "manifests" / "node-scraper" / "run-node-scraper.manifest.json"
    body = {
        "manifest_version": "1.0",
        "run_id": "run",
        "source_id": "football-data-csv",
        "adapter_version": "1.0.0",
        "schema_version": "1.0.0",
        "started_at": "2026-06-26T10:00:00Z",
        "completed_at": "2026-06-26T10:00:01Z",
        "status": status,
        "record_count": 1,
        "raw_files": [],
        "processed_files": [str(payload)],
        "payload_hashes": {str(payload): hash_value or hashlib.sha256(payload.read_bytes()).hexdigest()},
        "source_timestamp": None,
        "oldest_record_timestamp": None,
        "freshness": "UNKNOWN",
        "errors": [],
        "licence": {"source_policy": "fixture"},
        "attribution": "test",
    }
    _write(manifest_path, json.dumps(body))
    return manifest_path


def test_valid_manifest_accepts_completed_payload(workspace_tmp: Path):
    data_root = workspace_tmp / "data"
    payload = data_root / "processed" / "node-scraper" / "fixtures-test.json"
    _write(payload, json.dumps([{"fixture_id": "fixture-1"}]) + "\n")
    manifest = _manifest(data_root, payload)

    result = validate_manifest(manifest, data_root=data_root)

    assert result.manifest["status"] == "SUCCESS"
    assert result.payload_paths == (payload.resolve(),)


def test_failed_manifest_is_rejected(workspace_tmp: Path):
    data_root = workspace_tmp / "data"
    payload = data_root / "processed" / "node-scraper" / "fixtures-test.json"
    _write(payload, "[]\n")
    manifest = _manifest(data_root, payload, status="FAILED")

    with pytest.raises(ManifestValidationError, match="not ingestible"):
        validate_manifest(manifest, data_root=data_root)


def test_payload_path_traversal_is_rejected(workspace_tmp: Path):
    data_root = workspace_tmp / "data"
    outside = workspace_tmp / "outside.json"
    _write(outside, "[]\n")
    manifest = _manifest(data_root, outside)

    with pytest.raises(ManifestValidationError, match="escapes configured data root"):
        validate_manifest(manifest, data_root=data_root)


def test_payload_hash_mismatch_is_rejected(workspace_tmp: Path):
    data_root = workspace_tmp / "data"
    payload = data_root / "processed" / "node-scraper" / "fixtures-test.json"
    _write(payload, "[]\n")
    manifest = _manifest(data_root, payload, hash_value="bad-hash")

    with pytest.raises(ManifestValidationError, match="hash mismatch"):
        validate_manifest(manifest, data_root=data_root)


def test_manifest_v2_accepts_content_addressed_artifact(workspace_tmp: Path):
    data_root = workspace_tmp / "data"
    payload = data_root / "processed" / "football-data-csv" / "run" / "fixtures.json"
    _write(payload, "[]\n")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest_path = _manifest(data_root, payload)
    body = json.loads(manifest_path.read_text(encoding="utf-8"))
    body.update({
        "manifest_version": "2.0",
        "adapter_version": "2.0.0",
        "schema_version": "2.0.0",
        "registry_version": "2.0.0",
        "attribution": "football-data.co.uk",
        "processed_files": [{
            "file": str(payload),
            "uri": str(payload),
            "object_key": f"processed/football-data-csv/run/{digest}.json",
            "hash": digest,
            "size_bytes": payload.stat().st_size,
            "content_type": "application/json",
        }],
        "payload_hashes": {str(payload): digest},
    })
    manifest_path.write_text(json.dumps(body), encoding="utf-8")

    result = validate_manifest(manifest_path, data_root=data_root)

    assert result.payload_paths == (payload.resolve(),)


def test_manifest_v2_rejects_unsafe_object_key(workspace_tmp: Path):
    data_root = workspace_tmp / "data"
    payload = data_root / "processed" / "fixtures.json"
    _write(payload, "[]\n")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest_path = _manifest(data_root, payload)
    body = json.loads(manifest_path.read_text(encoding="utf-8"))
    body.update({
        "manifest_version": "2.0",
        "adapter_version": "2.0.0",
        "registry_version": "2.0.0",
        "processed_files": [{
            "file": str(payload),
            "uri": str(payload),
            "object_key": "../escape.json",
            "hash": digest,
        }],
    })
    manifest_path.write_text(json.dumps(body), encoding="utf-8")

    with pytest.raises(ManifestValidationError, match="unsafe object_key"):
        validate_manifest(manifest_path, data_root=data_root)
