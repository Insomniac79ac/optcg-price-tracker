import pytest

from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    ReleaseProduct,
    Source,
    SourceCardMapping,
)


def make_print(db_session, card_code: str = "OP01-001") -> CardPrint:
    """An active, verified printing for a mapping to name.

    Approval now requires one: a row with no card_print_id cannot enter
    `approved`, because a price attached to a card code says nothing about
    which printing was sold.
    """
    product = ReleaseProduct(
        source_catalogue="jp",
        official_code="OP-01",
        display_name="OP-01",
        first_seen_name="OP-01",
        source_series_id="OP01",
        source_url="https://example.test/OP-01",
        verification_status="verified",
    )
    db_session.add(product)
    db_session.flush()
    canonical = CanonicalCard(
        card_code=card_code,
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        card_type="Leader",
        rarity="L",
    )
    db_session.add(canonical)
    db_session.flush()
    row = CardPrint(
        canonical_card_id=canonical.id,
        language="jp",
        release_product_code="OP-01",
        release_product_id=product.id,
        artwork_key=f"sha256:{card_code}-base",
        official_asset_variant="base",
        verification_status="verified",
        is_active=True,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


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


def make_source(db_session, name: str = "yuyutei") -> Source:
    source = Source(name=name, base_url=f"https://{name}.example")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def make_mapping(db_session, card: Card, source: Source, **overrides) -> SourceCardMapping:
    fields = dict(
        card_id=card.id,
        source_id=source.id,
        source_card_id=card.card_code,
        source_url=f"https://{source.name}.example/{card.card_code}",
    )
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(mapping)
    return mapping


def test_list_source_mappings_empty(client, db_session):
    response = client.get("/admin/source-mappings")
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


def test_list_source_mappings_returns_mappings(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session, "yuyutei")
    mapping = make_mapping(db_session, card, source)

    response = client.get("/admin/source-mappings")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == mapping.id
    assert item["card_id"] == card.id
    assert item["card_code"] == "OP01-001"
    assert item["name_en"] == "Monkey D. Luffy"
    assert item["source_name"] == "yuyutei"
    assert item["source_url"] == mapping.source_url
    assert item["manual_verified"] is False
    assert item["is_active"] is True
    assert item["review_status"] == "approved"
    assert item["review_notes"] is None
    assert item["last_verified_at"] is None


def test_list_source_mappings_filters_by_source(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    make_mapping(db_session, card, yuyutei)
    make_mapping(db_session, card, snkrdunk)

    response = client.get("/admin/source-mappings", params={"source": "snkrdunk"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["source_name"] == "snkrdunk"


def test_list_source_mappings_rejects_invalid_source(client, db_session):
    response = client.get("/admin/source-mappings", params={"source": "bogus"})
    assert response.status_code == 400


def test_list_source_mappings_filters_by_review_status(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    make_mapping(db_session, card, source, source_url="https://yuyutei.example/a", review_status="approved")
    make_mapping(
        db_session, card, source, source_url="https://yuyutei.example/b", review_status="needs_review"
    )

    response = client.get("/admin/source-mappings", params={"review_status": "needs_review"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["review_status"] == "needs_review"


def test_list_source_mappings_rejects_invalid_review_status(client, db_session):
    response = client.get("/admin/source-mappings", params={"review_status": "bogus"})
    assert response.status_code == 400


def test_list_source_mappings_filters_by_is_active(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    make_mapping(db_session, card, source, source_url="https://yuyutei.example/active", is_active=True)
    make_mapping(
        db_session, card, source, source_url="https://yuyutei.example/inactive", is_active=False
    )

    response = client.get("/admin/source-mappings", params={"is_active": "false"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["is_active"] is False


def test_list_source_mappings_filters_by_card_code(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    source = make_source(db_session)
    make_mapping(db_session, card_a, source)
    make_mapping(db_session, card_b, source)

    response = client.get("/admin/source-mappings", params={"card_code": "OP01-002"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["card_code"] == "OP01-002"


def test_get_source_mapping_returns_mapping(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    mapping = make_mapping(db_session, card, source)

    response = client.get(f"/admin/source-mappings/{mapping.id}")

    assert response.status_code == 200
    assert response.json()["id"] == mapping.id


def test_get_source_mapping_not_found(client, db_session):
    response = client.get("/admin/source-mappings/999999")
    assert response.status_code == 404


def test_patch_source_mapping_updates_fields(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    mapping = make_mapping(db_session, card, source)

    response = client.patch(
        f"/admin/source-mappings/{mapping.id}",
        json={
            "source_url": "https://yuyutei.example/updated",
            "manual_verified": True,
            "review_notes": "looks right",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_url"] == "https://yuyutei.example/updated"
    assert body["manual_verified"] is True
    assert body["review_notes"] == "looks right"

    db_session.expire_all()
    updated = db_session.get(SourceCardMapping, mapping.id)
    assert updated.source_url == "https://yuyutei.example/updated"
    assert updated.manual_verified is True
    assert updated.review_notes == "looks right"


def test_patch_source_mapping_rejects_invalid_review_status(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    mapping = make_mapping(db_session, card, source)

    response = client.patch(
        f"/admin/source-mappings/{mapping.id}", json={"review_status": "bogus"}
    )

    assert response.status_code == 400


def test_patch_source_mapping_not_found(client, db_session):
    response = client.patch("/admin/source-mappings/999999", json={"is_active": False})
    assert response.status_code == 404


def test_reject_source_mapping(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    mapping = make_mapping(db_session, card, source)

    response = client.post(f"/admin/source-mappings/{mapping.id}/reject")

    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert body["review_status"] == "rejected"

    db_session.expire_all()
    updated = db_session.get(SourceCardMapping, mapping.id)
    assert updated.is_active is False
    assert updated.review_status == "rejected"


def test_approve_source_mapping(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    print_row = make_print(db_session)
    mapping = make_mapping(
        db_session,
        card,
        source,
        is_active=False,
        review_status="needs_review",
        card_print_id=print_row.id,
    )

    response = client.post(f"/admin/source-mappings/{mapping.id}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is True
    assert body["review_status"] == "approved"
    assert body["last_verified_at"] is not None

    db_session.expire_all()
    updated = db_session.get(SourceCardMapping, mapping.id)
    assert updated.is_active is True
    assert updated.review_status == "approved"
    assert updated.last_verified_at is not None


# --- print-authoritative mappings (c9f31e2a7d04) ---------------------------
#
# card_id is legacy compatibility, not identity, and may be NULL. These pin
# the admin read paths against the two ways that used to break them: an inner
# join to `cards` silently dropping the row, and db.get(Card, None) raising.


def make_print_authoritative_mapping(db_session, source: Source, **overrides) -> SourceCardMapping:
    print_row = make_print(db_session, card_code=overrides.pop("card_code", "OP01-900"))
    fields = dict(
        card_id=None,
        source_id=source.id,
        card_print_id=print_row.id,
        source_card_id="print-only-listing",
        source_url=f"https://{source.name}.example/print-only",
    )
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(mapping)
    return mapping


def test_list_source_mappings_includes_a_mapping_with_no_legacy_card(client, db_session):
    source = make_source(db_session)
    mapping = make_print_authoritative_mapping(db_session, source)

    response = client.get("/admin/source-mappings")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == mapping.id
    assert item["card_id"] is None
    assert item["card_print_id"] == mapping.card_print_id
    assert item["card_code"] is None
    assert item["name_en"] is None
    assert item["source_name"] == source.name


def test_list_source_mappings_returns_legacy_and_print_authoritative_together(client, db_session):
    source = make_source(db_session)
    card = make_card(db_session)
    legacy = make_mapping(db_session, card, source)
    print_only = make_print_authoritative_mapping(db_session, source)

    response = client.get("/admin/source-mappings")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[legacy.id]["card_id"] == card.id
    assert by_id[print_only.id]["card_id"] is None


def test_list_source_mappings_card_code_filter_excludes_the_cardless_mapping(client, db_session):
    source = make_source(db_session)
    card = make_card(db_session, card_code="OP01-001")
    make_mapping(db_session, card, source)
    make_print_authoritative_mapping(db_session, source)

    response = client.get("/admin/source-mappings", params={"card_code": "OP01-001"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["card_id"] == card.id


# db.get(Card, None) does not raise on this SQLAlchemy version - it emits
# "fully NULL primary key identity cannot load any object" and returns None,
# with the warning itself saying it "may raise an error in a future release".
# Promoting it to an error here is what makes these two tests actually prove
# the None-guard in _to_out_with_lookups, rather than passing either way.
@pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning")
def test_get_source_mapping_with_no_legacy_card(client, db_session):
    source = make_source(db_session)
    mapping = make_print_authoritative_mapping(db_session, source)

    response = client.get(f"/admin/source-mappings/{mapping.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == mapping.id
    assert body["card_id"] is None
    assert body["card_code"] is None
    assert body["card_print_id"] == mapping.card_print_id


@pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning")
def test_patch_source_mapping_with_no_legacy_card_serializes_back(client, db_session):
    """The PATCH response goes through the same lookup-then-serialize path."""
    source = make_source(db_session)
    mapping = make_print_authoritative_mapping(db_session, source)

    response = client.patch(
        f"/admin/source-mappings/{mapping.id}", json={"review_notes": "print-only"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["card_id"] is None
    assert body["review_notes"] == "print-only"
