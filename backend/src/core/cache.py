import json
import logging
import pickle
import time
from dataclasses import dataclass
from functools import wraps
from threading import Lock
from typing import Any, Callable, Dict, Optional, Tuple
import hashlib
import fnmatch

import redis
from redis.exceptions import RedisError

from .config import settings
from .redaction import redact_text, safe_endpoint


logger = logging.getLogger(__name__)


class UpstashTier:
    """Tier-2 cache backed by Upstash Redis (Redis-protocol endpoint).

    Activated only when settings.upstash_enabled is True and
    settings.upstash_redis_url is set (rediss://default:token@host:port).
    All operations are best-effort — errors are caught and logged so the
    caller silently falls through to the in-memory tier.
    """

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None
        self._available = False
        self._circuit_open_until: Optional[float] = None

        if not settings.upstash_enabled or not settings.upstash_redis_url:
            return

        try:
            client = redis.Redis.from_url(
                settings.upstash_redis_url,
                max_connections=settings.upstash_max_connections,
                decode_responses=False,
                socket_timeout=3,
                socket_connect_timeout=3,
                retry_on_timeout=False,
            )
            client.ping()
            self._client = client
            self._available = True
            logger.info("Upstash (tier-2) connection established")
        except (RedisError, ConnectionError, TimeoutError) as exc:
            logger.warning("Upstash unavailable, tier-2 disabled: %s", redact_text(exc))

    # ── circuit breaker ────────────────────────────────────────────────────
    def _is_circuit_open(self) -> bool:
        if self._circuit_open_until is None:
            return False
        if time.time() > self._circuit_open_until:
            self._circuit_open_until = None
            return False
        return True

    def _trip(self) -> None:
        self._circuit_open_until = time.time() + 60
        self._available = False
        logger.warning("Upstash circuit opened for 60 s")

    # ── public interface ───────────────────────────────────────────────────
    @property
    def is_active(self) -> bool:
        return self._client is not None and not self._is_circuit_open()

    def get(self, key: str) -> Optional[bytes]:
        if not self.is_active:
            return None
        try:
            value = self._client.get(key)  # type: ignore[union-attr]
            self._available = True
            return value
        except (RedisError, Exception) as exc:
            logger.debug("Upstash get error: %s", redact_text(exc))
            self._trip()
            return None

    def set(self, key: str, value: bytes, ttl: int) -> bool:
        if not self.is_active:
            return False
        try:
            self._client.setex(key, ttl, value)  # type: ignore[union-attr]
            self._available = True
            return True
        except (RedisError, Exception) as exc:
            logger.debug("Upstash set error: %s", redact_text(exc))
            self._trip()
            return False

    def delete(self, key: str) -> None:
        if not self.is_active:
            return
        try:
            self._client.delete(key)  # type: ignore[union-attr]
        except (RedisError, Exception):
            pass

    def clear_pattern(self, pattern: str) -> int:
        if not self.is_active:
            return 0
        try:
            keys = self._client.keys(pattern)  # type: ignore[union-attr]
            if keys:
                return int(self._client.delete(*keys))  # type: ignore[union-attr]
            return 0
        except (RedisError, Exception) as exc:
            logger.debug("Upstash clear_pattern error: %s", redact_text(exc))
            return 0


@dataclass
class CacheMetrics:
    """Simple in-memory metrics tracker for observability hooks."""

    hits: int = 0
    misses: int = 0
    errors: int = 0

    def record_hit(self) -> None:
        self.hits += 1

    def record_miss(self) -> None:
        self.misses += 1

    def record_error(self) -> None:
        self.errors += 1

    def as_dict(self) -> Dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "errors": self.errors,
        }


