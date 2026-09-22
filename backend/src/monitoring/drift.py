"""Asynchronous feature-drift evaluation with FDR correction and OTel metrics.

This module is Phase-2 infrastructure. It must run in a worker/cron after the
first real prediction has been settled—not in the synchronous serving path.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from httpx import AsyncClient
from opentelemetry import metrics
from scipy.stats import ks_2samp

from src.services.alerting import trigger_slack_drift_alert

logger = logging.getLogger("sabiscore.mlops.drift")

meter = metrics.get_meter("sabiscore.mlops")
drift_evaluation_counter = meter.create_counter(
    "sabiscore_data_drift_evaluations",
    description="Number of drift batches evaluated",
)
drift_counter = meter.create_counter(
    "sabiscore_data_drift_events",
    description="Number of confirmed data drift events after FDR correction",
)
drift_batch_size = meter.create_histogram(
    "sabiscore_data_drift_batch_size",
    description="Number of fixture feature rows in each drift evaluation",
    unit="{fixture}",
)
drift_feature_share = meter.create_histogram(
    "sabiscore_data_drift_feature_share",
    description="Share of features flagged after FDR correction",
    unit="1",
)


class DriftConfigurationError(RuntimeError):
    """Raised when the reference artifact or monitor configuration is invalid."""


@dataclass(frozen=True)
class FeatureDrift:
    feature: str
    statistic: float
    p_value: float
    adjusted_p_value: float
    drift_detected: bool


@dataclass(frozen=True)
class DriftEvaluation:
    evaluation_id: str
    status: str
    reference_rows: int
    current_rows: int
    evaluated_features: int
    drifting_features: tuple[str, ...]
    drift_share: float
    fdr_alpha: float
    minimum_current_rows: int
    dataset_drift: bool
    alert_delivered: bool
    feature_results: tuple[FeatureDrift, ...]
    evidently_report: Mapping[str, Any] | None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["feature_results"] = [asdict(item) for item in self.feature_results]
        return payload


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    """Return monotonic Benjamini–Hochberg adjusted p-values."""

    count = len(p_values)
    if count == 0:
        return []
    values = np.asarray(p_values, dtype=float)
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("p-values must be finite values in [0, 1]")

    order = np.argsort(values)
    ranked = values[order]
    adjusted_ranked = np.empty(count, dtype=float)
    running = 1.0
    for index in range(count - 1, -1, -1):
        rank = index + 1
        candidate = ranked[index] * count / rank
        running = min(running, candidate)
        adjusted_ranked[index] = min(1.0, running)

    adjusted = np.empty(count, dtype=float)
    adjusted[order] = adjusted_ranked
    return adjusted.tolist()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(reference_path: Path, manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        raise DriftConfigurationError(f"Reference manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "READY":
        raise DriftConfigurationError("Reference manifest is not READY")
    expected_hash = manifest.get("artifact", {}).get("sha256")
    if not expected_hash or expected_hash != _sha256_file(reference_path):
        raise DriftConfigurationError(
            "Reference artifact SHA-256 does not match manifest"
        )
    return manifest


def _evidently_report(
    reference_df: pd.DataFrame, current_df: pd.DataFrame
) -> Mapping[str, Any]:
    """Run Evidently using the pinned 0.7 API, isolated from the event loop."""

    try:
        from evidently import Report
        from evidently.presets import DataDriftPreset
    except ImportError as exc:  # optional Phase-2 dependency
        raise DriftConfigurationError(
            "Evidently is not installed; install backend/requirements-mlops.txt"
        ) from exc

    report = Report([DataDriftPreset()])
    snapshot = report.run(current_data=current_df, reference_data=reference_df)
    if hasattr(snapshot, "dict"):
        return snapshot.dict()
    if hasattr(snapshot, "as_dict"):
        return snapshot.as_dict()
    if hasattr(snapshot, "json"):
        return json.loads(snapshot.json())
    raise DriftConfigurationError("Unsupported Evidently snapshot output API")


def _fdr_feature_drift(
    reference_df: pd.DataFrame,
    current_df: pd.DataFrame,
    *,
    alpha: float,
) -> tuple[FeatureDrift, ...]:
    raw: list[tuple[str, float, float]] = []
    for column in reference_df.columns:
        reference = pd.to_numeric(reference_df[column], errors="coerce").dropna()
        current = pd.to_numeric(current_df[column], errors="coerce").dropna()
        if reference.empty or current.empty:
            continue
        result = ks_2samp(reference, current, alternative="two-sided", method="auto")
        raw.append((column, float(result.statistic), float(result.pvalue)))

    adjusted = benjamini_hochberg([item[2] for item in raw])
    return tuple(
        FeatureDrift(
            feature=feature,
            statistic=statistic,
            p_value=p_value,
            adjusted_p_value=adjusted_p,
            drift_detected=adjusted_p < alpha,
        )
        for (feature, statistic, p_value), adjusted_p in zip(raw, adjusted, strict=True)
    )


class DriftMonitor:
    """Evaluate accumulated feature batches against a versioned reference."""

    def __init__(
        self,
        reference_path: str | Path,
        *,
        manifest_path: str | Path | None = None,
        minimum_current_rows: int,
        dataset_drift_share: float,
        fdr_alpha: float = 0.05,
    ) -> None:
        self.reference_path = Path(reference_path).resolve()
        self.manifest_path = (
            Path(manifest_path).resolve()
            if manifest_path
            else self.reference_path.with_name("baseline_v1.manifest.json")
        )
        if minimum_current_rows < 2:
            raise ValueError("minimum_current_rows must be at least 2")
        if not 0 < dataset_drift_share <= 1:
            raise ValueError("dataset_drift_share must be in (0, 1]")
        if not 0 < fdr_alpha < 1:
            raise ValueError("fdr_alpha must be in (0, 1)")
        if not self.reference_path.exists():
            raise DriftConfigurationError(
                f"Reference artifact not found: {self.reference_path}"
            )

        self.manifest = _load_manifest(self.reference_path, self.manifest_path)
        self.reference_df = pd.read_parquet(self.reference_path)
        if self.reference_df.empty:
            raise DriftConfigurationError("Reference artifact contains no rows")
        manifest_features = (
            self.manifest.get("feature_schema", {}).get("ordered_features") or []
        )
        if manifest_features and list(self.reference_df.columns) != list(
            manifest_features
        ):
            raise DriftConfigurationError(
                "Reference columns do not match manifest feature order"
            )

        self.minimum_current_rows = minimum_current_rows
        self.dataset_drift_share = dataset_drift_share
        self.fdr_alpha = fdr_alpha

    async def evaluate_batch(
        self,
        *,
        http_client: AsyncClient,
        current_batch_df: pd.DataFrame,
    ) -> DriftEvaluation:
        """Evaluate drift off-thread and emit advisory telemetry/Slack output."""

        evaluation_id = uuid.uuid4().hex
        current_rows = len(current_batch_df)
        attributes = {"status": "evaluated"}
        drift_evaluation_counter.add(1, attributes)
        drift_batch_size.record(current_rows)

        if current_rows < self.minimum_current_rows:
            return DriftEvaluation(
                evaluation_id=evaluation_id,
                status="INSUFFICIENT_SAMPLE",
                reference_rows=len(self.reference_df),
                current_rows=current_rows,
                evaluated_features=0,
                drifting_features=(),
                drift_share=0.0,
                fdr_alpha=self.fdr_alpha,
                minimum_current_rows=self.minimum_current_rows,
                dataset_drift=False,
                alert_delivered=False,
                feature_results=(),
                evidently_report=None,
                reason=(
                    f"Current batch has {current_rows} rows; "
                    f"requires {self.minimum_current_rows}."
                ),
            )

        if list(current_batch_df.columns) != list(self.reference_df.columns):
            return DriftEvaluation(
                evaluation_id=evaluation_id,
                status="SCHEMA_MISMATCH",
                reference_rows=len(self.reference_df),
                current_rows=current_rows,
                evaluated_features=0,
                drifting_features=(),
                drift_share=0.0,
                fdr_alpha=self.fdr_alpha,
                minimum_current_rows=self.minimum_current_rows,
                dataset_drift=False,
                alert_delivered=False,
                feature_results=(),
                evidently_report=None,
                reason="Current feature columns/order do not match the reference manifest.",
            )

        evidently_report, feature_results = await asyncio.gather(
            asyncio.to_thread(_evidently_report, self.reference_df, current_batch_df),
            asyncio.to_thread(
                _fdr_feature_drift,
                self.reference_df,
                current_batch_df,
                alpha=self.fdr_alpha,
            ),
        )

        drifting = tuple(
            item.feature for item in feature_results if item.drift_detected
        )
        evaluated_features = len(feature_results)
        drift_share = len(drifting) / evaluated_features if evaluated_features else 0.0
        dataset_drift = bool(
            evaluated_features and drift_share >= self.dataset_drift_share
        )
        drift_feature_share.record(drift_share)

        alert_delivered = False
        if dataset_drift:
            drift_counter.add(1, {"severity": "advisory"})
            alert_delivered = await trigger_slack_drift_alert(
                http_client=http_client,
                affected_features=drifting,
                batch_size=current_rows,
                drift_share=drift_share,
                correlation_id=evaluation_id,
            )

        return DriftEvaluation(
            evaluation_id=evaluation_id,
            status="DRIFT_DETECTED" if dataset_drift else "NO_DATASET_DRIFT",
            reference_rows=len(self.reference_df),
            current_rows=current_rows,
            evaluated_features=evaluated_features,
            drifting_features=drifting,
            drift_share=drift_share,
            fdr_alpha=self.fdr_alpha,
            minimum_current_rows=self.minimum_current_rows,
            dataset_drift=dataset_drift,
            alert_delivered=alert_delivered,
            feature_results=feature_results,
            evidently_report=evidently_report,
        )


__all__: Sequence[str] = (
    "DriftConfigurationError",
    "DriftEvaluation",
    "DriftMonitor",
    "FeatureDrift",
    "benjamini_hochberg",
)
