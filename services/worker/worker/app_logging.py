"""Best-effort structured production logging to app_log_events - the worker
side of the "observability and logs" feature. Mirrors
services/api/app/services/app_logging.py exactly (same redaction rules, same
best-effort semantics) - the worker has no shared code with the api service
(see worker/models.py, which already duplicates the api's ORM models
table-for-table), so this duplicates that module rather than importing it.

record_app_log/log_exception never raise - a logging failure must never
take down the actual job. Each call opens and commits its own short-lived
session, independent of the caller's own db session/transaction, so the log
row survives even if the caller's transaction is later rolled back.
"""

from __future__ import annotations

import logging
import traceback as traceback_module
from typing import Any

from worker.db import SessionLocal
from worker.models import AppLogEvent

logger = logging.getLogger(__name__)

LOG_LEVELS = ("debug", "info", "warning", "error", "critical")

REDACT_KEY_SUBSTRINGS = ("token", "secret", "password", "key", "authorization", "cookie")
REDACTED_VALUE = "[REDACTED]"

MAX_CONTEXT_STRING_LENGTH = 2000
MAX_CONTEXT_LIST_ITEMS = 50
MAX_CONTEXT_DEPTH = 6
MAX_TRACEBACK_LENGTH = 8000


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(substring in lowered for substring in REDACT_KEY_SUBSTRINGS)


def sanitize_context(value: Any, *, _depth: int = 0) -> Any:
    if _depth > MAX_CONTEXT_DEPTH:
        return "[truncated: too deeply nested]"
    if isinstance(value, dict):
        return {
            str(k): (REDACTED_VALUE if _is_secret_key(str(k)) else sanitize_context(v, _depth=_depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        truncated = len(value) > MAX_CONTEXT_LIST_ITEMS
        items = [sanitize_context(v, _depth=_depth + 1) for v in value[:MAX_CONTEXT_LIST_ITEMS]]
        if truncated:
            items.append(f"...[{len(value) - MAX_CONTEXT_LIST_ITEMS} more truncated]")
        return items
    if isinstance(value, str) and len(value) > MAX_CONTEXT_STRING_LENGTH:
        return value[:MAX_CONTEXT_STRING_LENGTH] + "...[truncated]"
    return value


def sanitize_traceback(tb: str | None) -> str | None:
    if tb is None:
        return None
    if len(tb) > MAX_TRACEBACK_LENGTH:
        return tb[:MAX_TRACEBACK_LENGTH] + "\n...[truncated]"
    return tb


def record_app_log(
    level: str,
    service: str,
    event_type: str,
    message: str,
    *,
    context: dict[str, Any] | None = None,
    traceback: str | None = None,
    related_run_id: int | None = None,
    related_entity_type: str | None = None,
    related_entity_id: int | None = None,
) -> None:
    if level not in LOG_LEVELS:
        logger.warning("record_app_log: unknown level %r, defaulting to 'info'.", level)
        level = "info"

    sanitized_context = sanitize_context(context) if context is not None else None
    sanitized_traceback = sanitize_traceback(traceback)

    db = None
    try:
        db = SessionLocal()
        db.add(
            AppLogEvent(
                level=level,
                service=service,
                event_type=event_type,
                message=message,
                context_json=sanitized_context,
                traceback=sanitized_traceback,
                related_run_id=related_run_id,
                related_entity_type=related_entity_type,
                related_entity_id=related_entity_id,
            )
        )
        db.commit()
    except Exception:
        logger.warning(
            "record_app_log: failed to write app_log_events row "
            "(level=%s service=%s event_type=%s message=%s) - logging via Python logger only.",
            level,
            service,
            event_type,
            message,
            exc_info=True,
        )
    finally:
        if db is not None:
            db.close()


def log_exception(
    service: str,
    event_type: str,
    message: str,
    exc: BaseException,
    *,
    level: str = "error",
    context: dict[str, Any] | None = None,
    related_run_id: int | None = None,
    related_entity_type: str | None = None,
    related_entity_id: int | None = None,
) -> None:
    tb_text = "".join(traceback_module.format_exception(type(exc), exc, exc.__traceback__))
    record_app_log(
        level,
        service,
        event_type,
        message,
        context=context,
        traceback=tb_text,
        related_run_id=related_run_id,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
    )
