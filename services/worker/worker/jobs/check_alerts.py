"""Checks active alert_rules against the latest price observations and
against failed price_refresh_runs, recording alert_events and sending
Telegram notifications for anything new. Pure DB-to-DB (plus Telegram) - it
does not scrape or refresh prices itself; run refresh_prices first.
"""

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator

from sqlalchemy import func
from sqlalchemy.orm import Session

from worker.alerts.telegram import TelegramSendError, send_telegram_message
from worker.db import SessionLocal
from worker.models import AlertEvent, AlertRule, Card, PriceObservation, PriceRefreshRun, Source

logger = logging.getLogger(__name__)

DEDUPE_WINDOW = timedelta(hours=24)


@dataclass
class AlertEventSummary:
    """Plain snapshot of an AlertEvent, safe to read after check_alerts()'s
    data transaction has been committed or rolled back (e.g. --dry-run) -
    the ORM row itself gets expired/expunged by either operation."""

    id: int | None
    event_type: str
    title: str
    message: str
    dedupe_key: str
    status: str
    card_id: int | None = None
    source_id: int | None = None
    refresh_run_id: int | None = None


def _card_label(card: Card | None) -> str:
    if card is None:
        return "unknown card"
    return card.name_en or card.card_code


def _pct_change(previous_price: int, latest_price: int) -> float:
    if previous_price == 0:
        return 0.0
    return (latest_price - previous_price) / previous_price * 100


def _is_recent_duplicate(db: Session, dedupe_key: str, now: datetime) -> bool:
    cutoff = now - DEDUPE_WINDOW
    existing = (
        db.query(AlertEvent)
        .filter(AlertEvent.dedupe_key == dedupe_key, AlertEvent.created_at >= cutoff)
        .first()
    )
    return existing is not None


def _record_event(
    db: Session,
    *,
    event_type: str,
    title: str,
    message: str,
    dedupe_key: str,
    dry_run: bool,
    now: datetime,
    card_id: int | None = None,
    source_id: int | None = None,
    price_observation_id: int | None = None,
    refresh_run_id: int | None = None,
) -> AlertEvent:
    is_duplicate = _is_recent_duplicate(db, dedupe_key, now)

    event = AlertEvent(
        event_type=event_type,
        card_id=card_id,
        source_id=source_id,
        price_observation_id=price_observation_id,
        refresh_run_id=refresh_run_id,
        title=title,
        message=message,
        dedupe_key=dedupe_key,
        status="skipped_duplicate" if is_duplicate else "pending",
    )
    db.add(event)
    db.flush()

    if is_duplicate:
        logger.info("Skipping duplicate alert (dedupe_key=%s).", dedupe_key)
        return event

    if dry_run:
        logger.info("[dry-run] would send Telegram alert: %s", title)
        return event

    try:
        send_telegram_message(f"{title}\n\n{message}")
    except TelegramSendError as exc:
        event.status = "failed"
        event.error_message = str(exc)
        logger.warning("Failed to send Telegram alert '%s': %s", title, exc)
    else:
        event.status = "sent"
        event.sent_at = now

    return event


def _latest_price_pairs(
    db: Session,
) -> Iterator[tuple[int, int, str, PriceObservation, PriceObservation]]:
    """Yields (card_id, source_id, price_type, latest, previous) for every
    combination with at least two observations."""
    combos = (
        db.query(
            PriceObservation.card_id,
            PriceObservation.source_id,
            PriceObservation.price_type,
        )
        .group_by(PriceObservation.card_id, PriceObservation.source_id, PriceObservation.price_type)
        .having(func.count(PriceObservation.id) >= 2)
        .all()
    )

    for card_id, source_id, price_type in combos:
        rows = (
            db.query(PriceObservation)
            .filter_by(card_id=card_id, source_id=source_id, price_type=price_type)
            .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc())
            .limit(2)
            .all()
        )
        if len(rows) < 2:
            continue
        yield card_id, source_id, price_type, rows[0], rows[1]


def _stock_status_pairs(
    db: Session,
) -> Iterator[tuple[int, int, PriceObservation, PriceObservation]]:
    """Yields (card_id, source_id, latest, previous) for every combination
    with at least two observations that carry a stock_status."""
    combos = (
        db.query(PriceObservation.card_id, PriceObservation.source_id)
        .filter(PriceObservation.stock_status.isnot(None))
        .group_by(PriceObservation.card_id, PriceObservation.source_id)
        .having(func.count(PriceObservation.id) >= 2)
        .all()
    )

    for card_id, source_id in combos:
        rows = (
            db.query(PriceObservation)
            .filter(
                PriceObservation.card_id == card_id,
                PriceObservation.source_id == source_id,
                PriceObservation.stock_status.isnot(None),
            )
            .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc())
            .limit(2)
            .all()
        )
        if len(rows) < 2:
            continue
        yield card_id, source_id, rows[0], rows[1]


