"""Fail-closed release identity for production parity verification.

Render exposes ``RENDER_GIT_COMMIT`` at runtime, but SabiScore also persists the
checked-out Git revision during the build.  The build manifest provides an
independent immutable identity source when runtime metadata is unavailable and
lets the API report ``UNVERIFIED`` rather than trusting conflicting metadata.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MANIFEST_PATH = _BACKEND_ROOT / ".cache" / "release_identity.json"
_MANIFEST_SCHEMA_VERSION = 1


def _validated_sha(value: object) -> str | None:
    candidate = str(value).strip() if value is not None else ""
    return candidate.lower() if _GIT_SHA_RE.fullmatch(candidate) else None


def _manifest_path() -> Path:
    override = os.getenv("SABISCORE_RELEASE_IDENTITY_PATH")
    return Path(override) if override else _DEFAULT_MANIFEST_PATH


def _checkout_sha() -> str | None:
    """Return the exact checked-out Git SHA when repository metadata is present."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_BACKEND_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _validated_sha(result.stdout)


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def write_release_identity_manifest(*, strict: bool = False) -> dict[str, Any] | None:
    """Persist build-time Git identity and fail if authoritative sources disagree.

    ``strict`` is enabled on Render builds.  A production build is not allowed to
    proceed when neither the checked-out repository nor Render metadata can prove
    an exact SHA, or when they disagree.
    """
    checkout_sha = _checkout_sha()
    render_sha = _validated_sha(os.getenv("RENDER_GIT_COMMIT"))

    if checkout_sha and render_sha and checkout_sha != render_sha:
        raise RuntimeError(
            "release identity conflict during build: "
            f"checkout={checkout_sha} render={render_sha}"
        )

    release_sha = checkout_sha or render_sha
    if release_sha is None:
        if strict:
            raise RuntimeError("unable to prove an exact release SHA during production build")
        return None

    payload: dict[str, Any] = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "release_sha": release_sha,
        "checkout_sha": checkout_sha,
        "render_git_commit": render_sha,
    }
    _write_atomic(
        _manifest_path(),
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return payload


def load_release_identity_manifest() -> dict[str, Any] | None:
    path = _manifest_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
        return None
    release_sha = _validated_sha(payload.get("release_sha"))
    if release_sha is None:
        return None
    return {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "release_sha": release_sha,
        "checkout_sha": _validated_sha(payload.get("checkout_sha")),
        "render_git_commit": _validated_sha(payload.get("render_git_commit")),
    }


def resolve_release_identity() -> dict[str, Any]:
    """Resolve runtime identity without upgrading disagreement to a false PASS."""
    runtime_render_sha = _validated_sha(os.getenv("RENDER_GIT_COMMIT"))
    fallback_sha = _validated_sha(os.getenv("SABISCORE_RELEASE_SHA"))
    manifest = load_release_identity_manifest()
    manifest_sha = manifest["release_sha"] if manifest else None

    conflict = bool(
        runtime_render_sha
        and manifest_sha
        and runtime_render_sha != manifest_sha
    )

    if conflict:
        release_sha = None
        source = "CONFLICT"
    elif runtime_render_sha:
        release_sha = runtime_render_sha
        source = "RENDER_RUNTIME"
    elif manifest_sha:
        release_sha = manifest_sha
        source = "BUILD_MANIFEST"
    elif fallback_sha:
        release_sha = fallback_sha
        source = "EXPLICIT_FALLBACK"
    else:
        release_sha = None
        source = "UNVERIFIED"

    fallback_conflict = bool(
        fallback_sha and release_sha and fallback_sha != release_sha
    )
    return {
        "release_sha": release_sha,
        "source": source,
        "runtime_render_sha": runtime_render_sha,
        "build_manifest_sha": manifest_sha,
        "fallback_sha": fallback_sha,
        "metadata_conflict": conflict,
        "fallback_conflict": fallback_conflict,
    }


def release_sha() -> str | None:
    return resolve_release_identity()["release_sha"]


__all__ = [
    "load_release_identity_manifest",
    "release_sha",
    "resolve_release_identity",
    "write_release_identity_manifest",
]
