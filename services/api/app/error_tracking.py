"""Error tracking for the API service (Sentry; Collector v1 plan §F2, rule A5).

``sentry-sdk`` is not in ``requirements.txt``: it lives in
``requirements-observability.txt``, installed only by
``deploy/railway/api.Dockerfile``. Only ``app.main`` imports this module, and
it imports ``sentry_sdk`` lazily, so neither collector image nor collector
import graph changes (``tests/test_error_tracking_import_graph.py``).

Without ``SENTRY_DSN`` (or without the package) this is a no-op.

Privacy contract: ``send_default_pii=False``, no local variables in stack
frames, no request bodies, no tracing, no release-health sessions, and
``scrub_event`` removes Authorization/cookie/admin headers, cookies, query
strings and the user before an event is sent.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

_SENSITIVE_HEADER = re.compile(
    r"^(authorization|proxy-authorization|cookie|set-cookie|x-admin-token|"
    r"x-admin-actor-assertion|x-api-key)$",
    re.IGNORECASE,
)


def _strip_query(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return re.split(r"[?#]", value, maxsplit=1)[0]


def scrub_event(event: dict[str, Any], hint: Any = None) -> dict[str, Any]:
    """``before_send``: drop credentials, cookies, bodies, queries and the user."""
    request = event.get("request")
    if isinstance(request, dict):
        for key in ("cookies", "data", "query_string"):
            request.pop(key, None)
        if "url" in request:
            request["url"] = _strip_query(request["url"])
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in [k for k in headers if _SENSITIVE_HEADER.match(str(k))]:
                del headers[key]
    event.pop("user", None)
    crumbs = event.get("breadcrumbs")
    values = crumbs.get("values") if isinstance(crumbs, dict) else crumbs
    for crumb in values or []:
        data = crumb.get("data") if isinstance(crumb, dict) else None
        if isinstance(data, dict):
            for key in ("url", "from", "to"):
                if key in data:
                    data[key] = _strip_query(data[key])
    return event


def release(environ: Mapping[str, str]) -> str | None:
    """The deployed Git SHA: Railway's, else the GIT_COMMIT build arg."""
    for key in ("RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT"):
        value = (environ.get(key) or "").strip()
        if value and value != "unknown":
            return value
    return None


def init_options(dsn: str, environ: Mapping[str, str]) -> dict[str, Any]:
    return {
        "dsn": dsn,
        "environment": (environ.get("SENTRY_ENVIRONMENT") or "").strip() or "staging",
        "release": release(environ),
        "send_default_pii": False,
        "include_local_variables": False,
        "max_request_body_size": "never",
        "traces_sample_rate": 0.0,
        # Errors only: no release-health session per request.
        "auto_session_tracking": False,
        "before_send": scrub_event,
    }


def init_error_tracking(environ: Mapping[str, str] | None = None) -> bool:
    """Initialise Sentry when SENTRY_DSN is set. Returns whether it did."""
    environ = os.environ if environ is None else environ
    dsn = (environ.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; error tracking is off.")
        return False
    sentry_sdk.init(**init_options(dsn, environ))
    return True
