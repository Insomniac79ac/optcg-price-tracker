"""Redis-backed throttling for the temporary admin Credentials login (POST
/auth/admin/verify, see app.api.admin_login) - deliberately separate from
app.core.rate_limit, which is in-memory/per-process and explicitly
documented there as unsuitable for anything that needs to persist across
processes or restarts. A public login endpoint is exactly that case: this
throttle must survive an API restart and be shared across every Railway
replica, or a restart (or round-robin across replicas) would silently reset
an attacker's failure count.

Tracks three independent counters per attempt. The account identifier is
the normalized email that was submitted, matching ADMIN_LOGIN_EMAIL or not
(see the module docstring on app.api.admin_login for why this must not be
conditioned on a real match). The client is the key from
app.core.client_ip (never None; a missing or invalid client address is the
shared unverified key):

- (a) email plus client: ADMIN_LOGIN_MAX_ATTEMPTS per
  ADMIN_LOGIN_WINDOW_SECONDS, then an ADMIN_LOGIN_LOCKOUT_SECONDS lock.
  Stops one source quickly without locking the account for everyone.
- (b) client across all emails: the same three settings.
- (c) the account across all clients: ACCOUNT_MAX_ATTEMPTS per
  ACCOUNT_WINDOW_SECONDS, then an ACCOUNT_LOCKOUT_SECONDS lock, so the
  account still has a ceiling when attempts come from many sources.

A successful login clears (a) for that email and client, and (c) for that
email, never (b). There is no other reset: a lock expires on its own.

Unlike app.services.cache (which fails open/silently on a Redis error - a
cache miss is harmless), every function here lets a redis.RedisError
propagate. A login endpoint that could silently skip throttling during a
Redis outage would let a brute-force window open exactly when observability
into it is also degraded - callers (app.api.admin_login) must catch this and
fail *closed* (deny the attempt with a generic "temporarily unavailable"
response), not fail open.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import redis

from app.settings import settings

KEY_PREFIX = "adminlogin"

# Counter (c), per account across all clients (owner decision): 20 failed
# attempts per hour, then a 30 minute lock.
ACCOUNT_MAX_ATTEMPTS = 20
ACCOUNT_WINDOW_SECONDS = 3600
ACCOUNT_LOCKOUT_SECONDS = 1800


def _hash_identifier(value: str) -> str:
    # Identifiers (email, IP) never appear verbatim in Redis key names -
    # consistent with this project's "hash or truncate" convention for
    # anything derived from a request's identity (see app.services.
    # app_logging's REDACT_KEY_SUBSTRINGS for the equivalent in stored
    # logs). Truncated to 16 hex chars: collision-resistant enough for a
    # throttle key namespace, not a security boundary in itself.
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _pair_key(email_normalized: str, client: str, suffix: str) -> str:
    return f"{KEY_PREFIX}:pair:{_hash_identifier(email_normalized + chr(10) + client)}:{suffix}"


def _ip_key(client: str, suffix: str) -> str:
    return f"{KEY_PREFIX}:ip:{_hash_identifier(client)}:{suffix}"


def _account_key(email_normalized: str, suffix: str) -> str:
    # "account", not the earlier "acct" shape: keys written under the old
    # rule are left to expire on their own.
    return f"{KEY_PREFIX}:account:{_hash_identifier(email_normalized)}:{suffix}"


_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        # Short socket timeouts: a login request must not hang waiting on a
        # half-dead Redis connection - a fast failure lets the caller return
        # its generic "unavailable" response promptly instead.
        _client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


def reset_state_for_tests() -> None:
    """Test-only: drops the cached client so a monkeypatched REDIS_URL (or
    a fakeredis substitute) takes effect on the next call."""
    global _client
    _client = None


@dataclass(frozen=True)
class ThrottleStatus:
    locked: bool
    retry_after_seconds: int


def _require_client(ip: str) -> str:
    # The caller always passes a key (app.core.client_ip maps a missing
    # address to the shared unverified key); an empty one is a bug.
    if not ip:
        raise ValueError("admin login throttle needs a client key")
    return ip


def check_locked(email_normalized: str, ip: str) -> ThrottleStatus:
    """Raises redis.RedisError on backend failure - see module docstring;
    callers must treat that as "deny the attempt", not "not locked"."""
    ip = _require_client(ip)
    client = _get_client()
    retry_after = 0
    for lock_key in (
        _pair_key(email_normalized, ip, "lock"),
        _ip_key(ip, "lock"),
        _account_key(email_normalized, "lock"),
    ):
        ttl = client.ttl(lock_key)
        if ttl and ttl > 0:
            retry_after = max(retry_after, ttl)
    return ThrottleStatus(locked=retry_after > 0, retry_after_seconds=retry_after)


def _record_failure_for(
    client: redis.Redis, fails_key: str, lock_key: str, max_attempts: int, window: int, lockout: int
) -> None:
    count = client.incr(fails_key)
    if count == 1:
        client.expire(fails_key, window)
    if count >= max_attempts:
        client.setex(lock_key, lockout, "1")


def record_failure(email_normalized: str, ip: str) -> None:
    """Raises redis.RedisError on backend failure - see module docstring."""
    ip = _require_client(ip)
    client = _get_client()
    per_source = (
        settings.ADMIN_LOGIN_MAX_ATTEMPTS,
        settings.ADMIN_LOGIN_WINDOW_SECONDS,
        settings.ADMIN_LOGIN_LOCKOUT_SECONDS,
    )
    _record_failure_for(
        client, _pair_key(email_normalized, ip, "fails"), _pair_key(email_normalized, ip, "lock"), *per_source
    )
    _record_failure_for(client, _ip_key(ip, "fails"), _ip_key(ip, "lock"), *per_source)
    _record_failure_for(
        client,
        _account_key(email_normalized, "fails"),
        _account_key(email_normalized, "lock"),
        ACCOUNT_MAX_ATTEMPTS,
        ACCOUNT_WINDOW_SECONDS,
        ACCOUNT_LOCKOUT_SECONDS,
    )


def clear_account_failures(email_normalized: str, ip: str) -> None:
    """Called on a successful login - clears counter (a) for this email and
    client and counter (c) for this email, never the client counter (b) (a
    shared office/NAT address with other, unrelated failed attempts should
    not have its own counter wiped by someone else's successful login).
    Raises redis.RedisError on backend failure."""
    ip = _require_client(ip)
    client = _get_client()
    client.delete(_pair_key(email_normalized, ip, "fails"))
    client.delete(_pair_key(email_normalized, ip, "lock"))
    client.delete(_account_key(email_normalized, "fails"))
    client.delete(_account_key(email_normalized, "lock"))
