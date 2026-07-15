from datetime import datetime, timezone

from app.models import (
    Card,
    CollectionItem,
    GradingSubmission,
    MarketSignalEvent,
    Source,
    SourceCardMapping,
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


def make_sources(db_session) -> None:
    db_session.add(Source(name="yuyutei", base_url="https://yuyu-tei.example.com"))
    db_session.add(Source(name="snkrdunk", base_url="https://snkrdunk.example.com"))
    db_session.commit()


def checks_by_name(data: dict) -> dict:
    return {c["name"]: c for c in data["checks"]}


def test_system_check_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/system-check")
    assert response.status_code == 401


def test_system_check_works_on_empty_db(client, db_session):
    response = client.get("/admin/system-check")
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["checks_total"] == len(data["checks"])
    assert data["summary"]["checks_total"] > 0
    assert data["status"] in ("ok", "warning", "critical")

    checks = checks_by_name(data)
    assert checks["database_reachable"]["status"] == "pass"
    assert checks["required_sources"]["status"] == "fail"  # no sources seeded
    assert checks["cards_count"]["message"].endswith("0 row(s).")
    assert checks["search_responds"]["status"] == "pass"
    assert checks["backup_tables_included"]["status"] == "pass"


def test_system_check_passes_required_sources_when_present(client, db_session):
    make_sources(db_session)
    response = client.get("/admin/system-check")
    data = response.json()
    assert checks_by_name(data)["required_sources"]["status"] == "pass"


def test_system_check_reports_table_counts(client, db_session):
    card = make_card(db_session)
    db_session.add(CollectionItem(user_id=1, card_id=card.id, quantity=3))
    db_session.commit()

    response = client.get("/admin/system-check")
    data = response.json()
    checks = checks_by_name(data)
    assert "1 row(s)" in checks["collection_items_count"]["message"]


def test_system_check_detects_orphan_collection_item_card_id(client, db_session):
    db_session.execute(
        CollectionItem.__table__.insert().values(
            user_id=1, card_id=999999, quantity=1, status="hold"
        )
    )
    db_session.commit()

    response = client.get("/admin/system-check")
    data = response.json()
    check = checks_by_name(data)["collection_items_valid_card_id"]
    assert check["status"] == "fail"
    assert check["severity"] == "critical"
    assert data["status"] == "critical"
    assert data["summary"]["critical"] >= 1


def test_system_check_detects_orphan_wishlist_item_card_id(client, db_session):
    db_session.execute(
        WishlistItem.__table__.insert().values(
            user_id=1, card_id=999999, priority="medium", status="watching"
        )
    )
    db_session.commit()

    response = client.get("/admin/system-check")
    data = response.json()
    assert checks_by_name(data)["wishlist_items_valid_card_id"]["status"] == "fail"


def test_system_check_detects_orphan_source_card_mapping_card_id(client, db_session):
    make_sources(db_session)
    source = db_session.query(Source).filter_by(name="yuyutei").one()
    db_session.execute(
        SourceCardMapping.__table__.insert().values(
            card_id=999999,
            source_id=source.id,
            source_card_id="abc123",
            is_active=True,
            review_status="approved",
        )
    )
    db_session.commit()

    response = client.get("/admin/system-check")
    data = response.json()
    assert checks_by_name(data)["source_mappings_valid_card_id"]["status"] == "fail"


def test_system_check_detects_orphan_grading_submission_collection_item_id(client, db_session):
    db_session.execute(
        GradingSubmission.__table__.insert().values(
            collection_item_id=999999,
            grading_company="PSA",
            submission_status="planned",
        )
    )
    db_session.commit()

    response = client.get("/admin/system-check")
    data = response.json()
    assert checks_by_name(data)["grading_submissions_valid_collection_item_id"]["status"] == "fail"


def test_system_check_detects_orphan_market_signal_event_card_id(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.execute(
        MarketSignalEvent.__table__.insert().values(
            signal_type="price_up_7d",
            dedupe_key="orphan-dedupe-1",
            card_id=999999,
            status="open",
            severity="info",
            first_seen_at=now,
            last_seen_at=now,
            seen_count=1,
        )
    )
    db_session.commit()

    response = client.get("/admin/system-check")
    data = response.json()
    assert checks_by_name(data)["market_signal_events_valid_card_id"]["status"] == "fail"


def test_system_check_ignores_null_market_signal_event_card_id(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.execute(
        MarketSignalEvent.__table__.insert().values(
            signal_type="review_mapping",
            dedupe_key="null-card-dedupe-1",
            card_id=None,
            status="open",
            severity="info",
            first_seen_at=now,
            last_seen_at=now,
            seen_count=1,
        )
    )
    db_session.commit()

    response = client.get("/admin/system-check")
    data = response.json()
    assert checks_by_name(data)["market_signal_events_valid_card_id"]["status"] == "pass"