def check_price_change_rules(
    db: Session, rules: list[AlertRule], dry_run: bool, now: datetime
) -> list[AlertEvent]:
    """price_change_pct: same card/source/price_type, latest vs previous
    observation. threshold_pct >= 0 means "alert on a rise of at least this
    much" (price_up); threshold_pct < 0 means "alert on a drop of at least
    this much" (price_down) - e.g. -10 fires when pct_change <= -10."""
    events: list[AlertEvent] = []
    sources_by_id = {s.id: s for s in db.query(Source).all()}
    cards_by_id = {c.id: c for c in db.query(Card).all()}

    applicable_rules = [
        r for r in rules if r.rule_type == "price_change_pct" and r.threshold_pct is not None
    ]
    if not applicable_rules:
        return events

    for card_id, source_id, price_type, latest, previous in _latest_price_pairs(db):
        source = sources_by_id.get(source_id)
        card = cards_by_id.get(card_id)
        pct = _pct_change(previous.price_jpy, latest.price_jpy)

        for rule in applicable_rules:
            if rule.source_name and (source is None or source.name != rule.source_name):
                continue
            if rule.price_type and price_type != rule.price_type:
                continue

            if rule.threshold_pct >= 0:
                if pct < rule.threshold_pct:
                    continue
                event_type = "price_up"
                direction = "up"
            else:
                if pct > rule.threshold_pct:
                    continue
                event_type = "price_down"
                direction = "down"

            label = _card_label(card)
            source_name = source.name if source else str(source_id)
            title = f"{label}: {price_type} price {direction} {abs(pct):.1f}% on {source_name}"
            message = (
                f"{previous.price_jpy} JPY -> {latest.price_jpy} JPY ({pct:+.1f}%) "
                f"[rule: {rule.name}]"
            )
            dedupe_key = (
                f"rule:{rule.id}:card:{card_id}:source:{source_id}:price_type:{price_type}"
            )

            events.append(
                _record_event(
                    db,
                    event_type=event_type,
                    title=title,
                    message=message,
                    dedupe_key=dedupe_key,
                    card_id=card_id,
                    source_id=source_id,
                    price_observation_id=latest.id,
                    dry_run=dry_run,
                    now=now,
                )
            )

    return events


def check_yuyutei_buy_rules(
    db: Session, rules: list[AlertRule], dry_run: bool, now: datetime
) -> list[AlertEvent]:
    """yuyutei_buy_change_pct: hardcoded to source=yuyutei, price_type=buy.
    Only fires on upward moves (there is no yuyutei_buy_down event type)."""
    events: list[AlertEvent] = []
    applicable_rules = [
        r
        for r in rules
        if r.rule_type == "yuyutei_buy_change_pct" and r.threshold_pct is not None
    ]
    if not applicable_rules:
        return events

    sources_by_id = {s.id: s for s in db.query(Source).all()}
    cards_by_id = {c.id: c for c in db.query(Card).all()}

    for card_id, source_id, price_type, latest, previous in _latest_price_pairs(db):
        source = sources_by_id.get(source_id)
        if source is None or source.name != "yuyutei" or price_type != "buy":
            continue

        pct = _pct_change(previous.price_jpy, latest.price_jpy)

        for rule in applicable_rules:
            if pct < rule.threshold_pct:
                continue

            card = cards_by_id.get(card_id)
            label = _card_label(card)
            title = f"{label}: Yuyu-Tei buy price up {pct:.1f}%"
            message = (
                f"{previous.price_jpy} JPY -> {latest.price_jpy} JPY ({pct:+.1f}%) "
                f"[rule: {rule.name}]"
            )
            dedupe_key = f"rule:{rule.id}:card:{card_id}:source:{source_id}:price_type:buy"

            events.append(
                _record_event(
                    db,
                    event_type="yuyutei_buy_up",
                    title=title,
                    message=message,
                    dedupe_key=dedupe_key,
                    card_id=card_id,
                    source_id=source_id,
                    price_observation_id=latest.id,
                    dry_run=dry_run,
                    now=now,
                )
            )

    return events


