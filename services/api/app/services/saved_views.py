"""Single-user saved filter/sort/column presets for dense list pages. See
app.models.saved_view for why this table has no user_id (one shared, global
preset store - this app has no multi-user accounts to scope by).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import pagination_response
from app.models.saved_view import SAVED_VIEW_DENSITIES, SAVED_VIEW_SCOPES, SavedView
from app.schemas import PaginationMeta

# Key-name substrings that must never appear in a saved filter/sort/column
# payload - the primary defense is that no page's filter-serialization code
# includes admin tokens or confirm-modal state in the first place (they're
# separate pieces of component state), this is just the backend-side
# safety net the task explicitly asked for.
_FORBIDDEN_KEY_SUBSTRINGS = ("token", "password", "secret", "confirm")


class SavedViewValidationError(ValueError):
    pass


class SavedViewNotFoundError(ValueError):
    pass


def _validate_json_field(name: str, value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise SavedViewValidationError(f"{name} must be an object or null")
    _reject_forbidden_keys(name, value)


def _reject_forbidden_keys(name: str, value: dict) -> None:
    for key in value:
        key_lower = str(key).lower()
        if any(bad in key_lower for bad in _FORBIDDEN_KEY_SUBSTRINGS):
            raise SavedViewValidationError(
                f"{name} must not contain a key resembling a token/password/secret/"
                f"confirmation field ({key!r})"
            )


def _validate_scope(scope: str) -> None:
    if scope not in SAVED_VIEW_SCOPES:
        raise SavedViewValidationError(f"Invalid scope: {scope}")


def _validate_density(density: str) -> None:
    if density not in SAVED_VIEW_DENSITIES:
        raise SavedViewValidationError(f"Invalid density: {density}")


def _get_saved_view_or_404(db: Session, view_id: int) -> SavedView:
    view = db.get(SavedView, view_id)
    if view is None:
        raise SavedViewNotFoundError(f"Saved view {view_id} not found")
    return view


def list_saved_views(
    db: Session,
    *,
    route_path: str | None = None,
    view_type: str | None = None,
    scope: str | None = None,
    pinned: bool | None = None,
    is_default: bool | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[SavedView], PaginationMeta]:
    filters = []
    if route_path is not None:
        filters.append(SavedView.route_path == route_path)
    if view_type is not None:
        filters.append(SavedView.view_type == view_type)
    if scope is not None:
        filters.append(SavedView.scope == scope)
    if pinned is not None:
        filters.append(SavedView.pinned == pinned)
    if is_default is not None:
        filters.append(SavedView.is_default == is_default)
    if q:
        like = f"%{q.strip()}%"
        filters.append(SavedView.name.ilike(like))

    total = len(db.scalars(select(SavedView.id).where(*filters)).all())
    items = db.scalars(
        select(SavedView)
        .where(*filters)
        .order_by(SavedView.pinned.desc(), SavedView.name.asc())
        .limit(limit)
        .offset(offset)
    ).all()

    return list(items), pagination_response(items, total, limit, offset)


def get_saved_view(db: Session, view_id: int) -> SavedView:
    return _get_saved_view_or_404(db, view_id)


def create_saved_view(db: Session, payload) -> SavedView:
    _validate_scope(payload.scope)
    _validate_density(payload.density)
    _validate_json_field("filters_json", payload.filters_json)
    _validate_json_field("sort_json", payload.sort_json)
    _validate_json_field("columns_json", payload.columns_json)

    view = SavedView(
        name=payload.name,
        description=payload.description,
        route_path=payload.route_path,
        view_type=payload.view_type,
        scope=payload.scope,
        filters_json=payload.filters_json,
        sort_json=payload.sort_json,
        columns_json=payload.columns_json,
        density=payload.density,
        is_default=False,
        pinned=payload.pinned,
        notes=payload.notes,
    )
    db.add(view)
    db.commit()
    db.refresh(view)

    if payload.is_default:
        set_default_saved_view(db, view.id)
        db.refresh(view)

    return view


def update_saved_view(db: Session, view_id: int, payload) -> SavedView:
    view = _get_saved_view_or_404(db, view_id)
    updates = payload.model_dump(exclude_unset=True)

    if "density" in updates and updates["density"] is not None:
        _validate_density(updates["density"])
    for field_name in ("filters_json", "sort_json", "columns_json"):
        if field_name in updates:
            _validate_json_field(field_name, updates[field_name])

    make_default = updates.pop("is_default", None)

    for field_name, value in updates.items():
        setattr(view, field_name, value)

    db.commit()
    db.refresh(view)

    if make_default:
        set_default_saved_view(db, view.id)
        db.refresh(view)
    elif make_default is False:
        view.is_default = False
        db.commit()
        db.refresh(view)

    return view


def delete_saved_view(db: Session, view_id: int) -> None:
    view = _get_saved_view_or_404(db, view_id)
    db.delete(view)
    db.commit()


def mark_saved_view_used(db: Session, view_id: int) -> SavedView:
    view = _get_saved_view_or_404(db, view_id)
    view.usage_count += 1
    view.last_used_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(view)
    return view


def set_default_saved_view(db: Session, view_id: int) -> SavedView:
    """Only one default saved view per (route_path, view_type) - unsets any
    other row sharing that pair before setting this one."""
    view = _get_saved_view_or_404(db, view_id)

    db.query(SavedView).filter(
        SavedView.route_path == view.route_path,
        SavedView.view_type == view.view_type,
        SavedView.id != view.id,
        SavedView.is_default.is_(True),
    ).update({"is_default": False})

    view.is_default = True
    db.commit()
    db.refresh(view)
    return view


def clear_default_saved_view(db: Session, route_path: str, view_type: str) -> None:
    db.query(SavedView).filter(
        SavedView.route_path == route_path,
        SavedView.view_type == view_type,
        SavedView.is_default.is_(True),
    ).update({"is_default": False})
    db.commit()
