import io

from app.models import Card, CollectionItem, PriceObservation, Source, WishlistItem


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


def make_source(db_session, name: str) -> Source:
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def add_observation(db_session, card, source, *, price_type, price_jpy, **kwargs):
    from datetime import datetime, timezone

    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=price_type,
        price_jpy=price_jpy,
        observed_at=kwargs.pop("observed_at", None) or datetime.now(timezone.utc),
        **kwargs,
    )
    db_session.add(obs)
    db_session.commit()
    return obs


def make_wishlist_item(client, card_id: int, **overrides) -> dict:
    body = {"card_id": card_id}
    body.update(overrides)
    response = client.post("/wishlist", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- create -----------------------------------------------------------------


def test_create_wishlist_item(client, db_session):
    card = make_card(db_session)

    body = make_wishlist_item(
        client,
        card.id,
        priority="high",
        target_buy_price_jpy=1000,
        max_buy_price_jpy=1500,
        preferred_condition="raw",
        preferred_source="snkrdunk",
        desired_quantity=1,
        notes="Looking for clean copy",
    )

    assert body["card_id"] == card.id
    assert body["card_code"] == "OP01-001"
    assert body["priority"] == "high"
    assert body["status"] == "watching"
    assert body["target_buy_price_jpy"] == 1000
    assert body["max_buy_price_jpy"] == 1500
    assert body["preferred_condition"] == "raw"
    assert body["preferred_source"] == "snkrdunk"
    assert body["desired_quantity"] == 1
    assert body["acquired_quantity"] == 0
    assert body["notes"] == "Looking for clean copy"


def test_create_wishlist_item_card_not_found(client, db_session):
    response = client.post("/wishlist", json={"card_id": 999999})
    assert response.status_code == 404


def test_create_wishlist_item_duplicate_rejected(client, db_session):
    card = make_card(db_session)
    make_wishlist_item(client, card.id, preferred_condition="raw", preferred_source="snkrdunk")

    response = client.post(
        "/wishlist",
        json={"card_id": card.id, "preferred_condition": "raw", "preferred_source": "snkrdunk"},
    )
    assert response.status_code == 409


def test_create_wishlist_item_duplicate_allowed_after_removed(client, db_session):
    card = make_card(db_session)
    first = make_wishlist_item(
        client, card.id, preferred_condition="raw", preferred_source="snkrdunk"
    )
    client.delete(f"/wishlist/{first['id']}")

    response = client.post(
        "/wishlist",
        json={"card_id": card.id, "preferred_condition": "raw", "preferred_source": "snkrdunk"},
    )
    assert response.status_code == 201


def test_create_wishlist_item_different_condition_allowed(client, db_session):
    card = make_card(db_session)
    make_wishlist_item(client, card.id, preferred_condition="raw", preferred_source="snkrdunk")

    response = client.post(
        "/wishlist",
        json={"card_id": card.id, "preferred_condition": "PSA 10", "preferred_source": "snkrdunk"},
    )
    assert response.status_code == 201


def test_create_wishlist_item_invalid_priority_rejected(client, db_session):
    card = make_card(db_session)
    response = client.post("/wishlist", json={"card_id": card.id, "priority": "bogus"})
    assert response.status_code == 422


# --- list / filters -----------------------------------------------------


def test_list_wishlist_items(client, db_session):
    card = make_card(db_session)
    make_wishlist_item(client, card.id)

    response = client.get("/wishlist")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


def test_filter_by_status(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    make_wishlist_item(client, card_a.id)
    passed_item = make_wishlist_item(client, card_b.id)
    client.patch(f"/wishlist/{passed_item['id']}", json={"status": "passed"})

    response = client.get("/wishlist", params={"status": "passed"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["card_code"] == "OP01-002"


def test_filter_by_status_invalid(client, db_session):
    response = client.get("/wishlist", params={"status": "bogus"})
    assert response.status_code == 400


def test_filter_by_priority(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    make_wishlist_item(client, card_a.id, priority="grail")
    make_wishlist_item(client, card_b.id, priority="low")

    response = client.get("/wishlist", params={"priority": "grail"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["priority"] == "grail"


def test_filter_by_owned(client, db_session):
    owned_card = make_card(db_session, card_code="OP01-001")
    unowned_card = make_card(db_session, card_code="OP01-002")
    make_wishlist_item(client, owned_card.id)
    make_wishlist_item(client, unowned_card.id)

    db_session.add(CollectionItem(user_id=1, card_id=owned_card.id, quantity=2))
    db_session.commit()

    response = client.get("/wishlist", params={"owned": True})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["card_code"] == "OP01-001"
    assert body["items"][0]["owned_quantity"] == 2


# --- target hit / pricing ----------------------------------------------


def test_target_hit_true_when_price_at_or_below_target(client, db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=900)

    body = make_wishlist_item(
        client, card.id, target_buy_price_jpy=1000, preferred_source="snkrdunk"
    )

    response = client.get(f"/wishlist/{body['id']}")
    out = response.json()
    assert out["latest_prices"]["snkrdunk_floor"] == 900
    assert out["preferred_current_price_jpy"] == 900
    assert out["preferred_current_price_source"] == "snkrdunk_floor"
    assert out["target_hit"] is True
    assert out["gap_to_target_jpy"] == -100
    assert out["gap_to_target_pct"] == -10.0


def test_target_hit_false_when_price_above_target(client, db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1200)

    body = make_wishlist_item(
        client, card.id, target_buy_price_jpy=1000, preferred_source="snkrdunk"
    )

    response = client.get(f"/wishlist/{body['id']}")
    out = response.json()
    assert out["target_hit"] is False
    assert out["gap_to_target_jpy"] == 200


def test_preferred_source_yuyutei_uses_yuyutei_sell(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1100)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=900)

    body = make_wishlist_item(client, card.id, preferred_source="yuyutei")

    response = client.get(f"/wishlist/{body['id']}")
    out = response.json()
    assert out["preferred_current_price_jpy"] == 1100
    assert out["preferred_current_price_source"] == "yuyutei_sell"


def test_preferred_source_blank_prefers_snkrdunk_floor(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1100)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=900)

    body = make_wishlist_item(client, card.id)

    response = client.get(f"/wishlist/{body['id']}")
    out = response.json()
    assert out["preferred_current_price_jpy"] == 900
    assert out["preferred_current_price_source"] == "snkrdunk_floor"


def test_preferred_source_blank_falls_back_to_yuyutei_sell(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1100)

    body = make_wishlist_item(client, card.id)

    response = client.get(f"/wishlist/{body['id']}")
    out = response.json()
    assert out["preferred_current_price_jpy"] == 1100
    assert out["preferred_current_price_source"] == "yuyutei_sell"


def test_target_hit_filter(client, db_session):
    hit_card = make_card(db_session, card_code="OP01-001")
    miss_card = make_card(db_session, card_code="OP01-002")
    snkrdunk = make_source(db_session, "snkrdunk")
    add_observation(db_session, hit_card, snkrdunk, price_type="floor", price_jpy=500)
    add_observation(db_session, miss_card, snkrdunk, price_type="floor", price_jpy=1500)

    make_wishlist_item(client, hit_card.id, target_buy_price_jpy=1000)
    make_wishlist_item(client, miss_card.id, target_buy_price_jpy=1000)

    response = client.get("/wishlist", params={"target_hit": True})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["card_code"] == "OP01-001"


# --- update / delete ---------------------------------------------------


def test_patch_wishlist_item(client, db_session):
    card = make_card(db_session)
    created = make_wishlist_item(client, card.id, priority="low")

    response = client.patch(f"/wishlist/{created['id']}", json={"priority": "grail", "notes": "bump"})

    assert response.status_code == 200
    body = response.json()
    assert body["priority"] == "grail"
    assert body["notes"] == "bump"


def test_patch_wishlist_item_not_found(client, db_session):
    response = client.patch("/wishlist/999999", json={"priority": "grail"})
    assert response.status_code == 404


def test_soft_delete_sets_status_removed(client, db_session):
    card = make_card(db_session)
    created = make_wishlist_item(client, card.id)

    response = client.delete(f"/wishlist/{created['id']}")

    assert response.status_code == 200
    assert response.json()["status"] == "removed"

    db_session.expire_all()
    row = db_session.get(WishlistItem, created["id"])
    assert row is not None  # not physically deleted
    assert row.status == "removed"


# --- mark-purchased / convert-to-collection -----------------------------


def test_mark_purchased_links_collection_item(client, db_session):
    card = make_card(db_session)
    wishlist_item = make_wishlist_item(client, card.id)

    collection_response = client.post("/collection", json={"card_id": card.id, "quantity": 1})
    collection_item_id = collection_response.json()["id"]

    response = client.post(
        f"/wishlist/{wishlist_item['id']}/mark-purchased",
        json={"collection_item_id": collection_item_id, "acquired_quantity": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "purchased"
    assert body["acquired_collection_item_id"] == collection_item_id
    assert body["acquired_quantity"] == 1

    # mark-purchased does not create a new collection item itself.
    all_items = client.get("/collection").json()["items"]
    assert len(all_items) == 1


def test_mark_purchased_collection_item_not_found(client, db_session):
    card = make_card(db_session)
    wishlist_item = make_wishlist_item(client, card.id)

    response = client.post(
        f"/wishlist/{wishlist_item['id']}/mark-purchased",
        json={"collection_item_id": 999999, "acquired_quantity": 1},
    )
    assert response.status_code == 404


def test_convert_to_collection_creates_collection_item(client, db_session):
    card = make_card(db_session)
    wishlist_item = make_wishlist_item(client, card.id)

    response = client.post(
        f"/wishlist/{wishlist_item['id']}/convert-to-collection",
        json={
            "quantity": 1,
            "condition_label": "raw",
            "purchase_price_jpy": 1200,
            "purchase_date": "2026-07-13",
            "purchase_source": "SNKRDUNK",
            "status": "hold",
            "notes": "Bought from wishlist",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["wishlist_item"]["status"] == "purchased"
    assert body["wishlist_item"]["acquired_quantity"] == 1
    assert body["collection_item"]["card_id"] == card.id
    assert body["collection_item"]["purchase_price_jpy"] == 1200
    assert body["collection_item"]["condition_label"] == "raw"
    assert body["collection_item"]["notes"] == "Bought from wishlist"

    collection_item_id = body["collection_item"]["id"]
    assert body["wishlist_item"]["acquired_collection_item_id"] == collection_item_id

    collection_items = client.get("/collection").json()["items"]
    assert len(collection_items) == 1
    assert collection_items[0]["id"] == collection_item_id


def test_convert_to_collection_not_found(client, db_session):
    response = client.post(
        "/wishlist/999999/convert-to-collection", json={"quantity": 1}
    )
    assert response.status_code == 404


# --- summary --------------------------------------------------------------


def test_wishlist_summary_empty(client, db_session):
    response = client.get("/wishlist/summary")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "total_wishlist_items": 0,
        "watching": 0,
        "target_hit": 0,
        "purchased": 0,
        "passed": 0,
        "removed": 0,
        "grail_count": 0,
        "high_priority_count": 0,
        "total_target_budget_jpy": 0,
        "total_max_budget_jpy": 0,
        "items_owned_already": 0,
        "items_with_target_hit": 0,
    }


def test_wishlist_summary_calculation(client, db_session):
    grail_card = make_card(db_session, card_code="OP01-001")
    high_card = make_card(db_session, card_code="OP01-002")
    removed_card = make_card(db_session, card_code="OP01-003")
    snkrdunk = make_source(db_session, "snkrdunk")
    add_observation(db_session, grail_card, snkrdunk, price_type="floor", price_jpy=500)

    make_wishlist_item(client, grail_card.id, priority="grail", target_buy_price_jpy=1000, max_buy_price_jpy=1500)
    make_wishlist_item(client, high_card.id, priority="high", target_buy_price_jpy=2000, max_buy_price_jpy=2500)
    removed_item = make_wishlist_item(client, removed_card.id, priority="grail", target_buy_price_jpy=9999)
    client.delete(f"/wishlist/{removed_item['id']}")

    db_session.add(CollectionItem(user_id=1, card_id=high_card.id, quantity=1))
    db_session.commit()

    response = client.get("/wishlist/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_wishlist_items"] == 3
    assert body["watching"] == 2
    assert body["removed"] == 1
    assert body["grail_count"] == 1  # removed grail excluded
    assert body["high_priority_count"] == 1
    assert body["total_target_budget_jpy"] == 1000 + 2000
    assert body["total_max_budget_jpy"] == 1500 + 2500
    assert body["items_owned_already"] == 1
    assert body["items_with_target_hit"] == 1  # grail_card's floor (500) <= target (1000)


# --- CSV -------------------------------------------------------------------


def test_csv_export_works(client, db_session):
    card = make_card(db_session)
    make_wishlist_item(
        client,
        card.id,
        priority="high",
        target_buy_price_jpy=1000,
        preferred_condition="raw",
        preferred_source="snkrdunk",
        notes="want it",
    )

    response = client.get("/wishlist/export.csv")

    assert response.status_code == 200
    rows = list(io.StringIO(response.text))
    assert "card_code" in rows[0]
    assert "OP01-001" in rows[1]
    assert "high" in rows[1]


def test_csv_import_dry_run_does_not_write_db(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,priority,target_buy_price_jpy\nOP01-001,high,1000\n"

    response = client.post(
        "/wishlist/import.csv",
        params={"dry_run": True, "mode": "append"},
        files={"file": ("wishlist.csv", csv_text, "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["summary"]["created"] == 0
    assert body["preview"][0]["action"] == "would_create"

    db_session.expire_all()
    assert db_session.query(WishlistItem).count() == 0


def test_csv_import_upsert_works(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,priority,target_buy_price_jpy\nOP01-001,high,1000\n"

    response = client.post(
        "/wishlist/import.csv",
        params={"dry_run": False, "mode": "upsert"},
        files={"file": ("wishlist.csv", csv_text, "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["created"] == 1

    db_session.expire_all()
    items = db_session.query(WishlistItem).all()
    assert len(items) == 1
    assert items[0].priority == "high"
    assert items[0].target_buy_price_jpy == 1000

    # Re-importing with a changed value updates the same row (upsert).
    csv_text_2 = "card_code,priority,target_buy_price_jpy\nOP01-001,grail,500\n"
    response2 = client.post(
        "/wishlist/import.csv",
        params={"dry_run": False, "mode": "upsert"},
        files={"file": ("wishlist.csv", csv_text_2, "text/csv")},
    )
    assert response2.json()["summary"]["updated"] == 1

    db_session.expire_all()
    items = db_session.query(WishlistItem).all()
    assert len(items) == 1
    assert items[0].priority == "grail"
    assert items[0].target_buy_price_jpy == 500


def test_csv_import_card_not_found_reported_as_error(client, db_session):
    csv_text = "card_code,priority\nOP99-999,high\n"

    response = client.post(
        "/wishlist/import.csv",
        params={"dry_run": True, "mode": "append"},
        files={"file": ("wishlist.csv", csv_text, "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert "not found" in body["errors"][0]["error"].lower()
