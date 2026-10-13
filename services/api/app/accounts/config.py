"""Collector-accounts settings, read here rather than in ``app.settings``.

``app.settings`` is imported by both collectors, so a new field there would be a
collector release. These values are read from the process environment on every
call, which also lets tests flip them without reloading anything.
"""

from __future__ import annotations

import os

from fastapi import HTTPException

FLAG = "COLLECTOR_ACCOUNTS_ENABLED"
_TRUE = frozenset({"1", "true", "yes", "on"})


def accounts_enabled() -> bool:
    """Off unless the variable is explicitly truthy. Unset means off."""
    return os.environ.get(FLAG, "").strip().lower() in _TRUE


def require_accounts_enabled() -> None:
    """Router dependency: while the flag is off every /me route is a plain 404.

    It runs before authentication, so a dark deployment neither verifies tokens
    nor creates a user row on first call.
    """
    if not accounts_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
