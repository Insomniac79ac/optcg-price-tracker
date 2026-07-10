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
    fields = dict(card_id=card.id, quantity=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def test_create_collection_item(client, db_session):
    card = make_card(db_session)

    response = client.post(
        "/collection",
        json={
            "card_id": card.id,
            "quantity": 2,
            "condition_label": "raw",
            "purchase_price_jpy": 1000,
            "purchase_date": "2026-07-10",
            "purchase_source": "Yuyu-Tei",
            "target_sell_price_jpy": 2000,
            "notes": "hi",
            "status": "hold",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["card_id"] == card.id
    assert body["card_code"] == "OP01-001"
    assert body["name_en"] == "Monkey D. Luffy"
    assert body["quantity"] == 2
    assert body["condition_label"] == "raw"
    assert body["purchase_price_jpy"] == 1000
    assert body["purchase_date"] == "2026-07-10"
    assert body["purchase_source"] == "Yuyu-Tei"
    assert body["target_sell_price_jpy"] == 2000
    assert body["notes"] == "hi"
    assert body["status"] == "hold"

    db_session.expire_all()
    stored = db_session.query(CollectionItem).filter_by(card_id=card.id).one()
    assert stored.quantity == 2


def test_create_collection_item_defaults(client, db_session):
    card = make_card(db_session)

    response = client.post("/collection", json={"card_id": card.id})

    assert response.status_code == 201
    body = response.json()
    assert body["quantity"] == 1
    assert body["status"] == "hold"
    assert body["purchase_price_jpy"] is None


def test_create_collection_item_invalid_card_id(client, db_session):
    response = client.post("/collection", json={"card_id": 999999})
    assert response.status_code in (400, 404)


def test_create_collection_item_invalid_status_rejected(client, db_session):
    card = make_card(db_session)

    response = client.post(
        "/collection", json={"card_id": card.id, "status": "bogus"}
    )

    assert response.status_code == 422


def test_create_collection_item_quantity_less_than_1_rejected(client, db_session):
    card = make_card(db_session)

    response = client.post(
        "/collection", json={"card_id": card.id, "quantity": 0}
    )

    assert response.status_code == 422


def test_create_collection_item_negative_purchase_price_rejected(client, db_session):
    card = make_card(db_session)

    response = client.post(
        "/collection", json={"card_id": card.id, "purchase_price_jpy": -1}
    )

    assert response.status_code == 422


def test_list_collection_items(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, quantity=3)

    response = client.get("/collection")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == item.id
    assert body["items"][0]["quantity"] == 3
    assert body["items"][0]["card_code"] == "OP01-001"


def test_list_collection_items_filters_by_status(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card, status="hold")
    make_item(db_session, card, status="sold")

    response = client.get("/collection", params={"status": "sold"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "sold"


def test_list_collection_items_filters_by_card_code(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    make_item(db_session, card_a)
    make_item(db_session, card_b)

    response = client.get("/collection", params={"card_code": "OP01-002"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["card_code"] == "OP01-002"


def test_list_collection_items_filters_by_card_id(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    make_item(db_session, card_a)
    make_item(db_session, card_b)

    response = client.get("/collection", params={"card_id": card_b.id})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == card_b.id


def test_get_collection_item(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)

    response = client.get(f"/collection/{item.id}")

    assert response.status_code == 200
    assert response.json()["id"] == item.id


def test_get_collection_item_not_found(client, db_session):
    response = client.get("/collection/999999")
    assert response.status_code == 404


def test_patch_collection_item(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, quantity=1, status="hold")

    response = client.patch(
        f"/collection/{item.id}",
        json={"quantity": 5, "status": "sell", "notes": "selling soon"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["quantity"] == 5
    assert body["status"] == "sell"
    assert body["notes"] == "selling soon"

    db_session.expire_all()
    updated = db_session.get(CollectionItem, item.id)
    assert updated.quantity == 5
    assert updated.status == "sell"


def test_patch_collection_item_not_found(client, db_session):
    response = client.patch("/collection/999999", json={"quantity": 2})
    assert response.status_code == 404


def test_patch_collection_item_invalid_status_rejected(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)

    response = client.patch(f"/collection/{item.id}", json={"status": "bogus"})

    assert response.status_code == 422


def test_delete_collection_item(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    item_id = item.id
    card_id = card.id

    response = client.delete(f"/collection/{item_id}")

    assert response.status_code == 204

    db_session.expunge_all()
    assert db_session.get(CollectionItem, item_id) is None
    assert db_session.get(Card, card_id) is not None


def test_delete_collection_item_not_found(client, db_session):
    response = client.delete("/collection/999999")
    assert response.status_code == 404


def test_collection_summary_empty(client, db_session):
    response = client.get("/collection/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 0
    assert body["total_quantity"] == 0
    assert body["total_cost_basis_jpy"] == 0
    assert body["items_with_purchase_price"] == 0
    assert body["items_missing_purchase_price"] == 0
    assert body["items_by_status"] == {
        "hold": 0,
        "watch": 0,
        "sell": 0,
        "sold": 0,
        "grading": 0,
    }


def test_collection_summary_calculation(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card, quantity=2, purchase_price_jpy=1000, status="hold")
    make_item(db_session, card, quantity=1, purchase_price_jpy=500, status="sold")
    make_item(db_session, card, quantity=3, purchase_price_jpy=None, status="watch")

    response = client.get("/collection/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 3
    assert body["total_quantity"] == 6
    assert body["total_cost_basis_jpy"] == 2 * 1000 + 1 * 500
    assert body["items_with_purchase_price"] == 2
    assert body["items_missing_purchase_price"] == 1
    assert body["items_by_status"]["hold"] == 1
    assert body["items_by_status"]["sold"] == 1
    assert body["items_by_status"]["watch"] == 1
    assert body["items_by_status"]["sell"] == 0
    assert body["items_by_status"]["grading"] == 0
