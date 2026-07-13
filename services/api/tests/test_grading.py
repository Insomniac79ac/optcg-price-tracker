from app.models import Card, CollectionItem, GradingSubmission


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


def make_submission_via_api(client, item_id: int, **overrides) -> dict:
    body = {
        "collection_item_id": item_id,
        "grading_company": "PSA",
        "submission_name": "July PSA batch",
        "submission_status": "planned",
        "declared_value_jpy": 10000,
        "grading_fee_jpy": 3000,
        "shipping_fee_jpy": 1000,
        "insurance_fee_jpy": 500,
        "other_fee_jpy": 0,
        "notes": "",
    }
    body.update(overrides)
    response = client.post("/grading/submissions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- create ---------------------------------------------------------------


def test_create_grading_submission(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)

    body = make_submission_via_api(client, item.id)

    assert body["collection_item_id"] == item.id
    assert body["card_code"] == "OP01-001"
    assert body["grading_company"] == "PSA"
    assert body["submission_name"] == "July PSA batch"
    assert body["submission_status"] == "planned"
    assert body["declared_value_jpy"] == 10000
    assert body["total_cost_jpy"] == 3000 + 1000 + 500 + 0
    assert body["final_grade"] is None
    assert body["graded_value_jpy"] is None


def test_create_grading_submission_item_not_found(client, db_session):
    response = client.post(
        "/grading/submissions", json={"collection_item_id": 999999, "grading_company": "PSA"}
    )
    assert response.status_code == 404


def test_create_grading_submission_blank_company_rejected(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)

    response = client.post(
        "/grading/submissions", json={"collection_item_id": item.id, "grading_company": "   "}
    )
    assert response.status_code == 422


def test_create_grading_submission_invalid_status_rejected(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)

    response = client.post(
        "/grading/submissions",
        json={
            "collection_item_id": item.id,
            "grading_company": "PSA",
            "submission_status": "bogus",
        },
    )
    assert response.status_code == 422


# --- list / filters ---------------------------------------------------------


def test_list_grading_submissions(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    make_submission_via_api(client, item.id)
    make_submission_via_api(client, item.id, grading_company="BGS")

    response = client.get("/grading/submissions")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_filter_by_status(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    make_submission_via_api(client, item.id, submission_status="planned")
    make_submission_via_api(client, item.id, submission_status="submitted")

    response = client.get("/grading/submissions", params={"status": "submitted"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["submission_status"] == "submitted"


def test_filter_by_status_invalid(client, db_session):
    response = client.get("/grading/submissions", params={"status": "bogus"})
    assert response.status_code == 400


def test_filter_by_company(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    make_submission_via_api(client, item.id, grading_company="PSA")
    make_submission_via_api(client, item.id, grading_company="BGS")

    response = client.get("/grading/submissions", params={"grading_company": "BGS"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["grading_company"] == "BGS"


def test_filter_by_card_code(client, db_session):
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    item_a = make_item(db_session, card_a)
    item_b = make_item(db_session, card_b)
    make_submission_via_api(client, item_a.id)
    make_submission_via_api(client, item_b.id)

    response = client.get("/grading/submissions", params={"card_code": "OP01-002"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["card_code"] == "OP01-002"


# --- detail / patch / delete -----------------------------------------------


def test_get_detail(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    created = make_submission_via_api(client, item.id)

    response = client.get(f"/grading/submissions/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_detail_not_found(client, db_session):
    response = client.get("/grading/submissions/999999")
    assert response.status_code == 404


def test_patch_status(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    created = make_submission_via_api(client, item.id)

    response = client.patch(
        f"/grading/submissions/{created['id']}", json={"submission_status": "submitted"}
    )

    assert response.status_code == 200
    assert response.json()["submission_status"] == "submitted"


def test_patch_recomputes_total_cost(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    created = make_submission_via_api(client, item.id)

    response = client.patch(
        f"/grading/submissions/{created['id']}", json={"grading_fee_jpy": 5000}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grading_fee_jpy"] == 5000
    assert body["total_cost_jpy"] == 5000 + 1000 + 500 + 0


def test_patch_invalid_collection_item_id(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    created = make_submission_via_api(client, item.id)

    response = client.patch(
        f"/grading/submissions/{created['id']}", json={"collection_item_id": 999999}
    )
    assert response.status_code == 404


def test_delete_submission(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    created = make_submission_via_api(client, item.id)

    response = client.delete(f"/grading/submissions/{created['id']}")
    assert response.status_code == 204

    db_session.expire_all()
    assert db_session.get(GradingSubmission, created["id"]) is None


def test_delete_submission_not_found(client, db_session):
    response = client.delete("/grading/submissions/999999")
    assert response.status_code == 404


# --- total cost calculation --------------------------------------------------


def test_total_cost_partial_fees_treats_missing_as_zero(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)

    body = make_submission_via_api(
        client,
        item.id,
        grading_fee_jpy=3000,
        shipping_fee_jpy=None,
        insurance_fee_jpy=None,
        other_fee_jpy=None,
    )

    assert body["total_cost_jpy"] == 3000


def test_total_cost_all_fees_missing_is_null(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)

    body = make_submission_via_api(
        client,
        item.id,
        grading_fee_jpy=None,
        shipping_fee_jpy=None,
        insurance_fee_jpy=None,
        other_fee_jpy=None,
    )

    assert body["total_cost_jpy"] is None


# --- summary ------------------------------------------------------------


def test_summary_empty(client, db_session):
    response = client.get("/grading/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_submissions"] == 0
    assert body["by_status"] == {
        "planned": 0,
        "preparing": 0,
        "submitted": 0,
        "grading": 0,
        "shipped_back": 0,
        "received": 0,
        "cancelled": 0,
    }
    assert body["total_declared_value_jpy"] == 0
    assert body["total_grading_cost_jpy"] == 0
    assert body["total_graded_value_jpy"] == 0
    assert body["total_unrealized_gain_after_grading_jpy"] == 0
    assert body["average_grade"] is None
    assert body["items_waiting_return"] == 0


def test_summary_calculation(client, db_session):
    card = make_card(db_session)
    item1 = make_item(db_session, card, purchase_price_jpy=1000, quantity=1)
    item2 = make_item(db_session, card, purchase_price_jpy=None, quantity=1)

    make_submission_via_api(
        client,
        item1.id,
        submission_status="grading",
        declared_value_jpy=10000,
        grading_fee_jpy=3000,
        shipping_fee_jpy=1000,
        insurance_fee_jpy=500,
        other_fee_jpy=0,
        graded_value_jpy=None,
    )
    make_submission_via_api(
        client,
        item2.id,
        submission_status="received",
        declared_value_jpy=5000,
        grading_fee_jpy=2000,
        shipping_fee_jpy=500,
        insurance_fee_jpy=0,
        other_fee_jpy=0,
        final_grade="PSA 10",
        graded_value_jpy=8000,
    )

    response = client.get("/grading/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_submissions"] == 2
    assert body["by_status"]["grading"] == 1
    assert body["by_status"]["received"] == 1
    assert body["total_declared_value_jpy"] == 10000 + 5000
    assert body["total_grading_cost_jpy"] == 4500 + 2500
    assert body["total_graded_value_jpy"] == 8000
    # item2's purchase price is missing, so its gain is excluded entirely.
    assert body["total_unrealized_gain_after_grading_jpy"] == 0
    assert body["average_grade"] == 10.0
    assert body["items_waiting_return"] == 1  # "grading" status


def test_gain_calculation_excludes_missing_cost_basis(client, db_session):
    card = make_card(db_session)
    item_with_cost = make_item(db_session, card, purchase_price_jpy=2000, quantity=1)
    item_without_cost = make_item(db_session, card, purchase_price_jpy=None, quantity=1)

    make_submission_via_api(
        client,
        item_with_cost.id,
        grading_fee_jpy=1000,
        shipping_fee_jpy=0,
        insurance_fee_jpy=0,
        other_fee_jpy=0,
        graded_value_jpy=5000,
    )
    make_submission_via_api(
        client,
        item_without_cost.id,
        grading_fee_jpy=1000,
        shipping_fee_jpy=0,
        insurance_fee_jpy=0,
        other_fee_jpy=0,
        graded_value_jpy=5000,
    )

    response = client.get("/grading/summary")

    body = response.json()
    # Only item_with_cost contributes: 5000 - 2000 - 1000 = 2000.
    assert body["total_unrealized_gain_after_grading_jpy"] == 2000


def test_average_grade_numeric_only(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)

    make_submission_via_api(client, item.id, final_grade="10")
    make_submission_via_api(client, item.id, final_grade="9.5")
    make_submission_via_api(client, item.id, final_grade="Authentic")

    response = client.get("/grading/summary")

    body = response.json()
    assert body["average_grade"] == 9.75


# --- collection / valuation response inclusion -----------------------------


def test_collection_response_includes_grading_info(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    created = make_submission_via_api(client, item.id, submission_status="submitted")

    list_response = client.get("/collection")
    assert list_response.status_code == 200
    list_item = list_response.json()["items"][0]
    assert list_item["latest_grading_status"] == "submitted"
    assert len(list_item["grading_submissions"]) == 1
    assert list_item["grading_submissions"][0]["id"] == created["id"]

    detail_response = client.get(f"/collection/{item.id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["latest_grading_status"] == "submitted"


def test_valuation_response_includes_grading_info(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    make_submission_via_api(
        client,
        item.id,
        grading_company="BGS",
        submission_status="grading",
        grading_fee_jpy=2000,
        shipping_fee_jpy=0,
        insurance_fee_jpy=0,
        other_fee_jpy=0,
    )

    response = client.get("/collection/valuation")

    assert response.status_code == 200
    valuation_item = response.json()["items"][0]
    grading = valuation_item["grading"]
    assert grading["has_grading_submission"] is True
    assert grading["latest_status"] == "grading"
    assert grading["grading_company"] == "BGS"
    assert grading["total_grading_cost_jpy"] == 2000
    assert grading["graded_value_jpy"] is None


def test_valuation_response_grading_false_when_no_submission(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card)

    response = client.get("/collection/valuation")

    grading = response.json()["items"][0]["grading"]
    assert grading["has_grading_submission"] is False
    assert grading["latest_status"] is None


def test_opportunities_include_grading_status_for_owned(client, db_session):
    from datetime import datetime, timezone

    from app.models import MarketSignalEvent

    card = make_card(db_session)
    item = make_item(db_session, card, quantity=1)
    make_submission_via_api(client, item.id, submission_status="shipped_back")

    now = datetime.now(timezone.utc)
    event = MarketSignalEvent(
        signal_type="owned_above_target_sell",
        dedupe_key="dedupe-grading-1",
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
    opp = response.json()["opportunities"][0]
    assert opp["grading"]["has_grading_submission"] is True
    assert opp["grading"]["latest_status"] == "shipped_back"


# --- backup -------------------------------------------------------------


def test_backup_export_includes_grading_submissions(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    make_submission_via_api(client, item.id)

    response = client.get("/admin/backup/export")

    assert response.status_code == 200
    body = response.json()
    assert "grading_submissions" in body["tables"]
    assert len(body["tables"]["grading_submissions"]) == 1
    assert body["tables"]["grading_submissions"][0]["grading_company"] == "PSA"
