from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin_actions import router as admin_actions_router
from app.api.admin_backup import router as admin_backup_router
from app.api.alerts import router as alerts_router
from app.api.card_audit import router as card_audit_router
from app.api.cards import router as cards_router
from app.api.collection import router as collection_router
from app.api.collector import router as collector_router
from app.api.collector_activity import router as collector_activity_router
from app.api.collector_notes import router as collector_notes_router
from app.api.dashboard import router as dashboard_router
from app.api.grading import router as grading_router
from app.api.health import router as health_router
from app.api.market import router as market_router
from app.api.market_workflow_runs import router as market_workflow_runs_router
from app.api.refresh_runs import router as refresh_runs_router
from app.api.search import router as search_router
from app.api.snkrdunk_candidates import router as snkrdunk_candidates_router
from app.api.source_mappings import router as source_mappings_router
from app.api.wishlist import router as wishlist_router
from app.config_check import validate_config
from app.settings import settings

# Fail fast and loud: a misconfigured production deployment (no ADMIN_TOKEN)
# should never come up serving traffic. This only runs once, at process
# import, using whatever ENVIRONMENT/APP_ENV/ADMIN_TOKEN the OS environment
# actually has at boot - tests exercise validate_config() directly instead
# of relying on re-triggering this import-time check.
_startup_check = validate_config()
if not _startup_check.ok:
    raise RuntimeError(
        "Invalid API configuration - refusing to start: " + "; ".join(_startup_check.errors)
    )

app = FastAPI(title="optcg-price-tracker API")

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
app.include_router(market_workflow_runs_router)
app.include_router(search_router)
