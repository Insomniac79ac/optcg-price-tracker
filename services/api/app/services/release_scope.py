"""Shared release identity rules for public print and market reads."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReleaseProduct


class ReleaseScopeError(ValueError):
    """The two public release selectors identify different products."""


def resolve_release_scope(
    db: Session, *, release_product_id: int | None = None, set_code: str | None = None
) -> int | None:
    """Resolve legacy JP codes; keep explicit IDs, including empty ID scopes.

    An unknown legacy code returns None, but callers must still apply that
    code's empty scope rather than treating it as an unfiltered request.
    """
    if release_product_id is not None:
        if set_code is not None:
            product = db.get(ReleaseProduct, release_product_id)
            if (
                product is None
                or product.source_catalogue != "bandai_jp"
                or product.official_code != set_code
            ):
                raise ReleaseScopeError(
                    "set and release_product_id identify different release products"
                )
        return release_product_id
    if set_code:
        return db.scalar(select(ReleaseProduct.id).where(
            ReleaseProduct.source_catalogue == "bandai_jp",
            ReleaseProduct.official_code == set_code,
        ))
    return None
