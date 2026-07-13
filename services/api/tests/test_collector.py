from app.models import (
    Card,
    CardTag,
    CollectionItem,
    CollectionItemGroup,
    CollectionItemTag,
    CollectorGroup,
    CollectorTag,
)


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


def make_tag(client, name="Grade candidates", **extra) -> dict:
    body = {"name": name, **extra}
    response = client.post("/collector/tags", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def make_group(client, name="Manga wants", **extra) -> dict:
    body = {"name": name, **extra}
    response = client.post("/collector/groups", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- tags: CRUD --------------------------------------------------------


def test_create_tag(client, db_session):
    response = client.post(
        "/collector/tags",
        json={
            "name": "Grade candidates",
            "color": "#888888",
            "description": "Cards I may send for grading",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Grade candidates"
    assert body["slug"] == "grade-candidates"
    assert body["color"] == "#888888"
    assert body["description"] == "Cards I may send for grading"


def test_create_tag_requires_name(client, db_session):
    response = client.post("/collector/tags", json={"name": "   "})
    assert response.status_code == 422


def test_create_tag_rejects_invalid_color(client, db_session):
    response = client.post(
        "/collector/tags", json={"name": "Bad color", "color": "not-a-color"}
    )
    assert response.status_code == 400


def test_create_tag_allows_blank_color(client, db_session):
    response = client.post("/collector/tags", json={"name": "No color", "color": ""})
    assert response.status_code == 201
    assert response.json()["color"] is None


def test_create_tag_accepts_short_hex(client, db_session):
    response = client.post("/collector/tags", json={"name": "Short hex", "color": "#f80"})
    assert response.status_code == 201
    assert response.json()["color"] == "#f80"


def test_duplicate_tag_name_rejected(client, db_session):
    make_tag(client, name="Foils")
    response = client.post("/collector/tags", json={"name": "Foils"})
    assert response.status_code == 409


def test_tag_slug_collision_gets_unique_suffix(client, db_session):
    first = make_tag(client, name="Foo Bar")
    second = make_tag(client, name="foo-bar")
    assert first["slug"] == "foo-bar"
    assert second["slug"] != "foo-bar"
    assert second["slug"].startswith("foo-bar-")


def test_update_tag(client, db_session):
    tag = make_tag(client, name="Original")

    response = client.patch(
        f"/collector/tags/{tag['id']}", json={"name": "Renamed", "color": "#123456"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["slug"] == "renamed"
    assert body["color"] == "#123456"


def test_update_tag_rejects_invalid_color(client, db_session):
    tag = make_tag(client)
    response = client.patch(f"/collector/tags/{tag['id']}", json={"color": "nope"})
    assert response.status_code == 400


def test_update_tag_rejects_duplicate_name(client, db_session):
    make_tag(client, name="Alpha")
    tag_b = make_tag(client, name="Beta")

    response = client.patch(f"/collector/tags/{tag_b['id']}", json={"name": "Alpha"})
    assert response.status_code == 409


def test_delete_tag_removes_assignments(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    tag = make_tag(client)

    client.post(f"/cards/{card.id}/tags/{tag['id']}")
    client.post(f"/collection/{item.id}/tags/{tag['id']}")

    response = client.delete(f"/collector/tags/{tag['id']}")
    assert response.status_code == 204

    db_session.expire_all()
    assert db_session.get(CollectorTag, tag["id"]) is None
    assert db_session.query(CardTag).filter_by(tag_id=tag["id"]).count() == 0
    assert db_session.query(CollectionItemTag).filter_by(tag_id=tag["id"]).count() == 0


def test_delete_tag_not_found(client, db_session):
    response = client.delete("/collector/tags/999999")
    assert response.status_code == 404


def test_list_tags(client, db_session):
    make_tag(client, name="B tag")
    make_tag(client, name="A tag")

    response = client.get("/collector/tags")
    assert response.status_code == 200
    names = [t["name"] for t in response.json()]
    assert names == ["A tag", "B tag"]


# --- groups: CRUD --------------------------------------------------------


def test_create_group(client, db_session):
    response = client.post(
        "/collector/groups",
        json={"name": "Manga wants", "description": "High priority manga cards", "sort_order": 10},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Manga wants"
    assert body["slug"] == "manga-wants"
    assert body["sort_order"] == 10


def test_create_group_requires_name(client, db_session):
    response = client.post("/collector/groups", json={"name": ""})
    assert response.status_code == 422


def test_duplicate_group_name_rejected(client, db_session):
    make_group(client, name="Anime wants")
    response = client.post("/collector/groups", json={"name": "Anime wants"})
    assert response.status_code == 409


def test_update_group(client, db_session):
    group = make_group(client, name="Original group")

    response = client.patch(
        f"/collector/groups/{group['id']}", json={"name": "Renamed group", "sort_order": 5}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed group"
    assert body["slug"] == "renamed-group"
    assert body["sort_order"] == 5


def test_update_group_rejects_duplicate_name(client, db_session):
    make_group(client, name="Group A")
    group_b = make_group(client, name="Group B")

    response = client.patch(f"/collector/groups/{group_b['id']}", json={"name": "Group A"})
    assert response.status_code == 409


def test_delete_group_removes_assignments(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    group = make_group(client)

    client.post(f"/collection/{item.id}/groups/{group['id']}")

    response = client.delete(f"/collector/groups/{group['id']}")
    assert response.status_code == 204

    db_session.expire_all()
    assert db_session.get(CollectorGroup, group["id"]) is None
    assert db_session.query(CollectionItemGroup).filter_by(group_id=group["id"]).count() == 0


def test_delete_group_not_found(client, db_session):
    response = client.delete("/collector/groups/999999")
    assert response.status_code == 404


# --- card tag assignment --------------------------------------------------


def test_assign_tag_to_card(client, db_session):
    card = make_card(db_session)
    tag = make_tag(client)

    response = client.post(f"/cards/{card.id}/tags/{tag['id']}")

    assert response.status_code == 200
    body = response.json()
    assert [t["id"] for t in body["tags"]] == [tag["id"]]


def test_assign_tag_to_card_is_idempotent(client, db_session):
    card = make_card(db_session)
    tag = make_tag(client)

    client.post(f"/cards/{card.id}/tags/{tag['id']}")
    response = client.post(f"/cards/{card.id}/tags/{tag['id']}")

    assert response.status_code == 200
    assert len(response.json()["tags"]) == 1
    assert db_session.query(CardTag).filter_by(card_id=card.id, tag_id=tag["id"]).count() == 1


def test_assign_tag_to_card_not_found(client, db_session):
    tag = make_tag(client)
    response = client.post(f"/cards/999999/tags/{tag['id']}")
    assert response.status_code == 404


def test_assign_nonexistent_tag_to_card_not_found(client, db_session):
    card = make_card(db_session)
    response = client.post(f"/cards/{card.id}/tags/999999")
    assert response.status_code == 404


def test_remove_tag_from_card(client, db_session):
    card = make_card(db_session)
    tag = make_tag(client)
    client.post(f"/cards/{card.id}/tags/{tag['id']}")

    response = client.delete(f"/cards/{card.id}/tags/{tag['id']}")

    assert response.status_code == 200
    assert response.json()["tags"] == []


def test_cards_list_includes_tags(client, db_session):
    card = make_card(db_session)
    tag = make_tag(client)
    client.post(f"/cards/{card.id}/tags/{tag['id']}")

    response = client.get("/cards")
    assert response.status_code == 200
    matching = [c for c in response.json() if c["id"] == card.id][0]
    assert [t["id"] for t in matching["tags"]] == [tag["id"]]


# --- collection item tag/group assignment ---------------------------------


def test_assign_tag_to_collection_item(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    tag = make_tag(client)

    response = client.post(f"/collection/{item.id}/tags/{tag['id']}")

    assert response.status_code == 200
    body = response.json()
    assert [t["id"] for t in body["tags"]] == [tag["id"]]


def test_remove_tag_from_collection_item(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    tag = make_tag(client)
    client.post(f"/collection/{item.id}/tags/{tag['id']}")

    response = client.delete(f"/collection/{item.id}/tags/{tag['id']}")

    assert response.status_code == 200
    assert response.json()["tags"] == []


def test_assign_tag_to_collection_item_not_found(client, db_session):
    tag = make_tag(client)
    response = client.post(f"/collection/999999/tags/{tag['id']}")
    assert response.status_code == 404


def test_assign_group_to_collection_item(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    group = make_group(client)

    response = client.post(f"/collection/{item.id}/groups/{group['id']}")

    assert response.status_code == 200
    body = response.json()
    assert [g["id"] for g in body["groups"]] == [group["id"]]


def test_remove_group_from_collection_item(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    group = make_group(client)
    client.post(f"/collection/{item.id}/groups/{group['id']}")

    response = client.delete(f"/collection/{item.id}/groups/{group['id']}")

    assert response.status_code == 200
    assert response.json()["groups"] == []


def test_assign_group_to_collection_item_not_found(client, db_session):
    group = make_group(client)
    response = client.post(f"/collection/999999/groups/{group['id']}")
    assert response.status_code == 404


def test_assign_nonexistent_group_to_collection_item(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    response = client.post(f"/collection/{item.id}/groups/999999")
    assert response.status_code == 404


# --- responses include tags/groups -----------------------------------------


def test_collection_list_includes_tags_and_groups(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    tag = make_tag(client)
    group = make_group(client)
    client.post(f"/collection/{item.id}/tags/{tag['id']}")
    client.post(f"/collection/{item.id}/groups/{group['id']}")

    response = client.get("/collection")

    assert response.status_code == 200
    body = response.json()["items"][0]
    assert [t["id"] for t in body["tags"]] == [tag["id"]]
    assert [g["id"] for g in body["groups"]] == [group["id"]]


def test_collection_item_detail_includes_tags_and_groups(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    tag = make_tag(client)
    client.post(f"/collection/{item.id}/tags/{tag['id']}")

    response = client.get(f"/collection/{item.id}")

    assert response.status_code == 200
    assert [t["id"] for t in response.json()["tags"]] == [tag["id"]]


def test_valuation_response_includes_tags_and_groups(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    tag = make_tag(client)
    group = make_group(client)
    client.post(f"/collection/{item.id}/tags/{tag['id']}")
    client.post(f"/collection/{item.id}/groups/{group['id']}")

    response = client.get("/collection/valuation")

    assert response.status_code == 200
    valuation_item = response.json()["items"][0]
    assert [t["id"] for t in valuation_item["tags"]] == [tag["id"]]
    assert [g["id"] for g in valuation_item["groups"]] == [group["id"]]


def test_opportunities_include_owned_tags_and_groups(client, db_session):
    from datetime import datetime, timezone

    from app.models import MarketSignalEvent

    card = make_card(db_session)
    item = make_item(db_session, card, quantity=2)
    tag = make_tag(client)
    group = make_group(client)
    client.post(f"/cards/{card.id}/tags/{tag['id']}")
    client.post(f"/collection/{item.id}/groups/{group['id']}")

    now = datetime.now(timezone.utc)
    event = MarketSignalEvent(
        signal_type="owned_above_target_sell",
        dedupe_key="dedupe-owned-1",
        severity="info",
        suggested_action="review_sell_opportunity",
        status="open",
        message="test",
        card_id=card.id,
        first_seen_at=now,
        last_seen_at=now,
        seen_count=1,
    )
    db_session.add(event)
    db_session.commit()

    response = client.get("/market/opportunities")

    assert response.status_code == 200
    opportunities = response.json()["opportunities"]
    assert len(opportunities) == 1
    opp = opportunities[0]
    assert opp["owned_quantity"] == 2
    assert [t["id"] for t in opp["tags"]] == [tag["id"]]
    assert [g["id"] for g in opp["groups"]] == [group["id"]]


def test_opportunities_hide_tags_for_unowned_cards(client, db_session):
    from datetime import datetime, timezone

    from app.models import MarketSignalEvent

    card = make_card(db_session)
    tag = make_tag(client)
    client.post(f"/cards/{card.id}/tags/{tag['id']}")

    now = datetime.now(timezone.utc)
    event = MarketSignalEvent(
        signal_type="price_up_7d",
        dedupe_key="dedupe-unowned-1",
        severity="info",
        suggested_action="monitor_momentum",
        status="open",
        message="test",
        card_id=card.id,
        first_seen_at=now,
        last_seen_at=now,
        seen_count=1,
    )
    db_session.add(event)
    db_session.commit()

    response = client.get("/market/opportunities")

    assert response.status_code == 200
    opp = response.json()["opportunities"][0]
    assert opp["owned_quantity"] == 0
    assert opp["tags"] == []
    assert opp["groups"] == []
