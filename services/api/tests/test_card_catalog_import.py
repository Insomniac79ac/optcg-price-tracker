import csv
import io

from fastapi.testclient import TestClient

from app.main import app
from app.models import Card
from app.services.backup import export_backup
from app.services.card_catalog_import import import_cards_csv


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant=None,
        language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def csv_text(rows: list[dict[str, str]]) -> str:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def upload(client, rows: list[dict[str, str]], **params):
    return client.post(
        "/admin/cards/import.csv",
        params=params,
        files={"file": ("cards.csv", csv_text(rows).encode("utf-8"), "text/csv")},
    )


# --- import: dry-run / create / update --------------------------------------


def test_import_dry_run_does_not_write(client, db_session):
    rows = [{"card_code": "OP01-001", "name_en": "Monkey D. Luffy"}]

    response = upload(client, rows, dry_run="true")

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["summary"]["created"] == 1
    assert body["preview"][0]["action"] == "would_create"
    assert db_session.query(Card).count() == 0


def test_import_creates_new_cards(client, db_session):
    rows = [{"card_code": "OP01-001", "name_en": "Monkey D. Luffy", "rarity": "L"}]

    response = upload(client, rows, dry_run="false")

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is False
    assert body["summary"]["created"] == 1
    assert body["preview"][0]["action"] == "create"

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    assert card.name_en == "Monkey D. Luffy"
    assert card.set_code == "OP01"
    assert card.rarity == "L"
    assert card.language == "jp"


