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

    Dated products appear newest first. Same-day ties and undated products use
    deterministic catalogue ordering; undated products follow all dated rows.
    Item chronology availability is separate from endpoint chronology support.
    """
    return list_public_releases(db)
