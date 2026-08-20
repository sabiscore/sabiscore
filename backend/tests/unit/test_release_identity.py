"""Regression coverage for build/runtime release-SHA truthfulness."""
from __future__ import annotations

import json

import pytest

from src.core import release_identity


def _sha(char: str) -> str:
    return char * 40


def test_build_manifest_records_matching_checkout_and_render_sha(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    commit = _sha("a")
    manifest_path = tmp_path / "release_identity.json"
    monkeypatch.setenv("SABISCORE_RELEASE_IDENTITY_PATH", str(manifest_path))
    monkeypatch.setenv("RENDER_GIT_COMMIT", commit.upper())
    monkeypatch.setattr(release_identity, "_checkout_sha", lambda: commit)

    payload = release_identity.write_release_identity_manifest(strict=True)

    assert payload is not None
    assert payload["release_sha"] == commit
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted["release_sha"] == commit
    assert persisted["checkout_sha"] == commit
    assert persisted["render_git_commit"] == commit


def test_build_manifest_rejects_checkout_render_disagreement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "SABISCORE_RELEASE_IDENTITY_PATH", str(tmp_path / "release_identity.json")
    )
    monkeypatch.setenv("RENDER_GIT_COMMIT", _sha("b"))
    monkeypatch.setattr(release_identity, "_checkout_sha", lambda: _sha("c"))

    with pytest.raises(RuntimeError, match="release identity conflict"):
        release_identity.write_release_identity_manifest(strict=True)


def test_strict_build_requires_exact_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "SABISCORE_RELEASE_IDENTITY_PATH", str(tmp_path / "release_identity.json")
    )
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.setattr(release_identity, "_checkout_sha", lambda: None)

    with pytest.raises(RuntimeError, match="unable to prove an exact release SHA"):
        release_identity.write_release_identity_manifest(strict=True)


def test_runtime_uses_build_manifest_when_render_metadata_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    commit = _sha("d")
    manifest_path = tmp_path / "release_identity.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "release_sha": commit,
                "checkout_sha": commit,
                "render_git_commit": commit,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SABISCORE_RELEASE_IDENTITY_PATH", str(manifest_path))
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.setenv("SABISCORE_RELEASE_SHA", _sha("e"))

    identity = release_identity.resolve_release_identity()

    assert identity["release_sha"] == commit
    assert identity["source"] == "BUILD_MANIFEST"
    assert identity["fallback_conflict"] is True
    assert identity["metadata_conflict"] is False


def test_runtime_render_manifest_conflict_is_unverified(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    manifest_sha = _sha("f")
    runtime_sha = _sha("1")
    manifest_path = tmp_path / "release_identity.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "release_sha": manifest_sha,
                "checkout_sha": manifest_sha,
                "render_git_commit": manifest_sha,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SABISCORE_RELEASE_IDENTITY_PATH", str(manifest_path))
    monkeypatch.setenv("RENDER_GIT_COMMIT", runtime_sha)
    monkeypatch.delenv("SABISCORE_RELEASE_SHA", raising=False)

    identity = release_identity.resolve_release_identity()

    assert identity["release_sha"] is None
    assert identity["source"] == "CONFLICT"
    assert identity["metadata_conflict"] is True
    assert identity["runtime_render_sha"] == runtime_sha
    assert identity["build_manifest_sha"] == manifest_sha
