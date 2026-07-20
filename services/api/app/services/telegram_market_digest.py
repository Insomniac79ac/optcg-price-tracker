"""Formats and sends a concise Telegram digest of the latest deterministic
market intelligence report. Reads only fields the report already computed
(app/services/market_report.py) - no new scoring/valuation formulas, no
scraping, no AI/LLM-generated text.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalyticsDigestReport, MarketIntelligenceReport, MarketReportDigestSend
from app.services.job_locks import with_job_lock
from app.services.telegram_client import TelegramSendError, is_telegram_configured, send_telegram_message

DEFAULT_DESTINATION = "telegram"

# Telegram's real limit is 4096 characters - this leaves comfortable margin
# so truncation kicks in before a message would ever be rejected outright.
TELEGRAM_SAFE_MESSAGE_LENGTH = 3500

TRUNCATION_NOTE = "Open dashboard for full report."


def _jpy(value: int | None) -> str:
    if value is None:
        return "not available"
    return f"¥{value:,}"


def _number(value: int | float | None) -> str:
    if value is None:
        return "not available"
    return str(value)


def _opportunity_line(label: str, opp: dict | None) -> str:
    if not opp:
        return f"{label}: not available"
    score = opp.get("score")
    code = opp.get("card_code") or "unknown"
    name = opp.get("name_en") or opp.get("name_jp") or "unknown"
    message = opp.get("message") or ""
    line = f"{label}: [{score}] {code} {name}"
    if message:
        line += f" - {message}"
    return line


def _latest_report(db: Session) -> MarketIntelligenceReport | None:
    return db.scalar(
        select(MarketIntelligenceReport).order_by(
            MarketIntelligenceReport.created_at.desc(), MarketIntelligenceReport.id.desc()
        )
    )


def _latest_analytics_digest(db: Session) -> AnalyticsDigestReport | None:
    return db.scalar(
        select(AnalyticsDigestReport).order_by(
            AnalyticsDigestReport.created_at.desc(), AnalyticsDigestReport.id.desc()
        )
    )


def _analytics_digest_section(digest: AnalyticsDigestReport | None) -> list[str]:
    """Optional, compact addition to the Telegram message when an analytics
    digest (see app.services.analytics_digest) has been generated at least
    once - a handful of already-computed headline numbers, not the full
    digest. Omitted entirely (not even a header) when no digest exists yet,
    so this stays a no-op for anyone who never runs
    python -m app.generate_analytics_digest / the admin action."""
    if digest is None:
        return []
    return [
        "",
        "Analytics digest:",
        f"Portfolio risk: {digest.portfolio_risk_score} ({digest.portfolio_risk_level})",
        f"Buy review: {digest.buy_review_count} | Sell review: {digest.sell_review_count}",
        f"Wishlist target hits: {digest.wishlist_target_hits}",
    ]


def format_digest_message(
    report: MarketIntelligenceReport, digest: AnalyticsDigestReport | None = None
) -> str:
    payload = report.report_payload_json or {}
    top_opportunities = payload.get("top_opportunities") or {}
    top_5 = top_opportunities.get("top_5") or []
    summary_lines = payload.get("deterministic_summary_lines") or []

    header_lines = [
        "\U0001f4ca OPCG Market Report",
        "",
        f"Report date: {report.report_date.isoformat()}",
        f"Total opportunities: {report.total_opportunities}",
        f"Highest score: {_number(report.highest_score)}",
        f"Average score: {_number(report.average_score)}",
        f"Portfolio market floor: {_jpy(report.portfolio_market_floor_value_jpy)}",
        f"P/L vs market floor: {_jpy(report.portfolio_pnl_vs_market_floor_jpy)}",
        f"Buy opportunities: {report.buy_opportunities_count}",
        f"Sell opportunities: {report.sell_opportunities_count}",
        f"Data quality issues: {report.data_quality_count}",
    ]

    summary_section: list[str] = []
    if summary_lines:
        summary_section.append("")
        summary_section.append("Summary:")
        summary_section.extend(f"- {line}" for line in summary_lines)

    digest_section = _analytics_digest_section(digest)

    opportunities_section = [
        "",
        "Top opportunities:",
        _opportunity_line("Top overall", top_5[0] if top_5 else None),
        _opportunity_line("Top buy", report.top_buy_json),
        _opportunity_line("Top sell", report.top_sell_json),
        _opportunity_line("Top owned", report.top_owned_json),
    ]

    full_message = "\n".join(header_lines + summary_section + digest_section + opportunities_section)
    if len(full_message) <= TELEGRAM_SAFE_MESSAGE_LENGTH:
        return full_message

    # Top opportunities are the most verbose, least essential section for a
    # quick digest - drop them first rather than cutting the stats/summary/
    # analytics digest sections.
    truncated_message = "\n".join(
        header_lines + summary_section + digest_section + ["", TRUNCATION_NOTE]
    )
    return truncated_message


@dataclass
class DigestSendResult:
    report_id: int
    status: str
    sent: bool
    skipped_reason: str | None
    message_text: str
    error_message: str | None = None


def get_digest_send(
    db: Session, report_id: int, destination: str = DEFAULT_DESTINATION
) -> MarketReportDigestSend | None:
    return db.scalar(
        select(MarketReportDigestSend).where(
            MarketReportDigestSend.report_id == report_id,
            MarketReportDigestSend.destination == destination,
        )
    )


def _upsert_send_row(
    db: Session,
    existing: MarketReportDigestSend | None,
    *,
    report_id: int,
    destination: str,
    status: str,
    message_text: str,
    error_message: str | None,
    sent_at: datetime | None,
) -> MarketReportDigestSend:
    row = existing or MarketReportDigestSend(report_id=report_id, destination=destination)
    row.status = status
    row.message_text = message_text
    row.error_message = error_message
    row.sent_at = sent_at
    if existing is None:
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def send_market_report_digest(
    db: Session,
    dry_run: bool = False,
    force: bool = False,
    destination: str = DEFAULT_DESTINATION,
    *,
    skip_lock: bool = False,
) -> DigestSendResult | None:
    """Sends (or records skipping/failing to send) a Telegram digest for the
    latest market intelligence report. Returns None if no report has ever
    been generated - callers should treat that as a successful no-op ("No
    market report found."), not an error.

    dry_run never touches the database - it only formats and returns the
    message that would be sent. Without --force, a report that already has a
    "sent" digest row for this destination is skipped rather than resent -
    the unique (report_id, destination) constraint means there is exactly
    one row to check.

    Acquires the 'telegram_market_digest' concurrency lock for the call
    (including dry_run, so a preview can't race a real send) - shared by
    app/send_market_report_digest.py's CLI, POST
    /admin/actions/send-market-report-digest, and the digest step inside
    POST /admin/actions/full-market-refresh. skip_lock is test/dev-CLI only.
    """
    with with_job_lock("telegram_market_digest", skip_lock=skip_lock):
        return _send_market_report_digest_locked(db, dry_run, force, destination)


def _send_market_report_digest_locked(
    db: Session,
    dry_run: bool = False,
    force: bool = False,
    destination: str = DEFAULT_DESTINATION,
) -> DigestSendResult | None:
    report = _latest_report(db)
    if report is None:
        return None

    message = format_digest_message(report, _latest_analytics_digest(db))

    if dry_run:
        return DigestSendResult(
            report_id=report.id,
            status="pending",
            sent=False,
            skipped_reason=None,
            message_text=message,
        )

    existing = get_digest_send(db, report.id, destination)
    if existing is not None and existing.status == "sent" and not force:
        return DigestSendResult(
            report_id=report.id,
            status="skipped",
            sent=False,
            skipped_reason="Digest already sent for this report.",
            message_text=message,
        )

    if not is_telegram_configured():
        _upsert_send_row(
            db,
            existing,
            report_id=report.id,
            destination=destination,
            status="skipped",
            message_text=message,
            error_message=None,
            sent_at=None,
        )
        return DigestSendResult(
            report_id=report.id,
            status="skipped",
            sent=False,
            skipped_reason="Telegram is not configured.",
            message_text=message,
        )

    try:
        send_telegram_message(message)
    except TelegramSendError as exc:
        _upsert_send_row(
            db,
            existing,
            report_id=report.id,
            destination=destination,
            status="failed",
            message_text=message,
            error_message=str(exc),
            sent_at=None,
        )
        return DigestSendResult(
            report_id=report.id,
            status="failed",
            sent=False,
            skipped_reason=None,
            message_text=message,
            error_message=str(exc),
        )

    _upsert_send_row(
        db,
        existing,
        report_id=report.id,
        destination=destination,
        status="sent",
        message_text=message,
        error_message=None,
        sent_at=datetime.now(timezone.utc),
    )
    return DigestSendResult(
        report_id=report.id,
        status="sent",
        sent=True,
        skipped_reason=None,
        message_text=message,
    )
