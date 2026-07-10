from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.alerts import router as alerts_router
from app.api.card_audit import router as card_audit_router
from app.api.cards import router as cards_router
from app.api.health import router as health_router
from app.api.market import router as market_router
from app.api.refresh_runs import router as refresh_runs_router
from app.api.snkrdunk_candidates import router as snkrdunk_candidates_router
from app.api.source_mappings import router as source_mappings_router
from app.config_check import validate_config

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
