"""Per-request timing - every response gets an X-Process-Time-Ms header;
requests slower than settings.SLOW_REQUEST_MS additionally get a warning
app_log_events row (see GET /admin/performance/summary and 'Observability
and logs' in docs/operations.md). Normal (fast) requests are never logged -
only the header is added for those, so this doesn't flood app_log_events
under normal load.

Query params are passed through as-is to record_app_log's context - that
function already recursively redacts any key that looks like a token/
secret/password (see app.services.app_logging.sanitize_context), so a
query param like ?api_key=... or ?admin_token=... never reaches storage
unredacted without this module needing its own redaction logic.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services.app_logging import record_app_log
from app.settings import settings


class RequestTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"

        if settings.SLOW_REQUEST_LOGGING_ENABLED and duration_ms > settings.SLOW_REQUEST_MS:
            record_app_log(
                "warning",
                "api",
                "slow_request",
                f"{request.method} {request.url.path} took {duration_ms:.0f}ms "
                f"(threshold {settings.SLOW_REQUEST_MS}ms).",
                context={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                    "query_params": dict(request.query_params),
                },
            )

        return response
