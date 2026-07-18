from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.core.pagination import pagination_response
from app.db import get_db
from app.models import User
from app.schemas import (
    SearchResponseOut,
    SearchSuggestionsResponseOut,
    SearchSummaryOut,
)
from app.services.search import (
    MIN_QUERY_LENGTH,
    SEARCH_TYPES,
    get_suggestions,
    is_exact_card_code,
    record_search_history,
    search,
)

router = APIRouter(tags=["search"])


def _parse_types(types: str | None) -> list[str] | None:
    if types is None:
        return None
    requested = [t.strip() for t in types.split(",") if t.strip()]
    if not requested:
        return None
    invalid = [t for t in requested if t not in SEARCH_TYPES]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type(s): {invalid}. Must be one of {list(SEARCH_TYPES)}",
        )
    return requested


@router.get("/search", response_model=SearchResponseOut)
def search_endpoint(
    q: str = Query(...),
    types: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    q_clean = q.strip()
    if not q_clean:
        raise HTTPException(status_code=400, detail="q is required")
    if len(q_clean) < MIN_QUERY_LENGTH and not is_exact_card_code(db, q_clean):
        raise HTTPException(
            status_code=400,
            detail=f"q must be at least {MIN_QUERY_LENGTH} characters",
        )

    active_types = _parse_types(types)

    outcome = search(db, q_clean, types=active_types, limit=limit, offset=offset)
    record_search_history(db, q_clean, outcome.total_results)

    return SearchResponseOut(
        query=outcome.query,
        summary=SearchSummaryOut(total_results=outcome.total_results, by_type=outcome.by_type),
        results=outcome.results,
        limit=limit,
        offset=offset,
        pagination=pagination_response(outcome.results, outcome.total_results, limit, offset),
    )


@router.get("/search/suggestions", response_model=SearchSuggestionsResponseOut)
def search_suggestions_endpoint(
    q: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    q_clean = q.strip() if q else None
    suggestions = get_suggestions(db, q_clean or None, limit)
    return SearchSuggestionsResponseOut(suggestions=suggestions)
