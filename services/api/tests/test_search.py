from datetime import date, datetime, timezone

from app.models import (
    Card,
    CollectionItem,
    CollectorActivityEvent,
    CollectorNote,
    GradingSubmission,
    MarketIntelligenceReport,
    MarketSignalEvent,
    SearchHistory,
    WishlistItem,
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


def results_by_type(data: dict, type_: str) -> list[dict]:
    return [r for r in data["results"] if r["type"] == type_]


# --- validation ----------------------------------------------------------


def test_empty_q_rejected(client, db_session):
    response = client.get("/search", params={"q": ""})
    assert response.status_code == 400


def test_missing_q_rejected(client, db_session):
    response = client.get("/search")
    assert response.status_code == 422


def test_short_q_rejected(client, db_session):
    response = client.get("/search", params={"q": "a"})
    assert response.status_code == 400


def test_search_works_on_empty_db(client, db_session):
    response = client.get("/search", params={"q": "anything"})
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_results"] == 0
    assert data["results"] == []
    assert set(data["summary"]["by_type"]) == {
        "cards",
        "collection",
        "wishlist",
        "grading",
        "notes",
        "activity",
        "signals",
        "opportunities",
        "reports",
    }


def test_suggestions_work_on_empty_db(client, db_session):
    response = client.get("/search/suggestions")
    assert response.status_code == 200
    assert response.json()["suggestions"] == []


def test_short_q_allowed_when_exact_card_code(client, db_session):
    make_card(db_session, card_code="P", name_en="Promo Card")
    response = client.get("/search", params={"q": "P"})
    assert response.status_code == 200
    data = response.json()
    assert any(r["card_code"] == "P" for r in results_by_type(data, "cards"))


# --- cards -----------------------------------------------------------------


def test_exact_card_code_ranks_highest(client, db_session):
    make_card(db_session, card_code="OP01-001", name_en="Monkey D. Luffy")
    make_card(db_session, card_code="OP01-0011", name_en="Roronoa Zoro", set_code="OP01")

    response = client.get("/search", params={"q": "OP01-001"})
    assert response.status_code == 200
    data = response.json()
    cards = results_by_type(data, "cards")
    assert cards[0]["card_code"] == "OP01-001"
    assert cards[0]["score"] == 100
    assert "card_code" in cards[0]["matched_fields"]


def test_partial_card_code_search(client, db_session):
    make_card(db_session, card_code="OP01-001", name_en="Monkey D. Luffy")

    response = client.get("/search", params={"q": "OP01"})
    assert response.status_code == 200
    data = response.json()
    cards = results_by_type(data, "cards")
    assert len(cards) == 1
    assert cards[0]["score"] == 90


def test_name_search_exact_and_partial(client, db_session):
    make_card(db_session, card_code="OP01-001", name_en="Monkey D. Luffy")

    exact = client.get("/search", params={"q": "monkey d. luffy"}).json()
    partial = client.get("/search", params={"q": "luffy"}).json()

    assert results_by_type(exact, "cards")[0]["score"] == 85
    assert results_by_type(partial, "cards")[0]["score"] == 75


def test_card_search_types_filter(client, db_session):
    make_card(db_session, card_code="OP01-001", name_en="Monkey D. Luffy")

    response = client.get("/search", params={"q": "luffy", "types": "cards"})
    data = response.json()
    assert data["summary"]["by_type"]["cards"] == 1
    assert data["summary"]["by_type"]["collection"] == 0
    assert all(r["type"] == "cards" for r in data["results"])


def test_invalid_type_rejected(client, db_session):
    response = client.get("/search", params={"q": "luffy", "types": "bogus"})
    assert response.status_code == 400


# --- collection --------------------------------------------------------


def test_collection_search_by_status_and_notes(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card, status="hold", notes="great condition raw copy")

    by_status = client.get("/search", params={"q": "hold", "types": "collection"}).json()
    by_notes = client.get("/search", params={"q": "great condition", "types": "collection"}).json()

    assert len(results_by_type(by_status, "collection")) == 1
    assert results_by_type(by_status, "collection")[0]["score"] == 35 + 5  # meta + owned bonus
    assert len(results_by_type(by_notes, "collection")) == 1
    assert results_by_type(by_notes, "collection")[0]["score"] == 50 + 5  # text + owned bonus


def test_collection_search_by_card_code(client, db_session):
    card = make_card(db_session, card_code="OP01-001")
    make_item(db_session, card)

    response = client.get("/search", params={"q": "OP01-001", "types": "collection"})
    data = response.json()
    assert len(results_by_type(data, "collection")) == 1


# --- wishlist ------------------------------------------------------------


def test_wishlist_search_by_priority_with_bonus(client, db_session):
    card = make_card(db_session)
    db_session.add(
        WishlistItem(user_id=1, card_id=card.id, priority="grail", status="watching")
    )
    db_session.commit()

    response = client.get("/search", params={"q": "grail", "types": "wishlist"})
    data = response.json()
    results = results_by_type(data, "wishlist")
    assert len(results) == 1
    assert results[0]["score"] == 35 + 5  # meta match + grail priority bonus


def test_wishlist_search_by_notes(client, db_session):
    card = make_card(db_session)
    db_session.add(
        WishlistItem(
            user_id=1,
            card_id=card.id,
            priority="medium",
            status="watching",
            notes="waiting for a price drop",
        )
    )
    db_session.commit()

    response = client.get("/search", params={"q": "price drop", "types": "wishlist"})
    data = response.json()
    assert len(results_by_type(data, "wishlist")) == 1


# --- grading ---------------------------------------------------------------


def test_grading_search_by_company_and_status(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    db_session.add(
        GradingSubmission(
            collection_item_id=item.id,
            grading_company="PSA",
            submission_name="July batch",
            submission_status="submitted",
            cert_number="12345678",
        )
    )
    db_session.commit()

    by_company = client.get("/search", params={"q": "PSA", "types": "grading"}).json()
    by_cert = client.get("/search", params={"q": "12345678", "types": "grading"}).json()

    assert len(results_by_type(by_company, "grading")) == 1
    assert len(results_by_type(by_cert, "grading")) == 1


# --- notes -----------------------------------------------------------------


def test_notes_search_by_body_and_title(client, db_session):
    card = make_card(db_session)
    db_session.add(
        CollectorNote(
            note_type="card",
            card_id=card.id,
            title="Keep an eye on this",
            body="Considering grading this copy soon",
        )
    )
    db_session.commit()

    by_title = client.get("/search", params={"q": "keep an eye", "types": "notes"}).json()
    by_body = client.get("/search", params={"q": "considering grading", "types": "notes"}).json()
    by_card = client.get("/search", params={"q": card.card_code, "types": "notes"}).json()

    assert len(results_by_type(by_title, "notes")) == 1
    assert len(results_by_type(by_body, "notes")) == 1
    assert len(results_by_type(by_card, "notes")) == 1


# --- activity ----------------------------------------------------------------


def test_activity_search_by_type_and_message_with_recent_bonus(client, db_session):
    card = make_card(db_session)
    db_session.add(
        CollectorActivityEvent(
            event_type="collection_item_added",
            event_source="collection",
            card_id=card.id,
            title="Added to collection",
            message="Quantity: 1",
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    response = client.get("/search", params={"q": "collection_item_added", "types": "activity"})
    data = response.json()
    results = results_by_type(data, "activity")
    assert len(results) == 1
    assert results[0]["score"] == 35 + 5  # meta match + recent bonus (owned bonus not applicable, no collection item)


# --- signals -----------------------------------------------------------------


def test_signals_search_by_signal_type_and_status(client, db_session):
    card = make_card(db_session)
    now = datetime.now(timezone.utc)
    db_session.add(
        MarketSignalEvent(
            signal_type="owned_above_target_sell",
            dedupe_key="test-dedupe-1",
            card_id=card.id,
            status="open",
            suggested_action="review_sell_opportunity",
            message="Price is above your target sell",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    db_session.commit()

    response = client.get(
        "/search", params={"q": "owned_above_target_sell", "types": "signals"}
    )
    data = response.json()
    results = results_by_type(data, "signals")
    assert len(results) == 1
    assert results[0]["score"] == 35 + 5  # meta + recent bonus


# --- opportunities -------------------------------------------------------


def test_opportunities_search_filters_by_card_code(client, db_session):
    card = make_card(db_session, card_code="OP01-001")
    now = datetime.now(timezone.utc)
    db_session.add(
        MarketSignalEvent(
            signal_type="owned_above_target_sell",
            dedupe_key="test-dedupe-2",
            card_id=card.id,
            status="open",
            suggested_action="review_sell_opportunity",
            message="Above target",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    db_session.commit()

    response = client.get("/search", params={"q": "OP01-001", "types": "opportunities"})
    data = response.json()
    results = results_by_type(data, "opportunities")
    assert len(results) == 1
    assert results[0]["card_code"] == "OP01-001"


# --- reports -----------------------------------------------------------------


def test_reports_search_by_summary_line(client, db_session):
    db_session.add(
        MarketIntelligenceReport(
            report_date=date(2026, 7, 1),
            report_payload_json={
                "deterministic_summary_lines": ["Top ranked opportunity: OP01-001 with score 80."],
            },
        )
    )
    db_session.commit()

    response = client.get("/search", params={"q": "top ranked opportunity", "types": "reports"})
    data = response.json()
    results = results_by_type(data, "reports")
    assert len(results) == 1
    assert "deterministic_summary_lines" in results[0]["matched_fields"]


def test_reports_search_by_date(client, db_session):
    db_session.add(
        MarketIntelligenceReport(
            report_date=date(2026, 7, 1),
            report_payload_json={"deterministic_summary_lines": []},
        )
    )
    db_session.commit()

    response = client.get("/search", params={"q": "2026-07-01", "types": "reports"})
    data = response.json()
    assert len(results_by_type(data, "reports")) == 1


# --- search history --------------------------------------------------------


def test_search_records_history_on_success(client, db_session):
    make_card(db_session, card_code="OP01-001")

    response = client.get("/search", params={"q": "OP01-001"})
    assert response.status_code == 200

    history = db_session.query(SearchHistory).all()
    assert len(history) == 1
    assert history[0].query == "OP01-001"
    assert history[0].result_count == response.json()["summary"]["total_results"]


def test_search_does_not_record_history_on_rejected_query(client, db_session):
    response = client.get("/search", params={"q": "a"})
    assert response.status_code == 400

    history = db_session.query(SearchHistory).all()
    assert history == []


# --- suggestions -------------------------------------------------------


def test_suggestions_returns_owned_cards(client, db_session):
    card = make_card(db_session, card_code="OP01-001")
    make_item(db_session, card, quantity=3)

    response = client.get("/search/suggestions")
    assert response.status_code == 200
    data = response.json()
    assert any(s["type"] == "card" for s in data["suggestions"])


def test_suggestions_returns_wishlist_grails(client, db_session):
    card = make_card(db_session, card_code="OP01-001")
    db_session.add(WishlistItem(user_id=1, card_id=card.id, priority="grail", status="watching"))
    db_session.commit()

    response = client.get("/search/suggestions")
    data = response.json()
    assert any(s["type"] == "wishlist" for s in data["suggestions"])


def test_suggestions_filtered_by_q(client, db_session):
    card1 = make_card(db_session, card_code="OP01-001", name_en="Monkey D. Luffy")
    card2 = make_card(db_session, card_code="OP02-001", name_en="Roronoa Zoro", set_code="OP02")
    make_item(db_session, card1)
    make_item(db_session, card2)

    response = client.get("/search/suggestions", params={"q": "luffy"})
    data = response.json()
    assert all("luffy" in s["label"].lower() for s in data["suggestions"])
    assert any("luffy" in s["label"].lower() for s in data["suggestions"])


def test_suggestions_includes_recent_search_after_history(client, db_session):
    make_card(db_session, card_code="OP01-001")
    client.get("/search", params={"q": "some free text query"})

    response = client.get("/search/suggestions")
    data = response.json()
    assert any(s["type"] == "recent_search" for s in data["suggestions"])
