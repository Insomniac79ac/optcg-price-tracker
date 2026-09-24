"""Public release-navigation read model.

Release membership comes only from CardPrint.release_product_id. The current
schema has no release date or persisted cross-family catalogue sequence, so
this module deliberately returns a deterministic fallback and says that
chronology is unavailable. Consumers must not present this order as newest-
first until an authoritative sequence is persisted.
"""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import CardPrint, ReleaseProduct
from app.schemas import ReleaseCatalogueItemOut, ReleaseCatalogueListOut

ORDERING_BASIS = "deterministic_catalogue_fallback"


def list_public_releases(db: Session) -> ReleaseCatalogueListOut:
    uncoded_last = case((ReleaseProduct.official_code.is_(None), 1), else_=0)
    rows = db.execute(
        select(ReleaseProduct, func.count(CardPrint.id))
        .join(CardPrint, CardPrint.release_product_id == ReleaseProduct.id)
        .where(
            ReleaseProduct.source_catalogue == "bandai_jp",
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
            CardPrint.language == "jp",
        )
        .group_by(ReleaseProduct.id)
        .order_by(
            uncoded_last.asc(),
            ReleaseProduct.official_code.asc(),
            ReleaseProduct.display_name.asc(),
            ReleaseProduct.id.asc(),
        )
    ).all()
    return ReleaseCatalogueListOut(
        items=[
            ReleaseCatalogueItemOut(
                release_product_id=product.id,
                official_code=product.official_code,
                display_name=product.display_name,
                source_catalogue=product.source_catalogue,
                verification_status=product.verification_status,
                print_count=print_count,
                created_at=product.created_at,
            )
            for product, print_count in rows
        ],
        chronology_available=False,
        ordering_basis=ORDERING_BASIS,
    )
