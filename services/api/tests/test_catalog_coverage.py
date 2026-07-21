from datetime import datetime, timedelta, timezone

from app.models import CollectionItem, PriceObservation, WishlistItem
from app.services.catalog_coverage import (
    CatalogCoverageFilters,
    compute_catalog_coverage,
    summarize_catalog_coverage,
)
from tests.test_source_mappings import make_card, make_mapping, make_source

USER_ID = 1


def make_price(db_session, card, source, *, observed_at=None, price_jpy=1000, price_type="sell"):
    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=price_type,
        price_jpy=price_jpy,
        observed_at=observed_at or datetime.now(timezone.utc),
    )
    db_session.add(obs)
    db_session.commit()
    db_session.refresh(obs)
    return obs


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


# --- auth ----------------------------------------------------------------


def test_catalog_coverage_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    resp = TestClient(app).get("/admin/catalog-coverage")
    assert resp.status_code == 401


def test_catalog_coverage_gaps_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    resp = TestClient(app).get("/admin/catalog-coverage/gaps?gap_type=metadata")
    assert resp.status_code == 401


# --- empty catalog ---------------------------------------------------------


def test_empty_catalog_works(client, db_session):
    resp = client.get("/admin/catalog-coverage")
    assert resp.status_code == 200
    data = resp.json()
    summary = data["summary"]
    assert summary["total_cards"] == 0
    assert summary["mapping_coverage_pct"] == 0.0
    assert summary["recent_price_coverage_pct"] == 0.0
    assert summary["metadata_completion_pct"] == 0.0
    assert data["coverage_by_set"] == []
    assert data["metadata_gaps"] == []


def test_compute_catalog_coverage_empty_catalog(db_session):
    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    assert report.summary["total_cards"] == 0
    assert report.metadata_gaps == []
    assert report.duplicate_risks == []


# --- active/inactive -------------------------------------------------------


def test_active_inactive_counts(client, db_session):
    make_card(db_session, card_code="OP01-001", rarity="L")
    inactive = make_card(db_session, card_code="OP01-002", rarity="R")
    inactive.is_active = False
    inactive.merged_into_card_id = None
    db_session.commit()

    resp = client.get("/admin/catalog-coverage")
    data = resp.json()["summary"]
    assert data["total_cards"] == 1
    assert data["active_cards"] == 1
    assert data["inactive_merged_cards"] == 0


def test_include_inactive_includes_merged_cards(client, db_session):
    make_card(db_session, card_code="OP01-001", rarity="L")
    inactive = make_card(db_session, card_code="OP01-002", rarity="R")
    inactive.is_active = False
    db_session.commit()

    resp = client.get("/admin/catalog-coverage?include_inactive=true")
    data = resp.json()["summary"]
    assert data["total_cards"] == 2
    assert data["active_cards"] == 1
    assert data["inactive_merged_cards"] == 1


# --- mapping coverage -------------------------------------------------------


