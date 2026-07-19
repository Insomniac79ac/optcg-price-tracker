from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.db import get_db
from app.models import DashboardPreference, User
from app.schemas import DashboardOverviewOut, DashboardPreferencesOut, DashboardPreferencesUpdateIn
from app.services.cache import get_or_set_cache
from app.services.cache_headers import set_cache_headers
from app.services.dashboard import (
    DashboardValidationError,
    build_overview,
    get_or_create_preferences,
    update_preferences,
)
from app.settings import settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _to_preferences_out(pref: DashboardPreference) -> DashboardPreferencesOut:
    return DashboardPreferencesOut(**pref.preference_value_json)


@router.get("/preferences", response_model=DashboardPreferencesOut)
def get_dashboard_preferences(
    db: Session = Depends(get_db), _user: User = Depends(require_current_user)
):
    pref = get_or_create_preferences(db)
    return _to_preferences_out(pref)


@router.patch("/preferences", response_model=DashboardPreferencesOut)
def patch_dashboard_preferences(
    body: DashboardPreferencesUpdateIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    try:
        pref = update_preferences(db, body)
    except DashboardValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_preferences_out(pref)


@router.get("/overview", response_model=DashboardOverviewOut)
def get_dashboard_overview(
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    cache_key = f"dashboard:overview:{user.id}"
    ttl = settings.CACHE_DASHBOARD_TTL_SECONDS
    value, hit = get_or_set_cache(
        cache_key, ttl, lambda: build_overview(db, user.id).model_dump(mode="json")
    )
    set_cache_headers(response, hit=hit, ttl_seconds=ttl, cache_key=cache_key)
    return value
