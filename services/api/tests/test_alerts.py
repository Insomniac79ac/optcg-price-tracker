from datetime import datetime, timezone

from app.models import AlertEvent, AlertRule, Card, Source


def make_card(db_session, card_code: str = "OP01-001") -> Card:
    card = Card(
        card_code=card_code, name_en="Monkey D. Luffy", name_jp=None,
        set_code="OP01", rarity="L", variant=None, language="jp",
    )
    db_session.add(card)
    db_session.flush()
    return card


def make_source(db_session, name: str = "yuyutei") -> Source:
    source = Source(name=name, base_url=f"https://{name}.example")
    db_session.add(source)
    db_session.flush()
    return source


def make_event(db_session, **overrides) -> AlertEvent:
    fields = dict(
        event_type="price_up",
        title="Test alert",
        message="1000 JPY -> 1200 JPY (+20.0%)",
        dedupe_key="rule:1:card:1:source:1:price_type:sell",
        status="sent",
        sent_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    event = AlertEvent(**fields)
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    return event


def make_rule(db_session, **overrides) -> AlertRule:
    fields = dict(
        name="Yuyu-Tei buy price up 10%",
        rule_type="yuyutei_buy_change_pct",
        source_name="yuyutei",
        price_type="buy",
        threshold_pct=10.0,
        is_active=True,
    )
    fields.update(overrides)
    rule = AlertRule(**fields)
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)
    return rule


def test_list_alert_events_empty(client, db_session):
    response = client.get("/admin/alert-events")
    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "limit": 100,
        "offset": 0,
        "pagination": {
            "total": 0,
            "limit": 100,
            "offset": 0,
            "has_next": False,
            "has_previous": False,
            "next_offset": None,
            "previous_offset": None,
        },
    }


def test_list_alert_events_returns_card_and_source_details(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    event = make_event(db_session, card_id=card.id, source_id=source.id)

    response = client.get("/admin/alert-events")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == event.id
    assert item["event_type"] == "price_up"
    assert item["card_id"] == card.id
    assert item["card_code"] == "OP01-001"
    assert item["card_name"] == "Monkey D. Luffy"
    assert item["source_name"] == "yuyutei"
    assert item["status"] == "sent"
    assert item["title"] == "Test alert"
    assert item["dedupe_key"] == event.dedupe_key


def test_list_alert_events_without_card_or_source_has_null_fields(client, db_session):
    make_event(db_session, event_type="refresh_failed", card_id=None, source_id=None)

    response = client.get("/admin/alert-events")

    item = response.json()["items"][0]
    assert item["card_id"] is None
    assert item["card_code"] is None
    assert item["card_name"] is None
    assert item["source_name"] is None


def test_list_alert_events_orders_newest_first(client, db_session):
    older = make_event(
        db_session, dedupe_key="a", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    newer = make_event(
        db_session, dedupe_key="b", created_at=datetime(2026, 1, 2, tzinfo=timezone.utc)
    )

    response = client.get("/admin/alert-events")
    body = response.json()

    assert [item["id"] for item in body["items"]] == [newer.id, older.id]


def test_list_alert_events_filters_by_status(client, db_session):
    make_event(db_session, dedupe_key="a", status="sent")
    make_event(db_session, dedupe_key="b", status="failed", error_message="boom")

    response = client.get("/admin/alert-events", params={"status": "failed"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "failed"
    assert body["items"][0]["error_message"] == "boom"


def test_list_alert_events_filters_by_event_type(client, db_session):
    make_event(db_session, dedupe_key="a", event_type="price_up")
    make_event(db_session, dedupe_key="b", event_type="price_down")

    response = client.get("/admin/alert-events", params={"event_type": "price_down"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["event_type"] == "price_down"


def test_list_alert_events_rejects_invalid_status(client, db_session):
    response = client.get("/admin/alert-events", params={"status": "bogus"})
    assert response.status_code == 400


def test_list_alert_events_rejects_invalid_event_type(client, db_session):
    response = client.get("/admin/alert-events", params={"event_type": "bogus"})
    assert response.status_code == 400


def test_list_alert_events_pagination(client, db_session):
    for i in range(5):
        make_event(db_session, dedupe_key=f"key-{i}")

    response = client.get("/admin/alert-events", params={"limit": 2, "offset": 0})
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert len(body["items"]) == 2

    response = client.get("/admin/alert-events", params={"limit": 2, "offset": 4})
    assert len(response.json()["items"]) == 1


def test_get_alert_event_returns_event(client, db_session):
    card = make_card(db_session)
    event = make_event(db_session, card_id=card.id)

    response = client.get(f"/admin/alert-events/{event.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == event.id
    assert body["card_code"] == "OP01-001"


def test_get_alert_event_not_found(client, db_session):
    response = client.get("/admin/alert-events/999999")
    assert response.status_code == 404


def test_list_alert_rules_returns_rules(client, db_session):
    rule = make_rule(db_session)

    response = client.get("/admin/alert-rules")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    item = body[0]
    assert item["id"] == rule.id
    assert item["name"] == "Yuyu-Tei buy price up 10%"
    assert item["rule_type"] == "yuyutei_buy_change_pct"
    assert item["source_name"] == "yuyutei"
    assert item["price_type"] == "buy"
    assert item["threshold_pct"] == 10.0
    assert item["is_active"] is True


def test_update_alert_rule_toggles_active_status(client, db_session):
    rule = make_rule(db_session, is_active=True)

    response = client.patch(f"/admin/alert-rules/{rule.id}", json={"is_active": False})

    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert body["threshold_pct"] == 10.0  # untouched

    db_session.refresh(rule)
    assert rule.is_active is False


def test_update_alert_rule_updates_threshold_pct(client, db_session):
    rule = make_rule(db_session, threshold_pct=10.0)

    response = client.patch(f"/admin/alert-rules/{rule.id}", json={"threshold_pct": 15.5})

    assert response.status_code == 200
    body = response.json()
    assert body["threshold_pct"] == 15.5
    assert body["is_active"] is True  # untouched

    db_session.refresh(rule)
    assert rule.threshold_pct == 15.5


def test_update_alert_rule_not_found(client, db_session):
    response = client.patch("/admin/alert-rules/999999", json={"is_active": False})
    assert response.status_code == 404
