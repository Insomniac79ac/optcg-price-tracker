"""SQL boundary for customer-visible history; never use before latest-row ranking."""

from sqlalchemy import or_, select
from app.models import PriceObservation, Source
from app.services.source_semantics import PROMOTION_SALE, YUYUTEI


def customer_price_clause():
    return or_(
        PriceObservation.promotion_state.is_(None),
        PriceObservation.promotion_state != PROMOTION_SALE,
        PriceObservation.source_id.not_in(select(Source.id).where(Source.name == YUYUTEI)),
    )
