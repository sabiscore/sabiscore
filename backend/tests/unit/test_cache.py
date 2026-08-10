"""Tests for Redis-backed cache with fallback."""
from unittest.mock import MagicMock, patch
import pytest
import redis

from src.core.cache import RedisCache


@pytest.fixture
def cache():
    """Cache instance with mock Redis client."""
    with patch("redis.Redis.from_url") as mock_redis:
        mock_client = MagicMock(spec=redis.Redis)
        mock_redis.return_value = mock_client
        mock_client.ping.return_value = True
        
        cache = RedisCache()
        cache._enabled = True
        cache.redis_client = mock_client
        yield cache


def test_cache_hit(cache):
    """Test successful cache hit."""
    cache.redis_client.get.return_value = b'"test_value"'
    assert cache.get("test_key") == "test_value"
    assert cache.metrics.hits == 1


def test_cache_miss(cache):
    """Test cache miss behavior."""
    cache.redis_client.get.return_value = None
    assert cache.get("test_key") is None
    assert cache.metrics.misses == 1


def test_cache_fallback(cache):
    """Test memory fallback when Redis fails."""
    cache.redis_client.get.side_effect = redis.RedisError("Test error")
    cache.set("test_key", "fallback_value")
    assert cache.get("test_key") == "fallback_value"
    assert cache.metrics.errors == 1


def test_circuit_breaker(cache):
    """Test circuit breaker trips after errors."""
    cache.redis_client.get.side_effect = redis.RedisError("Test error")
    cache.get("test_key")
    assert cache._circuit_open_until is not None


def test_metrics_snapshot(cache):
    """Test metrics collection with proper hit/miss tracking."""
    # Reset metrics
    cache.metrics.hits = 0
    cache.metrics.misses = 0
    
    # Test miss
    cache.redis_client.get.return_value = None
    cache.get("test_key")
    
    # Test hit
    cache.redis_client.get.return_value = b'"test_value"'
    cache.get("test_key")
    
    metrics = cache.metrics_snapshot()
    assert metrics["hits"] == 1, f"Expected 1 hit, got {metrics['hits']}"
    assert metrics["misses"] == 1, f"Expected 1 miss, got {metrics['misses']}"
    assert not metrics["circuit_open"]


def test_cache_decorator():
    """Test the cache decorator functionality."""
    from src.core.cache import cache_decorator
    
    @cache_decorator(ttl=10)
    def test_func(arg):
        return arg * 2
    
    assert test_func(2) == 4  # Should cache
    assert test_func(2) == 4  # Should hit cache


def test_malformed_redis_url_degrades_to_memory_without_crashing(monkeypatch):
    """A bad deployment secret must not prevent the API module from importing."""
    from src.core.cache import settings

    monkeypatch.setattr(settings, "redis_enabled", True)
    monkeypatch.setattr(settings, "redis_url", "cache.example.com:6379")

    cache = RedisCache()

    assert cache.redis_client is None
    assert cache._enabled is True
    assert cache.production_ready() is False
    assert cache.metrics.errors == 1
    assert cache.set("health", {"status": "degraded"}) is True
    assert cache.get("health") == {"status": "degraded"}


def test_disabled_external_cache_is_ready_by_configuration(monkeypatch):
    from src.core.cache import settings

    monkeypatch.setattr(settings, "redis_enabled", False)
    cache = RedisCache()

    assert cache.production_ready() is True


def test_production_plaintext_redis_is_rejected_without_connection(monkeypatch):
    from src.core.cache import settings

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "redis_enabled", True)
    monkeypatch.setattr(settings, "redis_url", "redis://user:password@cache.example:6379/0")

    with patch("redis.Redis.from_url") as from_url:
        cache = RedisCache()

    from_url.assert_not_called()
    assert cache.production_ready() is False


def test_model_orchestrator_import_performs_no_redis_connection():
    import importlib
    import src.models.orchestrator as module

    with patch("redis.Redis.from_url") as from_url:
        importlib.reload(module)

    from_url.assert_not_called()
