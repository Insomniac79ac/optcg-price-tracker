from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.db import get_db
from app.models import DashboardPreference, User
from app.schemas import DashboardOverviewOut, DashboardPreferencesOut, DashboardPreferencesUpdateIn
from app.services.dashboard import (
    DashboardValidationError,
    build_overview,
    get_or_create_preferences,
    update_preferences,
)

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
def get_dashboard_overview(db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    return build_overview(db, user.id)