def test_import_updates_existing_cards(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L", language="en", artist=None)
    rows = [{"card_code": "OP01-001", "name_en": "Monkey D. Luffy", "rarity": "L", "language": "en", "artist": "Eiichiro Oda"}]

    response = upload(client, rows, dry_run="false")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["updated"] == 1
    assert body["preview"][0]["action"] == "update"
    assert body["preview"][0]["changes"]["artist"] == {"old": None, "new": "Eiichiro Oda"}

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    assert card.artist == "Eiichiro Oda"


# --- overwrite semantics ------------------------------------------------


def test_overwrite_false_preserves_existing_non_empty_fields(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L", language="en", artist="Original Artist")
    rows = [{"card_code": "OP01-001", "name_en": "Monkey D. Luffy", "rarity": "L", "language": "en", "artist": "New Artist"}]

    response = upload(client, rows, dry_run="false", overwrite="false")

    assert response.status_code == 200
    body = response.json()
    assert "artist" not in body["preview"][0]["changes"]

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    assert card.artist == "Original Artist"


def test_overwrite_true_replaces_fields(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L", language="en", artist="Original Artist")
    rows = [{"card_code": "OP01-001", "name_en": "Monkey D. Luffy", "rarity": "L", "language": "en", "artist": "New Artist"}]

    response = upload(client, rows, dry_run="false", overwrite="true")

    assert response.status_code == 200
    body = response.json()
    assert body["preview"][0]["changes"]["artist"] == {"old": "Original Artist", "new": "New Artist"}

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    assert card.artist == "New Artist"


# --- normalization -------------------------------------------------------


def test_language_normalization_works(client, db_session):
    rows = [
        {"card_code": "OP01-001", "name_en": "Card A", "language": "Japanese"},
        {"card_code": "OP01-002", "name_en": "Card B", "language": "EN"},
    ]

    response = upload(client, rows, dry_run="false")

    assert response.status_code == 200
    card_a = db_session.query(Card).filter_by(card_code="OP01-001").one()
    card_b = db_session.query(Card).filter_by(card_code="OP01-002").one()
    assert card_a.language == "jp"
    assert card_b.language == "en"


def test_variant_normalization_works(client, db_session):
    rows = [
        {"card_code": "OP01-001", "name_en": "Card A", "variant": "para"},
        {"card_code": "OP01-002", "name_en": "Card B", "variant": "Alternate"},
    ]

    response = upload(client, rows, dry_run="false")

    assert response.status_code == 200
    card_a = db_session.query(Card).filter_by(card_code="OP01-001").one()
    card_b = db_session.query(Card).filter_by(card_code="OP01-002").one()
    assert card_a.variant == "parallel"
    assert card_b.variant == "alt_art"


def test_set_code_inference_works(client, db_session):
    rows = [
        {"card_code": "OP01-001", "name_en": "Card A"},
        {"card_code": "EB01-001", "name_en": "Card B"},
        {"card_code": "ST01-001", "name_en": "Card C"},
        {"card_code": "P-001", "name_en": "Card D"},
    ]

    response = upload(client, rows, dry_run="false")

    assert response.status_code == 200
    cards = {c.card_code: c.set_code for c in db_session.query(Card).all()}
    assert cards == {"OP01-001": "OP01", "EB01-001": "EB01", "ST01-001": "ST01", "P-001": "P"}


def test_invalid_numeric_fields_rejected(client, db_session):
    rows = [{"card_code": "OP01-001", "name_en": "Card A", "cost": "not-a-number"}]

    response = upload(client, rows, dry_run="false")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert "cost" in body["errors"][0]["error"]
    assert db_session.query(Card).count() == 0


def test_invalid_language_rejected(client, db_session):
    rows = [{"card_code": "OP01-001", "name_en": "Card A", "language": "Klingon"}]

    response = upload(client, rows, dry_run="false")

    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert db_session.query(Card).count() == 0


def test_missing_required_columns_returns_400(client, db_session):
    response = client.post(
        "/admin/cards/import.csv",
        files={"file": ("cards.csv", b"foo,bar\n1,2\n", "text/csv")},
    )
    assert response.status_code == 400


# --- unit-level: matching/ambiguity (service function directly) -------------


def test_ambiguous_match_reports_row_error(db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L", variant=None, language="jp")
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="SR", variant=None, language="jp")

    result = import_cards_csv(
        db_session, csv_text([{"card_code": "OP01-001", "name_en": "X"}]), dry_run=True
    )

    assert result.error_rows == 1
    assert "ambiguous" in result.errors[0].error or "existing cards match" in result.errors[0].error


# --- export ---------------------------------------------------------------


def test_export_csv_works(client, db_session):
    make_card(
        db_session,
        card_code="OP01-001",
        set_code="OP01",
        rarity="L",
        language="en",
        artist="Eiichiro Oda",
        cost=5,
    )

    response = client.get("/admin/cards/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "cards_export_" in response.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1
    assert rows[0]["card_code"] == "OP01-001"
    assert rows[0]["artist"] == "Eiichiro Oda"
    assert rows[0]["cost"] == "5"


# --- GET /admin/cards --------------------------------------------------


def test_admin_cards_list_requires_token():
    raw_client = TestClient(app)
    response = raw_client.get("/admin/cards")
    assert response.status_code == 401


def test_admin_cards_list_filters_work(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L", language="en")
    make_card(db_session, card_code="OP02-001", set_code="OP02", rarity="C", language="jp")

    response = client.get("/admin/cards", params={"set_code": "OP01"})

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_cards"] == 2
    assert [c["card_code"] for c in body["cards"]] == ["OP01-001"]

    q_response = client.get("/admin/cards", params={"q": "op02"})
    assert [c["card_code"] for c in q_response.json()["cards"]] == ["OP02-001"]

    missing_response = client.get("/admin/cards", params={"missing_metadata": "true"})
    assert len(missing_response.json()["cards"]) == 2


# --- card_audit: new checks ------------------------------------------------


def test_card_audit_detects_missing_set_code(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="", rarity="L")

    response = client.get("/admin/card-audit")

    issue_types = {i["issue_type"] for i in response.json()["issues"]}
    assert "missing_set_code" in issue_types


def test_card_audit_detects_set_code_mismatch(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP02", rarity="L")

    response = client.get("/admin/card-audit")

    issue_types = {i["issue_type"] for i in response.json()["issues"]}
    assert "set_code_mismatch_card_code" in issue_types


def test_card_audit_detects_invalid_language(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L", language="fr")

    response = client.get("/admin/card-audit")

    issue_types = {i["issue_type"] for i in response.json()["issues"]}
    assert "invalid_language" in issue_types


def test_card_audit_detects_invalid_variant(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L", variant="totally_made_up")

    response = client.get("/admin/card-audit")

    issue_types = {i["issue_type"] for i in response.json()["issues"]}
    assert "invalid_variant" in issue_types


def test_card_audit_detects_missing_name_en(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L", name_en=None)

    response = client.get("/admin/card-audit")

    issue_types = {i["issue_type"] for i in response.json()["issues"]}
    assert "missing_name_en" in issue_types


def test_card_audit_suspicious_empty_metadata_needs_a_baseline(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L", artist=None)

    response = client.get("/admin/card-audit")
    issue_types = {i["issue_type"] for i in response.json()["issues"]}
    assert "suspicious_empty_metadata" not in issue_types

    make_card(db_session, card_code="OP01-002", set_code="OP01", rarity="R", artist="Someone")

    response = client.get("/admin/card-audit")
    issue_types = {i["issue_type"] for i in response.json()["issues"]}
    assert "suspicious_empty_metadata" in issue_types


def test_card_audit_detects_invalid_numeric_fields(client, db_session):
    make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L", cost=-1)

    response = client.get("/admin/card-audit")

    issue_types = {i["issue_type"] for i in response.json()["issues"]}
    assert "invalid_numeric_fields" in issue_types


# --- backup -----------------------------------------------------------


def test_backup_includes_new_card_fields(client, db_session):
    make_card(
        db_session,
        card_code="OP01-001",
        set_code="OP01",
        rarity="L",
        artist="Eiichiro Oda",
        cost=5,
        effect_text="Some effect",
    )

    body = export_backup(db_session)

    card_row = body["tables"]["cards"][0]
    assert card_row["artist"] == "Eiichiro Oda"
    assert card_row["cost"] == 5
    assert card_row["effect_text"] == "Some effect"
