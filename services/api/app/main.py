from fastapi import FastAPI

from app.api.cards import router as cards_router
from app.api.health import router as health_router

app = FastAPI(title="optcg-price-tracker API")

app.include_router(health_router)
app.include_router(cards_router)
