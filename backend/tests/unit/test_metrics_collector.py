"""Unit tests for MetricsCollector in monitoring/metrics.py."""

from __future__ import annotations

import pytest

from src.monitoring.metrics import MetricsCollector, monitor_latency, monitor_scraper


@pytest.fixture()
def mc() -> MetricsCollector:
    c = MetricsCollector()
    c.reset()
    return c


# ── Counter / gauge / histogram / timer ─────────────────────────────────────

def test_increment_default(mc):
    mc.increment("requests")
    assert mc._counters["requests"] == 1


def test_increment_custom_value(mc):
    mc.increment("requests", 5)
    assert mc._counters["requests"] == 5


def test_set_gauge(mc):
    mc.set_gauge("queue_depth", 42.0)
    assert mc._gauges["queue_depth"] == 42.0


def test_record_histogram(mc):
    for v in [1.0, 2.0, 3.0]:
        mc.record_histogram("response_size", v)
    assert len(mc._histograms["response_size"]) == 3


def test_record_histogram_trim_to_1000(mc):
    for i in range(1010):
        mc.record_histogram("h", float(i))
    assert len(mc._histograms["h"]) == 1000


def test_record_timer(mc):
    mc.record_timer("inference_ms", 120.5)
    assert mc._timers["inference_ms"] == [120.5]


def test_record_timer_trim_to_1000(mc):
    for i in range(1010):
        mc.record_timer("t", float(i))
    assert len(mc._timers["t"]) == 1000


# ── Error tracking ──────────────────────────────────────────────────────────

def test_record_error_appends(mc):
    mc.record_error("ValueError", "bad input", context={"field": "league"})
    assert len(mc._errors) == 1
    assert mc._errors[0]["type"] == "ValueError"
    assert mc._errors[0]["message"] == "bad input"
    assert mc._errors[0]["context"]["field"] == "league"


def test_record_error_trim_to_100(mc):
    for i in range(105):
        mc.record_error("E", f"msg {i}")
    assert len(mc._errors) == 100


def test_record_error_no_context(mc):
    mc.record_error("RuntimeError", "oops")
    assert mc._errors[0]["context"] == {}


# ── Scraper calls ────────────────────────────────────────────────────────────

def test_record_scraper_call_success(mc):
    mc.record_scraper_call("understat", 55.0, success=True)
    assert mc._scraper_calls["understat"] == 1
    assert mc._scraper_errors["understat"] == 0
    assert mc._scraper_latencies["understat"] == [55.0]


def test_record_scraper_call_failure(mc):
    mc.record_scraper_call("understat", 20.0, success=False)
    assert mc._scraper_errors["understat"] == 1


def test_record_scraper_call_trim(mc):
    for i in range(510):
        mc.record_scraper_call("s", float(i))
    assert len(mc._scraper_latencies["s"]) == 500


# ── Prediction recording ─────────────────────────────────────────────────────

def test_record_prediction_cache_hit(mc):
    mc.record_prediction(12.0, 0.72, cache_hit=True)
    assert mc._cache_hits == 1
    assert mc._cache_misses == 0


def test_record_prediction_cache_miss(mc):
    mc.record_prediction(40.0, 0.65, cache_hit=False)
    assert mc._cache_misses == 1


def test_record_prediction_value_bets(mc):
    mc.record_prediction(30.0, 0.80, value_bets=3)
    assert mc._value_bets_found == 3


def test_record_prediction_edge(mc):
    mc.record_prediction(30.0, 0.80, edge=0.08)
    assert mc._edge_values == [0.08]


def test_record_prediction_no_edge(mc):
    mc.record_prediction(30.0, 0.80, edge=None)
    assert mc._edge_values == []


def test_record_prediction_trim_latencies(mc):
    for i in range(1010):
        mc.record_prediction(float(i), 0.70)
    assert len(mc._prediction_latencies) == 1000


def test_record_prediction_trim_edges(mc):
    for i in range(510):
        mc.record_prediction(10.0, 0.70, edge=float(i) / 100.0)
    assert len(mc._edge_values) == 500


# ── Model accuracy ────────────────────────────────────────────────────────────

def test_record_model_accuracy_no_alert(mc):
    mc.record_model_accuracy(brier_score=0.10, accuracy=0.95, league="EPL", model_version="3.0")
    assert len(mc._calibration_drift_alerts) == 0


def test_record_model_accuracy_brier_alert(mc):
    mc.record_model_accuracy(
        brier_score=0.20,
        accuracy=0.95,
        league="EPL",
        model_version="3.0",
        brier_threshold=0.13,
        accuracy_threshold=0.90,
    )
    assert len(mc._calibration_drift_alerts) == 1
    alert = mc._calibration_drift_alerts[0]
    assert alert["brier_exceeded"] is True
    assert alert["accuracy_below"] is False


def test_record_model_accuracy_accuracy_alert(mc):
    mc.record_model_accuracy(
        brier_score=0.10,
        accuracy=0.80,
        league="Bundesliga",
        model_version="3.0",
        brier_threshold=0.13,
        accuracy_threshold=0.90,
    )
    assert len(mc._calibration_drift_alerts) == 1
    assert mc._calibration_drift_alerts[0]["accuracy_below"] is True


