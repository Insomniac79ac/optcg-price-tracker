from datetime import date, timedelta

import pytest

from app.models import Card, CollectionItem, GradingSubmission
from app.services import cache as cache_module
from app.settings import settings

TEST_USER_ID = 1


@pytest.fixture(autouse=True)
def _cache_memory_backend(monkeypatch):
    """conftest's _cache_disabled_by_default turns caching off for every
    other test - this file explicitly re-enables it (memory backend, so no
    real Redis is needed) to exercise the endpoint's real cache behavior."""
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    cache_module.reset_state_for_tests()
    yield
    cache_module.reset_state_for_tests()


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001", name_en="Monkey D. Luffy", name_jp="モンキー・D・ルフィ",
        set_code="OP01", rarity="L", variant="leader", language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_item(db_session, card: Card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=TEST_USER_ID)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def make_submission(db_session, item: CollectionItem, **overrides) -> GradingSubmission:
    fields = dict(collection_item_id=item.id, grading_company="PSA", submission_status="planned")
    fields.update(overrides)
    submission = GradingSubmission(**fields)
    db_session.add(submission)
    db_session.commit()
    db_session.refresh(submission)
    return submission


def by_card_code(submissions: list[dict]) -> dict:
    return {s["card_code"]: s for s in submissions}


def by_key(entries: list[dict]) -> dict:
    return {e["key"]: e for e in entries}


def test_empty_grading_analytics_works(client, db_session):
    response = client.get("/analytics/grading")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "total_submissions": 0,
        "active_submissions": 0,
        "received_submissions": 0,
        "cancelled_submissions": 0,
        "total_declared_value_jpy": 0,
        "total_grading_cost_jpy": 0,
        "total_graded_value_jpy": 0,
        "total_raw_cost_basis_jpy": 0,
        "total_roi_jpy": 0,
        "total_roi_pct": None,
        "average_grade": None,
        "median_grade": None,
        "profitable_count": 0,
        "unprofitable_count": 0,
        "missing_graded_value_count": 0,
        "missing_cost_basis_count": 0,
        "items_waiting_return": 0,
    }
    assert body["submissions"] == []
    assert body["pagination"]["total"] == 0


