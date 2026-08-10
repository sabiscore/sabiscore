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

    return {
        **payload,
        "manifest_path": manifest_path,
        "manifest_sha256": _sha256(manifest_path),
        "artifacts": verified,
    }


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


__all__ = [
    "ActiveGenerationError",
    "active_artifact_path",
    "active_generation_is_certified",
    "load_active_generation",
]
