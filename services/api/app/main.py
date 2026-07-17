import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin_actions import router as admin_actions_router
from app.api.admin_backup import router as admin_backup_router
from app.api.admin_db_backups import router as admin_db_backups_router
from app.api.admin_logs import router as admin_logs_router
from app.api.admin_observability import router as admin_observability_router
from app.api.admin_rate_limit import router as admin_rate_limit_router
from app.api.admin_release_status import router as admin_release_status_router
from app.api.alerts import router as alerts_router
from app.api.card_audit import router as card_audit_router
from app.api.cards import router as cards_router
from app.api.collection import router as collection_router
from app.api.collector import router as collector_router
from app.api.collector_activity import router as collector_activity_router
from app.api.collector_notes import router as collector_notes_router
from app.api.dashboard import router as dashboard_router
from app.api.env_check import router as env_check_router
from app.api.grading import router as grading_router
from app.api.health import router as health_router
from app.api.market import router as market_router
from app.api.market_workflow_runs import router as market_workflow_runs_router
from app.api.refresh_runs import router as refresh_runs_router
from app.api.search import router as search_router
from app.api.snkrdunk_candidates import router as snkrdunk_candidates_router
from app.api.source_mappings import router as source_mappings_router
from app.api.system_check import router as system_check_router
from app.api.version import router as version_router
from app.api.wishlist import router as wishlist_router
from app.config_check import validate_config
from app.core.env_validation import validate_environment
from app.core.rate_limit import RateLimitMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.services.app_logging import record_app_log
from app.settings import settings

logger = logging.getLogger(__name__)

# Fail fast and loud: a misconfigured production deployment (no ADMIN_TOKEN)
# should never come up serving traffic. This only runs once, at process
# import, using whatever ENVIRONMENT/APP_ENV/ADMIN_TOKEN the OS environment
# actually has at boot - tests exercise validate_config() directly instead
# of relying on re-triggering this import-time check.
_startup_check = validate_config()
if not _startup_check.ok:
    record_app_log(
        "critical",
        "api",
        "startup",
        "API refused to start: invalid configuration.",
        context={"errors": _startup_check.errors},
    )
    raise RuntimeError(
        "Invalid API configuration - refusing to start: " + "; ".join(_startup_check.errors)
    )

# Broader environment/startup safety sweep (ADMIN_TOKEN strength, DATABASE_URL
# default password, SCRAPING_MODE, market workflow schedule vars, Telegram
# config, ...) - see app/core/env_validation.py. Warnings are logged in every
# environment; only production treats a failed check as fatal (development
# keeps running with local defaults per rule 2 there).
_env_report = validate_environment()
for _warning in _env_report.warnings:
    logger.warning("env validation warning: %s", _warning)
if _env_report.warnings:
    record_app_log(
        "warning",
        "api",
        "env_validation",
        f"API startup: {len(_env_report.warnings)} environment validation warning(s).",
        context={"app_env": _env_report.app_env, "warnings": _env_report.warnings},
    )
if not _env_report.ok:
    record_app_log(
        "critical",
        "api",
        "env_validation",
        "API refused to start: invalid production environment configuration.",
        context={"app_env": _env_report.app_env, "errors": _env_report.errors},
    )
    raise RuntimeError(
        "Invalid production environment configuration - refusing to start: "
        + "; ".join(_env_report.errors)
    )

app = FastAPI(title="optcg-price-tracker API")

# Middleware order: FastAPI's add_middleware prepends, so the LAST call here
# ends up outermost (verify with `[m.cls.__name__ for m in app.user_middleware]`
# if this ever needs re-checking - it is not the "first added = outermost"
# rule older Starlette docs describe). RateLimitMiddleware is added first so
# it's innermost, closest to the router; SecurityHeadersMiddleware wraps it
# so a 429 still gets X-Frame-Options etc.; CORSMiddleware is added last so
# it's outermost and decorates every response - including a 429 - with CORS
# headers, which the browser needs to even let JS read that response's body/
# status instead of failing the fetch() as an opaque network error.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# CORS_ALLOWED_ORIGINS unset (dev default) keeps the wide-open "*" this app
# has always used locally. Set it (e.g. to the Vercel frontend's origin) to
# lock this down in production - see app/settings.py.
_cors_origins = [o.strip() for o in (settings.CORS_ALLOWED_ORIGINS or "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_origin_regex=settings.CORS_ALLOW_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(cards_router)
app.include_router(market_router)
app.include_router(snkrdunk_candidates_router)
app.include_router(refresh_runs_router)
app.include_router(alerts_router)
app.include_router(card_audit_router)
app.include_router(source_mappings_router)
app.include_router(collection_router)
app.include_router(collector_router)
app.include_router(collector_notes_router)
app.include_router(collector_activity_router)
app.include_router(grading_router)
app.include_router(wishlist_router)
app.include_router(dashboard_router)
app.include_router(admin_actions_router)
app.include_router(admin_backup_router)
app.include_router(admin_db_backups_router)
app.include_router(admin_logs_router)
app.include_router(admin_observability_router)
app.include_router(admin_rate_limit_router)
app.include_router(admin_release_status_router)
app.include_router(market_workflow_runs_router)
app.include_router(search_router)
app.include_router(system_check_router)
app.include_router(env_check_router)
app.include_router(version_router)
