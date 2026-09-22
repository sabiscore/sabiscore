"""
Simple monitoring helper for tracking key metrics during development/production.
Can be extended with APM integrations (Datadog, New Relic, etc.)
"""

import time
import logging
from typing import Dict, Optional
from datetime import datetime, timezone
from functools import wraps

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Lightweight metrics collector for SabiScore"""

    def __init__(self):
        self.metrics: Dict[str, list] = {
            "api_latency": [],
            "prediction_time": [],
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0,
        }
        self.start_time = datetime.now(timezone.utc)

    def record_latency(self, endpoint: str, duration_ms: float):
        """Record API endpoint latency"""
        self.metrics["api_latency"].append(
            {
                "endpoint": endpoint,
                "duration_ms": duration_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Keep only last 1000 records
        if len(self.metrics["api_latency"]) > 1000:
            self.metrics["api_latency"] = self.metrics["api_latency"][-1000:]

    def record_prediction(self, duration_ms: float):
        """Record prediction generation time"""
        self.metrics["prediction_time"].append(
            {
                "duration_ms": duration_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        if len(self.metrics["prediction_time"]) > 1000:
            self.metrics["prediction_time"] = self.metrics["prediction_time"][-1000:]

    def record_cache_hit(self):
        """Increment cache hit counter"""
        self.metrics["cache_hits"] += 1

    def record_cache_miss(self):
        """Increment cache miss counter"""
        self.metrics["cache_misses"] += 1

    def record_error(self):
        """Increment error counter"""
        self.metrics["errors"] += 1

    def get_summary(self) -> Dict:
        """Get metrics summary"""
        total_requests = len(self.metrics["api_latency"])
        total_cache_ops = self.metrics["cache_hits"] + self.metrics["cache_misses"]

        summary = {
            "uptime_seconds": (
                datetime.now(timezone.utc) - self.start_time
            ).total_seconds(),
            "total_requests": total_requests,
            "total_predictions": len(self.metrics["prediction_time"]),
            "total_errors": self.metrics["errors"],
            "cache_hit_rate": (
                self.metrics["cache_hits"] / total_cache_ops
                if total_cache_ops > 0
                else 0
            ),
        }

        # Calculate latency percentiles
        if self.metrics["api_latency"]:
            latencies = [m["duration_ms"] for m in self.metrics["api_latency"]]
            latencies.sort()

            summary["latency"] = {
                "p50": latencies[len(latencies) // 2],
                "p95": latencies[int(len(latencies) * 0.95)],
                "p99": latencies[int(len(latencies) * 0.99)],
                "max": max(latencies),
            }

        # Calculate prediction time stats
        if self.metrics["prediction_time"]:
            pred_times = [m["duration_ms"] for m in self.metrics["prediction_time"]]
            summary["prediction_time"] = {
                "avg": sum(pred_times) / len(pred_times),
                "max": max(pred_times),
                "min": min(pred_times),
            }

        return summary


# Global metrics instance
metrics_collector = MetricsCollector()


def monitor_latency(endpoint_name: Optional[str] = None):
    """Decorator to monitor endpoint latency"""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.time() - start) * 1000
                name = endpoint_name or func.__name__
                metrics_collector.record_latency(name, duration_ms)

                # Log slow requests
                if duration_ms > 500:
                    logger.warning(f"Slow request: {name} took {duration_ms:.1f}ms")

        return wrapper

    return decorator


def get_metrics_endpoint():
    """
    FastAPI endpoint to expose metrics.
    Add to your router:

    @router.get("/metrics")
    async def get_metrics():
        return get_metrics_endpoint()
    """
    return metrics_collector.get_summary()
