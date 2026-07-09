from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.alerts import router as alerts_router
from app.api.cards import router as cards_router
from app.api.health import router as health_router
from app.api.market import router as market_router
from app.api.refresh_runs import router as refresh_runs_router
from app.api.snkrdunk_candidates import router as snkrdunk_candidates_router

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