def check_stock_status_rules(
    db: Session, rules: list[AlertRule], dry_run: bool, now: datetime
) -> list[AlertEvent]:
    """stock_status_change: detects an in_stock -> out_of_stock transition
    between the latest two stock-status-bearing observations for a card/source."""
    events: list[AlertEvent] = []
    applicable_rules = [r for r in rules if r.rule_type == "stock_status_change"]
    if not applicable_rules:
        return events

    sources_by_id = {s.id: s for s in db.query(Source).all()}
    cards_by_id = {c.id: c for c in db.query(Card).all()}

    for card_id, source_id, latest, previous in _stock_status_pairs(db):
        if previous.stock_status != "in_stock" or latest.stock_status != "out_of_stock":
            continue

        source = sources_by_id.get(source_id)

        for rule in applicable_rules:
            if rule.source_name and (source is None or source.name != rule.source_name):
                continue

            card = cards_by_id.get(card_id)
            label = _card_label(card)
            source_name = source.name if source else str(source_id)
            title = f"{label}: out of stock on {source_name}"
            message = f"Stock changed from in_stock to out_of_stock [rule: {rule.name}]"
            dedupe_key = f"rule:{rule.id}:card:{card_id}:source:{source_id}"

            events.append(
                _record_event(
                    db,
                    event_type="stock_out",
                    title=title,
                    message=message,
                    dedupe_key=dedupe_key,
                    card_id=card_id,
                    source_id=source_id,
                    price_observation_id=latest.id,
                    dry_run=dry_run,
                    now=now,
                )
            )

    return events


def check_refresh_failed_rules(
    db: Session, rules: list[AlertRule], dry_run: bool, now: datetime
) -> list[AlertEvent]:
    """refresh_failed: one alert per failed price_refresh_runs row, ever -
    once a run has been alerted on it is never re-alerted, regardless of the
    24h dedupe window (the run's outcome never changes)."""
    events: list[AlertEvent] = []
    applicable_rules = [r for r in rules if r.rule_type == "refresh_failed"]
    if not applicable_rules:
        return events

    failed_runs = db.query(PriceRefreshRun).filter(PriceRefreshRun.status == "failed").all()

    for run in failed_runs:
        already_alerted = (
            db.query(AlertEvent)
            .filter(
                AlertEvent.refresh_run_id == run.id,
                AlertEvent.event_type == "refresh_failed",
            )
            .first()
        )
        if already_alerted is not None:
            continue

        for rule in applicable_rules:
            title = f"Price refresh run {run.id} failed"
            message = run.error_message or "Refresh run failed with no error message recorded."
            dedupe_key = f"rule:{rule.id}:refresh_run:{run.id}"

            events.append(
                _record_event(
                    db,
                    event_type="refresh_failed",
                    title=title,
                    message=message,
                    dedupe_key=dedupe_key,
                    refresh_run_id=run.id,
                    dry_run=dry_run,
                    now=now,
                )
            )

    return events


def check_alerts(db: Session, dry_run: bool = False) -> list[AlertEventSummary]:
    now = datetime.now(timezone.utc)
    rules = db.query(AlertRule).filter(AlertRule.is_active.is_(True)).all()

    events: list[AlertEvent] = []
    events += check_price_change_rules(db, rules, dry_run, now)
    events += check_yuyutei_buy_rules(db, rules, dry_run, now)
    events += check_stock_status_rules(db, rules, dry_run, now)
    events += check_refresh_failed_rules(db, rules, dry_run, now)

    # Captured as plain data before commit/rollback, since either operation
    # expires (dry-run: expunges) the ORM rows above - see AlertEventSummary.
    summaries = [
        AlertEventSummary(
            id=event.id,
            event_type=event.event_type,
            title=event.title,
            message=event.message,
            dedupe_key=event.dedupe_key,
            status=event.status,
            card_id=event.card_id,
            source_id=event.source_id,
            refresh_run_id=event.refresh_run_id,
        )
        for event in events
    ]

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return summaries


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check active alert rules against the latest price observations and "
        "failed refresh runs, sending Telegram alerts for anything new."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Detect alert conditions without sending Telegram messages or committing.",
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
        events = check_alerts(db, dry_run=args.dry_run)
    finally:
        db.close()

    print(f"alert_events_created: {len(events)}")
    for event in events:
        print(f"- [{event.status}] {event.event_type}: {event.title}")


if __name__ == "__main__":
    main()
