import csv
import io
import sys

from app.models import Card, CollectionItem


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
    fields = dict(card_id=card.id, quantity=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def upload(client, csv_text: str, **params):
    return client.post(
        "/collection/import.csv",
        params=params,
        files={"file": ("collection.csv", csv_text.encode("utf-8"), "text/csv")},
    )


# --- export ---------------------------------------------------------------


def test_export_returns_valid_csv(client, db_session):
    card = make_card(db_session)
    make_item(
        db_session,
        card,
        quantity=2,
        condition_label="raw",
        purchase_price_jpy=1000,
        purchase_source="Yuyu-Tei",
        status="hold",
    )

    response = client.get("/collection/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "collection_export_" in response.headers["content-disposition"]
    assert response.headers["content-disposition"].endswith(".csv")

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1
    assert rows[0]["card_code"] == "OP01-001"
    assert rows[0]["quantity"] == "2"
    assert rows[0]["condition_label"] == "raw"
    assert rows[0]["purchase_price_jpy"] == "1000"


def test_export_includes_card_fields(client, db_session):
    card = make_card(db_session, name_en="Roronoa Zoro", set_code="OP02", rarity="SR")
    make_item(db_session, card)

    response = client.get("/collection/export.csv")

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["name_en"] == "Roronoa Zoro"
    assert rows[0]["set_code"] == "OP02"
    assert rows[0]["rarity"] == "SR"
    assert rows[0]["name_jp"] == "モンキー・D・ルフィ"


def test_export_blank_for_missing_values(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card, condition_label=None, purchase_price_jpy=None)

    response = client.get("/collection/export.csv")

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["condition_label"] == ""
    assert rows[0]["purchase_price_jpy"] == ""


# --- import: dry run / db writes ------------------------------------------


def test_import_dry_run_does_not_write_db(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,quantity\nOP01-001,3\n"

    response = upload(client, csv_text, dry_run=True, mode="append")

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["summary"]["valid_rows"] == 1
    assert body["summary"]["created"] == 0
    assert body["preview"][0]["action"] == "would_create"

    db_session.expire_all()
    assert db_session.query(CollectionItem).count() == 0


def test_import_defaults_to_dry_run(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,quantity\nOP01-001,3\n"

    response = upload(client, csv_text)

    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    db_session.expire_all()
    assert db_session.query(CollectionItem).count() == 0


def test_import_append_creates_rows(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,quantity\nOP01-001,3\nOP01-001,5\n"

    response = upload(client, csv_text, dry_run=False, mode="append")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["created"] == 2
    assert body["summary"]["updated"] == 0

    db_session.expire_all()
    items = db_session.query(CollectionItem).order_by(CollectionItem.id).all()
    assert len(items) == 2
    assert [i.quantity for i in items] == [3, 5]


def test_import_upsert_updates_existing_rows(client, db_session):
    card = make_card(db_session, card_code="OP01-001")
    existing = make_item(
        db_session, card, quantity=1, condition_label="raw", purchase_source="Yuyu-Tei"
    )
    csv_text = (
        "card_code,quantity,condition_label,purchase_source\n"
        "OP01-001,9,raw,Yuyu-Tei\n"
    )

    response = upload(client, csv_text, dry_run=False, mode="upsert")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["created"] == 0
    assert body["summary"]["updated"] == 1
    assert body["preview"][0]["action"] == "updated"

    db_session.expire_all()
    assert db_session.query(CollectionItem).count() == 1
    updated = db_session.get(CollectionItem, existing.id)
    assert updated.quantity == 9


def test_import_upsert_creates_when_no_match(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,quantity\nOP01-001,4\n"

    response = upload(client, csv_text, dry_run=False, mode="upsert")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["created"] == 1
    assert body["summary"]["updated"] == 0


def test_import_upsert_duplicate_rows_in_same_batch_update_each_other(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,quantity\nOP01-001,1\nOP01-001,2\n"

    response = upload(client, csv_text, dry_run=False, mode="upsert")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["created"] == 1
    assert body["summary"]["updated"] == 1

    db_session.expire_all()
    items = db_session.query(CollectionItem).all()
    assert len(items) == 1
    assert items[0].quantity == 2


# --- import: row-level validation errors ----------------------------------


def test_import_invalid_card_code_returns_row_error(client, db_session):
    csv_text = "card_code,quantity\nOP99-999,1\n"

    response = upload(client, csv_text, dry_run=True, mode="append")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert body["errors"][0]["card_code"] == "OP99-999"
    assert body["errors"][0]["error"] == "Card code not found"
    assert body["errors"][0]["row_number"] == 2


def test_import_invalid_quantity_returns_row_error(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,quantity\nOP01-001,0\n"

    response = upload(client, csv_text, dry_run=True, mode="append")

    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert "quantity" in body["errors"][0]["error"]


def test_import_invalid_status_returns_row_error(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,quantity,status\nOP01-001,1,bogus\n"

    response = upload(client, csv_text, dry_run=True, mode="append")

    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert "status" in body["errors"][0]["error"].lower()


def test_import_invalid_date_returns_row_error(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,quantity,purchase_date\nOP01-001,1,07/12/2026\n"

    response = upload(client, csv_text, dry_run=True, mode="append")

    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert "purchase_date" in body["errors"][0]["error"]


def test_import_negative_purchase_price_returns_row_error(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,quantity,purchase_price_jpy\nOP01-001,1,-5\n"

    response = upload(client, csv_text, dry_run=True, mode="append")

    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert "purchase_price_jpy" in body["errors"][0]["error"]


# --- import: optional/blank field handling ---------------------------------


def test_import_missing_optional_fields_allowed(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,quantity\nOP01-001,1\n"

    response = upload(client, csv_text, dry_run=False, mode="append")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["error_rows"] == 0
    assert body["preview"][0]["status"] == "hold"

    db_session.expire_all()
    item = db_session.query(CollectionItem).one()
    assert item.status == "hold"
    assert item.condition_label is None
    assert item.purchase_price_jpy is None


def test_import_blank_numeric_fields_treated_as_null(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = (
        "card_code,quantity,purchase_price_jpy,target_sell_price_jpy\n"
        "OP01-001,1,,\n"
    )

    response = upload(client, csv_text, dry_run=False, mode="append")

    assert response.status_code == 200
    assert response.json()["summary"]["error_rows"] == 0

    db_session.expire_all()
    item = db_session.query(CollectionItem).one()
    assert item.purchase_price_jpy is None
    assert item.target_sell_price_jpy is None


def test_import_invalid_mode_rejected(client, db_session):
    csv_text = "card_code,quantity\nOP01-001,1\n"

    response = upload(client, csv_text, mode="bogus")

    assert response.status_code == 400


def test_import_missing_required_columns_rejected(client, db_session):
    csv_text = "card_code\nOP01-001\n"

    response = upload(client, csv_text, dry_run=True, mode="append")

    assert response.status_code == 400


# --- CLI --------------------------------------------------------------


def test_cli_export_works(db_session, tmp_path, monkeypatch):
    from app import export_collection_csv as export_cli

    card = make_card(db_session)
    make_item(db_session, card, quantity=7)

    monkeypatch.setattr(export_cli, "SessionLocal", lambda: db_session)
    output_path = tmp_path / "out" / "collection.csv"
    monkeypatch.setattr(sys, "argv", ["export_collection_csv", "--output", str(output_path)])

    export_cli.main()

    assert output_path.exists()
    rows = list(csv.DictReader(output_path.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["card_code"] == "OP01-001"
    assert rows[0]["quantity"] == "7"


def test_cli_import_dry_run_works(db_session, tmp_path, monkeypatch, capsys):
    from app import import_collection_csv as import_cli

    make_card(db_session, card_code="OP01-001")
    csv_path = tmp_path / "collection.csv"
    csv_path.write_text("card_code,quantity\nOP01-001,4\n", encoding="utf-8")

    monkeypatch.setattr(import_cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        sys, "argv", ["import_collection_csv", str(csv_path), "--dry-run", "--mode", "append"]
    )

    import_cli.main()

    db_session.expire_all()
    assert db_session.query(CollectionItem).count() == 0

    captured = capsys.readouterr()
    assert "dry_run: True" in captured.out
    assert "created: 0" in captured.out
