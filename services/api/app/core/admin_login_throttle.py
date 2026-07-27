"""Redis-backed throttling for the temporary admin Credentials login (POST
/auth/admin/verify, see app.api.admin_login) - deliberately separate from
app.core.rate_limit, which is in-memory/per-process and explicitly
documented there as unsuitable for anything that needs to persist across
processes or restarts. A public login endpoint is exactly that case: this
throttle must survive an API restart and be shared across every Railway
replica, or a restart (or round-robin across replicas) would silently reset
an attacker's failure count.

Tracks two independent counters per attempt - the normalized account
identifier (whatever email was submitted, matching ADMIN_LOGIN_EMAIL or
not - see the module docstring on app.api.admin_login for why this must not
be conditioned on a real match) and the caller's IP where available - so the
account-level lockout stays effective even if an attacker spreads attempts
across many source IPs, while the IP-level lockout separately limits blind
guessing across many different email values from one source.

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


def _hash_identifier(value: str) -> str:
    # Identifiers (email, IP) never appear verbatim in Redis key names -
    # consistent with this project's "hash or truncate" convention for
    # anything derived from a request's identity (see app.services.
    # app_logging's REDACT_KEY_SUBSTRINGS for the equivalent in stored
    # logs). Truncated to 16 hex chars: collision-resistant enough for a
    # throttle key namespace, not a security boundary in itself.
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _account_key(email_normalized: str, suffix: str) -> str:
    return f"{KEY_PREFIX}:acct:{_hash_identifier(email_normalized)}:{suffix}"


def _ip_key(ip: str, suffix: str) -> str:
    return f"{KEY_PREFIX}:ip:{_hash_identifier(ip)}:{suffix}"


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


def check_locked(email_normalized: str, ip: str | None) -> ThrottleStatus:
    """Raises redis.RedisError on backend failure - see module docstring;
    callers must treat that as "deny the attempt", not "not locked"."""
    client = _get_client()
    retry_after = 0

    acct_ttl = client.ttl(_account_key(email_normalized, "lock"))
    if acct_ttl and acct_ttl > 0:
        retry_after = max(retry_after, acct_ttl)

    if ip:
        ip_ttl = client.ttl(_ip_key(ip, "lock"))
        if ip_ttl and ip_ttl > 0:
            retry_after = max(retry_after, ip_ttl)

    return ThrottleStatus(locked=retry_after > 0, retry_after_seconds=retry_after)


def _record_failure_for(client: redis.Redis, fails_key: str, lock_key: str) -> None:
    count = client.incr(fails_key)
    if count == 1:
        client.expire(fails_key, settings.ADMIN_LOGIN_WINDOW_SECONDS)
    if count >= settings.ADMIN_LOGIN_MAX_ATTEMPTS:
        client.setex(lock_key, settings.ADMIN_LOGIN_LOCKOUT_SECONDS, "1")


def record_failure(email_normalized: str, ip: str | None) -> None:
    """Raises redis.RedisError on backend failure - see module docstring."""
    client = _get_client()
    _record_failure_for(
        client, _account_key(email_normalized, "fails"), _account_key(email_normalized, "lock")
    )
    if ip:
        _record_failure_for(client, _ip_key(ip, "fails"), _ip_key(ip, "lock"))


def clear_account_failures(email_normalized: str) -> None:
    """Called on a successful login - clears only the account counter/lock,
    never the IP one (a shared office/NAT IP with other, unrelated failed
    attempts should not have its own counter wiped by someone else's
    successful login - see 'Successful login may clear the account failure
    counter' in the task spec, which is account-scoped, not IP-scoped).
    Raises redis.RedisError on backend failure."""
    client = _get_client()
    client.delete(_account_key(email_normalized, "fails"))
    client.delete(_account_key(email_normalized, "lock"))
