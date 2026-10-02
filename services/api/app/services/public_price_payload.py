"""Read-time removal of promotional quotes from archived signal/report payloads.

Archives are never mutated. Resolve the source observation at the payload's
capture time, so a later sale cannot hide an earlier regular quote (or vice versa).
"""

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import PriceObservation, Source
from app.services.source_semantics import YUYUTEI, PROMOTION_SALE


def public_price_payload(db: Session, payload, *, captured_at, card_id=None):
    cache = {}

    def promotional(card, price_type, at):
        key = (card, price_type, at)
        if key not in cache:
            cache[key] = (
                db.scalar(
                    select(PriceObservation.promotion_state)
                    .join(Source, Source.id == PriceObservation.source_id)
                    .where(
                        PriceObservation.card_id == card,
                        Source.name == YUYUTEI,
                        PriceObservation.price_type == price_type,
                        PriceObservation.observed_at <= at,
                    )
                    .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc())
                    .limit(1)
                )
                == PROMOTION_SALE
            )
        return cache[key]

    def visit(value, card, at):
        if isinstance(value, list):
            pairs = [visit(item, card, at) for item in value]
            return [item for item, _ in pairs], any(changed for _, changed in pairs)
        if not isinstance(value, dict):
            return value, False
        card = value.get("card_id") or card
        stamp = value.get("last_seen_at")
        if isinstance(stamp, str):
            at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        elif isinstance(stamp, datetime):
            at = stamp
        result, changed = {}, False
        for key, item in value.items():
            result[key], child_changed = visit(item, card, at)
            changed |= child_changed
        prices = result.get("latest_prices")
        if card is not None and isinstance(prices, dict):
            for price_type in ("sell", "buy"):
                key = f"yuyutei_{price_type}"
                if prices.get(key) is not None and promotional(card, price_type, at):
                    prices[key] = None
                    changed = True
        if changed:
            if "message" in result:
                result["message"] = None
            if "metrics" in result:
                result["metrics"] = {}
        return result, changed

    return visit(payload, card_id, captured_at)[0]
