"""A CERTIFIED claim must be earned, not asserted.

`certification_state` is the one string that switches on value-bet computation,
Kelly staking, and the public `stake: ENABLED` signal across every consumer. The
manifest has always protected the *artifacts* with SHA-256 while leaving the
*verdict about them* as unvalidated free text, so promotion was a one-word edit
away at all times. These tests pin the guard that closes that asymmetry.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.models.active_generation import (
    ActiveGenerationError,
    active_model_version,
    load_active_generation,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    """A minimal but structurally real generation: one artifact + metadata pair."""

    artifact = tmp_path / "epl_ensemble.pkl"
    artifact.write_bytes(b"not-a-real-model-but-hashes-fine")
    metadata = tmp_path / "epl_ensemble_metadata.json"
    metadata.write_text(json.dumps({"feature_count": 68}), encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "generation": "test-gen-20260817",
        "active_version": "v5_phase7",
        "feature_schema_version": "phase7_68",
        "certification_state": "UNVERIFIED",
        "artifacts": {
            "epl": {
                "artifact": artifact.name,
                "artifact_sha256": _sha256(artifact),
                "metadata": metadata.name,
                "metadata_sha256": _sha256(metadata),
                "required": True,
            }
        },
    }
    (tmp_path / "active_generation.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def _rewrite_manifest(models_dir: Path, **changes) -> None:
    path = models_dir / "active_generation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(changes)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_report(models_dir: Path, *, permitted: bool, gates: dict) -> Path:
    report = models_dir / "comparison_report.json"
    report.write_text(
        json.dumps({"promotion_permitted": permitted, "gates": gates}), encoding="utf-8"
    )
    return report


_ALL_PASS = {"market_baseline": {"status": "PASS"}, "no_league_regression": {"status": "PASS"}}


def test_unverified_generation_loads_without_evidence(models_dir: Path) -> None:
    """The safe default stays frictionless — this must not become a deploy blocker."""

    generation = load_active_generation(models_dir)
    assert generation["certification_state"] == "UNVERIFIED"
    assert active_model_version(models_dir) == "v5_phase7"


def test_bare_certified_claim_is_rejected(models_dir: Path) -> None:
    """The exact attack: hand-edit one word, ship staking. Must fail closed."""

    _rewrite_manifest(models_dir, certification_state="CERTIFIED")
    with pytest.raises(ActiveGenerationError, match="no certification_evidence"):
        load_active_generation(models_dir)


def test_unknown_certification_state_is_rejected(models_dir: Path) -> None:
    _rewrite_manifest(models_dir, certification_state="PROBABLY_FINE")
    with pytest.raises(ActiveGenerationError, match="Unknown certification_state"):
        load_active_generation(models_dir)


def test_certified_with_failing_report_is_rejected(models_dir: Path) -> None:
    """Mirrors the real candidate today: promotion_permitted false, 3 gates FAIL."""

    report = _write_report(
        models_dir,
        permitted=False,
        gates={"market_baseline": {"status": "FAIL"}, **_ALL_PASS},
    )
    _rewrite_manifest(
        models_dir,
        certification_state="CERTIFIED",
        certification_evidence={"report": report.name, "report_sha256": _sha256(report)},
    )
    with pytest.raises(ActiveGenerationError, match="does not grant promotion"):
        load_active_generation(models_dir)


def test_certified_with_tampered_report_hash_is_rejected(models_dir: Path) -> None:
    """Evidence must be hash-locked like artifacts, or it can be swapped post-review."""

    report = _write_report(models_dir, permitted=True, gates=_ALL_PASS)
    _rewrite_manifest(
        models_dir,
        certification_state="CERTIFIED",
        certification_evidence={"report": report.name, "report_sha256": _sha256(report)},
    )
    report.write_text(
        json.dumps({"promotion_permitted": True, "gates": _ALL_PASS, "tampered": True}),
        encoding="utf-8",
    )
    with pytest.raises(ActiveGenerationError, match="hash mismatch"):
        load_active_generation(models_dir)


def test_certified_with_permitted_flag_but_failing_gate_is_rejected(models_dir: Path) -> None:
    """Defence in depth: a hand-set promotion_permitted cannot outvote its own gates."""

    report = _write_report(
        models_dir,
        permitted=True,
        gates={"market_baseline": {"status": "FAIL"}, "no_league_regression": {"status": "PASS"}},
    )
    _rewrite_manifest(
        models_dir,
        certification_state="CERTIFIED",
        certification_evidence={"report": report.name, "report_sha256": _sha256(report)},
    )
    with pytest.raises(ActiveGenerationError, match="failing gates: market_baseline"):
        load_active_generation(models_dir)


def test_fully_earned_certification_is_accepted(models_dir: Path) -> None:
    """The guard must not be unpassable — a real promotion still loads."""

    report = _write_report(models_dir, permitted=True, gates=_ALL_PASS)
    _rewrite_manifest(
        models_dir,
        certification_state="CERTIFIED",
        certification_evidence={"report": report.name, "report_sha256": _sha256(report)},
    )
    generation = load_active_generation(models_dir)
    assert generation["certification_state"] == "CERTIFIED"


def test_evidence_cannot_escape_the_models_directory(models_dir: Path, tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside_report.json"
    outside.write_text(json.dumps({"promotion_permitted": True, "gates": _ALL_PASS}), encoding="utf-8")
    _rewrite_manifest(
        models_dir,
        certification_state="CERTIFIED",
        certification_evidence={"report": "../outside_report.json", "report_sha256": _sha256(outside)},
    )
    with pytest.raises(ActiveGenerationError):
        load_active_generation(models_dir)
