"""Production monitoring and metrics collection for SabiScore."""

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from ..core.redaction import redact_mapping, redact_text

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Lightweight metrics aggregation for production monitoring."""

    def __init__(self):
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._timers: Dict[str, List[float]] = defaultdict(list)
        self._errors: List[Dict[str, Any]] = []
        self._start_time = time.time()
        self._last_reset = datetime.now(timezone.utc)
        
        # Scraper-specific metrics
        self._scraper_calls: Dict[str, int] = defaultdict(int)
        self._scraper_errors: Dict[str, int] = defaultdict(int)
        self._scraper_latencies: Dict[str, List[float]] = defaultdict(list)
        
        # Prediction-specific metrics
        self._prediction_latencies: List[float] = []
        self._cache_hits = 0
        self._cache_misses = 0
        
        # Value bet tracking
        self._value_bets_found = 0
        self._edge_values: List[float] = []
        
        # Model accuracy tracking (per audit: Brier <0.13, accuracy >90%)
        self._brier_scores: List[float] = []
        self._accuracy_scores: List[float] = []
        self._model_versions: Dict[str, str] = {}  # league -> version
        self._calibration_drift_alerts: List[Dict[str, Any]] = []
        self._model_thresholds: Dict[str, Dict[str, float]] = {}

    def increment(self, metric: str, value: int = 1) -> None:
        """Increment a counter metric."""
        self._counters[metric] += value

    def set_gauge(self, metric: str, value: float) -> None:
        """Set a gauge metric to a specific value."""
        self._gauges[metric] = value

    def record_histogram(self, metric: str, value: float) -> None:
        """Record a value in a histogram."""
        self._histograms[metric].append(value)
        # Keep only last 1000 values to prevent memory bloat
        if len(self._histograms[metric]) > 1000:
            self._histograms[metric] = self._histograms[metric][-1000:]

    def record_timer(self, metric: str, duration_ms: float) -> None:
        """Record timing data."""
        self._timers[metric].append(duration_ms)
        if len(self._timers[metric]) > 1000:
            self._timers[metric] = self._timers[metric][-1000:]

    def record_error(
        self,
        error_type: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log error for monitoring dashboard."""
        error_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": error_type,
            "message": redact_text(message),
            "context": redact_mapping(context or {}),
        }
        self._errors.append(error_record)
        # Keep only last 100 errors
        if len(self._errors) > 100:
            self._errors = self._errors[-100:]

    def record_scraper_call(
        self,
        scraper_name: str,
        duration_ms: float,
        success: bool = True,
    ) -> None:
        """Track scraper performance and reliability."""
        self._scraper_calls[scraper_name] += 1
        self._scraper_latencies[scraper_name].append(duration_ms)
        
        if not success:
            self._scraper_errors[scraper_name] += 1
            
        # Limit latency tracking
        if len(self._scraper_latencies[scraper_name]) > 500:
            self._scraper_latencies[scraper_name] = (
                self._scraper_latencies[scraper_name][-500:]
            )

    def record_prediction(
        self,
        duration_ms: float,
        confidence: float,
        value_bets: int = 0,
        edge: Optional[float] = None,
        cache_hit: bool = False,
    ) -> None:
        """Track prediction service performance."""
        self._prediction_latencies.append(duration_ms)
        
        if cache_hit:
            self._cache_hits += 1
        else:
            self._cache_misses += 1
            
        if value_bets > 0:
            self._value_bets_found += value_bets
            
        if edge is not None:
            self._edge_values.append(edge)
            
        # Limit tracking
        if len(self._prediction_latencies) > 1000:
            self._prediction_latencies = self._prediction_latencies[-1000:]
        if len(self._edge_values) > 500:
            self._edge_values = self._edge_values[-500:]

    def record_model_accuracy(
        self,
        brier_score: float,
        accuracy: float,
        league: str,
        model_version: str,
        brier_threshold: Optional[float] = None,
        accuracy_threshold: Optional[float] = None,
    ) -> None:
        """
        Track settled model metrics against explicitly registered thresholds.

        No threshold is inferred. A model registry must supply thresholds that
        were actually approved for the active artifact.
        """
        self._brier_scores.append(brier_score)
        self._accuracy_scores.append(accuracy)
        self._model_versions[league] = model_version
        
        # Limit tracking
        if len(self._brier_scores) > 500:
            self._brier_scores = self._brier_scores[-500:]
        if len(self._accuracy_scores) > 500:
            self._accuracy_scores = self._accuracy_scores[-500:]
        
        if brier_threshold is not None or accuracy_threshold is not None:
            self._model_thresholds[league] = {
                **({"brier": brier_threshold} if brier_threshold is not None else {}),
                **({"accuracy": accuracy_threshold} if accuracy_threshold is not None else {}),
            }

        brier_exceeded = brier_threshold is not None and brier_score > brier_threshold
        accuracy_below = accuracy_threshold is not None and accuracy < accuracy_threshold
        if brier_exceeded or accuracy_below:
            alert = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "league": league,
                "model_version": model_version,
                "brier_score": brier_score,
                "accuracy": accuracy,
                "brier_exceeded": brier_exceeded,
                "accuracy_below": accuracy_below,
            }
            self._calibration_drift_alerts.append(alert)
            logger.warning(
                f"Calibration drift alert: {league} model v{model_version} "
                f"Brier={brier_score:.4f} Accuracy={accuracy:.2%}"
            )
            
            # Keep only last 50 alerts
            if len(self._calibration_drift_alerts) > 50:
                self._calibration_drift_alerts = self._calibration_drift_alerts[-50:]

    def record_analysis_state(
        self,
        *,
        prediction_available: bool,
        evidence_completeness: float,
        abstention_reason: str,
        calibration_status: str,
        duration_ms: float,
    ) -> None:
        """Record bounded, low-cardinality full-analysis production signals."""
        completeness = min(1.0, max(0.0, float(evidence_completeness)))
        reason = (abstention_reason or "NONE").upper()[:80]
        calibration = (calibration_status or "UNKNOWN").upper()[:40]
        self.increment(
            "analysis.prediction.available"
            if prediction_available
            else "analysis.prediction.unavailable"
        )
        self.increment(f"analysis.abstention.{reason}")
        self.increment(f"analysis.calibration.{calibration}")
        self.record_histogram("analysis.evidence_completeness", completeness)
        self.record_timer("analysis.latency", max(0.0, float(duration_ms)))

    def record_provider_outcome(
        self,
        *,
        provider: str,
        outcome: str,
        duration_ms: float,
        cache_tier: str = "none",
        circuit_state: str = "unknown",
        schema_rejected: bool = False,
    ) -> None:
        """Record provider/cache/circuit outcomes without payloads or credentials."""
        safe_provider = provider.casefold().replace(" ", "_")[:40]
        safe_outcome = outcome.casefold().replace(" ", "_")[:40]
        safe_tier = cache_tier.casefold().replace(" ", "_")[:20]
        safe_circuit = circuit_state.casefold().replace(" ", "_")[:20]
        self.increment(f"provider.{safe_provider}.{safe_outcome}")
        self.increment(f"cache.tier.{safe_tier}")
        self.increment(f"circuit.{safe_provider}.{safe_circuit}")
        if schema_rejected and safe_outcome != "schema_rejected":
            self.increment(f"provider.{safe_provider}.schema_rejected")
        self.record_timer(f"provider.{safe_provider}.latency", max(0.0, float(duration_ms)))

    def get_summary(self) -> Dict[str, Any]:
        """Generate summary statistics for monitoring dashboard."""
        uptime_seconds = time.time() - self._start_time
        
        summary = {
            "uptime_seconds": uptime_seconds,
            "uptime_human": str(timedelta(seconds=int(uptime_seconds))),
            "last_reset": self._last_reset.isoformat(),
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "recent_errors": self._errors[-10:],  # Last 10 errors
        }
        
        # Add histogram percentiles
        if self._histograms:
            summary["histograms"] = {}
            for metric, values in self._histograms.items():
                if values:
                    sorted_values = sorted(values)
                    summary["histograms"][metric] = {
                        "count": len(values),
                        "min": min(values),
                        "max": max(values),
                        "mean": sum(values) / len(values),
                        "p50": sorted_values[len(sorted_values) // 2],
                        "p95": sorted_values[int(len(sorted_values) * 0.95)],
                        "p99": sorted_values[int(len(sorted_values) * 0.99)],
                    }
        
        # Add timer statistics
        if self._timers:
            summary["timers"] = {}
            for metric, durations in self._timers.items():
                if durations:
                    sorted_durations = sorted(durations)
                    summary["timers"][metric] = {
                        "count": len(durations),
                        "min_ms": min(durations),
                        "max_ms": max(durations),
                        "mean_ms": sum(durations) / len(durations),
                        "p50_ms": sorted_durations[len(sorted_durations) // 2],
                        "p95_ms": sorted_durations[int(len(sorted_durations) * 0.95)],
                        "p99_ms": sorted_durations[int(len(sorted_durations) * 0.99)],
                    }
        
        # Scraper health
        if self._scraper_calls:
            summary["scrapers"] = {}
            for scraper, calls in self._scraper_calls.items():
                errors = self._scraper_errors.get(scraper, 0)
                latencies = self._scraper_latencies.get(scraper, [])
                
                scraper_stats = {
                    "calls": calls,
                    "errors": errors,
                    "error_rate": errors / calls if calls > 0 else 0,
                    "success_rate": 1 - (errors / calls) if calls > 0 else 1.0,
                }
                
                if latencies:
                    sorted_latencies = sorted(latencies)
                    scraper_stats.update({
                        "avg_latency_ms": sum(latencies) / len(latencies),
                        "p95_latency_ms": sorted_latencies[int(len(sorted_latencies) * 0.95)],
                    })
                
                summary["scrapers"][scraper] = scraper_stats
        
        # Prediction metrics
        if self._prediction_latencies:
            sorted_pred = sorted(self._prediction_latencies)
            summary["predictions"] = {
                "total": len(self._prediction_latencies),
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "cache_hit_rate": (
                    self._cache_hits / (self._cache_hits + self._cache_misses)
                    if (self._cache_hits + self._cache_misses) > 0
                    else 0
                ),
                "avg_latency_ms": sum(self._prediction_latencies) / len(self._prediction_latencies),
                "p95_latency_ms": sorted_pred[int(len(sorted_pred) * 0.95)],
                "value_bets_found": self._value_bets_found,
            }
            
            if self._edge_values:
                summary["predictions"]["avg_edge"] = (
                    sum(self._edge_values) / len(self._edge_values)
                )
        
        # Model accuracy metrics (per audit requirements)
        if self._brier_scores or self._accuracy_scores:
            model_metrics: Dict[str, Any] = {
                "model_versions": dict(self._model_versions),
                "registered_thresholds": dict(self._model_thresholds),
                "calibration_alerts": len(self._calibration_drift_alerts),
                "recent_alerts": self._calibration_drift_alerts[-5:],
            }
            
            if self._brier_scores:
                sorted_brier = sorted(self._brier_scores)
                model_metrics["brier"] = {
                    "count": len(self._brier_scores),
                    "mean": sum(self._brier_scores) / len(self._brier_scores),
                    "min": min(self._brier_scores),
                    "max": max(self._brier_scores),
                    "p50": sorted_brier[len(sorted_brier) // 2],
                }
            
            if self._accuracy_scores:
                sorted_acc = sorted(self._accuracy_scores)
                model_metrics["accuracy"] = {
                    "count": len(self._accuracy_scores),
                    "mean": sum(self._accuracy_scores) / len(self._accuracy_scores),
                    "min": min(self._accuracy_scores),
                    "max": max(self._accuracy_scores),
                    "p50": sorted_acc[len(sorted_acc) // 2],
                }
            
            summary["model_accuracy"] = model_metrics
        
        return summary

    def reset(self) -> None:
        """Reset all metrics (useful for testing or daily resets)."""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()
        self._timers.clear()
        self._errors.clear()
        self._scraper_calls.clear()
        self._scraper_errors.clear()
        self._scraper_latencies.clear()
        self._prediction_latencies.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        self._value_bets_found = 0
        self._edge_values.clear()
        self._brier_scores.clear()
        self._accuracy_scores.clear()
        self._model_versions.clear()
        self._model_thresholds.clear()
        self._calibration_drift_alerts.clear()
        self._last_reset = datetime.now(timezone.utc)
        logger.info("Metrics collector reset")


# Global metrics collector instance
metrics_collector = MetricsCollector()


def monitor_latency(metric_name: str) -> Callable:
    """Decorator to monitor function execution time."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                metrics_collector.record_timer(metric_name, duration_ms)
                return result
            except Exception as exc:
                duration_ms = (time.time() - start) * 1000
                metrics_collector.record_timer(f"{metric_name}_error", duration_ms)
                metrics_collector.record_error(
                    error_type=type(exc).__name__,
                    message=str(exc),
                    context={"function": func.__name__},
                )
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                metrics_collector.record_timer(metric_name, duration_ms)
                return result
            except Exception as exc:
                duration_ms = (time.time() - start) * 1000
                metrics_collector.record_timer(f"{metric_name}_error", duration_ms)
                metrics_collector.record_error(
                    error_type=type(exc).__name__,
                    message=str(exc),
                    context={"function": func.__name__},
                )
                raise
        
        # Return appropriate wrapper based on function type
        if hasattr(func, "__code__") and func.__code__.co_flags & 0x80:
            return async_wrapper
        return sync_wrapper
    
    return decorator


def monitor_scraper(scraper_name: str) -> Callable:
    """Decorator to monitor scraper performance."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            success = True
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception:
                success = False
                raise
            finally:
                duration_ms = (time.time() - start) * 1000
                metrics_collector.record_scraper_call(
                    scraper_name,
                    duration_ms,
                    success,
                )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            success = True
            try:
                result = func(*args, **kwargs)
                return result
            except Exception:
                success = False
                raise
            finally:
                duration_ms = (time.time() - start) * 1000
                metrics_collector.record_scraper_call(
                    scraper_name,
                    duration_ms,
                    success,
                )
        
        if hasattr(func, "__code__") and func.__code__.co_flags & 0x80:
            return async_wrapper
        return sync_wrapper
    
    return decorator
