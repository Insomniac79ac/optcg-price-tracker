"""Shared helper for stamping the X-Cache/X-Cache-Key/X-Cache-TTL headers
documented in 'Cache operations' (docs/operations.md) onto a cached
endpoint's response - see app.services.cache for the actual cache
read/write logic this just reports on."""

from __future__ import annotations

from fastapi import Response

from app.env import is_development_environment


def set_cache_headers(response: Response, *, hit: bool, ttl_seconds: int, cache_key: str) -> None:
    response.headers["X-Cache"] = "HIT" if hit else "MISS"
    response.headers["X-Cache-TTL"] = str(ttl_seconds)
    if is_development_environment():
        response.headers["X-Cache-Key"] = cache_key
