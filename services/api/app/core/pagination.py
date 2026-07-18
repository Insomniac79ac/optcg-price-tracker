"""Shared pagination helpers for list endpoints - see 'API pagination and
response size limits' in docs/operations.md.

Most list endpoints already validate limit/offset via FastAPI's
Query(..., ge=1, le=<max>) - that already rejects out-of-range values with a
422 before the endpoint body ever runs, so parse_pagination() exists for the
handful of endpoints that don't get that for free (e.g. ones deriving
limit/offset from something other than a plain Query param, or building a
brand-new paginated surface) and as the one place the default/max limit
constants live. Everything paginated builds its response metadata with
pagination_response() so every paginated endpoint exposes the same
"pagination" shape regardless of what its items array is called
(items/logs/events/opportunities/signals/results/...).
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class PaginationMeta(BaseModel):
    total: int
    limit: int
    offset: int
    has_next: bool
    has_previous: bool
    next_offset: int | None
    previous_offset: int | None


def parse_pagination(
    limit: int | None,
    offset: int | None,
    *,
    default_limit: int = DEFAULT_LIMIT,
    max_limit: int = MAX_LIMIT,
) -> tuple[int, int]:
    """Validates/normalizes a limit/offset pair. Rejects (422) rather than
    clamps - matches the existing Query(..., le=max) style used across the
    API, where an out-of-range limit is a client error, not something to
    silently reinterpret."""
    resolved_limit = default_limit if limit is None else limit
    resolved_offset = 0 if offset is None else offset

    if resolved_offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")
    if resolved_limit <= 0:
        raise HTTPException(status_code=422, detail="limit must be >= 1")
    if resolved_limit > max_limit:
        raise HTTPException(status_code=422, detail=f"limit must be <= {max_limit}")

    return resolved_limit, resolved_offset


def pagination_response(items: list, total: int, limit: int, offset: int) -> PaginationMeta:
    """Builds the standard pagination metadata block for a page `items` of
    `total` matching rows. has_next/has_previous are derived from the actual
    returned count (offset + len(items)) rather than blindly from `limit`,
    so a short final page is still correctly reported as the last page."""
    has_next = offset + len(items) < total
    has_previous = offset > 0
    return PaginationMeta(
        total=total,
        limit=limit,
        offset=offset,
        has_next=has_next,
        has_previous=has_previous,
        next_offset=offset + limit if has_next else None,
        previous_offset=max(offset - limit, 0) if has_previous else None,
    )
