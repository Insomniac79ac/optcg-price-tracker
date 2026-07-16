"""Best-effort structured production logging to app_log_events - the
"observability and logs" feature (see GET /admin/logs, GET
/admin/observability/summary, and 'Observability and logs' in
docs/operations.md). Lets production issues be diagnosed from the app
itself instead of SSHing into the server for every small problem.

record_app_log/log_exception never raise - a logging failure (DB down,
session error, ...) must never take down the caller's actual work. They
also never touch the caller's own db session/transaction, so a log row
survives even if the caller's transaction is later rolled back (e.g. a
failed CSV import or backup restore) - each call opens and commits its own
short-lived session.

Secrets never make it into a stored row: context_json is recursively
sanitized (keys containing token/secret/password/key/authorization/cookie
are redacted) and neither request bodies nor raw tracebacks are trusted
as-is (tracebacks are length-capped, never string-searched for secrets,
so callers must not pass exception args that might contain them).
"""

from __future__ import annotations

import logging
import traceback as traceback_module
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AppLogEvent

logger = logging.getLogger(__name__)

LOG_LEVELS = ("debug", "info", "warning", "error", "critical")

# Substrings (case-insensitive) that mark a context_json key as secret-shaped.
# Matches on substring, not exact key name, so e.g. "api_key", "AccessToken",
# and "Cookie" are all caught without having to enumerate every variant.
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
    """Recursively redacts values under secret-shaped keys and caps
    string/list size, so context_json can never leak a token/secret/password
    even if a caller passes something it shouldn't have."""
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
    """Writes one app_log_events row. Best-effort: if the write fails for any
    reason, falls back to the normal Python logger and returns rather than
    raising - callers should never need to wrap this in their own try/except."""
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
    """record_app_log convenience wrapper for exception sites - formats exc's
    traceback for storage. Defaults to level='error'; pass level='critical'
    for e.g. a startup failure."""
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


@dataclass
class LogListResult:
    logs: list[AppLogEvent]
    total_logs: int
    error_count: int = 0
    warning_count: int = 0
    critical_count: int = 0
    by_service: dict[str, int] = field(default_factory=dict)
    by_event_type: dict[str, int] = field(default_factory=dict)


def list_app_logs(
    db: Session,
    *,
    level: str | None = None,
    service: str | None = None,
    event_type: str | None = None,
    q: str | None = None,
    since_hours: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> LogListResult:
    """Lists app_log_events rows matching the given filters (newest first),
    plus a summary of the whole filtered set (not just the returned page) -
    total count, counts by level, and breakdowns by service/event_type."""
    filters = []
    if level is not None:
        filters.append(AppLogEvent.level == level)
    if service is not None:
        filters.append(AppLogEvent.service == service)
    if event_type is not None:
        filters.append(AppLogEvent.event_type == event_type)
    if q:
        filters.append(AppLogEvent.message.ilike(f"%{q}%"))
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        filters.append(AppLogEvent.created_at >= cutoff)

    total_logs = db.scalar(select(func.count()).select_from(AppLogEvent).where(*filters)) or 0

    level_counts = dict(
        db.execute(
            select(AppLogEvent.level, func.count()).where(*filters).group_by(AppLogEvent.level)
        ).all()
    )
    by_service = dict(
        db.execute(
            select(AppLogEvent.service, func.count()).where(*filters).group_by(AppLogEvent.service)
        ).all()
    )
    by_event_type = dict(
        db.execute(
            select(AppLogEvent.event_type, func.count())
            .where(*filters)
            .group_by(AppLogEvent.event_type)
        ).all()
    )

    logs = db.scalars(
        select(AppLogEvent)
        .where(*filters)
        .order_by(AppLogEvent.created_at.desc(), AppLogEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return LogListResult(
        logs=list(logs),
        total_logs=total_logs,
        error_count=level_counts.get("error", 0),
        warning_count=level_counts.get("warning", 0),
        critical_count=level_counts.get("critical", 0),
        by_service=by_service,
        by_event_type=by_event_type,
    )


MIN_PRUNE_OLDER_THAN_DAYS = 7
PRUNE_CONFIRM_PHRASE = "PRUNE"


class PruneConfirmationRequired(ValueError):
    pass


@dataclass
class PruneResult:
    dry_run: bool
    older_than_days: int
    would_delete: int
    deleted: int = 0


def prune_app_logs(
    db: Session, *, older_than_days: int, dry_run: bool = True, confirm: str | None = None
) -> PruneResult:
    """Deletes app_log_events rows older than older_than_days. dry_run=True
    (the default) only counts what would be deleted. Refuses older_than_days
    below MIN_PRUNE_OLDER_THAN_DAYS unless confirm='PRUNE', so a mistyped
    small number can't wipe out most of the table in one call."""
    if older_than_days < MIN_PRUNE_OLDER_THAN_DAYS and confirm != PRUNE_CONFIRM_PHRASE:
        raise PruneConfirmationRequired(
            f"older_than_days < {MIN_PRUNE_OLDER_THAN_DAYS} requires confirm={PRUNE_CONFIRM_PHRASE}"
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    would_delete = db.scalar(
        select(func.count()).select_from(AppLogEvent).where(AppLogEvent.created_at < cutoff)
    ) or 0

    if dry_run:
        return PruneResult(dry_run=True, older_than_days=older_than_days, would_delete=would_delete)

    db.execute(delete(AppLogEvent).where(AppLogEvent.created_at < cutoff))
    db.commit()
    return PruneResult(
        dry_run=False, older_than_days=older_than_days, would_delete=would_delete, deleted=would_delete
    )
