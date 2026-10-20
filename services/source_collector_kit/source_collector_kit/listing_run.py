"""The list-page work unit every new collector runs (plan §2.4).

Order, and why:
  1. a parser is registered for the version (else no request at all);
  2. the budget reserves every planned request plus robots.txt (else no request at all);
  3. robots.txt is read first and must allow every planned page (fail closed);
  4. each page: fetch, write RAW and COMMIT, then parse and hand rows to the collector; a page
     the parser rejects (ValueError) is counted and skipped, its RAW kept for a re-parse;
  5. the stop rule (403, 429, challenge page) stores that response's RAW, pauses the source
     indefinitely and ends the run, with no retry;
  6. the reservation is settled with the requests actually made, whatever happened.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RawSnapshot, Source
from source_collector_kit import budget as budgets
from source_collector_kit.fetch import PoliteFetcher, SourceDenied
from source_collector_kit.health import RunReport
from source_collector_kit.raw import write_raw
from source_collector_kit.registry import ParsedPage, parser_for
from source_collector_kit.robots import RobotsRefused

PageHandler = Callable[[Session, Source, ParsedPage, RawSnapshot, RunReport], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_list_pages(
    db: Session,
    *,
    source_name: str,
    parser_version: str,
    robots_url: str,
    pages: Sequence[str],
    fetcher: PoliteFetcher,
    handle_page: PageHandler,
    clock: Callable[[], datetime] = _now,
) -> RunReport:
    report = RunReport(source=source_name, parser_version=parser_version, started_at=clock())
    report.pages_planned = len(pages)
    parse = parser_for(parser_version)
    source = db.scalar(select(Source).where(Source.name == source_name))
    if source is None:
        raise RuntimeError(f"source {source_name} is not seeded")
    reservation = budgets.reserve(db, source.id, len(pages) + 1, now=clock())
    db.commit()
    try:
        fetcher.load_robots(robots_url)
        fetcher.robots.require(list(pages))
        for url in pages:
            try:
                response = fetcher.get(url)
            except SourceDenied as denied:
                _store(db, source, denied.response, parser_version, clock, report)
                budgets.pause_for_denial(db, source.id)
                db.commit()
                report.stopped = denied.reason
                break
            raw = _store(db, source, response, parser_version, clock, report)
            db.commit()
            if response.status != 200:
                report.pages_failed += 1
                continue
            report.pages_fetched += 1
            try:
                parsed = parse(raw.raw_content, response.url)
            except ValueError as error:
                # The RAW row is already committed, so the page can be re-parsed once fixed.
                report.parse_failures += 1
                report.outcomes[f"parse_error:{type(error).__name__}"] += 1
                continue
            report.rows_parsed += len(parsed.rows)
            report.parse_failures += len(parsed.failures)
            report.header_total += parsed.header_total or 0
            handle_page(db, source, parsed, raw, report)
            db.commit()
    except SourceDenied as denied:
        # robots.txt itself answered with a stop status or a challenge.
        budgets.pause_for_denial(db, source.id)
        db.commit()
        report.stopped = denied.reason
    except RobotsRefused as refused:
        db.rollback()
        report.stopped = f"robots: {refused}"
    finally:
        db.rollback()
        budgets.settle(db, reservation, fetcher.requests_made)
        db.commit()
        report.requests = fetcher.requests_made
        report.bytes_fetched = fetcher.bytes_fetched
        report.finished_at = clock()
    return report


def _store(db, source, response, parser_version, clock, report) -> RawSnapshot:
    raw = write_raw(db, source_id=source.id, response=response, parser_version=parser_version, fetched_at=clock())
    report.raw_rows += 1
    report.raw_bytes_stored += len(raw._stored_raw_content.encode("utf-8"))
    return raw
