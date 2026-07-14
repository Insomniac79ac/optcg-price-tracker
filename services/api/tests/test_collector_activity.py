from app.models import Card, CollectionItem, CollectorActivityEvent


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


def make_item(db_session, card: Card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def make_event(db_session, **overrides) -> CollectorActivityEvent:
    fields = dict(
        event_type="collection_item_added",
        event_source="collection",
        title="Added a card",
    )
    fields.update(overrides)
    event = CollectorActivityEvent(**fields)
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    return event


def test_list_activity_empty(client, db_session):
    response = client.get("/collector/activity")
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_events"] == 0
    assert data["events"] == []


def test_list_activity_returns_events_newest_first(client, db_session):
    first = make_event(db_session, title="first")
    second = make_event(db_session, title="second")

    response = client.get("/collector/activity")
    assert response.status_code == 200
    data = response.json()
    assert [e["id"] for e in data["events"]] == [second.id, first.id]


def test_list_activity_filters_by_event_source(client, db_session):
    make_event(db_session, event_source="collection", event_type="collection_item_added")
    make_event(db_session, event_source="wishlist", event_type="wishlist_item_added")

    response = client.get("/collector/activity", params={"event_source": "wishlist"})
    data = response.json()
    assert data["summary"]["total_events"] == 1
    assert data["events"][0]["event_source"] == "wishlist"


def test_list_activity_filters_by_card_id_and_enriches_card_fields(client, db_session):
    card = make_card(db_session)
    make_event(db_session, card_id=card.id, event_type="card_note")
    make_event(db_session, event_type="unrelated")

    response = client.get("/collector/activity", params={"card_id": card.id})
    data = response.json()
    assert data["summary"]["total_events"] == 1
    event = data["events"][0]
    assert event["card_code"] == card.card_code
    assert event["name_en"] == card.name_en


def test_list_activity_summary_by_source_and_type(client, db_session):
    make_event(db_session, event_source="collection", event_type="collection_item_added")
    make_event(db_session, event_source="collection", event_type="collection_item_added")
    make_event(db_session, event_source="wishlist", event_type="wishlist_item_added")

    response = client.get("/collector/activity")
    data = response.json()
    assert data["summary"]["by_source"] == {"collection": 2, "wishlist": 1}
    assert data["summary"]["by_type"] == {"collection_item_added": 2, "wishlist_item_added": 1}


def test_list_activity_pagination(client, db_session):
    for i in range(5):
        make_event(db_session, title=f"event {i}")

    response = client.get("/collector/activity", params={"limit": 2, "offset": 0})
    data = response.json()
    assert data["summary"]["total_events"] == 5
    assert len(data["events"]) == 2


def test_activity_summary_endpoint(client, db_session):
    make_event(db_session, event_source="collection")
    make_event(db_session, event_source="wishlist")

    response = client.get("/collector/activity/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["today_count"] == 2
    assert data["last_7d_count"] == 2
    assert data["last_30d_count"] == 2
    assert data["by_source"] == {"collection": 1, "wishlist": 1}
    assert len(data["recent_events"]) == 2
