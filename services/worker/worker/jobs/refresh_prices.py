import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from worker.adapters.base import SourceAdapter
from worker.adapters.mock_snkrdunk import MockSnkrdunkAdapter
from worker.adapters.mock_yuyutei import MockYuyuTeiAdapter
from worker.adapters.yuyutei import YuyuTeiAdapter
from worker.db import SessionLocal
from worker.market_report import generate_market_report
from worker.market_signal_events import snapshot_market_signals
from worker.models import PriceObservation, PriceRefreshRun, RawSnapshot, Source, SourceCardMapping
from worker.portfolio_valuation import create_portfolio_valuation_snapshot
from worker.settings import settings

logger = logging.getLogger(__name__)

MOCK_ADAPTERS: dict[str, SourceAdapter] = {
    "yuyutei": MockYuyuTeiAdapter(),
    "snkrdunk": MockSnkrdunkAdapter(),
}

SUPPORTED_SOURCES = ("yuyutei", "snkrdunk", "all")


@dataclass
class RefreshRunSummary:
    """Plain snapshot of a PriceRefreshRun, safe to read after the run's data
    transaction has been committed or rolled back (e.g. --dry-run)."""

    id: int | None
    status: str
    scraping_mode: str
    source_filter: str | None
    limit_count: int
    dry_run: bool
    mappings_checked: int = 0
    mappings_processed: int = 0
    mappings_failed: int = 0
    snapshots_created: int = 0
    observations_parsed: int = 0
    observations_inserted: int = 0
    error_message: str | None = None
    portfolio_snapshot_id: int | None = None
    market_signal_events_created: int | None = None
    market_signal_events_updated: int | None = None
    market_signal_events_resolved: int | None = None
    market_report_id: int | None = None

    def report_lines(self) -> list[str]:
        lines = [
            f"refresh_run_id: {self.id}",
            f"status: {self.status}",
            f"mappings_checked: {self.mappings_checked}",
            f"mappings_processed: {self.mappings_processed}",
            f"mappings_failed: {self.mappings_failed}",
            f"snapshots_created: {self.snapshots_created}",
            f"observations_parsed: {self.observations_parsed}",
            f"observations_inserted: {self.observations_inserted}",
        ]
        if self.error_message:
            lines.append(f"error_message: {self.error_message}")
        if self.portfolio_snapshot_id is not None:
            lines.append(f"portfolio_snapshot_id={self.portfolio_snapshot_id}")
        if self.market_signal_events_created is not None:
            lines.append(
                f"market_signal_events_created={self.market_signal_events_created} "
                f"updated={self.market_signal_events_updated} "
                f"resolved={self.market_signal_events_resolved}"
            )
        if self.market_report_id is not None:
            lines.append(f"market_report_id={self.market_report_id}")
        return lines

    def print_report(self) -> None:
        for line in self.report_lines():
            print(line)


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
) -> RefreshRunSummary:
    owns_adapters = adapters is None

    # Committed immediately so the run is on record (with an id) even if the
    # rest of the job crashes hard, and so it survives the --dry-run rollback
    # of the price data below - the run itself is audit metadata, not price
    # data, and dry runs are exactly the kind of thing worth auditing.
    run = PriceRefreshRun(
        status="running",
        scraping_mode=settings.SCRAPING_MODE,
        source_filter=source,
        limit_count=limit,
        dry_run=dry_run,
    )
    db.add(run)
    db.commit()
    run_id = run.id

    mappings_checked = 0
    mappings_processed = 0
    mappings_failed = 0
    snapshots_created = 0
    observations_parsed = 0
    observations_inserted = 0
    error_message: str | None = None

    try:
        try:
            if adapters is None:
                adapters = _build_adapters(source)

            sources_by_id = {src.id: src for src in db.query(Source).all()}

            query = (
                db.query(SourceCardMapping)
                .join(Source, SourceCardMapping.source_id == Source.id)
                .filter(SourceCardMapping.is_active.is_(True))
            )
            if source and source != "all":
                query = query.filter(Source.name == source)
            mappings = query.order_by(SourceCardMapping.id).limit(limit).all()

            for mapping in mappings:
                mappings_checked += 1
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
                    mappings_failed += 1
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
                snapshots_created += 1

                try:
                    observations = adapter.parse_snapshot(snapshot_data)
                except Exception:
                    logger.exception(
                        "Failed to parse mapping %s from source '%s', skipping.",
                        mapping.id,
                        src.name,
                    )
                    mappings_failed += 1
                    continue

                observations_parsed += len(observations)

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
                    observations_inserted += 1

                mappings_processed += 1

            if dry_run:
                db.rollback()
            else:
                db.commit()

            status = "completed_with_warnings" if mappings_failed > 0 else "completed"
        finally:
            if owns_adapters and adapters is not None:
                for adapter in adapters.values():
                    close = getattr(adapter, "close", None)
                    if callable(close):
                        close()
    except Exception as exc:
        db.rollback()
        status = "failed"
        error_message = str(exc)
        logger.exception("Refresh run %s crashed.", run_id)

    if dry_run:
        # Nothing was actually persisted, so the "inserted" count should
        # reflect that even though we know how many rows we attempted.
        observations_inserted = 0

    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.mappings_checked = mappings_checked
    run.snapshots_created = snapshots_created
    run.observations_parsed = observations_parsed
    run.observations_inserted = observations_inserted
    run.mappings_failed = mappings_failed
    run.error_message = error_message
    db.commit()

    portfolio_snapshot_id: int | None = None
    if not dry_run and status != "failed":
        try:
            portfolio_snapshot_id = create_portfolio_valuation_snapshot(db).id
        except Exception:
            # Snapshotting the portfolio is a nice-to-have on top of the
            # refresh itself - a failure here (e.g. a transient DB error)
            # must never mark an otherwise-successful refresh run as failed.
            db.rollback()
            logger.warning(
                "Failed to create portfolio valuation snapshot after refresh run %s.",
                run_id,
                exc_info=True,
            )

    market_signal_events_created: int | None = None
    market_signal_events_updated: int | None = None
    market_signal_events_resolved: int | None = None
    if not dry_run and status != "failed":
        try:
            signal_result = snapshot_market_signals(db)
            market_signal_events_created = signal_result.created
            market_signal_events_updated = signal_result.updated
            market_signal_events_resolved = signal_result.resolved
        except Exception:
            # Same rationale as the portfolio snapshot above - this must
            # never mark an otherwise-successful refresh run as failed.
            db.rollback()
            logger.warning(
                "Failed to snapshot market signal events after refresh run %s.",
                run_id,
                exc_info=True,
            )

    market_report_id: int | None = None
    if not dry_run and status != "failed":
        try:
            market_report_id = generate_market_report(db).id
        except Exception:
            # Same rationale as the portfolio snapshot and market signal
            # events above - report generation is a nice-to-have on top of
            # the refresh itself and must never mark an otherwise-successful
            # refresh run as failed.
            db.rollback()
            logger.warning(
                "Failed to generate market intelligence report after refresh run %s.",
                run_id,
                exc_info=True,
            )

    return RefreshRunSummary(
        id=run_id,
        status=status,
        scraping_mode=settings.SCRAPING_MODE,
        source_filter=source,
        limit_count=limit,
        dry_run=dry_run,
        mappings_checked=mappings_checked,
        mappings_processed=mappings_processed,
        mappings_failed=mappings_failed,
        snapshots_created=snapshots_created,
        observations_parsed=observations_parsed,
        observations_inserted=observations_inserted,
        portfolio_snapshot_id=portfolio_snapshot_id,
        market_signal_events_created=market_signal_events_created,
        market_signal_events_updated=market_signal_events_updated,
        market_signal_events_resolved=market_signal_events_resolved,
        market_report_id=market_report_id,
        error_message=error_message,
    )


def build_arg_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug-level logging.",
    )
    return parser


def log_run_config(source: str, limit: int, dry_run: bool) -> None:
    """SCRAPING_MODE always comes from settings (the SCRAPING_MODE env var),
    never from CLI args - --dry-run only ever sets dry_run, it must never be
    mistaken for (or logged as) the scraping mode."""
    logger.info("SCRAPING_MODE=%s", settings.SCRAPING_MODE)
    logger.info("source_filter=%s", source)
    logger.info("limit=%s", limit)
    logger.info("dry_run=%s", "true" if dry_run else "false")


def main() -> None:
    args = build_arg_parser().parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    log_run_config(source=args.source, limit=args.limit, dry_run=args.dry_run)

    db = SessionLocal()
    try:
        summary = refresh_prices(args.limit, db, source=args.source, dry_run=args.dry_run)
    finally:
        db.close()

    summary.print_report()


if __name__ == "__main__":
    main()
