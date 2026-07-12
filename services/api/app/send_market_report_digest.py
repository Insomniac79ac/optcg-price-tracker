import argparse

from app.db import SessionLocal
from app.services.telegram_market_digest import send_market_report_digest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send a Telegram digest of the latest market intelligence report."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the message that would be sent, without sending it.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Resend even if a digest was already sent for the latest report.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()

    db = SessionLocal()
    try:
        result = send_market_report_digest(db, dry_run=args.dry_run, force=args.force)
    finally:
        db.close()

    if result is None:
        print("No market report found.")
        return

    if args.dry_run:
        print(result.message_text)
        return

    print(f"report_id: {result.report_id}")
    print(f"status: {result.status}")
    if result.skipped_reason:
        print(f"skipped_reason: {result.skipped_reason}")
    if result.error_message:
        print(f"error_message: {result.error_message}")


if __name__ == "__main__":
    main()
