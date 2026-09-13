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
import re
import subprocess
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.models.certification_policy import policy_sha256

#: This file lives at backend/src/models/, so parents[2] is backend/ — the same
#: depth convention test_training_leakage_contract.py's BACKEND_ROOT uses.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_METRIC_CONTRACT_PATH = _BACKEND_ROOT / "reports" / "evaluation" / "metric-contract.json"

#: Architecture summary for the trained artifact (directive v7.3 P4's
#: "model_family"), recorded as a contract so a change to the base learners or
#: meta-model is a visible, hashed manifest change rather than an undocumented
#: swap.
MODEL_FAMILY: Dict[str, Any] = {
    "architecture": "stacking_ensemble",
    "base_learners": ["random_forest", "xgboost", "lightgbm"],
    "meta_model": "logistic_regression",
    "calibration_candidates": ["temperature", "vector", "beta", "isotonic"],
    "source": "scripts/train_on_real_matches.py",
}

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


def metric_contract_sha256(path: Path = _METRIC_CONTRACT_PATH) -> Optional[str]:
    """Digest of the frozen metric contract, for citation in a manifest.

    None (never a fabricated digest) when the contract file is absent or
    unreadable — the same "absent is a real, reportable state" convention
    ``environment_fingerprint()`` already uses for a missing library.
    """
    try:
        return _sha256_bytes(Path(path).read_bytes())
    except OSError:
        return None


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
    auxiliary_datasets: Optional[Mapping[str, Dict[str, Any]]] = None,
    generation_id: Optional[str] = None,
    artifact_hashes: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Assemble the full reproducibility record for one training run.

    ``leagues`` maps league -> that league's emitted metrics/split counts; it is
    passed in rather than recomputed so the manifest reports what the run
    actually produced, not a second opinion about it.

    ``auxiliary_datasets`` fingerprints any corpus BESIDE ``cache_dir`` that fed
    the run — name -> :func:`dataset_fingerprint` output. It exists because the
    apex_v2_71 schema derives three of its columns from the Understat parquet
    corpus, which ``cache_dir``'s ``fd_*.csv`` glob does not see: without it the
    manifest would assert reproducibility while silently omitting a third of the
    inputs. It is folded into ``reproducibility_sha256`` like any other dataset
    field, so changing that corpus changes the digest.

    ``generation_id`` and ``artifact_hashes`` are post-hoc, assigned only once a
    run is promoted into ``models/active_generation.json`` — a run being built
    for candidate evaluation has neither yet. Both stay ``None`` (never a
    fabricated placeholder) until a caller that actually knows them supplies
    them, and neither participates in ``reproducibility_sha256``: a later
    promotion decision must not retroactively change the digest of what was
    already fit.
    """
    feature_names = list(feature_names)
    manifest: Dict[str, Any] = {
        "schema": "sabiscore_training_manifest_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_family": MODEL_FAMILY,
        "git": {"commit": git_commit(), "dirty": git_is_dirty()},
        "dataset": {
            **dataset_fingerprint(cache_dir),
            "auxiliary": {name: dict(fp) for name, fp in (auxiliary_datasets or {}).items()},
        },
        "provider_versions": {
            "mode": "offline_corpus",
            "note": (
                "Training reads cached football-data.co.uk CSV snapshots (see "
                "dataset.dataset_sha256 for exact corpus identity); there is no "
                "live provider API call at training time, so no API version "
                "string applies. The dataset content hash is a stronger "
                "per-exact-corpus identity than a provider version number "
                "would be."
            ),
        },
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
        "certification_policy_sha256": policy_sha256(),
        "metric_contract_sha256": metric_contract_sha256(),
        "generation_id": generation_id,
        "artifact_hashes": dict(artifact_hashes) if artifact_hashes else None,
    }
    # Self-digest excludes volatile/derived/post-hoc fields so two runs of
    # identical training inputs produce the same reproducibility_sha256 even
    # though timestamps, experiment_id, generation_id and artifact_hashes
    # differ (the last two may not even be known yet at build time).
    reproducible_view = {
        key: manifest[key]
        for key in ("dataset", "labels", "features", "training_config", "environment")
    }
    manifest["reproducibility_sha256"] = _stable_digest(reproducible_view)
    # Derived from the content digest rather than a random/counter id, so the
    # same inputs always yield the same experiment_id (and a changed input
    # always yields a different one) without a second source of truth to
    # keep in sync. Placed after the fields it's derived from, not folded
    # into reproducible_view itself (it would be circular).
    manifest["experiment_id"] = (
        f"{artifact_suffix}-{manifest['generated_at'][:10].replace('-', '')}"
        f"-{manifest['reproducibility_sha256'][:10]}"
    )
    return manifest


#: Artifact suffixes may only be a conservative slug. The filename is built
#: from this, so the pattern is what keeps a path-traversal component out of it.
_ARTIFACT_SUFFIX_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def write_training_manifest(
    manifest: Mapping[str, Any], out_dir: Path, artifact_suffix: str | None = None
) -> Path:
    """Write the manifest beside the artifacts it describes.

    ``out_dir`` comes from a CLI argument, so it is resolved and constrained to
    the repository before anything is written.

    ``artifact_suffix`` scopes the filename to one generation. Without it every
    schema wrote ``training_manifest.json``, so training a second candidate into
    the same ``models/candidate/`` destroyed the first one's reproducibility
    evidence while both sets of .pkl files sat there side by side — the manifest
    described whichever ran last. ``None`` keeps the historical bare name, so
    the v5_phase7 candidate's manifest keeps the path everything already
    references. The suffix is validated against a strict pattern rather than
    trusted, so the resolved path still cannot escape via traversal.
    """
    repo_root = Path(__file__).resolve().parents[3]
    out_dir = Path(out_dir).resolve()
    if not out_dir.is_relative_to(repo_root):
        raise ValueError(
            f"refusing to write a training manifest outside the repository: {out_dir}"
        )
    if artifact_suffix is not None and not _ARTIFACT_SUFFIX_RE.fullmatch(artifact_suffix):
        raise ValueError(f"invalid artifact suffix for a manifest filename: {artifact_suffix!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    name = (
        "training_manifest.json"
        if artifact_suffix is None
        else f"training_manifest_{artifact_suffix}.json"
    )
    path = out_dir / name
    path.write_text(
        json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


__all__ = [
    "LABEL_CONTRACT",
    "MODEL_FAMILY",
    "REPRODUCIBILITY_PREDICTION_TOLERANCE",
    "build_training_manifest",
    "dataset_fingerprint",
    "environment_fingerprint",
    "git_commit",
    "git_is_dirty",
    "label_contract_sha256",
    "metric_contract_sha256",
    "write_training_manifest",
]
