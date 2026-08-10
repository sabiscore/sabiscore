import pytest
from unittest.mock import patch, MagicMock
from src.core.cache import RedisCache

@pytest.fixture
def mocked_cache():
    with patch('src.core.cache.redis.Redis'):
        cache = RedisCache()
        cache._enabled = True  # Force enable
        cache._redis_available = True  # Mark as available
        cache.redis_client = MagicMock()
        yield cache

def test_cache_get(mocked_cache):
    # Setup mock
    mocked_cache.redis_client.get.return_value = b'{"test": "data"}'
    
    # Test
    result = mocked_cache.get("test_key")
    assert result == {"test": "data"}
    mocked_cache.redis_client.get.assert_called_once_with("test_key")

def test_cache_set(mocked_cache):
    # Test
    assert mocked_cache.set("test_key", {"test": "data"}) is True
    mocked_cache.redis_client.setex.assert_called_once()
