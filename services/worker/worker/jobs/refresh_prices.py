import argparse
import logging

from sqlalchemy.orm import Session

from worker.adapters.base import SourceAdapter
from worker.adapters.mock_snkrdunk import MockSnkrdunkAdapter
from worker.adapters.mock_yuyutei import MockYuyuTeiAdapter
from worker.adapters.yuyutei import YuyuTeiAdapter
from worker.db import SessionLocal
from worker.models import PriceObservation, RawSnapshot, Source, SourceCardMapping
from worker.settings import settings

logger = logging.getLogger(__name__)

MOCK_ADAPTERS: dict[str, SourceAdapter] = {
    "yuyutei": MockYuyuTeiAdapter(),
    "snkrdunk": MockSnkrdunkAdapter(),
}


def _build_adapters() -> dict[str, SourceAdapter]:
    if settings.SCRAPING_MODE == "mock":
        return MOCK_ADAPTERS
    if settings.SCRAPING_MODE == "live":
        # Only yuyutei has a live adapter so far; snkrdunk is skipped below.
        return {"yuyutei": YuyuTeiAdapter()}
    raise ValueError(f"Unknown SCRAPING_MODE '{settings.SCRAPING_MODE}'.")


def refresh_prices(limit: int, db: Session, adapters: dict[str, SourceAdapter] | None = None) -> int:
    if adapters is None:
        adapters = _build_adapters()

    sources_by_id = {source.id: source for source in db.query(Source).all()}
    mappings = (
        db.query(SourceCardMapping).order_by(SourceCardMapping.id).limit(limit).all()
    )

    processed = 0
    for mapping in mappings:
        source = sources_by_id.get(mapping.source_id)
        if source is None:
            continue

        adapter = adapters.get(source.name)
        if adapter is None:
            logger.info(
                "No %s adapter for source '%s', skipping mapping %s.",
                settings.SCRAPING_MODE,
                source.name,
                mapping.id,
            )
            continue

        try:
            snapshot_data = adapter.fetch_card(mapping)
        except Exception:
            logger.exception(
                "Failed to fetch mapping %s from source '%s', skipping.",
                mapping.id,
                source.name,
            )
            continue

        raw_snapshot = RawSnapshot(
            source_id=source.id,
            source_url=snapshot_data.source_url,
            fetched_at=snapshot_data.fetched_at,
            http_status=snapshot_data.http_status,
            content_hash=snapshot_data.content_hash,
            raw_content=snapshot_data.raw_content,
            parser_version=snapshot_data.parser_version,
        )
        db.add(raw_snapshot)
        db.flush()

        try:
            observations = adapter.parse_snapshot(snapshot_data)
        except Exception:
            logger.exception(
                "Failed to parse mapping %s from source '%s', skipping.",
                mapping.id,
                source.name,
            )
            continue

        for observation in observations:
            db.add(
                PriceObservation(
                    card_id=mapping.card_id,
                    source_id=source.id,
                    observed_at=observation.observed_at,
                    price_type=observation.price_type,
                    price_jpy=observation.price_jpy,
                    condition_label=observation.condition_label,
                    stock_status=observation.stock_status,
                    listing_count=observation.listing_count,
                    raw_snapshot_id=raw_snapshot.id,
                )
            )

        processed += 1

    db.commit()
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh price observations from mock sources.")
    parser.add_argument("--limit", type=int, default=10, help="Max number of mappings to process.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        processed = refresh_prices(args.limit, db)
        print(f"Processed {processed} source_card_mapping(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
