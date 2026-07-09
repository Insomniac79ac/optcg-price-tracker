import argparse
import logging

from app.config_check import check_database_connected, check_redis_connected, validate_config
from app.settings import settings


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate API configuration and check database/redis connectivity."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable debug-level logging.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    result = validate_config()
    database_connected = check_database_connected()
    redis_connected = check_redis_connected()

    print(f"api_config_status: {'ok' if result.ok else 'invalid'}")
    print(f"database_connected: {'yes' if database_connected else 'no'}")
    print(f"redis_connected: {'yes' if redis_connected else 'no'}")
    print(f"admin_token_configured: {'yes' if settings.ADMIN_TOKEN else 'no'}")
    print(f"environment: {result.app_env}")
    for error in result.errors:
        print(f"error: {error}")

    if not result.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
