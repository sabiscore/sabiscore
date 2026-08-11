"""
Unit tests for GET /api/v1/models/status.

These tests mock the filesystem so no real artifacts or database are required.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.endpoints.model_status import router, _feature_count_from_schema


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


_SAMPLE_MANIFEST = {
    "schema_version": 1,
    "generation": "v5_phase7-20260808",
    "active_version": "v5_phase7",
    "feature_schema_version": "phase7_68",
    "served_head": "SoftmaxMetaModel",
    "certification_state": "UNVERIFIED",
    "certified_at": None,
    "promotion_state": "ACTIVE_FAIL_CLOSED",
    "promoted_at": None,
    "artifacts": {
        "epl": {
            "artifact": "epl_ensemble_v5_phase7.pkl",
            "artifact_sha256": "abc123",
            "required": True,
        },
        "bundesliga": {
            "artifact": "bundesliga_ensemble_v5_phase7.pkl",
            "artifact_sha256": "def456",
            "required": True,
        },
    },
}


def test_returns_manifest_fields(client):
    raw = json.dumps(_SAMPLE_MANIFEST)
    with patch("src.api.endpoints.model_status._load_manifest", return_value=(
        _SAMPLE_MANIFEST,
        "abc123hash",
    )):
        resp = client.get("/api/v1/models/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["active_version"] == "v5_phase7"
    assert data["generation"] == "v5_phase7-20260808"
    assert data["generation_hash"] == "abc123hash"
    assert data["certification_state"] == "UNVERIFIED"
    assert data["promotion_state"] == "ACTIVE_FAIL_CLOSED"
    assert data["validation_status"] == "UNVERIFIED"
    assert data["manifest_valid"] is True
    assert data["stake_permitted"] is False
    assert "epl" in data["models"]
    assert "bundesliga" in data["models"]


def test_model_records_have_required_shape(client):
    with patch("src.api.endpoints.model_status._load_manifest", return_value=(
        _SAMPLE_MANIFEST,
        "somehash",
    )):
        resp = client.get("/api/v1/models/status")

    models = resp.json()["models"]
    for record in models.values():
        assert "feature_schema_version" in record
        assert "feature_count" in record
        assert "served_head" in record
        assert "artifact_sha256" in record
        assert record["feature_count"] == 68
        assert record["served_head"] == "SoftmaxMetaModel"


def test_graceful_degradation_when_manifest_absent(client):
    with patch("src.api.endpoints.model_status._load_manifest", return_value=(None, None)):
        resp = client.get("/api/v1/models/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["certification_state"] == "UNVERIFIED"
    assert data["validation_status"] == "UNVERIFIED"
    assert data["manifest_valid"] is False
    assert data["stake_permitted"] is False
    assert data["models"] == {}
    assert data["active_version"] is None


@pytest.mark.parametrize("schema,expected", [
    ("phase7_68", 68),
    ("v6_phase8_86", 86),
    ("unknown", None),
    (None, None),
    ("", None),
])
def test_feature_count_parsing(schema, expected):
    assert _feature_count_from_schema(schema) == expected
