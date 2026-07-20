from app.models import CardTag, CollectionItem, CollectorTag, WishlistItem
from app.models.card_alias import CardAlias
from app.services.card_identity_merge import (
    DuplicateDetectionFilters,
    MergeOptions,
    MergeValidationError,
    calculate_duplicate_score,
    detect_duplicate_cards,
    execute_card_merge,
)
from tests.test_source_mappings import make_card, make_mapping, make_source

USER_ID = 1


def make_collection_item(db_session, card, **overrides):
    fields = dict(user_id=USER_ID, card_id=card.id, quantity=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def make_wishlist_item(db_session, card, **overrides):
    fields = dict(user_id=USER_ID, card_id=card.id)
    fields.update(overrides)
    item = WishlistItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def make_tag(db_session, name="Grail") -> CollectorTag:
    tag = CollectorTag(user_id=USER_ID, name=name, slug=name.lower())
    db_session.add(tag)
    db_session.commit()
    db_session.refresh(tag)
    return tag


# cards has UNIQUE(card_code, set_code, rarity, variant, language) - every
# "duplicate pair" fixture below must differ in at least one of those columns
# (real duplicates always do: a re-import with a different rarity/variant
# label, never a byte-for-byte identical row) - rarity is used as that one
# differing column throughout, since a rarity mismatch alone carries no score
# cap (unlike set_code/variant/language mismatches).


# --- scoring -----------------------------------------------------------


def test_exact_card_code_match_scores_high(db_session):
    a = make_card(db_session, card_code="OP01-001", rarity="L")
    b = make_card(db_session, card_code="OP01-001", rarity="SR")
    result = calculate_duplicate_score(a, b)
    assert result.score >= 90
    assert result.confidence_label == "exact_duplicate"
    assert "exact card_code match" in result.explanation.to_dict()["positive"]


def test_variant_mismatch_caps_score_when_card_code_matches(db_session):
    a = make_card(db_session, card_code="OP01-001", variant="base")
    b = make_card(db_session, card_code="OP01-001", variant="parallel")
    result = calculate_duplicate_score(a, b)
    assert result.score <= 74
    assert result.confidence_label in ("possible_duplicate", "weak_match", "not_duplicate")
    assert "variant_mismatch_cap_74" in result.explanation.caps_applied


def test_set_code_mismatch_caps_score(db_session):
    # Same card_code once normalized (case-only difference, so this is a
    # *normalized*, not exact, card_code match) but different set_code -
    # every other signal matches, so the score would clear 60 without the
    # cap; the cap only applies without an *exact* (raw string) card_code
    # match, which this deliberately isn't.
    a = make_card(db_session, card_code="OP01-001", set_code="OP01")
    b = make_card(db_session, card_code="op01-001", set_code="OP02")
    result = calculate_duplicate_score(a, b)
    assert result.score <= 60
    assert "set_code_mismatch_cap_60" in result.explanation.caps_applied


def test_language_mismatch_caps_score_when_both_languages_known(db_session):
    a = make_card(db_session, card_code="OP01-001", language="en")
    b = make_card(db_session, card_code="OP01-001", language="jp")
    result = calculate_duplicate_score(a, b)
    assert result.score <= 74
    assert "language_mismatch_cap_74" in result.explanation.caps_applied


# --- detection endpoint --------------------------------------------------


def test_duplicates_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/cards/duplicates")
    assert response.status_code == 401


def test_duplicates_endpoint_returns_pairs(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L")
    make_card(
        db_session,
        card_code="OP01-001",
        set_code="OP01",
        rarity="SR",
        name_en="Monkey D. Luffy (dup)",
    )

    response = client.get("/admin/cards/duplicates")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_pairs"] >= 1
    assert len(body["pairs"]) >= 1
    pair = body["pairs"][0]
    assert pair["score"] > 0
    assert "confidence_label" in pair


def test_duplicates_endpoint_empty_catalog(client, db_session):
    response = client.get("/admin/cards/duplicates")
    assert response.status_code == 200
    body = response.json()
    assert body["pairs"] == []
    assert body["summary"]["total_pairs"] == 0


# --- merge preview --------------------------------------------------------


def test_merge_preview_returns_affected_records(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card_a = make_card(db_session, card_code="OP01-001", rarity="L")
    card_b = make_card(db_session, card_code="OP01-001", rarity="SR", name_en="Monkey D. Luffy (dup)")
    make_mapping(db_session, card_b, source, source_card_id="OP01-001")
    make_collection_item(db_session, card_b)
    make_wishlist_item(db_session, card_b)

    response = client.get(
        f"/admin/cards/{card_b.id}/merge-preview", params={"target_card_id": card_a.id}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["affected_records"]["source_card_mappings"] == 1
    assert body["affected_records"]["collection_items"] == 1
    assert body["affected_records"]["wishlist_items"] == 1
    assert body["duplicate_score"] > 0


# --- merge execution --------------------------------------------------------


def test_dry_run_merge_does_not_write(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card_a = make_card(db_session, card_code="OP01-001", rarity="L")
    card_b = make_card(db_session, card_code="OP01-001", rarity="SR", name_en="dup")
    make_mapping(db_session, card_b, source, source_card_id="OP01-001")

    response = client.post(
        "/admin/cards/merge",
        json={"source_card_id": card_b.id, "target_card_id": card_a.id, "dry_run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["merged"] is False

    db_session.refresh(card_b)
    assert card_b.is_active is True
    assert card_b.merged_into_card_id is None


def test_real_merge_reassigns_source_mappings_collection_wishlist(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card_a = make_card(db_session, card_code="OP01-001", rarity="L")
    card_b = make_card(db_session, card_code="OP01-001", rarity="SR", name_en="dup")
    mapping = make_mapping(db_session, card_b, source, source_card_id="OP01-001")
    collection_item = make_collection_item(db_session, card_b)
    wishlist_item = make_wishlist_item(db_session, card_b)

    response = client.post(
        "/admin/cards/merge",
        json={
            "source_card_id": card_b.id,
            "target_card_id": card_a.id,
            "dry_run": False,
            "merge_notes": "Duplicate imported from watchlist",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["merged"] is True

    db_session.refresh(mapping)
    db_session.refresh(collection_item)
    db_session.refresh(wishlist_item)
    db_session.refresh(card_a)
    db_session.refresh(card_b)

    assert mapping.card_id == card_a.id
    assert collection_item.card_id == card_a.id
    assert wishlist_item.card_id == card_a.id
    assert card_b.is_active is False
    assert card_b.merged_into_card_id == card_a.id
    assert card_b.merge_notes == "Duplicate imported from watchlist"
    assert card_b.merged_at is not None


def test_real_merge_reassigns_card_tags(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001", rarity="L")
    card_b = make_card(db_session, card_code="OP01-001", rarity="SR", name_en="dup")
    tag = make_tag(db_session)
    card_tag = CardTag(card_id=card_b.id, tag_id=tag.id)
    db_session.add(card_tag)
    db_session.commit()
    db_session.refresh(card_tag)

    response = client.post(
        "/admin/cards/merge",
        json={"source_card_id": card_b.id, "target_card_id": card_a.id, "dry_run": False},
    )
    assert response.status_code == 200

    db_session.refresh(card_tag)
    assert card_tag.card_id == card_a.id


def test_real_merge_skips_conflicting_card_tag(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001", rarity="L")
    card_b = make_card(db_session, card_code="OP01-001", rarity="SR", name_en="dup")
    tag = make_tag(db_session)
    db_session.add(CardTag(card_id=card_a.id, tag_id=tag.id))
    source_tag = CardTag(card_id=card_b.id, tag_id=tag.id)
    db_session.add(source_tag)
    db_session.commit()
    db_session.refresh(source_tag)

    response = client.post(
        "/admin/cards/merge",
        json={"source_card_id": card_b.id, "target_card_id": card_a.id, "dry_run": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert any("card_tags" in w for w in body["warnings"])

    db_session.refresh(source_tag)
    assert source_tag.card_id == card_b.id


def test_target_fields_filled_when_strategy_fill_missing(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001", rarity="L", artist=None)
    card_b = make_card(
        db_session, card_code="OP01-001", rarity="SR", name_en="dup", artist="Eiichiro Oda"
    )

    response = client.post(
        "/admin/cards/merge",
        json={
            "source_card_id": card_b.id,
            "target_card_id": card_a.id,
            "dry_run": False,
            "field_strategy": "fill_missing_target_fields",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "artist" in body["field_changes"]

    db_session.refresh(card_a)
    assert card_a.artist == "Eiichiro Oda"


def test_low_confidence_merge_rejected_unless_approved(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001", set_code="OP01", variant="base")
    card_b = make_card(db_session, card_code="OP02-999", set_code="OP02", name_en="totally different")

    response = client.post(
        "/admin/cards/merge",
        json={"source_card_id": card_b.id, "target_card_id": card_a.id, "dry_run": False},
    )
    assert response.status_code == 400

    response = client.post(
        "/admin/cards/merge",
        json={
            "source_card_id": card_b.id,
            "target_card_id": card_a.id,
            "dry_run": False,
            "approve_low_confidence": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["merged"] is True
    assert any("low duplicate_score" in w for w in body["warnings"])


def test_card_aliases_created_on_merge(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001", rarity="L", name_en="Monkey D. Luffy")
    card_b = make_card(db_session, card_code="OP01-001", rarity="SR", name_en="Luffy (import)")

    response = client.post(
        "/admin/cards/merge",
        json={"source_card_id": card_b.id, "target_card_id": card_a.id, "dry_run": False},
    )
    assert response.status_code == 200

    aliases = db_session.query(CardAlias).filter(CardAlias.card_id == card_a.id).all()
    alias_types = {a.alias_type for a in aliases}
    assert "old_name_en" in alias_types
    matching = next(a for a in aliases if a.alias_type == "old_name_en")
    assert matching.alias_value == "Luffy (import)"


def test_merge_target_already_merged_rejected(db_session):
    card_a = make_card(db_session, card_code="OP01-001", rarity="L")
    card_b = make_card(db_session, card_code="OP01-001", rarity="SR", name_en="dup1")
    card_c = make_card(db_session, card_code="OP01-001", rarity="SEC", name_en="dup2")

    execute_card_merge(db_session, card_b.id, card_a.id, MergeOptions(dry_run=False))

    try:
        execute_card_merge(db_session, card_c.id, card_b.id, MergeOptions(dry_run=False))
        assert False, "expected MergeValidationError"
    except MergeValidationError:
        pass


def test_detect_duplicate_cards_service_paginates(db_session):
    for i, rarity in enumerate(("L", "SR", "SEC")):
        make_card(db_session, card_code="OP01-001", rarity=rarity, name_en=f"dup{i}")
    pairs, total, summary = detect_duplicate_cards(
        db_session, DuplicateDetectionFilters(), limit=1, offset=0
    )
    assert total >= 3
    assert len(pairs) == 1
