"""Baseline security response headers for every API response - this is a
pure JSON API, never meant to be framed, rendered directly in a browser as
HTML, or granted device access, so these are safe defaults rather than a
tunable policy. See 'Security headers' in docs/deployment.md.

Kept separate from app.core.rate_limit's RateLimitMiddleware (and added as
the outer of the two in app/main.py) so these headers land on every
response that middleware produces too, including its 429s.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.rate_limit import is_admin_path

# Deliberately restrictive: this API never itself embeds third-party
# content, so there's nothing default-src/frame-ancestors need to allow.
CONTENT_SECURITY_POLICY = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        if is_admin_path(request.url.path):
            response.headers["Cache-Control"] = "no-store"
        return response
