from app.models import Card, CollectionItem


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


def test_create_note_general(client, db_session):
    response = client.post("/collector/notes", json={"body": "Watch this card closely"})
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["note_type"] == "general"
    assert data["body"] == "Watch this card closely"
    assert data["pinned"] is False
    assert data["card_id"] is None


def test_create_note_blank_body_rejected(client, db_session):
    response = client.post("/collector/notes", json={"body": "   "})
    assert response.status_code == 422


def test_create_note_invalid_note_type_rejected(client, db_session):
    response = client.post(
        "/collector/notes", json={"body": "hi", "note_type": "not-a-real-type"}
    )
    assert response.status_code == 400


def test_create_note_linked_to_card(client, db_session):
    card = make_card(db_session)
    response = client.post(
        "/collector/notes",
        json={"body": "Great pull", "note_type": "card", "card_id": card.id, "title": "Nice"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["card_id"] == card.id
    assert data["title"] == "Nice"


def test_create_note_linked_to_collection_item(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    response = client.post(
        "/collector/notes",
        json={
            "body": "Bought at a good price",
            "note_type": "collection",
            "collection_item_id": item.id,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["collection_item_id"] == item.id


def test_list_notes_default_order_pinned_then_recent(client, db_session):
    client.post("/collector/notes", json={"body": "first"})
    second = client.post("/collector/notes", json={"body": "second", "pinned": True}).json()
    client.post("/collector/notes", json={"body": "third"})

    response = client.get("/collector/notes")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["items"][0]["id"] == second["id"]
    assert data["items"][0]["pinned"] is True


def test_list_notes_filters_by_note_type(client, db_session):
    card = make_card(db_session)
    client.post("/collector/notes", json={"body": "general note"})
    client.post("/collector/notes", json={"body": "card note", "note_type": "card", "card_id": card.id})

    response = client.get("/collector/notes", params={"note_type": "card"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["note_type"] == "card"


def test_list_notes_filters_by_pinned(client, db_session):
    client.post("/collector/notes", json={"body": "not pinned"})
    client.post("/collector/notes", json={"body": "pinned one", "pinned": True})

    response = client.get("/collector/notes", params={"pinned": True})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["pinned"] is True


def test_list_notes_pagination(client, db_session):
    for i in range(5):
        client.post("/collector/notes", json={"body": f"note {i}"})

    response = client.get("/collector/notes", params={"limit": 2, "offset": 0})
    data = response.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 0


def test_update_note(client, db_session):
    created = client.post("/collector/notes", json={"body": "original"}).json()

    response = client.patch(
        f"/collector/notes/{created['id']}", json={"body": "updated", "pinned": True}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["body"] == "updated"
    assert data["pinned"] is True


def test_update_note_blank_body_rejected(client, db_session):
    created = client.post("/collector/notes", json={"body": "original"}).json()
    response = client.patch(f"/collector/notes/{created['id']}", json={"body": "   "})
    assert response.status_code == 422


def test_update_note_invalid_note_type_rejected(client, db_session):
    created = client.post("/collector/notes", json={"body": "original"}).json()
    response = client.patch(
        f"/collector/notes/{created['id']}", json={"note_type": "bogus"}
    )
    assert response.status_code == 400


def test_update_note_not_found(client, db_session):
    response = client.patch("/collector/notes/999999", json={"body": "updated"})
    assert response.status_code == 404


def test_delete_note(client, db_session):
    created = client.post("/collector/notes", json={"body": "to be deleted"}).json()

    response = client.delete(f"/collector/notes/{created['id']}")
    assert response.status_code == 204

    list_response = client.get("/collector/notes")
    assert list_response.json()["total"] == 0


def test_delete_note_not_found(client, db_session):
    response = client.delete("/collector/notes/999999")
    assert response.status_code == 404


def test_creating_note_records_activity_event(client, db_session):
    client.post("/collector/notes", json={"body": "Something noteworthy", "title": "Heads up"})

    response = client.get("/collector/activity", params={"event_source": "note"})
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_events"] == 1
    assert data["events"][0]["event_type"] == "note_created"
    assert data["events"][0]["title"] == "Heads up"
