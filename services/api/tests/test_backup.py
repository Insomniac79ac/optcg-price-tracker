import json
import sys
from datetime import datetime, timezone

import pytest

from app.models import (
    AlertRule,
    Card,
    CollectionItem,
    CollectionItemGroup,
    CollectionItemTag,
    CollectorActivityEvent,
    CollectorGroup,
    CollectorNote,
    CollectorTag,
    GradingSubmission,
    MarketReportDigestSend,
    MarketWorkflowRun,
    PortfolioValuationSnapshot,
    SearchHistory,
    Source,
    SourceCardMapping,
    WishlistItem,
)
from app.services.backup import BACKUP_VERSION, OPTIONAL_TABLES, REQUIRED_TABLES, export_backup
from app.services.job_locks import acquire_lock
from app.services.market_report import generate_market_report

# --- factories --------------------------------------------------------------


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
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def make_mapping(db_session, card: Card, source: Source, **overrides) -> SourceCardMapping:
    fields = dict(card_id=card.id, source_id=source.id, source_card_id=card.card_code)
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(mapping)
    return mapping


def make_item(db_session, card: Card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def make_alert_rule(db_session, **overrides) -> AlertRule:
    fields = dict(name="rule-1", rule_type="price_change_pct", threshold_pct=10.0)
    fields.update(overrides)
    rule = AlertRule(**fields)
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)
    return rule


def make_snapshot(db_session, **overrides) -> PortfolioValuationSnapshot:
    fields = dict(
        total_items=0,
        total_quantity=0,
        items_missing_yuyutei_sell=0,
        items_missing_yuyutei_buy=0,
        items_missing_snkrdunk_floor=0,
        items_missing_cost_basis=0,
        cards_above_target_sell=0,
    )
    fields.update(overrides)
    snapshot = PortfolioValuationSnapshot(**fields)
    db_session.add(snapshot)
    db_session.commit()
    db_session.refresh(snapshot)
    return snapshot


def make_digest_send(db_session, report_id: int, **overrides) -> MarketReportDigestSend:
    fields = dict(report_id=report_id, destination="telegram", status="sent")
    fields.update(overrides)
    send = MarketReportDigestSend(**fields)
    db_session.add(send)
    db_session.commit()
    db_session.refresh(send)
    return send


def make_workflow_run(db_session, **overrides) -> MarketWorkflowRun:
    fields = dict(
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        status="success",
        source="yuyutei",
        limit=10,
        send_telegram=False,
        signal_events_created=0,
        signal_events_updated=0,
        signal_events_resolved=0,
        warnings_json=[],
    )
    fields.update(overrides)
    run = MarketWorkflowRun(**fields)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def upload_validate(client, backup: dict):
    payload = json.dumps(backup).encode("utf-8")
    return client.post(
        "/admin/backup/validate",
        files={"file": ("backup.json", payload, "application/json")},
    )


def upload_restore(client, backup: dict, **params):
    payload = json.dumps(backup).encode("utf-8")
    return client.post(
        "/admin/backup/restore",
        params=params,
        files={"file": ("backup.json", payload, "application/json")},
    )


def empty_backup(**table_overrides) -> dict:
    tables = {t: [] for t in REQUIRED_TABLES}
    tables.update(table_overrides)
    return {
        "metadata": {
            "app": "opcg-price-tracker",
            "backup_version": BACKUP_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "include_prices": False,
            "include_raw_snapshots": False,
            "include_refresh_runs": False,
        },
        "tables": tables,
    }


# --- export -------------------------------------------------------------


