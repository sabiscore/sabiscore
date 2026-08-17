"""Hash-validated active model generation authority.

The manifest is committed with the complete active artifact set. Loaders may not
silently select a differently named file when a manifested artifact is missing or
modified: that would make promotion non-atomic and rollback unverifiable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ActiveGenerationError(RuntimeError):
    """The committed active generation is absent, malformed, or tampered with."""


DEFAULT_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
MANIFEST_NAME = "active_generation.json"

# certification_state is the single string that switches on value-bet
# computation, Kelly staking, and the public `stake: ENABLED` signal across
# every consumer. Until now the manifest protected the *artifacts* with SHA-256
# while leaving the *verdict* as unvalidated free text, so a one-character edit
# could claim certification that no evaluation ever granted. These two
# constants close that asymmetry: the state must be a known value, and the
# CERTIFIED claim must carry hash-verified evidence that earned it.
UNVERIFIED = "UNVERIFIED"
CERTIFIED = "CERTIFIED"
ALLOWED_CERTIFICATION_STATES = frozenset({UNVERIFIED, CERTIFIED})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file(models_dir: Path, relative_name: object) -> Path:
    if not isinstance(relative_name, str) or not relative_name:
        raise ActiveGenerationError("Active manifest contains an invalid file name")
    candidate = (models_dir / relative_name).resolve()
    try:
        candidate.relative_to(models_dir.resolve())
    except ValueError as exc:
        raise ActiveGenerationError("Active manifest path escapes the models directory") from exc
    if not candidate.is_file():
        raise ActiveGenerationError(f"Active generation file is missing: {relative_name}")
    return candidate


def load_active_generation(models_dir: Path | None = None) -> dict[str, Any]:
    """Load and verify every file in the active generation manifest."""

    root = (models_dir or DEFAULT_MODELS_DIR).resolve()
    manifest_path = root / MANIFEST_NAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActiveGenerationError("Active generation manifest is unavailable or invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ActiveGenerationError("Unsupported active generation manifest schema")
    if not isinstance(payload.get("generation"), str) or not payload["generation"]:
        raise ActiveGenerationError("Active generation identifier is missing")

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ActiveGenerationError("Active generation contains no artifacts")

    verified: dict[str, dict[str, Any]] = {}
    for raw_league, raw_entry in artifacts.items():
        if not isinstance(raw_league, str) or not isinstance(raw_entry, dict):
            raise ActiveGenerationError("Active generation contains a malformed artifact entry")
        league = raw_league.lower()
        artifact = _safe_file(root, raw_entry.get("artifact"))
        metadata = _safe_file(root, raw_entry.get("metadata"))
        artifact_hash = str(raw_entry.get("artifact_sha256") or "").lower()
        metadata_hash = str(raw_entry.get("metadata_sha256") or "").lower()
        if _sha256(artifact) != artifact_hash:
            raise ActiveGenerationError(f"Active artifact hash mismatch for {league}")
        if _sha256(metadata) != metadata_hash:
            raise ActiveGenerationError(f"Active metadata hash mismatch for {league}")
        verified[league] = {
            **raw_entry,
            "artifact_path": artifact,
            "metadata_path": metadata,
        }

    _verify_certification_claim(payload, root)

    return {
        **payload,
        "manifest_path": manifest_path,
        "manifest_sha256": _sha256(manifest_path),
        "artifacts": verified,
    }


def _verify_certification_claim(payload: dict[str, Any], root: Path) -> None:
    """Reject a certification verdict that no evaluation actually granted.

    ``UNVERIFIED`` is the safe default and requires nothing. ``CERTIFIED``
    switches on staking everywhere, so it must be backed by a hash-verified
    promotion report whose own gates all passed. Without this, promotion is a
    one-word text edit — the artifacts are tamper-evident but the verdict about
    them was not.
    """

    state = payload.get("certification_state", UNVERIFIED)
    if state not in ALLOWED_CERTIFICATION_STATES:
        raise ActiveGenerationError(
            f"Unknown certification_state {state!r}; expected one of "
            f"{sorted(ALLOWED_CERTIFICATION_STATES)}"
        )
    if state != CERTIFIED:
        return

    evidence = payload.get("certification_evidence")
    if not isinstance(evidence, dict):
        raise ActiveGenerationError(
            "certification_state is CERTIFIED but no certification_evidence is declared"
        )

    report_path = _safe_file(root, evidence.get("report"))
    expected_hash = str(evidence.get("report_sha256") or "").lower()
    if _sha256(report_path) != expected_hash:
        raise ActiveGenerationError("Certification evidence hash mismatch")

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActiveGenerationError("Certification evidence is unreadable or invalid") from exc

    if not isinstance(report, dict) or report.get("promotion_permitted") is not True:
        raise ActiveGenerationError(
            "Certification evidence does not grant promotion "
            "(promotion_permitted is not true)"
        )

    gates = report.get("gates")
    if not isinstance(gates, dict) or not gates:
        raise ActiveGenerationError("Certification evidence declares no promotion gates")
    failed = sorted(
        name
        for name, gate in gates.items()
        if not isinstance(gate, dict) or gate.get("status") != "PASS"
    )
    if failed:
        raise ActiveGenerationError(
            f"Certification evidence has failing gates: {', '.join(failed)}"
        )


def active_artifact_path(league_slug: str, models_dir: Path | None = None) -> Path | None:
    """Return the verified artifact for a manifested league, if one is active."""

    generation = load_active_generation(models_dir)
    entry = generation["artifacts"].get(league_slug.lower())
    return entry["artifact_path"] if entry else None


def active_generation_is_certified(models_dir: Path | None = None) -> bool:
    try:
        generation = load_active_generation(models_dir)
    except ActiveGenerationError:
        return False
    return generation.get("certification_state") == "CERTIFIED"


def active_model_version(models_dir: Path | None = None) -> str:
    """Return the serving generation's model version (e.g. ``v5_phase7``).

    Deliberately raises instead of returning a permissive default. Callers use
    this to scope accuracy/CLV evidence to a single generation; a ``None``
    fallback would silently restore the cross-generation pooling that scoping
    exists to prevent, and would do so precisely when provenance is least
    trustworthy. No metric is safer than a metric describing two models at once.
    """

    generation = load_active_generation(models_dir)
    version = str(generation.get("active_version") or "").strip()
    if not version:
        raise ActiveGenerationError("Active generation does not declare active_version")
    return version


__all__ = [
    "ActiveGenerationError",
    "active_artifact_path",
    "active_generation_is_certified",
    "active_model_version",
    "load_active_generation",
]
