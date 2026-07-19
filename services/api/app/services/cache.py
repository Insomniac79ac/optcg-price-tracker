"""Short-lived caching for expensive read endpoints (dashboard overview,
collection valuation, market opportunities/signals/reports, ...) - see
'Cache operations' in docs/operations.md. Redis-backed by default, with an
in-memory fallback for local development only; production never silently
switches backend on a Redis hiccup - an individual operation just fails
closed (log + treat as uncached), so a Redis outage degrades response times,
not correctness (see _with_backend below).

Every stored value must be JSON-serializable - callers pass/receive plain
dicts, typically a pydantic model's `.model_dump(mode="json")`. Every cache
key this module touches is namespaced under KEY_PREFIX so admin-triggered
clears (see GET/POST /admin/cache) can never reach into REDIS_URL's other
tenants - Celery uses the same Redis instance as its broker/result backend
(see app.services.refresh_trigger), and this module must not be able to
delete those keys.

Cache reads/writes never raise: a backend failure or serialization failure
is logged (throttled - see _throttle below, since the same failure tends to
repeat on every request) and treated as a cache miss / no-op, so callers
always get a correct (if uncached) response instead of a 500.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.env import is_development_environment
from app.services.app_logging import record_app_log
from app.settings import settings

logger = logging.getLogger(__name__)

KEY_PREFIX = "occache"

BACKEND_VALUES = ("redis", "memory", "none")

# Debounces how often a given failure class becomes an app_log_events row -
# the underlying condition (Redis down, a value that can't be JSON-encoded)
# tends to repeat on every single request, and logging every occurrence
# would flood app_log_events without adding information beyond "still
# happening". A row is written at most once per _FAILURE_LOG_INTERVAL_SECONDS
# per distinct failure class (event_type).
_FAILURE_LOG_INTERVAL_SECONDS = 300


class _FailureLogThrottle:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_logged: dict[str, float] = {}

    def should_log(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            last = self._last_logged.get(key, 0.0)
            if now - last >= _FAILURE_LOG_INTERVAL_SECONDS:
                self._last_logged[key] = now
                return True
            return False


_throttle = _FailureLogThrottle()


def _log_throttled(event_type: str, message: str, *, context: dict[str, Any] | None = None) -> None:
    logger.warning("cache: %s: %s", event_type, message)
    if _throttle.should_log(event_type):
        record_app_log("warning", "api", event_type, message, context=context)


class _Stats:
    """Per-process hit/miss counters, same single-instance limitation as
    app.core.rate_limit's counters - good enough for the admin cache status
    page, not a cross-process metric."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def record_hit(self) -> None:
        with self._lock:
            self.hits += 1

    def record_miss(self) -> None:
        with self._lock:
            self.misses += 1

    def snapshot(self) -> tuple[int, int]:
        with self._lock:
            return self.hits, self.misses


_stats = _Stats()


class _CacheBackend:
    name = "none"

    def get(self, key: str) -> str | None:
        raise NotImplementedError

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def delete_prefix(self, prefix: str) -> int:
        raise NotImplementedError

    def count_keys(self) -> int:
        raise NotImplementedError


class _NoneCacheBackend(_CacheBackend):
    name = "none"

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        return None

    def delete(self, key: str) -> None:
        return None

    def delete_prefix(self, prefix: str) -> int:
        return 0

    def count_keys(self) -> int:
        return 0


class _MemoryCacheBackend(_CacheBackend):
    """Dev-only fallback (see module docstring) - a plain dict with per-key
    expiry, checked lazily on read. Not shared across processes/restarts."""

    name = "memory"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, key: str) -> str | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + max(1, ttl_seconds), value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def delete_prefix(self, prefix: str) -> int:
        match = f"{prefix}:"
        with self._lock:
            keys = [k for k in self._store if k == prefix or k.startswith(match)]
            for k in keys:
                del self._store[k]
            return len(keys)

    def count_keys(self) -> int:
        now = time.monotonic()
        with self._lock:
            expired = [k for k, (expires_at, _v) in self._store.items() if expires_at <= now]
            for k in expired:
                del self._store[k]
            return len(self._store)


