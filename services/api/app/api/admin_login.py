"""Temporary single-admin Credentials login (see app.settings' ADMIN_LOGIN_*
fields, app.core.admin_login_throttle, and app.core.admin_password) - the
staging-only prototype that lets the Next.js Credentials provider's
authorize() establish an Auth.js session with role="admin", without a
user-table row, Google OAuth, or ADMIN_TOKEN ever reaching the browser. See
docs/staging_deployment.md for the full architecture and its planned
replacement (Google OAuth + an admin-email allowlist).

This endpoint is intentionally NOT behind require_admin_token - it is the
thing that establishes an admin identity in the first place, not a consumer
of one. It grants no access to any other backend admin operation by itself:
the caller (Next.js) is responsible for turning a successful response here
into an Auth.js session, and every other /admin/* backend route still
independently requires a valid X-Admin-Token exactly as before (see
app.auth.require_admin_token) - this endpoint doesn't touch that dependency
at all.

Every failure path - unknown email, wrong password, disabled login, missing
configuration, throttled, Redis unavailable - returns one of exactly two
generic response shapes (_generic_invalid_credentials / _generic_unavailable
/ _generic_throttled), with no information that lets a caller distinguish
one cause from another beyond "wrong credentials" vs. "try again later" vs.
"not available at all". See verify_admin_credentials for how each case maps.
"""

from __future__ import annotations

import hashlib

import redis
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.admin_login_throttle import check_locked, clear_account_failures, record_failure
from app.core.admin_password import verify_password
from app.schemas import AdminLoginVerifyIn, AdminLoginVerifyOut
from app.services.app_logging import record_app_log
from app.settings import settings

router = APIRouter(prefix="/auth/admin", tags=["auth"])

ADMIN_LOGIN_ID = "staging-admin"


def _client_ip(request: Request) -> str | None:
    # Same trusted-proxy convention as app.core.rate_limit's private
    # _client_ip - duplicated rather than imported (that helper belongs to
    # a different module's concerns, and this router's "optional, may be
    # None" usage differs slightly).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


def _log_hash(value: str | None) -> str | None:
    """Truncated one-way hash for security-event context fields - never the
    raw email/IP (see app.core.admin_login_throttle's identical rationale
    for Redis key names)."""
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _generic_invalid_credentials() -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": "Invalid email or password."})


def _generic_unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Admin login is not available."})


def _generic_throttled(retry_after_seconds: int) -> JSONResponse:
    response = JSONResponse(status_code=429, content={"detail": "Too many attempts. Try again later."})
    response.headers["Retry-After"] = str(max(1, retry_after_seconds))
    return response


def _login_configured() -> bool:
    return bool(
        settings.ADMIN_LOGIN_ENABLED
        and settings.ADMIN_LOGIN_EMAIL
        and settings.ADMIN_LOGIN_PASSWORD_HASH
    )


@router.get("/status")
def admin_login_status() -> dict:
    """Lets the frontend's /admin/login page show a proactive "admin login
    is not available" state instead of only discovering that after a failed
    submit - see apps/web/src/app/admin/login/page.tsx. Reveals nothing
    beyond a boolean: not which piece of config is missing, not whether an
    email/hash exists independently of the other, nothing Redis/throttle-
    related. Also unauthenticated by design, same reasoning as POST
    /verify - there is no admin identity yet to gate this behind."""
    return {"enabled": _login_configured()}


@router.post("/verify", response_model=AdminLoginVerifyOut)
def verify_admin_credentials(body: AdminLoginVerifyIn, request: Request):
    if not _login_configured():
        return _generic_unavailable()

    # Normalized regardless of whether it matches ADMIN_LOGIN_EMAIL - the
    # throttle is keyed on whatever was submitted, not on a real match, so
    # the lockout signal itself never reveals whether an email is the
    # configured admin account (see app.core.admin_login_throttle).
    submitted_email = body.email.strip().lower()
    configured_email = (settings.ADMIN_LOGIN_EMAIL or "").strip().lower()
    ip = _client_ip(request)

    try:
        throttle_status = check_locked(submitted_email, ip)
    except redis.RedisError:
        record_app_log(
            "error",
            "api",
            "admin_login_redis_error",
            "Admin login throttle check failed (Redis unavailable) - denying the attempt.",
        )
        return _generic_unavailable()

    if throttle_status.locked:
        record_app_log(
            "warning",
            "api",
            "admin_login_throttled",
            "Admin login attempt rejected: account or source is currently locked out.",
            context={"email_hash": _log_hash(submitted_email), "ip_hash": _log_hash(ip)},
        )
        return _generic_throttled(throttle_status.retry_after_seconds)

    # Always performs a real Argon2 verify - against the dummy hash when
    # the email doesn't match - so "unknown email" and "known email, wrong
    # password" take about the same time (see app.core.admin_password).
    email_matches = bool(configured_email) and submitted_email == configured_email
    hash_to_check = settings.ADMIN_LOGIN_PASSWORD_HASH if email_matches else None
    password_ok = verify_password(body.password, hash_to_check)
    success = email_matches and password_ok

    if not success:
        try:
            record_failure(submitted_email, ip)
        except redis.RedisError:
            record_app_log(
                "error",
                "api",
                "admin_login_redis_error",
                "Admin login failure-counter update failed (Redis unavailable).",
            )
        record_app_log(
            "warning",
            "api",
            "admin_login_failure",
            "Admin login attempt failed.",
            context={"email_hash": _log_hash(submitted_email), "ip_hash": _log_hash(ip)},
        )
        return _generic_invalid_credentials()

    try:
        clear_account_failures(submitted_email)
    except redis.RedisError:
        # Non-fatal: the login itself already succeeded on its merits: a
        # stale failure counter only makes a *future* login marginally
        # closer to a lockout, it doesn't grant or deny anything now.
        record_app_log(
            "error",
            "api",
            "admin_login_redis_error",
            "Admin login failure-counter clear failed (Redis unavailable); login still succeeds.",
        )

    record_app_log(
        "info",
        "api",
        "admin_login_success",
        "Admin login succeeded.",
        context={"email_hash": _log_hash(submitted_email)},
    )

    return AdminLoginVerifyOut(id=ADMIN_LOGIN_ID, email=configured_email, role="admin")
