"""Per-response size visibility - every response gets an
X-Response-Size-Bytes header; a response larger than
settings.RESPONSE_SIZE_WARNING_BYTES additionally gets a warning
app_log_events row (event_type=response_size_warning), surfaced on GET
/admin/performance/summary and filterable on GET /admin/logs. See 'API
pagination and response size limits' in docs/operations.md.

Reads the size off the Content-Length header call_next already produced,
rather than buffering/re-reading the body - every response in this API
(including CSV/backup exports) is built as a fully-materialized
fastapi.responses.Response, which always sets Content-Length, so this never
needs to hold a second copy of a large body in memory just to measure it.
A response.body_iterator-only response wouldn't have Content-Length; if that
ever happens, the header/warning are silently skipped rather than resorting
to a memory-doubling read - the whole point of this middleware is to guard
against exactly that kind of blowup, not cause it.

Never blocks a response by default - this is visibility only, same
philosophy as app.core.request_timing.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services.app_logging import record_app_log
from app.settings import settings


class ResponseSizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        content_length = response.headers.get("content-length")
        if content_length is None:
            return response

        try:
            size_bytes = int(content_length)
        except ValueError:
            return response

        response.headers["X-Response-Size-Bytes"] = str(size_bytes)

        if settings.RESPONSE_SIZE_WARNING_ENABLED and size_bytes > settings.RESPONSE_SIZE_WARNING_BYTES:
            record_app_log(
                "warning",
                "api",
                "response_size_warning",
                f"{request.method} {request.url.path} response was {size_bytes} bytes "
                f"(threshold {settings.RESPONSE_SIZE_WARNING_BYTES}).",
                context={
                    "method": request.method,
                    "path": request.url.path,
                    "size_bytes": size_bytes,
                    "query_params": dict(request.query_params),
                },
            )

        return response
