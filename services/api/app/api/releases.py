"""Public, read-only product catalogue for release navigation."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import ReleaseCatalogueListOut
from app.services.release_catalogue import list_public_releases

router = APIRouter(prefix="/releases", tags=["releases"])


@router.get("", response_model=ReleaseCatalogueListOut)
def get_releases(db: Session = Depends(get_db)):
    """Relevant Bandai JP products with authoritative print counts.

    The response explicitly reports that cross-family release chronology is
    unavailable; its order is a stable catalogue fallback, not a release-date
    claim.
    """
    return list_public_releases(db)
