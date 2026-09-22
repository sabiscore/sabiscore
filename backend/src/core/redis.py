"""
Redis Connection Utility
Async Redis client for caching xG chains, features, and live match data
"""

import logging
from typing import Optional
import redis.asyncio as redis
from contextlib import asynccontextmanager

from ..core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Async Redis client wrapper with connection pooling"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        decode_responses: bool = True,
    ):
        """Initialize Redis client

        Args:
            host: Redis host
            port: Redis port
            db: Database number
            password: Redis password (if required)
            decode_responses: Auto-decode responses to strings
        """
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.decode_responses = decode_responses
        self._client: Optional[redis.Redis] = None
        self._pool: Optional[redis.ConnectionPool] = None

    async def connect(self) -> redis.Redis:
        """Establish Redis connection with pool

        Returns:
            Redis client instance
        """
        if self._client is None:
            try:
                self._pool = redis.ConnectionPool(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    decode_responses=self.decode_responses,
                    max_connections=50,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                )

                self._client = redis.Redis(connection_pool=self._pool)

                # Test connection
                await self._client.ping()
                logger.info(f"Redis connected: {self.host}:{self.port}/{self.db}")

            except Exception as e:
                logger.error(f"Redis connection failed: {e}")
                raise

        return self._client

    async def disconnect(self):
        """Close Redis connection and pool"""
        if self._client:
            await self._client.aclose()
            self._client = None

        if self._pool:
            await self._pool.aclose()
            self._pool = None

        logger.info("Redis disconnected")

    async def get_client(self) -> redis.Redis:
        """Get connected Redis client

        Returns:
            Redis client (connects if needed)
        """
        if self._client is None:
            await self.connect()
        return self._client

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> bool:
        """Set key with TTL

        Args:
            key: Redis key
            value: Value to store
            ttl_seconds: Time-to-live in seconds

        Returns:
            True if successful
        """
        try:
            client = await self.get_client()
            await client.setex(key, ttl_seconds, value)
            return True
        except Exception as e:
            logger.error(f"Redis SET error: {e}")
            return False

    async def get(self, key: str) -> Optional[str]:
        """Get value by key

        Args:
            key: Redis key

        Returns:
            Value or None if not found
        """
        try:
            client = await self.get_client()
            return await client.get(key)
        except Exception as e:
            logger.error(f"Redis GET error: {e}")
            return None

    async def delete(self, key: str) -> bool:
        """Delete key

        Args:
            key: Redis key

        Returns:
            True if deleted
        """
        try:
            client = await self.get_client()
            result = await client.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis DELETE error: {e}")
            return False

    async def exists(self, key: str) -> bool:
        """Check if key exists

        Args:
            key: Redis key

        Returns:
            True if exists
        """
        try:
            client = await self.get_client()
            result = await client.exists(key)
            return result > 0
        except Exception as e:
            logger.error(f"Redis EXISTS error: {e}")
            return False

    async def set_hash(
        self, key: str, mapping: dict, ttl_seconds: Optional[int] = None
    ) -> bool:
        """Set hash with optional TTL

        Args:
            key: Redis key
            mapping: Dictionary to store
            ttl_seconds: Optional TTL

        Returns:
            True if successful
        """
        try:
            client = await self.get_client()
            await client.hset(key, mapping=mapping)

            if ttl_seconds:
                await client.expire(key, ttl_seconds)

            return True
        except Exception as e:
            logger.error(f"Redis HSET error: {e}")
            return False

    async def get_hash(self, key: str) -> Optional[dict]:
        """Get hash by key

        Args:
            key: Redis key

        Returns:
            Dictionary or None
        """
        try:
            client = await self.get_client()
            return await client.hgetall(key)
        except Exception as e:
            logger.error(f"Redis HGETALL error: {e}")
            return None


# Global Redis client instance
_redis_client: Optional[RedisClient] = None


def get_redis_client() -> RedisClient:
    """Get global Redis client instance

    Returns:
        RedisClient singleton
    """
    global _redis_client

    if _redis_client is None:
        redis_config = getattr(settings, "redis", {})
        _redis_client = RedisClient(
            host=redis_config.get("host", "localhost"),
            port=redis_config.get("port", 6379),
            db=redis_config.get("db", 0),
            password=redis_config.get("password"),
        )

    return _redis_client


@asynccontextmanager
async def redis_session():
    """Async context manager for Redis operations

    Usage:
        async with redis_session() as client:
            await client.set("key", "value")
    """
    client = get_redis_client()
    try:
        await client.connect()
        yield await client.get_client()
    finally:
        # Don't disconnect - reuse connection pool
        pass


# Cache key builders for consistent naming
class CacheKeys:
    """Redis cache key builders"""

    @staticmethod
    def xg_chain(match_id: str) -> str:
        """xG chain cache key"""
        return f"xg:{match_id}"

    @staticmethod
    def features(match_id: str) -> str:
        """Features cache key"""
        return f"features:{match_id}"

    @staticmethod
    def hot_match(match_id: str) -> str:
        """Hot match data cache key"""
        return f"hot:match:{match_id}"

    @staticmethod
    def live_prediction(match_id: str) -> str:
        """Live prediction cache key"""
        return f"live:prediction:{match_id}"

    @staticmethod
    def odds_snapshot(match_id: str, bookmaker: str) -> str:
        """Odds snapshot cache key"""
        return f"odds:{match_id}:{bookmaker}"

    @staticmethod
    def calibration_params() -> str:
        """Calibration parameters cache key"""
        return "calibration:params"


# TTL constants (in seconds)
class CacheTTL:
    """Cache TTL policies"""

    XG_CHAIN = 30  # 30 seconds for live xG
    FEATURES = 60  # 1 minute for features
    HOT_MATCH = 5  # 5 seconds for hot data
    LIVE_PREDICTION = 15  # 15 seconds for predictions
    ODDS = 2  # 2 seconds for odds
    CALIBRATION = 180  # 3 minutes for calibration params


if __name__ == "__main__":
    import asyncio

    async def test():
        # Test Redis connection
        async with redis_session() as client:
            # Set test key
            await client.set("test:key", "test_value", ex=60)

            # Get test key
            value = await client.get("test:key")
            print(f"Retrieved: {value}")

            # Set hash
            redis_client = get_redis_client()
            await redis_client.set_hash(
                CacheKeys.hot_match("test_123"),
                {"home_score": "2", "away_score": "1"},
                ttl_seconds=CacheTTL.HOT_MATCH,
            )

            # Get hash
            match_data = await redis_client.get_hash(CacheKeys.hot_match("test_123"))
            print(f"Match data: {match_data}")

    asyncio.run(test())