def test_record_model_accuracy_trim_alerts(mc):
    for i in range(55):
        mc.record_model_accuracy(
            0.20,
            0.80,
            "EPL",
            f"v{i}",
            brier_threshold=0.13,
            accuracy_threshold=0.90,
        )
    assert len(mc._calibration_drift_alerts) == 50


def test_analysis_and_provider_metrics_are_bounded_and_payload_free(mc):
    mc.record_analysis_state(
        prediction_available=False,
        evidence_completeness=1.5,
        abstention_reason="COHERENT_1X2_MARKET_UNAVAILABLE",
        calibration_status="UNKNOWN",
        duration_ms=12.5,
    )
    mc.record_provider_outcome(
        provider="The Odds API",
        outcome="failed",
        duration_ms=4.0,
        cache_tier="memory",
        circuit_state="open",
        schema_rejected=True,
    )

    summary = mc.get_summary()
    assert summary["counters"]["analysis.prediction.unavailable"] == 1
    assert summary["histograms"]["analysis.evidence_completeness"]["max"] == 1.0
    assert summary["counters"]["provider.the_odds_api.schema_rejected"] == 1


def test_error_metrics_redact_credentials(mc):
    mc.record_error(
        "ProviderError",
        "redis://user:super-secret-password@example.test:6379/0",
        {"authorization": "Bearer secret-token"},
    )
    assert "super-secret-password" not in mc._errors[0]["message"]
    assert "secret-token" not in str(mc._errors[0]["context"])


# ── get_summary ───────────────────────────────────────────────────────────────

def test_get_summary_empty(mc):
    summary = mc.get_summary()
    assert "uptime_seconds" in summary
    assert "counters" in summary
    assert "gauges" in summary
    assert "recent_errors" in summary


def test_get_summary_with_histograms(mc):
    for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
        mc.record_histogram("latency", v)
    summary = mc.get_summary()
    assert "histograms" in summary
    assert "latency" in summary["histograms"]
    h = summary["histograms"]["latency"]
    assert h["count"] == 5
    assert h["min"] == 1.0
    assert h["max"] == 5.0


def test_get_summary_with_timers(mc):
    mc.record_timer("inference", 100.0)
    mc.record_timer("inference", 200.0)
    summary = mc.get_summary()
    assert "timers" in summary
    t = summary["timers"]["inference"]
    assert t["count"] == 2
    assert t["min_ms"] == 100.0


def test_get_summary_with_scrapers(mc):
    mc.record_scraper_call("understat", 50.0, success=True)
    mc.record_scraper_call("understat", 70.0, success=False)
    summary = mc.get_summary()
    assert "scrapers" in summary
    s = summary["scrapers"]["understat"]
    assert s["calls"] == 2
    assert s["errors"] == 1
    assert s["error_rate"] == 0.5


def test_get_summary_with_predictions(mc):
    mc.record_prediction(100.0, 0.72, value_bets=2, edge=0.09, cache_hit=False)
    mc.record_prediction(50.0, 0.68, cache_hit=True)
    summary = mc.get_summary()
    assert "predictions" in summary
    p = summary["predictions"]
    assert p["total"] == 2
    assert p["cache_hits"] == 1
    assert p["cache_misses"] == 1
    assert p["value_bets_found"] == 2
    assert "avg_edge" in p


def test_get_summary_with_model_accuracy(mc):
    mc.record_model_accuracy(0.10, 0.92, "EPL", "3.0")
    summary = mc.get_summary()
    assert "model_accuracy" in summary
    ma = summary["model_accuracy"]
    assert "brier" in ma
    assert "accuracy" in ma
    assert ma["calibration_alerts"] == 0


# ── reset ────────────────────────────────────────────────────────────────────

def test_reset_clears_all_state(mc):
    mc.increment("requests")
    mc.set_gauge("depth", 5.0)
    mc.record_error("E", "msg")
    mc.record_prediction(10.0, 0.7, cache_hit=True)
    mc.reset()
    assert not mc._counters
    assert not mc._gauges
    assert not mc._errors
    assert mc._cache_hits == 0
    assert mc._prediction_latencies == []


# ── monitor_latency decorator ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_monitor_latency_async():
    @monitor_latency("test_op")
    async def my_async_func():
        return 42

    result = await my_async_func()
    assert result == 42


def test_monitor_latency_sync():
    @monitor_latency("test_sync_op")
    def my_sync_func():
        return "ok"

    result = my_sync_func()
    assert result == "ok"


@pytest.mark.asyncio
async def test_monitor_latency_async_error():
    @monitor_latency("test_error_op")
    async def failing():
        raise ValueError("fail")

    with pytest.raises(ValueError):
        await failing()


# ── monitor_scraper decorator ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_monitor_scraper_async_success():
    @monitor_scraper("test_scraper")
    async def scraper():
        return "data"

    result = await scraper()
    assert result == "data"


def test_monitor_scraper_sync_success():
    @monitor_scraper("sync_scraper")
    def scraper():
        return "sync_data"

    result = scraper()
    assert result == "sync_data"
