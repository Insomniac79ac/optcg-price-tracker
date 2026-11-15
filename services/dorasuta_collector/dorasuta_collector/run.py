"""One Dorasuta asks run: `python -m dorasuta_collector.run`.

Refuses before any request when the contact variable is missing (N16), no series is configured,
or no parser is registered for PARSER_VERSION. The list-page parser waits for real list-page
fixtures (plan D0: the source hosts are not reachable from the build environment), so today every
run stops at that check.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from app.db import SessionLocal
from dorasuta_collector import config
from dorasuta_collector.resolve import resolve_all
from dorasuta_collector.writer import handle_page
from source_collector_kit.etiquette import CONTACT_ENV, EtiquetteError, user_agent
from source_collector_kit.fetch import PoliteFetcher
from source_collector_kit.listing_run import run_list_pages
from source_collector_kit.registry import ParserUnavailable, parser_for


def main(argv: list[str] | None = None) -> int:
    try:
        agent = user_agent(os.environ.get(CONTACT_ENV))
        parser_for(config.PARSER_VERSION)
        series = config.parse_series(os.environ.get(config.SERIES_ENV))
        if not series:
            raise ValueError(f"{config.SERIES_ENV} names no series")
    except (EtiquetteError, ParserUnavailable, ValueError) as refusal:
        print(f'{{"event": "dorasuta_run_refused", "reason": "{type(refusal).__name__}"}}')
        return 2
    today = datetime.now(timezone.utc).date()
    pages = config.plan_pages(series, today.toordinal())
    fetcher = PoliteFetcher(
        user_agent=agent, allowed_hosts=config.HOSTS, max_requests=len(pages) + 1
    )
    with SessionLocal() as db:
        report = run_list_pages(
            db,
            source_name=config.SOURCE,
            parser_version=config.PARSER_VERSION,
            robots_url=config.ROBOTS_URL,
            pages=pages,
            fetcher=fetcher,
            handle_page=handle_page,
        )
        if report.stopped is None:
            report.outcomes.update({f"identity:{k}": v for k, v in resolve_all(db).items()})
            db.commit()
        print(report.to_log())
    return 1 if report.stopped else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