class RedisCache:
    """3-tier cache: Tier-1 Redis Labs (KV) → Tier-2 Upstash → Tier-3 in-memory.

    Tier fallback rules
    -------------------
    GET: try T1 → on miss/error try T2 → on miss/error try T3.
         A hit in T2 is written back to T1 (refresh).
         A hit in T3 is written back to T1+T2 (refresh).
    SET: write to T1 → T2 → T3 (all tiers, best-effort).
    """

    def __init__(self) -> None:
        self.ttl = settings.redis_cache_ttl
        self.metrics = CacheMetrics()
        self._circuit_open_until: Optional[float] = None
        self._memory_cache: Dict[str, Tuple[Any, Optional[float]]] = {}
        self._lock = Lock()
        # Preserve the operator's configured intent separately from transient
        # connectivity. Readiness must not silently turn REDIS_ENABLED=true
        # into an optional in-process cache after a malformed URL or outage.
        self._enabled = settings.redis_enabled
        self._redis_available = False
        self.redis_client: Optional[redis.Redis] = None
        self._max_memory_entries = 1000  # Prevent unbounded growth

        # Tier-2: Upstash (optional; no-op if not configured)
        self._upstash = UpstashTier()

        if self._enabled:
            try:
                if settings.app_env == "production" and not settings.redis_url.startswith("rediss://"):
                    raise ValueError("production Redis requires a rediss:// URL")
                client = redis.Redis.from_url(
                    settings.redis_url,
                    max_connections=settings.redis_max_connections,
                    decode_responses=False,
                    health_check_interval=30,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                    retry_on_error=[ConnectionError]
                )
                client.ping()
                self.redis_client = client
                self._redis_available = True
                logger.info("Redis (tier-1) connection established successfully")
            except (RedisError, ConnectionError, TimeoutError, ValueError) as exc:
                logger.warning(
                    "Redis unavailable at %s, falling back through tier-2/3: %s",
                    safe_endpoint(settings.redis_url),
                    redact_text(exc),
                )
                logger.info(
                    "In-memory cache active with %d entry limit. "
                    "Set REDIS_ENABLED=false to suppress Redis connection attempts.",
                    self._max_memory_entries
                )
                self.metrics.record_error()
                self.redis_client = None

    # Internal helpers -------------------------------------------------
    def _is_circuit_open(self) -> bool:
        if self._circuit_open_until is None:
            return False
        if time.time() > self._circuit_open_until:
            self._circuit_open_until = None
            return False
        return True

    def _trip_circuit(self, cooldown_seconds: int = 30) -> None:
        self._circuit_open_until = time.time() + cooldown_seconds
        logger.warning("Redis circuit opened for %s seconds", cooldown_seconds)

    def _serialize(self, value: Any) -> bytes:
        # Ensure MagicMock or non-JSON-serializable objects don't leak
        try:
            if hasattr(value, "model_dump"):
                value = value.model_dump(mode="json")  # type: ignore[attr-defined]
            return json.dumps(value).encode("utf-8")
        except (TypeError, ValueError):
            return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)

    def _deserialize(self, payload: Optional[bytes]) -> Any:
        if payload is None:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            try:
                return pickle.loads(payload)
            except pickle.UnpicklingError:
                logger.error("Failed to deserialize cache payload")
                self.metrics.record_error()
                return None

    # Public API -------------------------------------------------------
    def get(self, key: str) -> Optional[Any]:
        # ── Tier 1: Redis Labs ────────────────────────────────────────────
        if self._enabled and not self._is_circuit_open() and self.redis_client:
            try:
                payload = self.redis_client.get(key)
                self._redis_available = True
                if payload is not None:
                    self.metrics.record_hit()
                    return self._deserialize(payload)
                # T1 miss — fall through to T2
            except RedisError as exc:
                logger.error("Cache get error (tier-1): %s", redact_text(exc))
                self.metrics.record_error()
                self._trip_circuit()
                self._redis_available = False

        # ── Tier 2: Upstash ───────────────────────────────────────────────
        if self._upstash.is_active:
            payload = self._upstash.get(key)
            if payload is not None:
                value = self._deserialize(payload)
                self.metrics.record_hit()
                # Write-back to T1 so future reads are served from the faster tier
                ttl_value = self.ttl
                self._set_tier1(key, payload, ttl_value)
                self._write_to_memory(key, value, ttl_value)
                return value
            # T2 miss — fall through to T3

        # ── Tier 3: in-memory ─────────────────────────────────────────────
        mem_value = self._read_from_memory(key, record_metrics=False)
        if mem_value is not None:
            self.metrics.record_hit()
            return mem_value

        self.metrics.record_miss()
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        ttl_value = ttl or self.ttl
        payload = self._serialize(value)

        # Write to all available tiers (best-effort)
        self._set_tier1(key, payload, ttl_value)
        if self._upstash.is_active:
            self._upstash.set(key, payload, ttl_value)
        return self._write_to_memory(key, value, ttl_value)

    def _set_tier1(self, key: str, payload: bytes, ttl_value: int) -> None:
        """Write serialized payload to Redis Labs (T1) — best-effort, no exception raised."""
        if not self._enabled or self._is_circuit_open() or not self.redis_client:
            return
        try:
            self.redis_client.setex(key, ttl_value, payload)
            self._redis_available = True
        except RedisError as exc:
            logger.error("Cache set error (tier-1): %s", exc)
            self.metrics.record_error()
            self._trip_circuit()
            self._redis_available = False

    def delete(self, key: str) -> bool:
        deleted = False
        if self._enabled and self.redis_client:
            try:
                deleted = bool(self.redis_client.delete(key))
                self._redis_available = True
            except RedisError as exc:
                logger.error("Cache delete error: %s", exc)
                self.metrics.record_error()
                self._redis_available = False

        self._upstash.delete(key)
        return self._delete_from_memory(key) or deleted

    def exists(self, key: str) -> bool:
        if self._enabled and self.redis_client:
            try:
                if self.redis_client.exists(key):
                    self._redis_available = True
                    return True
            except RedisError as exc:
                logger.error("Cache exists error: %s", exc)
                self.metrics.record_error()
                self._redis_available = False

        value = self._read_from_memory(key, record_metrics=False)
        return value is not None

    def clear_pattern(self, pattern: str) -> int:
        deleted = 0
        if self._enabled and self.redis_client:
            try:
                keys = self.redis_client.keys(pattern)
                if keys:
                    deleted = int(self.redis_client.delete(*keys))
                self._redis_available = True
            except RedisError as exc:
                logger.error("Cache clear pattern error: %s", exc)
                self.metrics.record_error()
                self._redis_available = False
        self._upstash.clear_pattern(pattern)
        deleted += self._purge_memory(pattern)
        return deleted

    def clear_namespace(self, namespace: str) -> int:
        """Clear all keys matching namespace pattern across all tiers."""
        pattern = f"{namespace}:*"
        deleted = 0
        if self._enabled and self.redis_client:
            try:
                keys = self.redis_client.keys(pattern)
                if keys:
                    deleted = int(self.redis_client.delete(*keys))
                self._redis_available = True
            except RedisError as exc:
                logger.error("Namespace clear error: %s", exc)
                self.metrics.record_error()
                self._redis_available = False
        self._upstash.clear_pattern(pattern)
        deleted += self._purge_memory(pattern)
        return deleted

    def ping(self) -> bool:
        if not self._enabled:
            return True
        if not self.redis_client:
            self._redis_available = False
            return bool(self._memory_cache)

        try:
            self._redis_available = bool(self.redis_client.ping())
            return self._redis_available
        except RedisError as exc:
            logger.error("Redis ping failed: %s", exc)
            self.metrics.record_error()
            self._trip_circuit()
            self._redis_available = False
            return bool(self._memory_cache)

    def production_ready(self) -> bool:
        """Return whether the configured production cache dependency is ready.

        In-memory storage preserves process liveness, but it is neither shared
        nor durable. It cannot satisfy readiness when tier-1 Redis is enabled.
        """

        if not self._enabled:
            return True
        if not self.redis_client:
            self._redis_available = False
            return False
        try:
            self._redis_available = bool(self.redis_client.ping())
        except (RedisError, ConnectionError, TimeoutError):
            self._redis_available = False
        return self._redis_available

    def metrics_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            memory_entries = len(self._memory_cache)
        snapshot = self.metrics.as_dict()
        snapshot.update({
            # Tier-1: Redis Labs
            "tier1_redis_enabled": self._enabled,
            "tier1_redis_available": self._redis_available,
            "tier1_circuit_open": bool(self._is_circuit_open()),
            # Tier-2: Upstash
            "tier2_upstash_active": self._upstash.is_active,
            "tier2_upstash_configured": (
                self._upstash._client is not None
            ),
            # Tier-3: in-memory
            "tier3_memory_entries": memory_entries,
            "tier3_memory_limit": self._max_memory_entries,
            # Legacy aliases (backwards-compat for health endpoint)
            "circuit_open": bool(self._is_circuit_open()),
            "memory_entries": memory_entries,
            "backend_enabled": self._enabled,
            "backend_available": self._redis_available,
        })
        return snapshot

    # Memory fallback helpers ------------------------------------------
    def _read_from_memory(self, key: str, record_metrics: bool = True) -> Optional[Any]:
        with self._lock:
            entry = self._memory_cache.get(key)
            if not entry:
                if record_metrics:
                    self.metrics.record_miss()
                return None

            value, expires_at = entry
            if expires_at is not None and expires_at < time.time():
                self._memory_cache.pop(key, None)
                if record_metrics:
                    self.metrics.record_miss()
                return None

        if record_metrics:
            self.metrics.record_hit()
        # Return a deep JSON-friendly copy if possible to avoid test-time mutation or mocks
        try:
            if hasattr(value, "model_dump"):
                return value.model_dump(mode="json")  # type: ignore[attr-defined]
            json_payload = json.dumps(value, default=str)
            return json.loads(json_payload)
        except Exception:
            return value

    def _write_to_memory(self, key: str, value: Any, ttl: Optional[int]) -> bool:
        expires_at = time.time() + ttl if ttl else None
        with self._lock:
            # Enforce memory cache size limit
            if len(self._memory_cache) >= self._max_memory_entries:
                # Remove oldest expired entry or first entry
                now = time.time()
                removed = False
                for k, (_, exp) in list(self._memory_cache.items()):
                    if exp and exp < now:
                        self._memory_cache.pop(k)
                        removed = True
                        break
                if not removed and self._memory_cache:
                    # Remove first entry (FIFO)
                    first_key = next(iter(self._memory_cache))
                    self._memory_cache.pop(first_key)
                    logger.debug(f"Memory cache full, evicted: {first_key}")
            
            self._memory_cache[key] = (value, expires_at)
        return True

    def _delete_from_memory(self, key: str) -> bool:
        with self._lock:
            return self._memory_cache.pop(key, None) is not None

    def _purge_memory(self, pattern: str) -> int:
        removed = 0
        with self._lock:
            for key in list(self._memory_cache.keys()):
                if fnmatch.fnmatch(key, pattern):
                    self._memory_cache.pop(key, None)
                    removed += 1
        return removed


# Global cache instance
cache = RedisCache()

# Alias for backwards compatibility
cache_manager = cache


def cache_decorator(ttl: Optional[int] = None):
    """Decorator to cache function results."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = _make_cache_key(func.__name__, args, kwargs)

            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug("Cache hit for %s", cache_key)
                return cached_result

            result = func(*args, **kwargs)
            if result is not None:
                cache.set(cache_key, result, ttl)
                logger.debug("Cache set for %s", cache_key)

            return result

        return wrapper

    return decorator


def _make_cache_key(prefix: str, args: tuple, kwargs: dict) -> str:
    """Build a deterministic cache key resilient to complex argument types."""

    def _normalize(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return [_normalize(item) for item in value]
        if isinstance(value, dict):
            return {str(k): _normalize(v) for k, v in sorted(value.items())}
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                pass
        if hasattr(value, "to_json"):
            try:
                return json.loads(value.to_json())
            except Exception:
                pass
        return repr(value)

    normalized = {
        "args": _normalize(args),
        "kwargs": _normalize(kwargs),
    }

    digest = hashlib.sha1(json.dumps(normalized, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"cache:{prefix}:{digest}"