def test_cancelled_excluded_by_default(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    make_submission(db_session, item, submission_status="cancelled")

    response = client.get("/analytics/grading")

    assert response.json()["summary"]["total_submissions"] == 0


def test_include_cancelled_includes_cancelled(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    make_submission(db_session, item, submission_status="cancelled")

    response = client.get("/analytics/grading", params={"include_cancelled": "true"})

    body = response.json()
    assert body["summary"]["total_submissions"] == 1
    assert body["summary"]["cancelled_submissions"] == 1


def test_roi_calculation_works(client, db_session):
    """Matches the feature spec's own worked example exactly: raw cost basis
    8000, total grading cost 4500, graded value 18000 -> ROI 5500 (44.0%)."""
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=8000, quantity=1)
    make_submission(
        db_session, item,
        submission_status="received",
        grading_fee_jpy=3000, shipping_fee_jpy=1000, insurance_fee_jpy=500, other_fee_jpy=0,
        graded_value_jpy=18000, final_grade="10",
    )

    response = client.get("/analytics/grading")

    submission = response.json()["submissions"][0]
    assert submission["raw_cost_basis_jpy"] == 8000
    assert submission["total_cost_jpy"] == 4500
    assert submission["roi_jpy"] == 5500
    assert submission["roi_pct"] == 44.0
    assert submission["flags"]["profitable"] is True


def test_roi_null_when_cost_basis_missing(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=None)
    make_submission(db_session, item, submission_status="received", graded_value_jpy=18000)

    response = client.get("/analytics/grading")

    submission = response.json()["submissions"][0]
    assert submission["roi_jpy"] is None
    assert submission["roi_pct"] is None
    assert submission["flags"]["missing_cost_basis"] is True


def test_roi_null_when_graded_value_missing(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=8000)
    make_submission(db_session, item, submission_status="submitted", graded_value_jpy=None)

    response = client.get("/analytics/grading")

    submission = response.json()["submissions"][0]
    assert submission["roi_jpy"] is None
    assert submission["flags"]["missing_graded_value"] is True


def test_missing_fee_components_treated_as_0(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    make_submission(db_session, item, grading_fee_jpy=1000)  # every other fee left unset

    response = client.get("/analytics/grading")

    assert response.json()["submissions"][0]["total_cost_jpy"] == 1000


def test_profitable_unprofitable_counts_work(client, db_session):
    profitable_card = make_card(db_session, card_code="OP01-001")
    unprofitable_card = make_card(db_session, card_code="OP01-002")
    profitable_item = make_item(db_session, profitable_card, purchase_price_jpy=1000)
    unprofitable_item = make_item(db_session, unprofitable_card, purchase_price_jpy=10000)
    make_submission(db_session, profitable_item, submission_status="received", graded_value_jpy=5000)
    make_submission(db_session, unprofitable_item, submission_status="received", graded_value_jpy=2000)

    response = client.get("/analytics/grading")

    summary = response.json()["summary"]
    assert summary["profitable_count"] == 1
    assert summary["unprofitable_count"] == 1


def test_average_grade_numeric_only(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    make_submission(db_session, item, final_grade="10")
    make_submission(db_session, item, final_grade="9.5")
    make_submission(db_session, item, final_grade="Authentic")  # non-numeric, excluded

    response = client.get("/analytics/grading")

    assert response.json()["summary"]["average_grade"] == 9.75


def test_median_grade_numeric_only(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    make_submission(db_session, item, final_grade="8")
    make_submission(db_session, item, final_grade="9")
    make_submission(db_session, item, final_grade="10")
    make_submission(db_session, item, final_grade="N/A")  # non-numeric, excluded

    response = client.get("/analytics/grading")

    assert response.json()["summary"]["median_grade"] == 9.0


def test_overdue_detection_works(client, db_session):
    card = make_card(db_session)
    overdue_item = make_item(db_session, card, purchase_price_jpy=1000)
    make_submission(
        db_session, overdue_item, submission_status="grading",
        expected_return_date=date.today() - timedelta(days=1),
    )
    future_card = make_card(db_session, card_code="OP01-002")
    future_item = make_item(db_session, future_card, purchase_price_jpy=1000)
    make_submission(
        db_session, future_item, submission_status="grading",
        expected_return_date=date.today() + timedelta(days=5),
    )

    response = client.get("/analytics/grading")

    body = response.json()
    assert len(body["pending"]["overdue"]) == 1
    assert body["pending"]["overdue"][0]["card_code"] == "OP01-001"


def test_expected_next_30d_works(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    make_submission(
        db_session, item, submission_status="submitted",
        expected_return_date=date.today() + timedelta(days=10),
    )

    response = client.get("/analytics/grading")

    body = response.json()
    assert len(body["pending"]["expected_next_30d"]) == 1
    assert body["pending"]["expected_next_30d"][0]["card_code"] == "OP01-001"


def test_breakdown_by_status_works(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    make_submission(db_session, item, submission_status="received")
    make_submission(db_session, item, submission_status="submitted")

    response = client.get("/analytics/grading")

    breakdown = by_key(response.json()["breakdowns"]["by_status"])
    assert breakdown["received"]["submission_count"] == 1
    assert breakdown["submitted"]["submission_count"] == 1


def test_breakdown_by_company_works(client, db_session):
    card1 = make_card(db_session, card_code="OP01-001")
    card2 = make_card(db_session, card_code="OP01-002")
    item1 = make_item(db_session, card1, purchase_price_jpy=1000)
    item2 = make_item(db_session, card2, purchase_price_jpy=1000)
    make_submission(db_session, item1, grading_company="PSA")
    make_submission(db_session, item2, grading_company="BGS")

    response = client.get("/analytics/grading")

    breakdown = by_key(response.json()["breakdowns"]["by_company"])
    assert breakdown["PSA"]["submission_count"] == 1
    assert breakdown["BGS"]["submission_count"] == 1


def test_breakdown_by_grade_works(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    make_submission(db_session, item, final_grade="10")
    make_submission(db_session, item, final_grade="10")
    make_submission(db_session, item, final_grade=None)  # excluded from by_grade

    response = client.get("/analytics/grading")

    breakdown = by_key(response.json()["breakdowns"]["by_grade"])
    assert breakdown["10"]["submission_count"] == 2
    assert len(response.json()["breakdowns"]["by_grade"]) == 1


def test_filters_by_grading_company(client, db_session):
    card1 = make_card(db_session, card_code="OP01-001")
    card2 = make_card(db_session, card_code="OP01-002")
    item1 = make_item(db_session, card1, purchase_price_jpy=1000)
    item2 = make_item(db_session, card2, purchase_price_jpy=1000)
    make_submission(db_session, item1, grading_company="PSA")
    make_submission(db_session, item2, grading_company="BGS")

    response = client.get("/analytics/grading", params={"grading_company": "PSA"})

    body = response.json()
    assert body["summary"]["total_submissions"] == 1
    assert body["submissions"][0]["grading_company"] == "PSA"


def test_filters_by_status(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    make_submission(db_session, item, submission_status="received")
    make_submission(db_session, item, submission_status="submitted")

    response = client.get("/analytics/grading", params={"status": "received"})

    body = response.json()
    assert body["summary"]["total_submissions"] == 1
    assert body["submissions"][0]["submission_status"] == "received"


def test_pagination_works(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    for _ in range(3):
        make_submission(db_session, item)

    first_page = client.get("/analytics/grading", params={"limit": 2, "offset": 0}).json()
    assert len(first_page["submissions"]) == 2
    assert first_page["pagination"]["total"] == 3
    assert first_page["pagination"]["has_next"] is True
    assert first_page["pagination"]["has_previous"] is False

    second_page = client.get("/analytics/grading", params={"limit": 2, "offset": 2}).json()
    assert len(second_page["submissions"]) == 1
    assert second_page["pagination"]["has_next"] is False
    assert second_page["pagination"]["has_previous"] is True


def test_cache_invalidates_after_grading_write(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, purchase_price_jpy=1000)

    first = client.get("/analytics/grading")
    assert first.headers["X-Cache"] == "MISS"
    second = client.get("/analytics/grading")
    assert second.headers["X-Cache"] == "HIT"

    response = client.post(
        "/grading/submissions",
        json={"collection_item_id": item.id, "grading_company": "PSA"},
    )
    assert response.status_code == 201, response.text

    third = client.get("/analytics/grading")
    assert third.headers["X-Cache"] == "MISS"
    assert third.json()["summary"]["total_submissions"] == 1
