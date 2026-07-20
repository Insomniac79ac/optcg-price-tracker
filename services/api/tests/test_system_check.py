from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.models import (
    Card,
    CollectionItem,
    GradingSubmission,
    JobLock,
    MarketSignalEvent,
    Source,
    SourceCardMapping,
    WishlistItem,
)
from app.models.snkrdunk_candidate import SnkrdunkCandidate
from app.services.job_locks import acquire_lock
from app.services.system_check import MIN_CANDIDATES_FOR_BACKLOG_CHECK


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


# --- job lock checks ---------------------------------------------------------


def test_system_check_active_job_locks_passes_with_no_locks(client, db_session):
    response = client.get("/admin/system-check")
    data = response.json()
    checks = checks_by_name(data)
    assert checks["active_job_locks"]["status"] == "pass"
    assert "0 active" in checks["active_job_locks"]["message"]
    assert checks["expired_job_locks"]["status"] == "pass"
    assert checks["market_workflow_lock_ttl"]["status"] == "pass"


def test_system_check_active_job_locks_counts_active_lock(client, db_session):
    acquire_lock("portfolio_snapshot", "portfolio_snapshot:a", 600)

    response = client.get("/admin/system-check")
    data = response.json()
    assert "1 active" in checks_by_name(data)["active_job_locks"]["message"]


def test_system_check_warns_on_expired_active_lock(client, db_session):
    acquire_lock("portfolio_snapshot", "portfolio_snapshot:a", ttl_seconds=1)
    db_session.execute(
        update(JobLock)
        .where(JobLock.lock_name == "portfolio_snapshot")
        .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        .execution_options(synchronize_session=False)
    )
    db_session.commit()

    response = client.get("/admin/system-check")
    data = response.json()
    check = checks_by_name(data)["expired_job_locks"]
    assert check["status"] == "warning"
    assert "portfolio_snapshot" in check["message"]


def test_system_check_warns_when_market_workflow_lock_past_ttl(client, db_session):
    acquire_lock("market_workflow", "market_workflow:a", ttl_seconds=1)
    db_session.execute(
        update(JobLock)
        .where(JobLock.lock_name == "market_workflow")
        .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        .execution_options(synchronize_session=False)
    )
    db_session.commit()

    response = client.get("/admin/system-check")
    data = response.json()
    check = checks_by_name(data)["market_workflow_lock_ttl"]
    assert check["status"] == "warning"
    assert "stuck" in check["message"]


def test_system_check_market_workflow_lock_ttl_passes_when_within_ttl(client, db_session):
    acquire_lock("market_workflow", "market_workflow:a", ttl_seconds=3600)

    response = client.get("/admin/system-check")
    data = response.json()
    check = checks_by_name(data)["market_workflow_lock_ttl"]
    assert check["status"] == "pass"
    assert "within its TTL" in check["message"]


def _make_candidates(db_session, count: int, match_status: str) -> None:
    for i in range(count):
        db_session.add(
            SnkrdunkCandidate(
                source_url=f"https://snkrdunk.com/trading-cards/{match_status}-{i}",
                title=f"listing {i}",
                match_status=match_status,
            )
        )
    db_session.commit()


def test_system_check_candidate_backlog_passes_below_sample_size(client, db_session):
    _make_candidates(db_session, MIN_CANDIDATES_FOR_BACKLOG_CHECK - 1, "unmatched")

    response = client.get("/admin/system-check")
    data = response.json()
    check = checks_by_name(data)["candidate_match_backlog"]
    assert check["status"] == "pass"
    assert "too few" in check["message"]


def test_system_check_candidate_backlog_warns_when_mostly_unresolved(client, db_session):
    _make_candidates(db_session, MIN_CANDIDATES_FOR_BACKLOG_CHECK, "unmatched")

    response = client.get("/admin/system-check")
    data = response.json()
    check = checks_by_name(data)["candidate_match_backlog"]
    assert check["status"] == "warning"


def test_system_check_candidate_backlog_passes_when_mostly_matched(client, db_session):
    matched_count = MIN_CANDIDATES_FOR_BACKLOG_CHECK
    _make_candidates(db_session, matched_count, "matched")
    _make_candidates(db_session, 1, "unmatched")

    response = client.get("/admin/system-check")
    data = response.json()
    check = checks_by_name(data)["candidate_match_backlog"]
    assert check["status"] == "pass"


def test_system_check_low_confidence_source_mappings(client, db_session):
    make_sources(db_session)
    card = make_card(db_session)
    source = db_session.query(Source).filter_by(name="yuyutei").one()
    db_session.add(
        SourceCardMapping(
            card_id=card.id,
            source_id=source.id,
            source_card_id=card.card_code,
            source_url="https://yuyu-tei.example.com/low-conf",
            match_confidence=0.3,
        )
    )
    db_session.commit()

    response = client.get("/admin/system-check")
    data = response.json()
    check = checks_by_name(data)["low_confidence_source_mappings"]
    assert check["status"] == "warning"
    assert "1 source_card_mappings" in check["message"]


def test_system_check_no_low_confidence_source_mappings_passes(client, db_session):
    response = client.get("/admin/system-check")
    data = response.json()
    check = checks_by_name(data)["low_confidence_source_mappings"]
    assert check["status"] == "pass"


def test_system_check_warns_on_critical_mapping_quality(client, db_session):
    make_sources(db_session)
    card = make_card(db_session)
    source = db_session.query(Source).filter_by(name="yuyutei").one()
    for i in range(2):
        db_session.add(
            SourceCardMapping(
                card_id=card.id,
                source_id=source.id,
                source_card_id=card.card_code,
                source_url=f"https://yuyu-tei.example.com/dup{'' if i == 0 else ' '}",
            )
        )
    db_session.commit()

    response = client.get("/admin/system-check")
    data = response.json()
    check = checks_by_name(data)["mapping_quality_summary"]
    assert check["status"] == "warning"
    assert "critical-risk mapping" in check["message"]


def test_system_check_mapping_quality_summary_passes_when_healthy(client, db_session):
    response = client.get("/admin/system-check")
    data = response.json()
    check = checks_by_name(data)["mapping_quality_summary"]
    assert check["status"] == "pass"
