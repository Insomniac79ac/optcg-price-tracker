from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.db import get_db
from app.models import User
from app.schemas import (
    ClearDefaultSavedViewIn,
    SavedViewCreateIn,
    SavedViewListOut,
    SavedViewOut,
    SavedViewUpdateIn,
)
from app.services.saved_views import (
    SavedViewNotFoundError,
    SavedViewValidationError,
    clear_default_saved_view,
    create_saved_view,
    delete_saved_view,
    get_saved_view,
    list_saved_views,
    mark_saved_view_used,
    set_default_saved_view,
    update_saved_view,
)

router = APIRouter(prefix="/saved-views", tags=["saved_views"])


@router.get("", response_model=SavedViewListOut)
def get_saved_views(
    route_path: str | None = None,
    view_type: str | None = None,
    scope: str | None = None,
    pinned: bool | None = None,
    is_default: bool | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    items, pagination = list_saved_views(
        db,
        route_path=route_path,
        view_type=view_type,
        scope=scope,
        pinned=pinned,
        is_default=is_default,
        q=q,
        limit=limit,
        offset=offset,
    )
    return SavedViewListOut(items=items, pagination=pagination)


@router.post("", response_model=SavedViewOut, status_code=201)
def post_saved_view(
    body: SavedViewCreateIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    try:
        return create_saved_view(db, body)
    except SavedViewValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{view_id}", response_model=SavedViewOut)
def get_saved_view_by_id(
    view_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    try:
        return get_saved_view(db, view_id)
    except SavedViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{view_id}", response_model=SavedViewOut)
def patch_saved_view(
    view_id: int,
    body: SavedViewUpdateIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    try:
        return update_saved_view(db, view_id, body)
    except SavedViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SavedViewValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{view_id}", status_code=204)
def delete_saved_view_by_id(
    view_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    try:
        delete_saved_view(db, view_id)
    except SavedViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return None


@router.post("/{view_id}/use", response_model=SavedViewOut)
def post_use_saved_view(
    view_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    try:
        return mark_saved_view_used(db, view_id)
    except SavedViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{view_id}/set-default", response_model=SavedViewOut)
def post_set_default_saved_view(
    view_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    try:
        return set_default_saved_view(db, view_id)
    except SavedViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/clear-default", status_code=204)
def post_clear_default_saved_view(
    body: ClearDefaultSavedViewIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    clear_default_saved_view(db, body.route_path, body.view_type)
    return None
