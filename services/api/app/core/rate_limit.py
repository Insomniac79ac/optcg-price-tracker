"""In-memory per-IP request rate limiting - no external dependency (no
Redis, no third-party library). Acceptable for a single-server deployment,
where all requests land on the same process; state lives in a module-level
dict, so a multi-instance/distributed deployment would need to move this to
a reverse proxy or a shared store (Redis) instead - see 'Rate limiting' in
docs/deployment.md.

Requests are classified into one of five route groups (see classify_route)
based on path + method, each with its own limit/window read live from
Settings (so tests can monkeypatch settings.RATE_LIMIT_* and see the change
immediately, and so RATE_LIMIT_ENABLED=false can be toggled without a
restart). Within a group, requests are keyed by client IP using a fixed
window counter: cheap, bounded memory, and precise enough for basic abuse
hardening (as opposed to a sliding-log window, which would need unbounded
per-IP timestamp lists).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.services.app_logging import record_app_log
from app.settings import settings

# --- route classification ------------------------------------------------

# Endpoints requiring the admin token - /admin/* by prefix, plus
# /snkrdunk/candidates* which is admin-token-gated (see
# app.api.snkrdunk_candidates) despite not living under /admin in the URL.
# Both Cache-Control: no-store (app.core.security_headers) and the "admin"
# rate-limit group use this same boundary.
ADMIN_PATH_PREFIXES = ("/admin", "/snkrdunk")

# Exact paths that move data in bulk (CSV import/export, backup
# export/validate/restore, the db-backups listing) - stricter/lower limit
# than the general "admin" or "public_read" groups they'd otherwise fall
# into, since these are the most expensive/sensitive operations to abuse.
IMPORT_EXPORT_PATHS = frozenset(
    {
        "/admin/backup/export",
        "/admin/backup/validate",
        "/admin/backup/restore",
        "/admin/db-backups",
        "/collection/import.csv",
        "/collection/export.csv",
        "/wishlist/import.csv",
        "/wishlist/export.csv",
    }
)

SEARCH_PATHS = frozenset({"/search", "/search/suggestions"})

# Non-admin write endpoints for collection/wishlist/grading/notes - see
# app.api.collection, app.api.wishlist, app.api.grading, app.api.collector_notes.
COLLECTION_WRITE_PREFIXES = ("/collection", "/wishlist", "/grading", "/collector/notes")

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Never rate limited - Docker/Compose healthchecks poll this frequently and
# it does no work worth protecting.
EXEMPT_PATHS = frozenset({"/health"})


def is_admin_path(path: str) -> bool:
    return path.startswith(ADMIN_PATH_PREFIXES)


def classify_route(path: str, method: str) -> str | None:
    """Maps a request to one of the five rate-limit groups, or None if it
    isn't rate limited at all (health check, or a write endpoint outside the
    groups the spec defines - e.g. market signal event actions, dashboard
    preference updates - deliberately left uncovered rather than guessing at
    a group for them)."""
    if path in EXEMPT_PATHS:
        return None
    if path in SEARCH_PATHS:
        return "search"
    if path in IMPORT_EXPORT_PATHS:
        return "import_export"
    if is_admin_path(path):
        return "admin"
    if method == "GET":
        return "public_read"
    if method in WRITE_METHODS and path.startswith(COLLECTION_WRITE_PREFIXES):
        return "collection_write"
    return None


@dataclass(frozen=True)
class GroupConfig:
    group: str
    limit: int
    window_seconds: int


# window_seconds per group is fixed (matches the spec's "per 5 minutes" /
# "per 10 minutes" wording); only the limit itself is configurable via
# Settings, read live so tests/ops can change it without restarting.
_WINDOW_SECONDS = {
    "public_read": 300,
    "collection_write": 300,
    "admin": 300,
    "import_export": 600,
    "search": 300,
}


def _limit_for(group: str) -> int:
    return {
        "public_read": settings.RATE_LIMIT_PUBLIC_READ_PER_5M,
        "collection_write": settings.RATE_LIMIT_COLLECTION_WRITE_PER_5M,
        "admin": settings.RATE_LIMIT_ADMIN_PER_5M,
        "import_export": settings.RATE_LIMIT_IMPORT_EXPORT_PER_10M,
        "search": settings.RATE_LIMIT_SEARCH_PER_5M,
    }[group]


def group_config(group: str) -> GroupConfig:
    return GroupConfig(group=group, limit=_limit_for(group), window_seconds=_WINDOW_SECONDS[group])


ALL_GROUPS: tuple[str, ...] = ("public_read", "collection_write", "admin", "import_export", "search")


# --- in-memory fixed-window counters -------------------------------------


@dataclass
class _WindowState:
    window_index: int
    count: int


class RateLimiter:
    """Fixed-window counter per (group, client IP). A single asyncio event
    loop processes requests cooperatively, so plain dict access here needs
    no locking - see the module docstring for why this doesn't extend to
    multiple worker processes/instances."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, _WindowState]] = {g: {} for g in ALL_GROUPS}
        # Tracks the last window_index a 429 was logged for, per (group, ip)
        # - caps app_log_events writes to at most one per route group/IP/
        # window instead of one per rejected request (see record repeated_429).
        self._last_logged_window: dict[tuple[str, str], int] = {}

    def check(self, group: str, client_ip: str) -> "RateLimitResult":
        cfg = group_config(group)
        now = time.time()
        window_index = int(now // cfg.window_seconds)
        window_start = window_index * cfg.window_seconds
        reset_at = window_start + cfg.window_seconds

        bucket = self._state[group]
        state = bucket.get(client_ip)
        if state is None or state.window_index != window_index:
            state = _WindowState(window_index=window_index, count=0)
            bucket[client_ip] = state

        state.count += 1
        allowed = state.count <= cfg.limit
        remaining = max(0, cfg.limit - state.count)

        return RateLimitResult(
            allowed=allowed,
            limit=cfg.limit,
            remaining=remaining,
            reset_at=reset_at,
            retry_after_seconds=max(1, math.ceil(reset_at - now)),
            window_index=window_index,
        )

    def should_log_429(self, group: str, client_ip: str, window_index: int) -> bool:
        key = (group, client_ip)
        if self._last_logged_window.get(key) == window_index:
            return False
        self._last_logged_window[key] = window_index
        return True

    def active_keys(self, group: str) -> int:
        """Number of distinct client IPs with a live (non-expired) counter
        in this group right now - prunes expired entries as a side effect,
        so this also bounds the dict's memory over time."""
        cfg = group_config(group)
        now = time.time()
        current_window = int(now // cfg.window_seconds)
        bucket = self._state[group]
        expired = [ip for ip, state in bucket.items() if state.window_index != current_window]
        for ip in expired:
            del bucket[ip]
        return len(bucket)

    def reset(self) -> None:
        """Test-only: clears all counters and 429-log dedupe state."""
        self._state = {g: {} for g in ALL_GROUPS}
        self._last_logged_window = {}


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at: float
    retry_after_seconds: int
    window_index: int


_limiter = RateLimiter()


def reset_rate_limits() -> None:
    """Test hook - see tests/conftest.py."""
    _limiter.reset()


def rate_limit_status() -> dict:
    return {
        "enabled": settings.RATE_LIMIT_ENABLED,
        "windows": [
            {
                "group": group,
                "limit": group_config(group).limit,
                "window_seconds": group_config(group).window_seconds,
                "active_keys": _limiter.active_keys(group),
            }
            for group in ALL_GROUPS
        ],
    }


def _client_ip(request: Request) -> str:
    # Behind a reverse proxy, the real client IP arrives via
    # X-Forwarded-For (first hop = original client) - see 'Rate limiting'
    # in docs/deployment.md for why this still isn't sufficient for a
    # multi-instance deployment (each instance has its own counters).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        group = classify_route(request.url.path, request.method)
        if group is None:
            return await call_next(request)

        client_ip = _client_ip(request)
        result = _limiter.check(group, client_ip)

        if not result.allowed:
            if _limiter.should_log_429(group, client_ip, result.window_index):
                record_app_log(
                    "warning",
                    "api",
                    "rate_limit",
                    f"Rate limit exceeded for group '{group}' from {client_ip}.",
                    context={"group": group, "limit": result.limit},
                )
            response: Response = JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after_seconds": result.retry_after_seconds,
                },
            )
            response.headers["Retry-After"] = str(result.retry_after_seconds)
        else:
            response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(int(result.reset_at))
        return response
