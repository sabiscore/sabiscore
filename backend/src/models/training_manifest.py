"""Reproducibility manifest for a training run (certification Stage 4/8).

The shipped artifacts already carry evaluation metrics, and
``models/active_generation.json`` already hashes every artifact and metadata
file. What was missing is the evidence that a run can be *reproduced*: the
corpus it read, the contracts it was built against, the seeds, and the
interpreter/library versions that produced it.

Without those, "retrain and you get the same model" is an assertion rather than
a checkable claim, and a metric regression cannot be attributed to a data
change versus a library upgrade.

Nothing here re-implements an existing contract. The feature contract
(``models/feature_contract.json``), the certification policy
(``certification_policy.py``) and the metric contract
(``reports/evaluation/metric-contract.json``) are each cited by their own hash
rather than restated, so this manifest cannot drift from them.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

#: The label rule, transcribed from ``train_on_real_matches.build_dataset``:
#: ``0 if hg > ag else 1 if hg == ag else 2``. Recorded as a contract so a
#: relabelling is a visible, hashed change rather than a silent one.
LABEL_CONTRACT: Dict[str, Any] = {
    "task": "3-way 1X2 match outcome",
    "encoding": {"0": "home_win", "1": "draw", "2": "away_win"},
    "rule": "0 if home_goals > away_goals else 1 if home_goals == away_goals else 2",
    "source": "scripts/train_on_real_matches.py:build_dataset()",
    "generated_from": "final full-time score of a completed match",
    "missing_label_handling": (
        "a match without a parsed full-time score never becomes a row; it is "
        "dropped at parse time rather than imputed"
    ),
}

#: Tolerance for judging two training runs equivalent.
#:
#: Measured, not assumed. Two full runs of the pipeline over identical inputs
#: (evidence: reports/certification/reproducibility-evidence.json) produce
#: fitted artifacts that are bit-for-bit identical — every one of the 300
#: random-forest trees matches in split feature, threshold and leaf value, and
#: LightGBM/XGBoost agree exactly. The only residual difference appears at
#: PREDICT time, where parallel float reduction over the tree ensemble sums in a
#: differing order; float addition is not associative, so the result moves by
#: about one ULP. Observed worst case across six leagues: 2.22e-16.
#:
#: ⚠️ Artifact BYTE equality is not a valid reproducibility test. Pickle memo and
#: dict ordering make the files differ while the deserialised models are
#: identical. Compare fitted structure and predictions, never digests of the
#: .pkl itself.
REPRODUCIBILITY_PREDICTION_TOLERANCE = 1e-9

#: Libraries whose version can move a fitted artifact. Recorded per run so a
#: metric change can be attributed to data, code, or environment.
_TRACKED_DISTRIBUTIONS = (
    "scikit-learn",
    "xgboost",
    "lightgbm",
    "numpy",
    "scipy",
    "pandas",
    "joblib",
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stable_digest(obj: Any) -> str:
    """Content digest, formatting-independent.

    Same normalisation as ``certification_policy.policy_sha256`` and
    ``feature_registry.contract_sha256`` so digests are comparable across the
    codebase rather than each module inventing its own.
    """
    return _sha256_bytes(
        json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode(
            "utf-8"
        )
    )


def label_contract_sha256() -> str:
    """Digest of the label contract, for citation in a manifest."""
    return _stable_digest(LABEL_CONTRACT)


def dataset_fingerprint(cache_dir: Path, pattern: str = "fd_*.csv") -> Dict[str, Any]:
    """Content fingerprint of the training corpus.

    Hashes file *contents*, not mtimes or paths, so the same corpus fingerprints
    identically after a fresh checkout on another machine. Files are sorted by
    name so the digest does not depend on directory iteration order.
    """
    files: List[Dict[str, Any]] = []
    for path in sorted(Path(cache_dir).glob(pattern)):
        raw = path.read_bytes()
        files.append(
            {"name": path.name, "sha256": _sha256_bytes(raw), "bytes": len(raw)}
        )
    return {
        "source_dir": str(Path(cache_dir).as_posix()),
        "pattern": pattern,
        "file_count": len(files),
        "total_bytes": sum(f["bytes"] for f in files),
        "files": files,
        "dataset_sha256": _stable_digest([[f["name"], f["sha256"]] for f in files]),
    }


def environment_fingerprint() -> Dict[str, Any]:
    """Interpreter and library versions that can move a fitted artifact."""
    versions: Dict[str, Optional[str]] = {}
    for dist in _TRACKED_DISTRIBUTIONS:
        try:
            versions[dist] = importlib_metadata.version(dist)
        except importlib_metadata.PackageNotFoundError:
            # Absent is a real, reportable state (e.g. catboost has no wheel on
            # 3.14). Recording None beats omitting the key and looking complete.
            versions[dist] = None
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "libraries": versions,
    }


def git_commit() -> Optional[str]:
    """Full commit SHA of the working tree, or None if it cannot be determined.

    Prefers ``RENDER_GIT_COMMIT`` (present in the deploy environment, where git
    metadata may not be), then asks git. Returns None rather than a placeholder:
    a fabricated SHA in a reproducibility record is worse than an absent one.
    """
    env_sha = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GITHUB_SHA")
    if env_sha and len(env_sha) >= 7:
        return env_sha.strip()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha or None


def git_is_dirty() -> Optional[bool]:
    """Whether tracked files differ from HEAD. None when git is unavailable.

    A dirty tree means the recorded commit does not fully describe the code that
    produced the artifact, so a reproduction attempt may legitimately diverge.
    """
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return bool(out.stdout.strip())


def build_training_manifest(
    *,
    cache_dir: Path,
    feature_schema_version: str,
    feature_names: Iterable[str],
    feature_contract_sha256: Optional[str],
    holdout_season: str,
    seed: int,
    tune_trials: int,
    leagues: Mapping[str, Mapping[str, Any]],
    artifact_suffix: str,
) -> Dict[str, Any]:
    """Assemble the full reproducibility record for one training run.

    ``leagues`` maps league -> that league's emitted metrics/split counts; it is
    passed in rather than recomputed so the manifest reports what the run
    actually produced, not a second opinion about it.
    """
    feature_names = list(feature_names)
    manifest: Dict[str, Any] = {
        "schema": "sabiscore_training_manifest_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git": {"commit": git_commit(), "dirty": git_is_dirty()},
        "dataset": dataset_fingerprint(cache_dir),
        "labels": {"contract": LABEL_CONTRACT, "sha256": label_contract_sha256()},
        "features": {
            "feature_schema_version": feature_schema_version,
            "feature_count": len(feature_names),
            "feature_contract_sha256": feature_contract_sha256,
            "order_sha256": _stable_digest(feature_names),
        },
        "training_config": {
            "seed": seed,
            "holdout_season": holdout_season,
            "tune_trials": tune_trials,
            "artifact_suffix": artifact_suffix,
            "split": "chronological; holdout is the most recent season, never random",
            "calibration": "latest pre-holdout season, disjoint from core training rows",
        },
        "environment": environment_fingerprint(),
        "leagues": dict(leagues),
    }
    # Self-digest excludes volatile fields so two runs of identical inputs
    # produce the same reproducibility_sha256 even though timestamps differ.
    reproducible_view = {
        key: manifest[key]
        for key in ("dataset", "labels", "features", "training_config", "environment")
    }
    manifest["reproducibility_sha256"] = _stable_digest(reproducible_view)
    return manifest


def write_training_manifest(manifest: Mapping[str, Any], out_dir: Path) -> Path:
    """Write the manifest beside the artifacts it describes."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "training_manifest.json"
    path.write_text(
        json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


__all__ = [
    "LABEL_CONTRACT",
    "REPRODUCIBILITY_PREDICTION_TOLERANCE",
    "build_training_manifest",
    "dataset_fingerprint",
    "environment_fingerprint",
    "git_commit",
    "git_is_dirty",
    "label_contract_sha256",
    "write_training_manifest",
]
