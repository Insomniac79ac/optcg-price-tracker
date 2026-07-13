import itertools
import sys
from datetime import date, datetime, timezone

from app.generate_market_report import main
from app.models import Card, CollectionItem, MarketIntelligenceReport, MarketSignalEvent
from app.services.market_report import build_report_payload, generate_market_report

_dedupe_counter = itertools.count()


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant="leader",
        language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_item(db_session, card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def make_event(db_session, **overrides) -> MarketSignalEvent:
    now = datetime.now(timezone.utc)
    fields = dict(
        signal_type="snkrdunk_floor_below_yuyutei_sell",
        dedupe_key=f"test-dedupe-{next(_dedupe_counter)}",
        severity="info",
        suggested_action="review_buy_opportunity",
        status="open",
        message="test message",
        first_seen_at=now,
        last_seen_at=now,
        seen_count=1,
    )
    fields.update(overrides)
    event = MarketSignalEvent(**fields)
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    return event


# --- build_report_payload / generate_market_report --------------------------


def test_report_generation_works_with_empty_data(db_session):
    report = generate_market_report(db_session)

    assert report.id is not None
    assert report.report_date is not None
    assert report.total_opportunities == 0
    assert report.highest_score is None
    assert report.average_score is None
    assert report.buy_opportunities_count == 0
    assert report.top_buy_json is None

    payload = report.report_payload_json
    assert payload["collection_quality"]["total_quality_issues"] == 0
    assert payload["signal_event_summary"]["most_common_signal_type"] is None
    assert payload["signal_event_summary"]["most_common_suggested_action"] is None
    assert payload["deterministic_summary_lines"] == ["No ranked opportunities found."]
    assert payload["top_opportunities"]["top_5"] == []


def test_report_generation_works_with_opportunities(db_session):
    card = make_card(db_session)
    make_event(
        db_session,
        card_id=card.id,
        signal_type="snkrdunk_floor_below_yuyutei_sell",
        suggested_action="review_buy_opportunity",
    )

    report = generate_market_report(db_session)

    assert report.total_opportunities == 1
    assert report.highest_score == 80  # 60 base + 20 signal modifier
    assert report.average_score == 80.0
    assert report.buy_opportunities_count == 1
    assert report.sell_opportunities_count == 0
    assert report.top_buy_json is not None
    assert report.top_sell_json is None


def test_top_opportunity_fields_populated_correctly(db_session):
    card = make_card(db_session, card_code="OP01-042")
    event = make_event(
        db_session,
        card_id=card.id,
        signal_type="snkrdunk_floor_below_yuyutei_sell",
        suggested_action="review_buy_opportunity",
    )

    report = generate_market_report(db_session)

    top_buy = report.top_buy_json
    assert top_buy["event_id"] == event.id
    assert top_buy["card_code"] == "OP01-042"
    assert top_buy["category"] == "buy"
    assert top_buy["score"] == 80

    payload = report.report_payload_json
    assert payload["top_opportunities"]["top_buy"]["card_code"] == "OP01-042"
    assert len(payload["top_opportunities"]["top_5"]) == 1
    assert payload["top_opportunities"]["top_5"][0]["event_id"] == event.id


def test_build_report_payload_does_not_crash_on_empty_collection_or_opportunities(db_session):
    payload = build_report_payload(db_session)

    assert payload.opportunity_summary.total_opportunities == 0
    assert payload.portfolio_snapshot.items_missing_prices == 0
    assert payload.collection_quality.total_quality_issues == 0


# --- GET /market/report/latest, /market/reports, /market/reports/{id} -------


def test_latest_report_endpoint_returns_newest_report(client, db_session):
    generate_market_report(db_session, report_date=date(2026, 1, 1))
    second = generate_market_report(db_session, report_date=date(2026, 1, 2))

    response = client.get("/market/report/latest")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == second.id
    assert body["report_date"] == "2026-01-02"
    assert "summary" in body
    assert "portfolio_snapshot" in body
    assert "payload" in body


def test_latest_report_endpoint_404_when_no_reports(client, db_session):
    response = client.get("/market/report/latest")
    assert response.status_code == 404


def test_reports_list_endpoint_works(client, db_session):
    first = generate_market_report(db_session, report_date=date(2026, 1, 1))
    second = generate_market_report(db_session, report_date=date(2026, 1, 2))
    third = generate_market_report(db_session, report_date=date(2026, 1, 3))

    response = client.get("/market/reports", params={"limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["reports"]) == 2
    returned_ids = [r["id"] for r in body["reports"]]
    assert returned_ids == [third.id, second.id]
    assert first.id not in returned_ids


def test_report_detail_endpoint_works(client, db_session):
    card = make_card(db_session)
    make_event(db_session, card_id=card.id)
    report = generate_market_report(db_session)

    response = client.get(f"/market/reports/{report.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == report.id
    assert body["summary"]["total_opportunities"] == 1
    assert body["opportunity_summary"]["by_category"]["buy"] == 1


def test_report_detail_endpoint_404_for_missing_report(client, db_session):
    response = client.get("/market/reports/999999")
    assert response.status_code == 404


# --- CLI ---------------------------------------------------------------


def test_cli_creates_report_row(db_session, monkeypatch, capsys):
    monkeypatch.setattr("app.generate_market_report.SessionLocal", lambda: db_session)
    monkeypatch.setattr(sys, "argv", ["generate_market_report"])

    main()

    assert db_session.query(MarketIntelligenceReport).count() == 1
    out = capsys.readouterr().out
    assert "report_id:" in out
    assert "total_opportunities:" in out
