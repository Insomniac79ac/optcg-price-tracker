"""Scheduled market intelligence workflow: refresh prices, then rely on
refresh_prices()'s own established cascade (see worker/jobs/refresh_prices.py)
to create the portfolio valuation snapshot, market signal snapshot, and
market intelligence report for a non-dry-run refresh - that cascade already
runs for every refresh (manual CLI, scheduled Yuyu-Tei task, or this job),
so calling the narrower snapshot/report functions again here would just
create duplicate rows for the same moment in time.

This job adds only what refresh_prices() doesn't already do: an optional
Telegram digest send, and persisting one market_workflow_runs row that
tracks the whole sequence's outcome (for /admin/market-workflow-runs).
"""

import argparse
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from worker.app_logging import log_exception, record_app_log
from worker.db import SessionLocal
from worker.jobs.refresh_prices import SUPPORTED_SOURCES, refresh_prices
from worker.market_report_digest import send_market_report_digest
from worker.models import MarketWorkflowRun

logger = logging.getLogger(__name__)

RUN_STATUSES = ("running", "success", "partial_success", "failed")

DEFAULT_MARKET_WORKFLOW_LIMIT = 10


@dataclass
class MarketWorkflowResult:
    market_workflow_run_id: int | None
    status: str
    price_refresh_run_id: int | None
    portfolio_snapshot_id: int | None
    signal_events_created: int
    signal_events_updated: int
    signal_events_resolved: int
    market_report_id: int | None
    telegram_digest_status: str | None
    warnings: list[str]
    error_message: str | None = None

    def report_lines(self) -> list[str]:
        return [
            f"market_workflow_run_id={self.market_workflow_run_id}",
            f"status={self.status}",
            f"price_refresh_run_id={self.price_refresh_run_id}",
            f"portfolio_snapshot_id={self.portfolio_snapshot_id}",
            f"market_signal_events_created={self.signal_events_created}",
            f"market_signal_events_updated={self.signal_events_updated}",
            f"market_signal_events_resolved={self.signal_events_resolved}",
            f"market_report_id={self.market_report_id}",
            f"telegram_digest_status={self.telegram_digest_status}",
            f"warnings_count={len(self.warnings)}",
        ]

    def print_report(self) -> None:
        for line in self.report_lines():
            print(line)
        for warning in self.warnings:
            print(f"warning: {warning}")


