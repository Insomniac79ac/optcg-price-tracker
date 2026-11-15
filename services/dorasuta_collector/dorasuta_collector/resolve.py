"""Re-resolve every stored Dorasuta product (plan §2.3). Run after each collection run.

Writes only source_products.match_status, refusal_code and card_print_id; a manual match is never
touched. Every outcome comes from app.source_products.resolver, which calls resolve_exact_print
unchanged. Fetches nothing.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source
from app.source_products import dorasuta_rules
from app.source_products.models import SourceProduct
from app.source_products.resolver import apply_resolution, resolve_stored_product
from dorasuta_collector.config import SOURCE


def resolve_all(db: Session) -> Counter:
    source = db.scalar(select(Source).where(Source.name == SOURCE))
    if source is None:
        raise RuntimeError(f"source {SOURCE} is not seeded")
    products = db.scalars(
        select(SourceProduct).where(SourceProduct.source_id == source.id).order_by(SourceProduct.id)
    ).all()
    outcomes: Counter = Counter()
    # Two passes: release every non-manual print first, so a print a product held last time is
    # not counted against its own re-resolution as "held elsewhere".
    for product in products:
        if product.match_status != "manual":
            product.match_status, product.card_print_id, product.refusal_code = "pending", None, None
    db.flush()
    for product in products:
        if product.match_status == "manual":
            outcomes["manual"] += 1
            continue
        resolution = resolve_stored_product(db, product, dorasuta_rules.parse_title(product.name))
        apply_resolution(product, resolution)
        db.flush()
        outcomes[resolution.refusal_code or resolution.match_status] += 1
    return outcomes