def test_mapping_coverage_calculation(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    mapped_both = make_card(db_session, card_code="OP01-001", rarity="L")
    mapped_one = make_card(db_session, card_code="OP01-002", rarity="R")
    unmapped = make_card(db_session, card_code="OP01-003", rarity="R", variant="alt")

    make_mapping(db_session, mapped_both, yuyutei)
    make_mapping(db_session, mapped_both, snkrdunk)
    make_mapping(db_session, mapped_one, yuyutei)

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    summary = report.summary
    assert summary["cards_with_yuyutei_mapping"] == 2
    assert summary["cards_with_snkrdunk_mapping"] == 1
    assert summary["cards_without_any_mapping"] == 1
    assert summary["mapping_coverage_pct"] == round(2 / 3 * 100, 2)

    gap_cards = {g.card_id for g in report.mapping_gaps}
    assert unmapped.id in gap_cards
    assert mapped_one.id in gap_cards
    assert mapped_both.id not in gap_cards

    unmapped_gap = next(g for g in report.mapping_gaps if g.card_id == unmapped.id)
    assert unmapped_gap.severity == "critical"
    partial_gap = next(g for g in report.mapping_gaps if g.card_id == mapped_one.id)
    assert partial_gap.severity == "warning"
    assert partial_gap.issue_types == ["missing_snkrdunk_mapping"]


def test_inactive_mapping_does_not_count_as_coverage(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session, card_code="OP01-001", rarity="L")
    make_mapping(db_session, card, yuyutei, is_active=False)

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    assert report.summary["cards_without_any_mapping"] == 1


# --- recent price coverage --------------------------------------------------


def test_recent_yuyutei_price_coverage(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    fresh = make_card(db_session, card_code="OP01-001", rarity="L")
    stale = make_card(db_session, card_code="OP01-002", rarity="R")

    now = datetime.now(timezone.utc)
    make_price(db_session, fresh, yuyutei, observed_at=now - timedelta(hours=1))
    make_price(db_session, stale, yuyutei, observed_at=now - timedelta(hours=25))

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    summary = report.summary
    assert summary["cards_with_recent_yuyutei_price"] == 1
    assert summary["cards_without_recent_price"] == 1  # stale has no recent price from either source

    stale_gap = next(g for g in report.price_gaps if g.card_id == stale.id)
    assert "missing_recent_yuyutei_price" in stale_gap.issue_types


def test_recent_snkrdunk_price_coverage(db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    fresh = make_card(db_session, card_code="OP01-001", rarity="L")
    stale = make_card(db_session, card_code="OP01-002", rarity="R")

    now = datetime.now(timezone.utc)
    make_price(db_session, fresh, snkrdunk, observed_at=now - timedelta(days=1))
    make_price(db_session, stale, snkrdunk, observed_at=now - timedelta(days=8))

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    summary = report.summary
    assert summary["cards_with_recent_snkrdunk_price"] == 1
    assert summary["cards_without_recent_price"] == 1


# --- metadata completion ----------------------------------------------------


def test_metadata_completion_calculation(db_session):
    complete = make_card(
        db_session,
        card_code="OP01-001",
        rarity="L",
        name_en="Complete Card",
        image_url="https://example.com/img.png",
        artist="Artist",
        character="Char",
        color="Red",
        card_type="Leader",
    )
    incomplete = make_card(db_session, card_code="OP01-002", rarity="R", name_en=None)

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    summary = report.summary
    assert summary["cards_with_missing_metadata"] == 1
    assert summary["metadata_completion_pct"] == 50.0

    gap = next(g for g in report.metadata_gaps if g.card_id == incomplete.id)
    assert gap.severity == "critical"
    assert "missing_name_en" in gap.issue_types
    assert complete.id not in {g.card_id for g in report.metadata_gaps}


# --- collection / wishlist coverage -----------------------------------------


def test_collection_and_wishlist_coverage_counts(db_session):
    in_collection = make_card(db_session, card_code="OP01-001", rarity="L")
    on_wishlist = make_card(db_session, card_code="OP01-002", rarity="R")
    neither = make_card(db_session, card_code="OP01-003", rarity="R", variant="alt")

    make_collection_item(db_session, in_collection)
    make_wishlist_item(db_session, on_wishlist)

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    summary = report.summary
    assert summary["total_cards"] == 3
    assert summary["cards_in_collection"] == 1
    assert summary["cards_on_wishlist"] == 1
    assert neither.card_code == "OP01-003"


# --- breakdowns --------------------------------------------------------------


def test_coverage_by_set(db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L")
    make_card(db_session, card_code="OP02-001", set_code="OP02", rarity="L")

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    keys = {i.key for i in report.coverage_by_set}
    assert keys == {"OP01", "OP02"}
    for item in report.coverage_by_set:
        assert item.total_cards == 1


def test_coverage_by_rarity(db_session):
    make_card(db_session, card_code="OP01-001", rarity="L")
    make_card(db_session, card_code="OP01-002", rarity="R")
    make_card(db_session, card_code="OP01-003", rarity="R", variant="alt")

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    by_rarity = {i.key: i.total_cards for i in report.coverage_by_rarity}
    assert by_rarity == {"L": 1, "R": 2}


# --- gaps endpoint -----------------------------------------------------------


def test_metadata_gaps_endpoint(client, db_session):
    make_card(db_session, card_code="OP01-001", rarity="L", name_en=None)
    resp = client.get("/admin/catalog-coverage/gaps?gap_type=metadata")
    assert resp.status_code == 200
    data = resp.json()
    assert data["gap_type"] == "metadata"
    assert len(data["items"]) == 1
    assert data["pagination"]["total"] == 1


def test_mapping_gaps_endpoint(client, db_session):
    make_card(db_session, card_code="OP01-001", rarity="L")
    resp = client.get("/admin/catalog-coverage/gaps?gap_type=mapping")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["severity"] == "critical"


def test_price_gaps_endpoint(client, db_session):
    make_card(db_session, card_code="OP01-001", rarity="L")
    resp = client.get("/admin/catalog-coverage/gaps?gap_type=price")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1


def test_duplicate_risks_endpoint(client, db_session):
    make_card(db_session, card_code="OP01-001", rarity="L", name_en="Luffy")
    make_card(db_session, card_code="OP01-001", rarity="R", name_en="Luffy")

    resp = client.get("/admin/catalog-coverage/gaps?gap_type=duplicate")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 1
    assert data["items"][0]["suggested_action"] == "review_card_merge"


def test_mapping_quality_risks_endpoint(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session, card_code="OP01-001", rarity="L")
    # source_card_id that clearly mismatches card_code -> critical risk mapping
    make_mapping(db_session, card, yuyutei, source_card_id="OP99-999")

    resp = client.get("/admin/catalog-coverage/gaps?gap_type=mapping_quality")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["card_id"] == card.id


def test_gaps_endpoint_invalid_gap_type(client, db_session):
    resp = client.get("/admin/catalog-coverage/gaps?gap_type=bogus")
    assert resp.status_code == 400


def test_gaps_endpoint_pagination(client, db_session):
    for i in range(3):
        make_card(db_session, card_code=f"OP01-00{i}", rarity="L", variant=f"v{i}")

    resp = client.get("/admin/catalog-coverage/gaps?gap_type=mapping&limit=2&offset=0")
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["pagination"]["total"] == 3
    assert data["pagination"]["has_next"] is True


# --- CLI -----------------------------------------------------------------


def test_cli_prints_summary(db_session, monkeypatch, capsys):
    make_card(db_session, card_code="OP01-001", rarity="L")

    import sys

    from app import catalog_coverage_report as cli_module

    monkeypatch.setattr(cli_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    old_argv = sys.argv
    sys.argv = ["catalog_coverage_report"]
    try:
        try:
            cli_module.main()
        except SystemExit as exc:
            assert exc.code == 0
    finally:
        sys.argv = old_argv

    captured = capsys.readouterr()
    assert "total_cards" in captured.out


# --- system check integration ----------------------------------------------


def test_system_check_includes_catalog_coverage(client, db_session):
    resp = client.get("/admin/system-check")
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["checks"]}
    assert "catalog_coverage_summary" in names


def test_system_check_warns_on_low_mapping_coverage(client, db_session):
    make_card(db_session, card_code="OP01-001", rarity="L")
    resp = client.get("/admin/system-check")
    checks = {c["name"]: c for c in resp.json()["checks"]}
    assert checks["catalog_coverage_summary"]["status"] == "warning"


# --- card audit integration -------------------------------------------------


def test_card_audit_includes_catalog_coverage_summary(client, db_session):
    make_card(db_session, card_code="OP01-001", rarity="L")
    resp = client.get("/admin/card-audit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["catalog_coverage"] is not None
    assert data["catalog_coverage"]["total_cards"] == 1


def test_summarize_catalog_coverage_matches_full_report(db_session):
    make_card(db_session, card_code="OP01-001", rarity="L")
    full = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    summary_only = summarize_catalog_coverage(db_session)
    assert summary_only == full.summary
