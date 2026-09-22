"""
Unit tests for GET /api/v1/models/status.

These tests mock the filesystem so no real artifacts or database are required.
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.endpoints.model_status import router, _feature_count_from_schema
from src.models.active_generation import StakingAuthorization

#: The endpoint reads the manifest twice, deliberately and at two trust levels:
#: `_load_manifest()` is a raw JSON read used for the descriptive fields, while
#: `staking_authorization()` goes through the verifying loader that checks the
#: hash-locked artifacts and the override attribution. In production both read
#: the same file and agree. A test that patches only the first leaves the
#: second reading the real shipped manifest, so it would report whatever
#: staking decision happens to be deployed - exactly the coupling that broke
#: this test when ADR-0011's operator override was activated. Pin both.
_UNCERTIFIED_AUTH = StakingAuthorization(
    permitted=False, basis="NONE", certification_state="UNVERIFIED"
)
_OVERRIDE_AUTH = StakingAuthorization(
    permitted=True,
    basis="OPERATOR_OVERRIDE",
    certification_state="OPERATOR_OVERRIDE_UNCERTIFIED",
    authorizing_identity="test-operator",
    rationale="pinned by test",
    authorized_at="2026-09-19T00:00:00Z",
    acknowledged_failures=("market_baseline",),
)


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
    with (
        patch(
            "src.api.endpoints.model_status._load_manifest",
            return_value=(
                _SAMPLE_MANIFEST,
                "abc123hash",
            ),
        ),
        patch(
            "src.api.endpoints.model_status.staking_authorization",
            return_value=_UNCERTIFIED_AUTH,
        ),
    ):
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
    assert data["staking_basis"] == "NONE"
    assert "epl" in data["models"]
    assert "bundesliga" in data["models"]


def test_operator_override_is_reported_as_staking_but_never_as_validation(client):
    """ADR-0011: an override permits staking; it is not certification.

    `stake_permitted` must track the authorization the serving path uses, or
    this endpoint reports a system that is actively staking as one that is not.
    `validation_status` must NOT follow it - only CERTIFIED earns "VALIDATED".
    """
    override_manifest = dict(
        _SAMPLE_MANIFEST, certification_state="OPERATOR_OVERRIDE_UNCERTIFIED"
    )
    with (
        patch(
            "src.api.endpoints.model_status._load_manifest",
            return_value=(
                override_manifest,
                "abc123hash",
            ),
        ),
        patch(
            "src.api.endpoints.model_status.staking_authorization",
            return_value=_OVERRIDE_AUTH,
        ),
    ):
        resp = client.get("/api/v1/models/status")

    data = resp.json()
    assert data["certification_state"] == "OPERATOR_OVERRIDE_UNCERTIFIED"
    assert data["stake_permitted"] is True
    assert data["staking_basis"] == "OPERATOR_OVERRIDE"
    assert data["validation_status"] == "UNVERIFIED"
    # The attribution travels with the disclosure - an override nobody can
    # attribute is indistinguishable from one taken in ignorance.
    assert data["staking_authorization"]["authorizing_identity"] == "test-operator"
    assert data["staking_authorization"]["acknowledged_failures"] == ["market_baseline"]


def test_model_records_have_required_shape(client):
    with patch(
        "src.api.endpoints.model_status._load_manifest",
        return_value=(
            _SAMPLE_MANIFEST,
            "somehash",
        ),
    ):
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
    with patch(
        "src.api.endpoints.model_status._load_manifest", return_value=(None, None)
    ):
        resp = client.get("/api/v1/models/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["certification_state"] == "UNVERIFIED"
    assert data["validation_status"] == "UNVERIFIED"
    assert data["manifest_valid"] is False
    assert data["stake_permitted"] is False
    assert data["models"] == {}
    assert data["active_version"] is None


@pytest.mark.parametrize(
    "schema,expected",
    [
        ("phase7_68", 68),
        ("v6_phase8_86", 86),
        ("unknown", None),
        (None, None),
        ("", None),
    ],
)
def test_feature_count_parsing(schema, expected):
    assert _feature_count_from_schema(schema) == expected
