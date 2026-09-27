"""Public release-navigation read model.

Release membership comes only from CardPrint.release_product_id. Dated products
sort newest first, with a deterministic fallback for ties and undated products.
The tie breakers express no chronology between products released on the same day.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CardPrint, ReleaseProduct
from app.schemas import ReleaseCatalogueItemOut, ReleaseCatalogueListOut
from app.services.release_ordering import ORDERING_BASIS, public_release_ordering


def list_public_releases(db: Session) -> ReleaseCatalogueListOut:
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
        .order_by(*public_release_ordering())
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
                released_on=product.released_on,
                chronology_available=product.released_on is not None,
                release_date_source=product.release_date_source,
            )
            for product, print_count in rows
        ],
        chronology_available=True,
        ordering_basis=ORDERING_BASIS,
    )
