"""Regression: a malformed/unconfigured REDIS_URL must never crash ModelOrchestrator.

Live incident (2026-08-10): `redis.from_url()` in ModelOrchestrator.__init__ was
unguarded, so any import of `src.models` (triggered by any request-path import of
`models.feature_registry`) crashed the whole process at startup when REDIS_URL was
invalid, unset, or unreachable. Mirrors the tiered-fallback pattern in
core/cache.py.
"""

from src.models.orchestrator import ModelOrchestrator, _InMemoryRedisAdapter


def _is_in_memory_adapter(value: object) -> bool:
    """Avoid brittle class-identity checks across module reloads in full-suite runs."""

    klass = value.__class__
    return klass.__name__ == "_InMemoryRedisAdapter" and klass.__module__.endswith(
        "models.orchestrator"
    )


def test_malformed_redis_url_degrades_to_in_memory_adapter():
    orchestrator = ModelOrchestrator(redis_url="not-a-valid-url")
    assert _is_in_memory_adapter(orchestrator.redis)


def test_unreachable_redis_url_degrades_to_in_memory_adapter():
    orchestrator = ModelOrchestrator(redis_url="redis://localhost:1/0")
    assert _is_in_memory_adapter(orchestrator.redis)


def test_redis_fallback_logs_a_redacted_endpoint(caplog):
    secret_url = "redis://alice:top-secret@localhost:1/0"

    ModelOrchestrator(redis_url=secret_url)

    assert "top-secret" not in caplog.text
    assert "redis://localhost:1" in caplog.text


def test_in_memory_adapter_supports_league_model_cache_calls():
    adapter = _InMemoryRedisAdapter()
    adapter.setex("k", 60, "v")
    assert adapter.get("k") == "v"
    adapter.lpush("l", "a")
    adapter.lpush("l", "b")
    assert adapter.llen("l") == 2
    assert adapter.lrange("l", 0, -1) == ["b", "a"]
    adapter.ltrim("l", 0, 0)
    assert adapter.llen("l") == 1
