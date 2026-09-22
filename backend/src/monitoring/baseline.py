"""Reference-dataset generation for feature drift monitoring.

The baseline is built through ``UpcomingMatchFeatureProjector``—the same
feature construction path used by production full-analysis inference. It never
selects ad-hoc feature columns directly from SQL.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Match
from ..repositories.fixtures import get_settled_fixtures
from ..services.upcoming_match_feature_service import UpcomingMatchFeatureProjector

logger = logging.getLogger(__name__)


class BaselineGenerationError(RuntimeError):
    """Base class for reference-baseline generation failures."""


class InsufficientBaselineSamples(BaselineGenerationError):
    """Raised when the verified baseline cannot meet its minimum sample."""


@dataclass(frozen=True)
class BaselineGenerationConfig:
    output_path: Path
    manifest_path: Path
    minimum_sample: int = 1_000
    fixture_limit: int = 5_000
    league: str | None = None
    include_reduced_evidence: bool = False

    def validate(self) -> None:
        if self.minimum_sample < 1:
            raise ValueError("minimum_sample must be positive")
        if self.fixture_limit < self.minimum_sample:
            raise ValueError("fixture_limit must be >= minimum_sample")
        if self.output_path.suffix != ".parquet":
            raise ValueError("output_path must use the .parquet suffix")
        if self.manifest_path.suffix != ".json":
            raise ValueError("manifest_path must use the .json suffix")


@dataclass(frozen=True)
class BaselineGenerationResult:
    artifact_path: str
    manifest_path: str
    rows: int
    columns: int
    artifact_sha256: str
    schema_sha256: str
    skipped_reduced_evidence: int
    skipped_failed_features: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_sha256(frame: pd.DataFrame) -> str:
    schema = [
        {"name": column, "dtype": str(frame[column].dtype)} for column in frame.columns
    ]
    payload = json.dumps(schema, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _git_sha(repository_root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
    try:
        frame.to_parquet(temp_path, index=False)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


class ReferenceBaselineGenerator:
    """Generate an immutable, provenance-rich feature reference baseline."""

    def __init__(
        self,
        projector: UpcomingMatchFeatureProjector | None = None,
    ) -> None:
        self.projector = projector or UpcomingMatchFeatureProjector()

    async def generate(
        self,
        session: AsyncSession,
        config: BaselineGenerationConfig,
    ) -> BaselineGenerationResult:
        config.validate()
        fixtures = await get_settled_fixtures(
            session,
            limit=config.fixture_limit,
            league=config.league,
        )

        feature_rows: list[dict[str, float]] = []
        included_fixtures: list[Match] = []
        skipped_reduced = 0
        skipped_failed = 0

        for fixture in fixtures:
            try:
                projected = await self.projector.build_live_feature_vector(
                    match_id=str(fixture.id),
                    league=str(fixture.league_id),
                    db=session,
                )
                if (
                    projected.get("is_reduced_evidence_baseline")
                    and not config.include_reduced_evidence
                ):
                    skipped_reduced += 1
                    continue

                source = projected.get("features_dict") or {}
                row = {
                    feature: float(source[feature])
                    for feature in self.projector.canonical_features
                }
                values = np.asarray(tuple(row.values()), dtype=np.float64)
                if not np.isfinite(values).all():
                    raise ValueError("feature vector contains non-finite values")

                feature_rows.append(row)
                included_fixtures.append(fixture)
            except (
                Exception
            ) as exc:  # one malformed fixture must not abort audit collection
                skipped_failed += 1
                logger.warning(
                    "Skipping fixture %s during baseline generation: %s",
                    fixture.id,
                    type(exc).__name__,
                )

        if len(feature_rows) < config.minimum_sample:
            raise InsufficientBaselineSamples(
                "Verified reference baseline is too small: "
                f"{len(feature_rows)} usable rows; require {config.minimum_sample}. "
                f"Examined {len(fixtures)}, skipped reduced={skipped_reduced}, "
                f"failed={skipped_failed}."
            )

        frame = pd.DataFrame(
            feature_rows,
            columns=list(self.projector.canonical_features),
            dtype="float64",
        )
        if frame.empty or frame.shape[1] == 0:
            raise BaselineGenerationError("reference frame is empty")

        _atomic_write_parquet(config.output_path, frame)
        artifact_sha = _sha256_file(config.output_path)
        schema_sha = _schema_sha256(frame)

        match_dates = [
            fixture.match_date for fixture in included_fixtures if fixture.match_date
        ]
        league_counts = Counter(str(fixture.league_id) for fixture in included_fixtures)
        backend_root = Path(__file__).resolve().parents[2]
        repository_root = backend_root.parent

        try:
            artifact_manifest_path = str(
                config.output_path.resolve().relative_to(repository_root.resolve())
            )
        except ValueError:
            artifact_manifest_path = config.output_path.name

        manifest = {
            "schema_version": 1,
            "status": "READY",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "artifact": {
                "path": artifact_manifest_path,
                "sha256": artifact_sha,
                "format": "parquet",
                "rows": int(frame.shape[0]),
                "columns": int(frame.shape[1]),
            },
            "feature_schema": {
                "sha256": schema_sha,
                "ordered_features": list(frame.columns),
                "dtypes": {
                    column: str(frame[column].dtype) for column in frame.columns
                },
            },
            "source": {
                "fixture_definition": "score-verified settled fixtures",
                "feature_builder": (
                    "src.services.upcoming_match_feature_service."
                    "UpcomingMatchFeatureProjector.build_live_feature_vector"
                ),
                "fixture_limit": config.fixture_limit,
                "minimum_sample": config.minimum_sample,
                "include_reduced_evidence": config.include_reduced_evidence,
                "league_filter": config.league,
                "examined": len(fixtures),
                "included": len(included_fixtures),
                "skipped_reduced_evidence": skipped_reduced,
                "skipped_failed_features": skipped_failed,
                "date_range": {
                    "start": min(match_dates).isoformat() if match_dates else None,
                    "end": max(match_dates).isoformat() if match_dates else None,
                },
                "league_composition": dict(sorted(league_counts.items())),
            },
            "code": {
                "git_sha": _git_sha(repository_root),
            },
            "governance": {
                "target_columns_included": False,
                "identifier_columns_included": False,
                "production_use": (
                    "Phase 2 only; activate after the first real prediction is settled"
                ),
            },
        }
        _atomic_write_json(config.manifest_path, manifest)

        return BaselineGenerationResult(
            artifact_path=str(config.output_path),
            manifest_path=str(config.manifest_path),
            rows=int(frame.shape[0]),
            columns=int(frame.shape[1]),
            artifact_sha256=artifact_sha,
            schema_sha256=schema_sha,
            skipped_reduced_evidence=skipped_reduced,
            skipped_failed_features=skipped_failed,
        )


__all__: Sequence[str] = (
    "BaselineGenerationConfig",
    "BaselineGenerationError",
    "BaselineGenerationResult",
    "InsufficientBaselineSamples",
    "ReferenceBaselineGenerator",
)