class _RedisCacheBackend(_CacheBackend):
    name = "redis"

    def __init__(self, redis_url: str) -> None:
        import redis  # local import: this module must stay importable even

        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def get(self, key: str) -> str | None:
        return self._client.get(key)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._client.set(key, value, ex=max(1, ttl_seconds))

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        for found_key in self._client.scan_iter(match=f"{prefix}:*", count=200):
            self._client.delete(found_key)
            deleted += 1
        # A bare prefix with no trailing segment can itself be a literal key
        # (e.g. "occache:market_report:latest" cleared via prefix
        # "occache:market_report").
        if self._client.delete(prefix):
            deleted += 1
        return deleted

    def count_keys(self) -> int:
        return sum(1 for _ in self._client.scan_iter(match=f"{KEY_PREFIX}:*", count=200))


_memory_fallback: _MemoryCacheBackend | None = None
_redis_backend: _RedisCacheBackend | None = None
_using_fallback = False


def _configured_backend_name() -> str:
    name = (settings.CACHE_BACKEND or "redis").strip().lower()
    return name if name in BACKEND_VALUES else "redis"


def current_backend_name() -> str:
    """The backend actually in effect right now - differs from
    CACHE_BACKEND only when development has fallen back to memory after a
    Redis failure (see _with_backend)."""
    if not settings.CACHE_ENABLED:
        return "none"
    configured = _configured_backend_name()
    if configured == "redis" and _using_fallback:
        return "memory"
    return configured


def _get_redis_backend() -> _RedisCacheBackend:
    global _redis_backend
    if _redis_backend is None:
        _redis_backend = _RedisCacheBackend(settings.REDIS_URL)
    return _redis_backend


def _get_memory_fallback() -> _MemoryCacheBackend:
    global _memory_fallback
    if _memory_fallback is None:
        _memory_fallback = _MemoryCacheBackend()
    return _memory_fallback


def _backend_for(name: str) -> _CacheBackend:
    if name == "none":
        return _NoneCacheBackend()
    if name == "memory":
        return _get_memory_fallback()
    return _get_redis_backend()


def _handle_backend_failure(exc: Exception) -> _CacheBackend | None:
    """Called when a redis operation raises. In development, falls back to
    the in-memory backend for subsequent calls (logged once via
    'redis_unavailable_fallback') and returns it so the current call can be
    retried against it. Outside development, returns None - the caller
    treats this single operation as uncached and will simply try Redis
    again on the next request (self-healing once Redis recovers), per 'Do
    not cache: ... Fallback to in-memory cache only in development'."""
    global _using_fallback
    if is_development_environment():
        if not _using_fallback:
            _using_fallback = True
            _log_throttled(
                "redis_unavailable_fallback",
                f"Redis unavailable, falling back to in-memory cache (development only): {exc}",
            )
        return _get_memory_fallback()
    _log_throttled("cache_backend_failure", f"Cache backend operation failed: {exc}")
    return None


def _active_backend() -> _CacheBackend | None:
    """Returns the backend to use for this call, or None if caching is
    disabled outright (CACHE_ENABLED=false or CACHE_BACKEND=none)."""
    if not settings.CACHE_ENABLED:
        return None
    configured = _configured_backend_name()
    if configured == "none":
        return None
    if configured == "memory":
        return _get_memory_fallback()
    if _using_fallback and is_development_environment():
        return _get_memory_fallback()
    return _get_redis_backend()


def _full_key(key: str) -> str:
    return f"{KEY_PREFIX}:{key}"


def _full_prefix(prefix: str) -> str:
    return f"{KEY_PREFIX}:{prefix}"


def get_cache(key: str) -> Any | None:
    """Returns the cached value for key, or None on a miss or any backend
    failure. Never raises."""
    backend = _active_backend()
    if backend is None:
        return None

    full_key = _full_key(key)
    try:
        raw = backend.get(full_key)
    except Exception as exc:  # noqa: BLE001 - backend failures must never propagate
        fallback = _handle_backend_failure(exc)
        if fallback is None:
            return None
        try:
            raw = fallback.get(full_key)
        except Exception:  # noqa: BLE001 - even the fallback must never raise
            return None

    if raw is None:
        return None
    try:
        envelope = json.loads(raw)
    except (TypeError, ValueError) as exc:
        _log_throttled("cache_serialization_failure", f"Failed to decode cached value: {exc}")
        return None
    return envelope.get("value")