def run_market_workflow(
    db: Session,
    source: str = "yuyutei",
    limit: int | None = None,
    send_telegram: bool = False,
    dry_run: bool = False,
) -> MarketWorkflowResult:
    effective_limit = limit if limit is not None else DEFAULT_MARKET_WORKFLOW_LIMIT
    started_at = datetime.now(timezone.utc)

    run = MarketWorkflowRun(
        started_at=started_at,
        status="running",
        source=source,
        limit=effective_limit,
        send_telegram=send_telegram,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    record_app_log(
        "info",
        "worker",
        "market_workflow",
        f"Market workflow run {run.id} started (source={source}, limit={effective_limit}, "
        f"send_telegram={send_telegram}).",
        related_run_id=run.id,
        related_entity_type="market_workflow_run",
        related_entity_id=run.id,
    )

    try:
        refresh_summary = refresh_prices(
            limit=effective_limit, db=db, source=source, dry_run=dry_run
        )
    except Exception as exc:
        logger.exception("run_market_workflow: refresh_prices crashed.")
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        log_exception(
            "worker",
            "market_workflow",
            f"Market workflow run {run.id} failed: refresh_prices crashed.",
            exc,
            related_run_id=run.id,
            related_entity_type="market_workflow_run",
            related_entity_id=run.id,
        )
        return MarketWorkflowResult(
            market_workflow_run_id=run.id,
            status="failed",
            price_refresh_run_id=None,
            portfolio_snapshot_id=None,
            signal_events_created=0,
            signal_events_updated=0,
            signal_events_resolved=0,
            market_report_id=None,
            telegram_digest_status=None,
            warnings=[],
            error_message=str(exc),
        )

    warnings: list[str] = []
    portfolio_snapshot_id: int | None = None
    created = updated = resolved = 0
    market_report_id: int | None = None
    telegram_digest_status: str | None = None

    if refresh_summary.status == "failed":
        warnings.append(f"Price refresh failed: {refresh_summary.error_message}")
    else:
        if refresh_summary.status == "completed_with_warnings":
            warnings.append(
                f"{refresh_summary.mappings_failed} mapping(s) failed during price refresh."
            )

        if not dry_run:
            portfolio_snapshot_id = refresh_summary.portfolio_snapshot_id
            if portfolio_snapshot_id is None:
                warnings.append("Portfolio valuation snapshot was not created.")

            if refresh_summary.market_signal_events_created is None:
                warnings.append("Market signal snapshot was not created.")
            else:
                created = refresh_summary.market_signal_events_created
                updated = refresh_summary.market_signal_events_updated or 0
                resolved = refresh_summary.market_signal_events_resolved or 0

            market_report_id = refresh_summary.market_report_id
            if market_report_id is None:
                warnings.append("Market intelligence report was not generated.")

            if send_telegram and market_report_id is not None:
                try:
                    digest_result = send_market_report_digest(db)
                    telegram_digest_status = (
                        digest_result.status if digest_result is not None else None
                    )
                    if digest_result is not None and digest_result.status == "failed":
                        warnings.append(
                            f"Telegram digest failed: {digest_result.error_message}"
                        )
                        record_app_log(
                            "error",
                            "worker",
                            "telegram_digest",
                            f"Telegram digest failed for market workflow run {run.id}: "
                            f"{digest_result.error_message}",
                            related_run_id=run.id,
                            related_entity_type="market_workflow_run",
                            related_entity_id=run.id,
                        )
                    elif digest_result is not None and digest_result.status == "skipped":
                        record_app_log(
                            "info",
                            "worker",
                            "telegram_digest",
                            f"Telegram digest skipped for market workflow run {run.id}: "
                            f"{digest_result.skipped_reason}",
                            related_run_id=run.id,
                            related_entity_type="market_workflow_run",
                            related_entity_id=run.id,
                        )
                    elif digest_result is not None and digest_result.status == "sent":
                        record_app_log(
                            "info",
                            "worker",
                            "telegram_digest",
                            f"Telegram digest sent for market workflow run {run.id}.",
                            related_run_id=run.id,
                            related_entity_type="market_workflow_run",
                            related_entity_id=run.id,
                        )
                except Exception as exc:
                    logger.exception("run_market_workflow: telegram digest crashed.")
                    telegram_digest_status = "failed"
                    warnings.append(f"Telegram digest failed: {exc}")
                    log_exception(
                        "worker",
                        "telegram_digest",
                        f"Telegram digest crashed for market workflow run {run.id}.",
                        exc,
                        related_run_id=run.id,
                        related_entity_type="market_workflow_run",
                        related_entity_id=run.id,
                    )

    final_status = "failed" if refresh_summary.status == "failed" else (
        "partial_success" if warnings else "success"
    )

    run.status = final_status
    run.finished_at = datetime.now(timezone.utc)
    run.price_refresh_run_id = refresh_summary.id
    run.portfolio_snapshot_id = portfolio_snapshot_id
    run.market_report_id = market_report_id
    run.signal_events_created = created
    run.signal_events_updated = updated
    run.signal_events_resolved = resolved
    run.telegram_digest_status = telegram_digest_status
    run.warnings_json = warnings
    db.commit()
    db.refresh(run)

    _final_log_kwargs = dict(
        related_run_id=run.id, related_entity_type="market_workflow_run", related_entity_id=run.id
    )
    if final_status == "failed":
        record_app_log(
            "error",
            "worker",
            "market_workflow",
            f"Market workflow run {run.id} failed: {refresh_summary.error_message}",
            context={"warnings": warnings},
            **_final_log_kwargs,
        )
    elif final_status == "partial_success":
        record_app_log(
            "warning",
            "worker",
            "market_workflow",
            f"Market workflow run {run.id} completed with warnings.",
            context={"warnings": warnings},
            **_final_log_kwargs,
        )
    else:
        record_app_log(
            "info",
            "worker",
            "market_workflow",
            f"Market workflow run {run.id} completed successfully.",
            **_final_log_kwargs,
        )

    result = MarketWorkflowResult(
        market_workflow_run_id=run.id,
        status=final_status,
        price_refresh_run_id=refresh_summary.id,
        portfolio_snapshot_id=portfolio_snapshot_id,
        signal_events_created=created,
        signal_events_updated=updated,
        signal_events_resolved=resolved,
        market_report_id=market_report_id,
        telegram_digest_status=telegram_digest_status,
        warnings=warnings,
    )

    logger.info(
        "market_workflow_run summary: %s",
        " ".join(result.report_lines()),
    )

    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the full market intelligence workflow: refresh prices, "
        "snapshot the portfolio and market signals, generate a report, and "
        "optionally send a Telegram digest."
    )
    parser.add_argument(
        "--source", choices=SUPPORTED_SOURCES, default="yuyutei",
        help="Restrict to a single source, or process all mapped sources.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help=f"Max number of mappings to process (default: {DEFAULT_MARKET_WORKFLOW_LIMIT}).",
    )
    parser.add_argument(
        "--send-telegram", action="store_true",
        help="Send a Telegram digest of the resulting report, if configured.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Refresh prices in dry-run mode; skip the snapshot, report, and digest steps.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug-level logging.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    db = SessionLocal()
    try:
        result = run_market_workflow(
            db,
            source=args.source,
            limit=args.limit,
            send_telegram=args.send_telegram,
            dry_run=args.dry_run,
        )
    finally:
        db.close()

    result.print_report()


if __name__ == "__main__":
    main()
