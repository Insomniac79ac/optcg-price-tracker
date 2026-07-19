from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.env import is_development_environment
from app.models import User
from app.settings import settings


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    """Guards admin routes with a shared token passed via the X-Admin-Token
    header. If ADMIN_TOKEN isn't configured, requests are only allowed in a
    development environment (ENVIRONMENT/APP_ENV=development) - anywhere else,
    an unconfigured token is a deployment misconfiguration, not an open door."""
    if not settings.ADMIN_TOKEN:
        if is_development_environment():
            return
        raise HTTPException(
            status_code=500,
            detail="ADMIN_TOKEN is not configured and ENVIRONMENT/APP_ENV is not 'development'.",
        )

    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Admin token required")


def _get_or_create_user(db: Session, *, google_sub: str, email: str, name: str | None) -> User:
    """JIT-provisions a User row the first time a given Google account is
    seen. The frontend never talks to this backend's DB directly to create
    accounts - the first authenticated request IS the signup."""
    user = db.scalar(select(User).where(User.google_sub == google_sub))
    if user is not None:
        return user
    user = User(google_sub=google_sub, email=email, name=name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def require_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Guards per-user routes (/collection, /grading, /collector) with a
    short-lived HS256 bearer JWT minted by the frontend's NextAuth session
    callback - not NextAuth's own internal session cookie/JWE, which would be
    awkward to verify cross-domain from a separately-hosted API. See
    docs/deployment.md for the full token-exchange rationale."""
    if not settings.API_JWT_SECRET:
        raise HTTPException(status_code=500, detail="API_JWT_SECRET is not configured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = jwt.decode(token, settings.API_JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    google_sub = payload.get("sub")
    email = payload.get("email")
    if not google_sub or not email:
        raise HTTPException(status_code=401, detail="Token missing required claims")

    return _get_or_create_user(db, google_sub=google_sub, email=email, name=payload.get("name"))


def require_current_user_optional(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    """Same bearer-token verification as require_current_user, but returns
    None instead of raising when no/invalid credentials are present - for
    routes that must stay publicly browsable (e.g. GET /cards) but that
    personalize part of their response (e.g. the caller's own card tags)
    when a valid session happens to be attached."""
    if not authorization:
        return None
    try:
        return require_current_user(authorization=authorization, db=db)
    except HTTPException:
        return None


@dataclass
class FileJobAccess:
    """Result of file_job_access() below - exactly one of user/is_admin
    reflects how the caller was authenticated."""

    user: User | None
    is_admin: bool


def file_job_access(
    x_admin_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> FileJobAccess:
    """Guards GET/POST /file-jobs* with EITHER a valid X-Admin-Token (full
    visibility across every job/owner, including admin-only job types like
    backup_export - used by the /admin/file-jobs page) OR a valid per-user
    bearer token (visibility limited to that user's own jobs - used by the
    collection/wishlist background import/export UI). Tries the admin path
    first via require_admin_token itself, so it stays the single source of
    truth for what counts as a valid admin request (including its dev-mode-
    with-no-ADMIN_TOKEN-configured behavior); any failure there (wrong/
    missing token, or ADMIN_TOKEN unconfigured outside development) falls
    through to ordinary bearer-token auth instead of failing the request
    outright. See app.services.file_jobs.list_file_jobs's `admin` flag and
    app.api.file_jobs's per-job ownership check for how each side is
    subsequently scoped."""
    try:
        require_admin_token(x_admin_token=x_admin_token)
        return FileJobAccess(user=None, is_admin=True)
    except HTTPException:
        pass

    user = require_current_user(authorization=authorization, db=db)
    return FileJobAccess(user=user, is_admin=False)