def test_export_backup_returns_json(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card)

    response = client.get("/admin/backup/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "opcg_backup_" in response.headers["content-disposition"]

    body = response.json()
    assert body["metadata"]["app"] == "opcg-price-tracker"
    assert body["metadata"]["backup_version"] == BACKUP_VERSION
    for table in REQUIRED_TABLES:
        assert table in body["tables"]
    assert len(body["tables"]["cards"]) == 1
    assert body["tables"]["cards"][0]["card_code"] == "OP01-001"
    assert len(body["tables"]["collection_items"]) == 1


def test_export_excludes_prices_by_default(client, db_session):
    response = client.get("/admin/backup/export")

    body = response.json()
    for table in OPTIONAL_TABLES:
        assert table not in body["tables"]
    assert body["metadata"]["include_prices"] is False


def test_export_includes_prices_when_requested(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    from app.models import PriceObservation

    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type="sell",
        price_jpy=1000,
        observed_at=datetime.now(timezone.utc),
    )
    db_session.add(obs)
    db_session.commit()

    response = client.get(
        "/admin/backup/export",
        params={"include_prices": "true"},
    )

    body = response.json()
    assert "price_observations" in body["tables"]
    assert body["metadata"]["include_prices"] is True
    assert len(body["tables"]["price_observations"]) == 1
    assert "raw_snapshots" not in body["tables"]


def test_export_excludes_logs_by_default(client, db_session):
    from app.services.app_logging import record_app_log

    record_app_log("info", "api", "startup", "test log row")

    response = client.get("/admin/backup/export")

    body = response.json()
    assert "app_log_events" not in body["tables"]
    assert body["metadata"]["include_logs"] is False


def test_export_includes_logs_when_requested(client, db_session):
    from app.services.app_logging import record_app_log

    record_app_log("info", "api", "startup", "test log row")

    response = client.get("/admin/backup/export", params={"include_logs": "true"})

    body = response.json()
    assert body["metadata"]["include_logs"] is True
    assert "app_log_events" in body["tables"]
    assert len(body["tables"]["app_log_events"]) == 1


def test_export_includes_all_required_tables_with_data(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    make_mapping(db_session, card, source)
    make_item(db_session, card)
    make_alert_rule(db_session)
    make_snapshot(db_session)
    report = generate_market_report(db_session)
    make_digest_send(db_session, report.id)
    make_workflow_run(db_session, market_report_id=report.id)
    db_session.add(WishlistItem(user_id=1, card_id=card.id))
    db_session.commit()
    client.get("/dashboard/preferences")  # JIT-creates the main_dashboard row

    response = client.get("/admin/backup/export")

    body = response.json()
    assert len(body["tables"]["cards"]) == 1
    assert len(body["tables"]["sources"]) == 1
    assert len(body["tables"]["source_card_mappings"]) == 1
    assert len(body["tables"]["collection_items"]) == 1
    assert len(body["tables"]["alert_rules"]) == 1
    assert len(body["tables"]["portfolio_valuation_snapshots"]) == 1
    assert len(body["tables"]["market_intelligence_reports"]) == 1
    assert len(body["tables"]["market_report_digest_sends"]) == 1
    assert len(body["tables"]["market_workflow_runs"]) == 1
    assert len(body["tables"]["wishlist_items"]) == 1
    assert len(body["tables"]["dashboard_preferences"]) == 1


def test_backup_export_includes_phase5_tables(client, db_session):
    """Phase 5 added collector_tags/groups, grading_submissions,
    wishlist_items, dashboard_preferences, collector_notes,
    collector_activity_events, and search_history - all of them must be
    covered by backup/restore, not just the tables that existed when
    BACKUP_VERSION was first introduced."""
    card = make_card(db_session)
    item = make_item(db_session, card)

    tag = CollectorTag(user_id=1, name="Chase", slug="chase")
    group = CollectorGroup(user_id=1, name="Binder 1", slug="binder-1")
    db_session.add_all([tag, group])
    db_session.commit()
    db_session.add(CollectionItemTag(collection_item_id=item.id, tag_id=tag.id))
    db_session.add(CollectionItemGroup(collection_item_id=item.id, group_id=group.id))
    db_session.add(
        GradingSubmission(collection_item_id=item.id, grading_company="PSA")
    )
    db_session.add(
        CollectorNote(note_type="card", card_id=card.id, body="Watching this one")
    )
    db_session.add(
        CollectorActivityEvent(
            event_type="collection_item_added",
            event_source="collection",
            card_id=card.id,
            title="Added to collection",
        )
    )
    db_session.add(SearchHistory(query="OP01-001", result_count=1))
    db_session.commit()
    client.get("/dashboard/preferences")  # JIT-creates the main_dashboard row

    response = client.get("/admin/backup/export")
    assert response.status_code == 200
    tables = response.json()["tables"]

    assert len(tables["collector_tags"]) == 1
    assert len(tables["collector_groups"]) == 1
    assert len(tables["collection_item_tags"]) == 1
    assert len(tables["collection_item_groups"]) == 1
    assert len(tables["grading_submissions"]) == 1
    assert len(tables["dashboard_preferences"]) == 1
    assert len(tables["collector_notes"]) == 1
    assert len(tables["collector_activity_events"]) == 1
    assert len(tables["search_history"]) == 1


def test_backup_export_includes_card_merge_fields_and_aliases(client, db_session):
    from app.services.card_identity_merge import MergeOptions, execute_card_merge

    card_a = make_card(db_session, card_code="OP01-001", rarity="L")
    card_b = make_card(db_session, card_code="OP01-001", rarity="SR", name_en="dup")
    execute_card_merge(db_session, card_b.id, card_a.id, MergeOptions(dry_run=False))

    response = client.get("/admin/backup/export")
    assert response.status_code == 200
    tables = response.json()["tables"]

    merged_row = next(r for r in tables["cards"] if r["id"] == card_b.id)
    assert merged_row["is_active"] is False
    assert merged_row["merged_into_card_id"] == card_a.id
    assert merged_row["merged_at"] is not None

    assert len(tables["card_aliases"]) >= 1
    assert tables["card_aliases"][0]["card_id"] == card_a.id


def test_backup_export_includes_wishlist_items(client, db_session):
    card = make_card(db_session)
    db_session.add(WishlistItem(user_id=1, card_id=card.id, priority="grail"))
    db_session.commit()

    response = client.get("/admin/backup/export")

    assert response.status_code == 200
    body = response.json()
    assert "wishlist_items" in body["tables"]
    assert len(body["tables"]["wishlist_items"]) == 1
    assert body["tables"]["wishlist_items"][0]["priority"] == "grail"


def test_backup_export_includes_dashboard_preferences(client, db_session):
    client.get("/dashboard/preferences")  # JIT-creates the main_dashboard row

    response = client.get("/admin/backup/export")

    assert response.status_code == 200
    body = response.json()
    assert "dashboard_preferences" in body["tables"]
    assert len(body["tables"]["dashboard_preferences"]) == 1
    assert body["tables"]["dashboard_preferences"][0]["preference_key"] == "main_dashboard"


def test_export_requires_admin_token():
    from fastapi.testclient import TestClient

    from app.main import app

    unauth_client = TestClient(app)
    response = unauth_client.get("/admin/backup/export")
    assert response.status_code == 401


def test_validate_requires_admin_token():
    from fastapi.testclient import TestClient

    from app.main import app

    unauth_client = TestClient(app)
    response = upload_validate(unauth_client, empty_backup())
    assert response.status_code == 401


def test_restore_requires_admin_token():
    from fastapi.testclient import TestClient

    from app.main import app

    unauth_client = TestClient(app)
    response = upload_restore(unauth_client, empty_backup(), dry_run=True, mode="merge")
    assert response.status_code == 401


# --- validate -------------------------------------------------------------


def test_validate_valid_backup(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    backup = export_backup(db_session)
    # sanity: our own export should always validate clean
    response = upload_validate(client, backup)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["backup_version"] == BACKUP_VERSION
    assert body["summary"]["cards"] == 1
    assert body["summary"]["collection_items"] == 1
    assert body["errors"] == []
    assert item.id  # keep item referenced


def test_validate_missing_metadata_fails(client):
    backup = {"tables": {t: [] for t in REQUIRED_TABLES}}
    response = upload_validate(client, backup)

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any("metadata" in e for e in body["errors"])


def test_validate_missing_required_table_fails(client):
    backup = empty_backup()
    del backup["tables"]["alert_rules"]

    response = upload_validate(client, backup)

    body = response.json()
    assert body["valid"] is False
    assert any("alert_rules" in e for e in body["errors"])


def test_validate_fk_mismatch_fails(client):
    backup = empty_backup(
        cards=[],
        collection_items=[
            {"id": 1, "card_id": 999, "quantity": 1, "status": "hold"}
        ],
    )

    response = upload_validate(client, backup)

    body = response.json()
    assert body["valid"] is False
    assert any("card_id 999" in e for e in body["errors"])


def test_validate_source_card_mapping_fk_mismatch_fails(client):
    backup = empty_backup(
        cards=[{"id": 1, "card_code": "OP01-001", "set_code": "OP01", "rarity": "L", "language": "en"}],
        sources=[],
        source_card_mappings=[
            {"id": 1, "card_id": 1, "source_id": 5, "source_card_id": "OP01-001"}
        ],
    )

    response = upload_validate(client, backup)

    body = response.json()
    assert body["valid"] is False
    assert any("source_id 5" in e for e in body["errors"])


# --- restore: dry run -------------------------------------------------------


def test_restore_returns_409_when_lock_held(client, db_session):
    acquire_lock("backup_restore", "backup_restore:other", 3600)
    backup = empty_backup()

    response = upload_restore(client, backup, dry_run="true", mode="merge")

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "Job already running"
    assert body["lock_name"] == "backup_restore"


def test_restore_dry_run_writes_nothing(client, db_session):
    backup = empty_backup(
        cards=[
            {
                "id": 1,
                "card_code": "OP01-001",
                "name_en": None,
                "name_jp": None,
                "set_code": "OP01",
                "rarity": "L",
                "variant": None,
                "language": "en",
                "image_url": None,
            }
        ]
    )

    response = upload_restore(client, backup, dry_run="true", mode="merge")

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["valid"] is True
    assert body["preview"]["cards"]["would_create"] == 1
    assert body["summary"]["created"] == {}

    db_session.expire_all()
    assert db_session.query(Card).count() == 0


# --- restore: merge ----------------------------------------------------------


def test_restore_merge_creates_and_updates_rows(client, db_session):
    existing_card = make_card(db_session, card_code="OP01-001", name_en="Old Name")
    existing_item = make_item(db_session, existing_card, quantity=1)

    backup = empty_backup(
        cards=[
            {
                "id": existing_card.id,
                "card_code": "OP01-001",
                "name_en": "Updated Name",
                "name_jp": None,
                "set_code": "OP01",
                "rarity": "L",
                "variant": "leader",
                "language": "en",
                "image_url": None,
            },
            {
                "id": existing_card.id + 100,
                "card_code": "OP01-002",
                "name_en": "New Card",
                "name_jp": None,
                "set_code": "OP01",
                "rarity": "C",
                "variant": None,
                "language": "en",
                "image_url": None,
            },
        ],
        collection_items=[
            {
                "id": existing_item.id,
                "card_id": existing_card.id,
                "quantity": 9,
                "condition_label": None,
                "purchase_price_jpy": None,
                "purchase_date": None,
                "purchase_source": None,
                "target_sell_price_jpy": None,
                "notes": None,
                "status": "hold",
            }
        ],
    )

    response = upload_restore(client, backup, dry_run="false", mode="merge")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["summary"]["created"]["cards"] == 1
    assert body["summary"]["updated"]["cards"] == 1
    assert body["summary"]["updated"]["collection_items"] == 1

    db_session.expire_all()
    assert db_session.query(Card).count() == 2
    updated_card = db_session.get(Card, existing_card.id)
    assert updated_card.name_en == "Updated Name"
    updated_item = db_session.get(CollectionItem, existing_item.id)
    assert updated_item.quantity == 9


def test_restore_merge_does_not_delete_rows_missing_from_backup(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card)
    make_item(db_session, card, quantity=2)

    backup = empty_backup(
        cards=[
            {
                "id": card.id,
                "card_code": card.card_code,
                "name_en": card.name_en,
                "name_jp": card.name_jp,
                "set_code": card.set_code,
                "rarity": card.rarity,
                "variant": card.variant,
                "language": card.language,
                "image_url": None,
            }
        ],
        collection_items=[],
    )

    response = upload_restore(client, backup, dry_run="false", mode="merge")

    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.query(CollectionItem).count() == 2


def test_restore_merge_handles_self_referential_merged_into_card_id(client, db_session):
    """cards.merged_into_card_id is self-referential - the row referencing
    the higher id is deliberately listed FIRST here, the scenario that would
    violate the FK at insert time without backup.py's deferred-self-ref
    handling (see _defer_self_referential_fk)."""
    backup = empty_backup(
        cards=[
            {
                "id": 501,
                "card_code": "OP01-001",
                "name_en": "Duplicate",
                "name_jp": None,
                "set_code": "OP01",
                "rarity": "SR",
                "variant": "leader",
                "language": "en",
                "image_url": None,
                "is_active": False,
                "merged_into_card_id": 502,
                "merged_at": datetime.now(timezone.utc).isoformat(),
                "merge_notes": "test",
            },
            {
                "id": 502,
                "card_code": "OP01-001",
                "name_en": "Canonical",
                "name_jp": None,
                "set_code": "OP01",
                "rarity": "L",
                "variant": "leader",
                "language": "en",
                "image_url": None,
            },
        ]
    )

    response = upload_restore(client, backup, dry_run="false", mode="merge")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True

    db_session.expire_all()
    merged = db_session.get(Card, 501)
    assert merged.merged_into_card_id == 502
    assert merged.is_active is False


# --- restore: replace --------------------------------------------------------


def test_restore_replace_requires_confirm(client, db_session):
    backup = empty_backup()

    response = upload_restore(client, backup, dry_run="false", mode="replace")

    assert response.status_code == 400


def test_restore_replace_dry_run_does_not_require_confirm(client, db_session):
    backup = empty_backup()

    response = upload_restore(client, backup, dry_run="true", mode="replace")

    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_restore_replace_deletes_existing_included_rows(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card)

    new_card_row = {
        "id": 500,
        "card_code": "OP02-001",
        "name_en": "Replacement Card",
        "name_jp": None,
        "set_code": "OP02",
        "rarity": "R",
        "variant": None,
        "language": "en",
        "image_url": None,
    }
    backup = empty_backup(cards=[new_card_row], collection_items=[])

    response = upload_restore(
        client, backup, dry_run="false", mode="replace", confirm="RESTORE"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["summary"]["deleted"]["collection_items"] == 1
    assert body["summary"]["deleted"]["cards"] == 1
    assert body["summary"]["created"]["cards"] == 1

    db_session.expire_all()
    cards = db_session.query(Card).all()
    assert len(cards) == 1
    assert cards[0].card_code == "OP02-001"
    assert db_session.query(CollectionItem).count() == 0


def test_restore_replace_wrong_confirm_rejected(client, db_session):
    backup = empty_backup()

    response = upload_restore(
        client, backup, dry_run="false", mode="replace", confirm="nope"
    )

    assert response.status_code == 400


# --- restore: rollback on failure -------------------------------------------


def test_restore_rollback_on_failure(client, db_session):
    # Two sources sharing the same unique `name` - passes our FK validation
    # (validate_backup doesn't check uniqueness) but fails at the DB layer,
    # so the whole restore must roll back rather than leave a partial write.
    backup = empty_backup(
        sources=[
            {"id": 1, "name": "yuyutei", "base_url": "https://a.example.com"},
            {"id": 2, "name": "yuyutei", "base_url": "https://b.example.com"},
        ]
    )

    response = upload_restore(client, backup, dry_run="false", mode="merge")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert len(body["errors"]) == 1

    db_session.expire_all()
    assert db_session.query(Source).count() == 0


def test_restore_invalid_backup_writes_nothing(client, db_session):
    backup = {"tables": {}}

    response = upload_restore(client, backup, dry_run="false", mode="merge")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["summary"]["created"] == {}


def test_restore_invalid_mode_rejected(client, db_session):
    backup = empty_backup()

    response = upload_restore(client, backup, mode="bogus")

    assert response.status_code == 400


# --- CLI ---------------------------------------------------------------


def test_cli_export_works(db_session, tmp_path, monkeypatch):
    from app import export_backup as export_cli

    card = make_card(db_session)
    make_item(db_session, card)

    monkeypatch.setattr(export_cli, "SessionLocal", lambda: db_session)
    output_path = tmp_path / "out" / "backup.json"
    monkeypatch.setattr(sys, "argv", ["export_backup", "--output", str(output_path)])

    export_cli.main()

    assert output_path.exists()
    data = json.loads(output_path.read_text())
    assert data["metadata"]["backup_version"] == BACKUP_VERSION
    assert len(data["tables"]["cards"]) == 1


def test_cli_validate_works(tmp_path):
    from app import validate_backup as validate_cli

    backup_path = tmp_path / "backup.json"
    backup_path.write_text(json.dumps(empty_backup()))

    monkeypatch_argv = ["validate_backup", str(backup_path)]
    sys.argv = monkeypatch_argv
    with pytest.raises(SystemExit) as exc_info:
        validate_cli.main()

    assert exc_info.value.code == 0


def test_cli_restore_dry_run_works(db_session, tmp_path, monkeypatch, capsys):
    from app import restore_backup as restore_cli

    card = make_card(db_session)
    backup = empty_backup(
        cards=[
            {
                "id": card.id,
                "card_code": card.card_code,
                "name_en": card.name_en,
                "name_jp": card.name_jp,
                "set_code": card.set_code,
                "rarity": card.rarity,
                "variant": card.variant,
                "language": card.language,
                "image_url": None,
            }
        ]
    )
    backup_path = tmp_path / "backup.json"
    backup_path.write_text(json.dumps(backup))

    monkeypatch.setattr(restore_cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        sys, "argv", ["restore_backup", str(backup_path), "--dry-run", "--mode", "merge"]
    )

    with pytest.raises(SystemExit) as exc_info:
        restore_cli.main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "dry_run: True" in captured.out
