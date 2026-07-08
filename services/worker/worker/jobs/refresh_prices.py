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

SUPPORTED_SOURCES = ("yuyutei", "snkrdunk", "all")


def _build_adapters(source: str | None = None) -> dict[str, SourceAdapter]:
    if settings.SCRAPING_MODE == "mock":
        adapters = MOCK_ADAPTERS
    elif settings.SCRAPING_MODE == "live":
        # Only yuyutei has a live adapter so far; snkrdunk is skipped below.
        adapters = {"yuyutei": YuyuTeiAdapter()}
    else:
        raise ValueError(f"Unknown SCRAPING_MODE '{settings.SCRAPING_MODE}'.")

    if source and source != "all":
        return {name: adapter for name, adapter in adapters.items() if name == source}
    return adapters


def refresh_prices(
    limit: int,
    db: Session,
    adapters: dict[str, SourceAdapter] | None = None,
    source: str | None = None,
    dry_run: bool = False,
) -> int:
    owns_adapters = adapters is None
    if adapters is None:
        adapters = _build_adapters(source)

    sources_by_id = {src.id: src for src in db.query(Source).all()}

    query = db.query(SourceCardMapping).join(Source, SourceCardMapping.source_id == Source.id)
    if source and source != "all":
        query = query.filter(Source.name == source)
    mappings = query.order_by(SourceCardMapping.id).limit(limit).all()

    processed = 0
    try:
        for mapping in mappings:
            src = sources_by_id.get(mapping.source_id)
            if src is None:
                continue

            adapter = adapters.get(src.name)
            if adapter is None:
                logger.info(
                    "No %s adapter for source '%s', skipping mapping %s.",
                    settings.SCRAPING_MODE,
                    src.name,
                    mapping.id,
                )
                continue

            try:
                snapshot_data = adapter.fetch_card(mapping)
            except Exception:
                logger.exception(
                    "Failed to fetch mapping %s from source '%s', skipping.",
                    mapping.id,
                    src.name,
                )
                continue

            raw_snapshot = RawSnapshot(
                source_id=src.id,
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
                    src.name,
                )
                continue

            for observation in observations:
                db.add(
                    PriceObservation(
                        card_id=mapping.card_id,
                        source_id=src.id,
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
    finally:
        if owns_adapters:
            for adapter in adapters.values():
                close = getattr(adapter, "close", None)
                if callable(close):
                    close()

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return processed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Refresh price observations from mapped sources.")
    parser.add_argument(
        "--source", choices=SUPPORTED_SOURCES, default="all",
        help="Restrict to a single source, or process all mapped sources (default).",
    )
    parser.add_argument("--limit", type=int, default=10, help="Max number of mappings to process.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and parse without committing new rows to the database.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        processed = refresh_prices(args.limit, db, source=args.source, dry_run=args.dry_run)
        print(f"Processed {processed} source_card_mapping(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
