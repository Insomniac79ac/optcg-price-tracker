from fastapi import Header, HTTPException

from app.env import is_development_environment
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
