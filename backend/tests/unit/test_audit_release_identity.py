"""Regression coverage for scripts/audit_release_identity.py.

docs/DEBT.md item 124 records this script as the audit tool for the release
identity chain (source commit, dataset snapshot, artifact hashes). It has no
prior test coverage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import audit_release_identity as ari  # noqa: E402


def _seed_models_dir(models_dir: Path, *, manifest_relpath: str) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "active_generation.json").write_text(
        json.dumps({"generation": "", "feature_schema_version": "", "artifacts": {}}),
        encoding="utf-8",
    )
    (models_dir / "feature_contract.json").write_text("{}", encoding="utf-8")
    manifest_path = models_dir / manifest_relpath
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"generation_id": None}), encoding="utf-8")


def test_training_manifest_paths_are_posix_style(monkeypatch, tmp_path) -> None:
    """A committed report must not churn between OSes over path separators.

    ``Path.relative_to(...)`` renders native separators under ``str()`` — on
    Windows that means backslashes, which would make a report generated
    locally diff noisily against one generated on Linux CI (where the
    committed report is normally produced). Regression for the fix that
    switched this to ``.as_posix()``.
    """
    repo_root = tmp_path
    models_dir = repo_root / "backend" / "models"
    _seed_models_dir(
        models_dir, manifest_relpath="candidate/sub/training_manifest.json"
    )

    monkeypatch.setattr(ari, "REPO_ROOT", repo_root)
    monkeypatch.setattr(ari, "MODELS_DIR", models_dir)

    report = ari.audit()

    paths = [c["path"] for c in report["training_manifests_found"]]
    assert paths, "expected the seeded training manifest to be discovered"
    assert all("\\" not in p for p in paths), paths
    assert any(p.count("/") >= 2 for p in paths), paths


def test_verdict_is_incomplete_when_no_manifest_binds_the_served_generation(
    monkeypatch, tmp_path
) -> None:
    """source_commit and dataset_snapshot stay UNBOUND with no binding manifest."""
    repo_root = tmp_path
    models_dir = repo_root / "backend" / "models"
    _seed_models_dir(models_dir, manifest_relpath="candidate/training_manifest.json")

    monkeypatch.setattr(ari, "REPO_ROOT", repo_root)
    monkeypatch.setattr(ari, "MODELS_DIR", models_dir)

    report = ari.audit()

    assert report["result"]["verdict"] == "RELEASE_IDENTITY_INCOMPLETE"
    assert "source_commit" in report["result"]["unbound_links"]
    assert "dataset_snapshot" in report["result"]["unbound_links"]


def test_verdict_is_complete_when_a_manifest_binds_the_served_generation(
    monkeypatch, tmp_path
) -> None:
    """A manifest naming the served generation_id binds source_commit/dataset_snapshot."""
    repo_root = tmp_path
    models_dir = repo_root / "backend" / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "active_generation.json").write_text(
        json.dumps(
            {
                "generation": "v99-test",
                "feature_schema_version": "apex_v1_68",
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )
    (models_dir / "feature_contract.json").write_text(
        json.dumps({"feature_schema_version": "apex_v1_68"}), encoding="utf-8"
    )
    manifest_path = models_dir / "candidate" / "training_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "generation_id": "v99-test",
                "git": {"commit": "a" * 40, "dirty": False},
                "dataset": {"dataset_sha256": "b" * 64},
                "features": {"feature_schema_version": "apex_v1_68"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(ari, "REPO_ROOT", repo_root)
    monkeypatch.setattr(ari, "MODELS_DIR", models_dir)

    report = ari.audit()

    assert report["identity_chain"]["source_commit"]["status"] == ari.BOUND
    assert report["identity_chain"]["dataset_snapshot"]["status"] == ari.BOUND
    assert (
        report["binding_training_manifest"]
        == "backend/models/candidate/training_manifest.json"
    )
