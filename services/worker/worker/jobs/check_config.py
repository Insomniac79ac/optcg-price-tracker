"""Validates worker configuration and checks database/redis connectivity.

Most config validation already happens the moment `worker.settings` is
imported - Settings' field validators (SCRAPING_MODE, YUYUTEI_REQUEST_DELAY_MS,
PRICE_REFRESH_INTERVAL_HOURS, DATABASE_URL, REDIS_URL) raise a clear
pydantic ValidationError at process startup if misconfigured, so if this
module's main() runs at all, that already passed. This CLI reports that
status plus the things that require actual I/O (database/redis reachability).
"""

import argparse
import logging

from worker.alerts.telegram import is_telegram_configured
from worker.config_check import check_database_connected, check_redis_connected
from worker.settings import settings


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate worker configuration and check database/redis connectivity."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug-level logging.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    database_connected = check_database_connected()
    redis_connected = check_redis_connected()
    telegram_configured = is_telegram_configured()

    print("worker_config_status: ok")
    print(f"scraping_mode: {settings.SCRAPING_MODE}")
    print(f"database_connected: {'yes' if database_connected else 'no'}")
    print(f"redis_connected: {'yes' if redis_connected else 'no'}")
    print(f"telegram_configured: {'yes' if telegram_configured else 'no'}")


if __name__ == "__main__":
    main()
