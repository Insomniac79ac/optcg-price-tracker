"""Which browser origins may call this API cross-origin (CORS).

Collector v1 S5 (PLAN §D1 item 2, owner decision Q2): CORS is no longer
open to every origin by default. Only the API process imports this module
(``app.main``); no collector does, so it is not a collector runtime input.
``app.settings`` is not edited: the existing ``CORS_ALLOWED_ORIGINS`` and
``CORS_ALLOW_ORIGIN_REGEX`` fields are only read here.

Rules, in order:

1. ``CORS_ALLOWED_ORIGINS`` set: exactly those origins (staging sets it to
   the stable alias).
2. Development (``ENVIRONMENT``/``APP_ENV`` = ``development``): ``*``, as
   local work always had.
3. Staging without the variable: the staging site's addresses only
   (staging.cardpirate.app since 2026-10-24, and the Vercel alias).
4. Anything else (production, or no environment at all): no cross-origin
   browser access. Server-to-server calls (the web app's route handlers) do
   not use CORS and are unaffected.

Credentials are never allowed cross-origin: the browser holds no API
credential since S5, and the admin token is server-side only.
"""

from __future__ import annotations

from app.settings import settings

STAGING_WEB_ORIGINS = (
    "https://staging.cardpirate.app",
    "https://optcg-price-tracker-staging.vercel.app",
)


def _environment() -> str:
    return (settings.ENVIRONMENT or settings.APP_ENV or "").strip().lower()


def allowed_origins() -> list[str]:
    configured = [o.strip() for o in (settings.CORS_ALLOWED_ORIGINS or "").split(",") if o.strip()]
    if configured:
        return configured
    environment = _environment()
    if environment == "development":
        return ["*"]
    if environment == "staging":
        return list(STAGING_WEB_ORIGINS)
    return []


def allowed_origin_regex() -> str | None:
    return settings.CORS_ALLOW_ORIGIN_REGEX or None


def cors_options() -> dict:
    """Keyword arguments for Starlette's ``CORSMiddleware``."""
    return {
        "allow_origins": allowed_origins(),
        "allow_origin_regex": allowed_origin_regex(),
        "allow_credentials": False,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
