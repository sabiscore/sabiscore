"""Additive C7 Model Certification Envelope.

Directive V18.0 Section 4.2.
Augments the frozen C6 market-relative benchmark with 14 comprehensive certification
dimensions (C7-A through C7-N) covering dataset integrity, leakage, probability
calibration, predictive scoring, market benchmark veracity, robustness, uncertainty,
drift policies, and operational safety.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Dict, List, Optional, Tuple


class MarketRelianceClass(str, Enum):
    """Model classification regarding market odds dependence (Directive V18 C7-F)."""
    MARKET_INDEPENDENT = "MARKET-INDEPENDENT"
    MARKET_AWARE = "MARKET-AWARE"
    MARKET_ANCHORED = "MARKET-ANCHORED"


class ShadowLifecycleState(str, Enum):
    """Promotion lifecycle stages (Directive V18 C7-N)."""
    CANDIDATE = "CANDIDATE"
    SHADOW = "SHADOW"
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    DEGRADED = "DEGRADED"
    WITHHELD = "WITHHELD"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class DatasetIntegrityC7A:
    total_samples: int
    duplicate_rows: int
    missing_labels: int
    dataset_snapshot_hash: str
    feature_schema_hash: str
    is_valid: bool = True


@dataclass(frozen=True)
class LeakageIntegrityC7B:
    pit_audit_passed: bool
    temporal_lineage_passed: bool
    negative_controls_passed: bool
    no_future_features: bool
    no_benchmark_leakage: bool
    is_valid: bool = True


@dataclass(frozen=True)
class CalibrationMetricsC7C:
    multiclass_log_loss: float
    rps_score: float
    brier_score: float
    expected_calibration_error: float
    calibration_method: str
    out_of_sample_verified: bool
    is_valid: bool = True


@dataclass(frozen=True)
class MarketBenchmarkC7E:
    benchmark_source_id: str
    benchmark_bookmaker_key: str  # e.g., "pinnacle"
    benchmark_bookmaker_name: str  # e.g., "Pinnacle"
    market_key: str  # "h2h"
    delta_rps_vs_market: float
    is_statistically_superior: bool
    is_valid: bool = True


@dataclass(frozen=True)
class OperationalProfileC7L:
    model_load_latency_ms: float
    inference_latency_p95_ms: float
    peak_rss_mb: float
    memory_headroom_mb: float
    thread_clamp_verified: bool
    is_valid: bool = True


@dataclass(frozen=True)
class C7CertificationEnvelope:
    """Additive C7 certification result across all 14 dimensions."""
    generation_id: str
    evaluated_at: str
    dataset_integrity: DatasetIntegrityC7A
    leakage_integrity: LeakageIntegrityC7B
    probability_calibration: CalibrationMetricsC7C
    market_benchmark: MarketBenchmarkC7E
    market_reliance: MarketRelianceClass
    operational_profile: OperationalProfileC7L
    lifecycle_state: ShadowLifecycleState
    c6_protocol_sha256: str
    c6_passed: bool
    c7_overall_passed: bool
    known_limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "evaluated_at": self.evaluated_at,
            "dataset_integrity": {
                "total_samples": self.dataset_integrity.total_samples,
                "duplicate_rows": self.dataset_integrity.duplicate_rows,
                "missing_labels": self.dataset_integrity.missing_labels,
                "dataset_snapshot_hash": self.dataset_integrity.dataset_snapshot_hash,
                "feature_schema_hash": self.dataset_integrity.feature_schema_hash,
                "is_valid": self.dataset_integrity.is_valid,
            },
            "leakage_integrity": {
                "pit_audit_passed": self.leakage_integrity.pit_audit_passed,
                "temporal_lineage_passed": self.leakage_integrity.temporal_lineage_passed,
                "negative_controls_passed": self.leakage_integrity.negative_controls_passed,
                "no_future_features": self.leakage_integrity.no_future_features,
                "no_benchmark_leakage": self.leakage_integrity.no_benchmark_leakage,
                "is_valid": self.leakage_integrity.is_valid,
            },
            "probability_calibration": {
                "multiclass_log_loss": self.probability_calibration.multiclass_log_loss,
                "rps_score": self.probability_calibration.rps_score,
                "brier_score": self.probability_calibration.brier_score,
                "expected_calibration_error": self.probability_calibration.expected_calibration_error,
                "calibration_method": self.probability_calibration.calibration_method,
                "out_of_sample_verified": self.probability_calibration.out_of_sample_verified,
                "is_valid": self.probability_calibration.is_valid,
            },
            "market_benchmark": {
                "benchmark_source_id": self.market_benchmark.benchmark_source_id,
                "benchmark_bookmaker_key": self.market_benchmark.benchmark_bookmaker_key,
                "benchmark_bookmaker_name": self.market_benchmark.benchmark_bookmaker_name,
                "market_key": self.market_benchmark.market_key,
                "delta_rps_vs_market": self.market_benchmark.delta_rps_vs_market,
                "is_statistically_superior": self.market_benchmark.is_statistically_superior,
                "is_valid": self.market_benchmark.is_valid,
            },
            "market_reliance": self.market_reliance.value,
            "operational_profile": {
                "model_load_latency_ms": self.operational_profile.model_load_latency_ms,
                "inference_latency_p95_ms": self.operational_profile.inference_latency_p95_ms,
                "peak_rss_mb": self.operational_profile.peak_rss_mb,
                "memory_headroom_mb": self.operational_profile.memory_headroom_mb,
                "thread_clamp_verified": self.operational_profile.thread_clamp_verified,
                "is_valid": self.operational_profile.is_valid,
            },
            "lifecycle_state": self.lifecycle_state.value,
            "c6_protocol_sha256": self.c6_protocol_sha256,
            "c6_passed": self.c6_passed,
            "c7_overall_passed": self.c7_overall_passed,
            "known_limitations": self.known_limitations,
        }