def set_cache(key: str, value: Any, ttl_seconds: int) -> None:
    """Stores value (with a cached_at timestamp) under key with the given
    TTL. No-op on any serialization or backend failure - callers should not
    need to check a return value; a failed write just means the next read
    is a miss."""
    backend = _active_backend()
    if backend is None:
        return

    envelope = {"cached_at": datetime.now(timezone.utc).isoformat(), "value": value}
    try:
        raw = json.dumps(envelope)
    except (TypeError, ValueError) as exc:
        _log_throttled(
            "cache_serialization_failure",
            f"Failed to JSON-encode value for cache key {key!r}: {exc}",
        )
        return

    full_key = _full_key(key)
    try:
        backend.set(full_key, raw, ttl_seconds)
    except Exception as exc:  # noqa: BLE001 - backend failures must never propagate
        fallback = _handle_backend_failure(exc)
        if fallback is None:
            return
        try:
            fallback.set(full_key, raw, ttl_seconds)
        except Exception:  # noqa: BLE001 - even the fallback must never raise
            return


def delete_cache(key: str) -> None:
    backend = _active_backend()
    if backend is None:
        return
    full_key = _full_key(key)
    try:
        backend.delete(full_key)
    except Exception as exc:  # noqa: BLE001 - backend failures must never propagate
        fallback = _handle_backend_failure(exc)
        if fallback is not None:
            try:
                fallback.delete(full_key)
            except Exception:  # noqa: BLE001
                pass


def delete_cache_prefix(prefix: str) -> int:
    """Deletes every cached key under prefix (":"-delimited, plus a literal
    key exactly matching prefix). Returns the number of keys deleted, or 0
    if caching is disabled/unavailable. Safe to call even when nothing
    matches."""
    backend = _active_backend()
    if backend is None:
        return 0
    full_prefix = _full_prefix(prefix)
    try:
        return backend.delete_prefix(full_prefix)
    except Exception as exc:  # noqa: BLE001 - backend failures must never propagate
        fallback = _handle_backend_failure(exc)
        if fallback is None:
            return 0
        try:
            return fallback.delete_prefix(full_prefix)
        except Exception:  # noqa: BLE001
            return 0


def clear_all_cache() -> int:
    """Deletes every key this module has ever written (under KEY_PREFIX)
    across whichever backend is currently active - used by POST
    /admin/cache/clear when no prefix is given. Never touches Celery's own
    Redis keys, which live outside KEY_PREFIX."""
    backend = _active_backend()
    if backend is None:
        return 0
    try:
        return backend.delete_prefix(KEY_PREFIX)
    except Exception as exc:  # noqa: BLE001
        fallback = _handle_backend_failure(exc)
        if fallback is None:
            return 0
        try:
            return fallback.delete_prefix(KEY_PREFIX)
        except Exception:  # noqa: BLE001
            return 0


def get_or_set_cache(
    key: str, ttl_seconds: int, factory: Callable[[], Any]
) -> tuple[Any, bool]:
    """Returns (value, was_hit). On a cache hit, value is the decoded cached
    payload. On a miss (or when caching is disabled/unavailable), calls
    factory() to compute the real value, best-effort stores it, and returns
    it with was_hit=False. factory() is always the source of truth - a
    caching failure never changes what's returned, only whether it was
    cached."""
    cached = get_cache(key)
    if cached is not None:
        _stats.record_hit()
        return cached, True

    _stats.record_miss()
    value = factory()
    set_cache(key, value, ttl_seconds)
    return value, False


def cache_stats() -> dict[str, int]:
    backend = _active_backend()
    keys = 0
    if backend is not None:
        try:
            keys = backend.count_keys()
        except Exception as exc:  # noqa: BLE001
            _log_throttled("cache_backend_failure", f"Failed to count cache keys: {exc}")
            keys = 0
    hits, misses = _stats.snapshot()
    return {"keys": keys, "hits": hits, "misses": misses}


def redis_ping() -> bool:
    """True if the configured Redis instance responds to PING right now.
    Used only by GET /admin/system-check's read-only diagnostic sweep (see
    app.services.system_check) - unlike every other function in this module,
    a failure here does not fall back to memory or get throttle-logged; the
    system check itself is what reports the problem."""
    try:
        return bool(_get_redis_backend()._client.ping())
    except Exception:
        return False


def reset_state_for_tests() -> None:
    """Test-only helper: clears the module-level backend singletons/fallback
    flag/stats so each test starts from a clean slate regardless of import
    order. Not used by any production code path."""
    global _redis_backend, _memory_fallback, _using_fallback
    _redis_backend = None
    _memory_fallback = None
    _using_fallback = False
    _stats.hits = 0
    _stats.misses = 0
