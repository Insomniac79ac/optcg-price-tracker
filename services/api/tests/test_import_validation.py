import csv
import io
import sys

import pytest

from app.models import Card, CollectionItem, ImportValidationReport, Source, SourceCardMapping
from app.services.backup import export_backup
from app.services.import_templates import TEMPLATE_TYPES

# --- factories ---------------------------------------------------------


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant="base",
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


def validate(client, import_type: str, rows: list[dict[str, str]], filename="upload.csv", **params):
    return client.post(
        f"/admin/import-validation/{import_type}",
        params=params,
        files={"file": (filename, csv_text(rows).encode("utf-8"), "text/csv")},
    )


# --- templates -----------------------------------------------------------


def test_import_templates_requires_admin_token():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon_client:
        response = anon_client.get("/admin/import-templates")
    assert response.status_code == 401


def test_import_templates_lists_all_types(client):
    response = client.get("/admin/import-templates")
    assert response.status_code == 200
    body = response.json()
    types = {t["template_type"] for t in body["templates"]}
    assert types == set(TEMPLATE_TYPES)
    for template in body["templates"]:
        assert template["download_url"] == f"/admin/import-templates/{template['template_type']}.csv"
        assert template["required_columns"]


@pytest.mark.parametrize("template_type", TEMPLATE_TYPES)
def test_each_template_csv_downloads(client, template_type):
    response = client.get(f"/admin/import-templates/{template_type}.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    reader = csv.DictReader(io.StringIO(response.text))
    assert reader.fieldnames is not None
    assert len(list(reader)) >= 1


def test_unknown_template_type_404s(client):
    response = client.get("/admin/import-templates/not-a-real-type.csv")
    assert response.status_code == 404


# --- card_catalog validation ----------------------------------------------


def test_card_catalog_validation_catches_missing_card_code(client, db_session):
    response = validate(client, "card_catalog", [{"card_code": "", "name_en": "Luffy"}])
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["summary"]["error_rows"] == 1
    codes = {e["code"] for e in body["errors"]}
    assert "required_field_missing" in codes


def test_card_catalog_validation_normalizes_language(client, db_session):
    response = validate(
        client, "card_catalog", [{"card_code": "OP01-005", "name_en": "Zoro", "language": "Japanese"}]
    )
    body = response.json()
    assert body["valid"] is True
    warning_codes = {w["code"] for w in body["warnings"]}
    assert "normalized_value" in warning_codes
    assert body["preview"][0]["normalized_values"]["language"] == "jp"


def test_card_catalog_validation_normalizes_variant(client, db_session):
    response = validate(
        client, "card_catalog", [{"card_code": "OP01-006", "name_en": "Sanji", "variant": "para"}]
    )
    body = response.json()
    assert body["valid"] is True
    assert body["preview"][0]["normalized_values"]["variant"] == "parallel"
    messages = " ".join(w["message"] for w in body["warnings"])
    assert "parallel" in messages


def test_card_catalog_validation_warns_duplicate_card_code(client, db_session):
    make_card(db_session, card_code="OP01-007", rarity="L", variant="base", language="en")
    response = validate(
        client,
        "card_catalog",
        [{"card_code": "OP01-007", "name_en": "Nami", "rarity": "L", "variant": "alt", "language": "en"}],
    )
    body = response.json()
    warning_codes = {w["code"] for w in body["warnings"]}
    assert "similar_existing_card" in warning_codes


def test_card_catalog_validation_validates_numeric_fields(client, db_session):
    response = validate(
        client,
        "card_catalog",
        [{"card_code": "OP01-008", "name_en": "Chopper", "cost": "not-a-number"}],
    )
    body = response.json()
    assert body["valid"] is False
    codes = {e["code"] for e in body["errors"]}
    assert "invalid_number" in codes


def test_card_catalog_validation_would_create_and_would_update(client, db_session):
    make_card(db_session, card_code="OP01-009", rarity="L", variant="base", language="en", name_en="Old Name")
    response = validate(
        client,
        "card_catalog",
        [
            {"card_code": "OP01-010", "name_en": "New Card"},
            {"card_code": "OP01-009", "name_en": "Updated Name", "rarity": "L", "variant": "base", "language": "en"},
        ],
    )
    body = response.json()
    assert body["summary"]["would_create"] == 1
    assert body["summary"]["would_update"] == 1


def test_card_catalog_validation_rejects_bad_card_code_format(client, db_session):
    response = validate(client, "card_catalog", [{"card_code": "NOTACARDCODE", "name_en": "X"}])
    body = response.json()
    assert body["valid"] is False
    codes = {e["code"] for e in body["errors"]}
    assert "invalid_card_code_format" in codes


def test_card_catalog_validation_accepts_promo_card_code(client, db_session):
    response = validate(client, "card_catalog", [{"card_code": "P-001", "name_en": "Promo Card"}])
    body = response.json()
    assert body["valid"] is True


# --- source_mappings validation --------------------------------------------


def test_source_mappings_validation_catches_missing_source_and_card(client, db_session):
    response = validate(
        client,
        "source_mappings",
        [{"source_name": "does_not_exist", "source_url": "https://example.com/x", "card_code": "OP99-999"}],
    )
    body = response.json()
    assert body["valid"] is False
    codes = {e["code"] for e in body["errors"]}
    assert "source_not_found" in codes
    assert "card_not_found" in codes


def test_source_mappings_validation_warns_duplicate_source_url(client, db_session):
    card = make_card(db_session)
    source = make_source(db_session, "yuyutei")
    db_session.add(
        SourceCardMapping(card_id=card.id, source_id=source.id, source_card_id=card.card_code, source_url="https://yuyutei.example.com/OP01-001")
    )
    db_session.commit()

    response = validate(
        client,
        "source_mappings",
        [{"source_name": "yuyutei", "source_url": "https://yuyutei.example.com/OP01-001", "card_code": card.card_code}],
    )
    body = response.json()
    assert body["valid"] is True
    warning_codes = {w["code"] for w in body["warnings"]}
    assert "duplicate_source_url" in warning_codes
    assert body["summary"]["would_update"] == 1


def test_source_mappings_validation_rejects_invalid_review_status(client, db_session):
    card = make_card(db_session)
    make_source(db_session, "yuyutei")
    response = validate(
        client,
        "source_mappings",
        [
            {
                "source_name": "yuyutei",
                "source_url": "https://yuyutei.example.com/x",
                "card_code": card.card_code,
                "review_status": "not_a_status",
            }
        ],
    )
    body = response.json()
    assert body["valid"] is False
    codes = {e["code"] for e in body["errors"]}
    assert "invalid_value" in codes


# --- snkrdunk_candidates validation -----------------------------------------


def test_snkrdunk_candidates_validation_catches_missing_title_and_url(client, db_session):
    response = validate(client, "snkrdunk_candidates", [{"source_url": "", "title": ""}])
    body = response.json()
    assert body["valid"] is False
    codes = {e["code"] for e in body["errors"]}
    assert codes == {"required_field_missing"}
    assert body["summary"]["error_rows"] == 1


def test_snkrdunk_candidates_validation_returns_match_confidence(client, db_session):
    make_card(db_session, card_code="OP01-011", name_en="Usopp", rarity="L", variant="base", language="en")
    response = validate(
        client,
        "snkrdunk_candidates",
        [
            {
                "source_url": "https://snkrdunk.com/items/abc",
                "title": "OP01-011 Usopp",
                "detected_card_code": "OP01-011",
            }
        ],
    )
    body = response.json()
    assert body["valid"] is True
    # A confident exact card_code match shouldn't produce a low-confidence/no-match warning.
    codes = {w["code"] for w in body["warnings"]}
    assert "no_good_match" not in codes


def test_snkrdunk_candidates_validation_warns_no_good_match_without_card_code(client, db_session):
    response = validate(
        client,
        "snkrdunk_candidates",
        [{"source_url": "https://snkrdunk.com/items/xyz", "title": "Unrecognizable listing text"}],
    )
    body = response.json()
    assert body["valid"] is True
    codes = {w["code"] for w in body["warnings"]}
    assert "no_good_match" in codes


# --- collection validation --------------------------------------------------


def test_collection_validation_catches_invalid_quantity(client, db_session):
    card = make_card(db_session)
    response = validate(client, "collection", [{"card_code": card.card_code, "quantity": "0"}])
    body = response.json()
    assert body["valid"] is False
    codes = {e["code"] for e in body["errors"]}
    assert "invalid_value" in codes


def test_collection_validation_would_create_without_user_id(client, db_session):
    card = make_card(db_session)
    response = validate(client, "collection", [{"card_code": card.card_code, "quantity": "1"}])
    body = response.json()
    assert body["valid"] is True
    assert body["summary"]["would_create"] == 1


def test_collection_validation_would_update_with_user_id(client, db_session):
    card = make_card(db_session)
    db_session.add(CollectionItem(user_id=1, card_id=card.id, quantity=2))
    db_session.commit()

    response = validate(client, "collection", [{"card_code": card.card_code, "quantity": "3"}], user_id=1)
    body = response.json()
    assert body["valid"] is True
    assert body["summary"]["would_update"] == 1
    warning_codes = {w["code"] for w in body["warnings"]}
    assert "likely_duplicate" in warning_codes


# --- wishlist validation -----------------------------------------------------


def test_wishlist_validation_catches_target_exceeds_max(client, db_session):
    card = make_card(db_session)
    response = validate(
        client,
        "wishlist",
        [{"card_code": card.card_code, "target_buy_price_jpy": "6000", "max_buy_price_jpy": "4000"}],
    )
    body = response.json()
    assert body["valid"] is True
    warning_codes = {w["code"] for w in body["warnings"]}
    assert "target_exceeds_max" in warning_codes


def test_wishlist_validation_catches_missing_card(client, db_session):
    response = validate(client, "wishlist", [{"card_code": "NOPE-999"}])
    body = response.json()
    assert body["valid"] is False
    codes = {e["code"] for e in body["errors"]}
    assert "card_not_found" in codes


# --- strict mode / unknown columns ------------------------------------------


def test_strict_mode_turns_unknown_columns_into_errors(client, db_session):
    card = make_card(db_session)
    response = validate(
        client, "collection", [{"card_code": card.card_code, "quantity": "1", "bogus_column": "x"}], strict="true"
    )
    body = response.json()
    assert body["valid"] is False
    assert "bogus_column" in body["columns"]["unknown_columns"]
    codes = {e["code"] for e in body["errors"]}
    assert "unknown_column" in codes


def test_non_strict_mode_reports_unknown_columns_as_warnings(client, db_session):
    card = make_card(db_session)
    response = validate(client, "collection", [{"card_code": card.card_code, "quantity": "1", "bogus_column": "x"}])
    body = response.json()
    assert body["valid"] is True
    codes = {w["code"] for w in body["warnings"]}
    assert "unknown_column" in codes


def test_missing_required_column_is_reported(client, db_session):
    response = client.post(
        "/admin/import-validation/card_catalog",
        files={"file": ("upload.csv", b"name_en\nLuffy\n", "text/csv")},
    )
    body = response.json()
    assert body["valid"] is False
    assert "card_code" in body["columns"]["missing_required_columns"]


def test_empty_file_is_reported(client, db_session):
    response = client.post(
        "/admin/import-validation/card_catalog",
        files={"file": ("upload.csv", b"", "text/csv")},
    )
    body = response.json()
    assert body["valid"] is False
    assert body["errors"][0]["code"] == "empty_file"


def test_unknown_import_type_404s(client, db_session):
    response = client.post(
        "/admin/import-validation/not_a_real_type",
        files={"file": ("upload.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert response.status_code == 404


# --- reports -----------------------------------------------------------------


def test_validation_report_is_stored(client, db_session):
    card = make_card(db_session)
    validate(client, "collection", [{"card_code": card.card_code, "quantity": "1"}], filename="my_collection.csv")

    reports = db_session.query(ImportValidationReport).all()
    assert len(reports) == 1
    assert reports[0].import_type == "collection"
    assert reports[0].filename == "my_collection.csv"
    assert reports[0].valid is True
    assert reports[0].report_payload_json["import_type"] == "collection"


def test_report_list_and_detail_work(client, db_session):
    card = make_card(db_session)
    validate(client, "collection", [{"card_code": card.card_code, "quantity": "1"}])
    validate(client, "collection", [{"card_code": "", "quantity": "1"}])

    list_response = client.get("/admin/import-validation/reports")
    assert list_response.status_code == 200
    list_body = list_response.json()
    assert len(list_body["reports"]) == 2
    assert list_body["pagination"]["total"] == 2

    filtered = client.get("/admin/import-validation/reports", params={"valid": "false"})
    assert filtered.status_code == 200
    assert len(filtered.json()["reports"]) == 1

    report_id = list_body["reports"][0]["id"]
    detail_response = client.get(f"/admin/import-validation/reports/{report_id}")
    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["id"] == report_id
    assert "report_payload_json" in detail_body


def test_report_detail_404s_for_missing_id(client, db_session):
    response = client.get("/admin/import-validation/reports/999999")
    assert response.status_code == 404


def test_reports_require_admin_token():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon_client:
        response = anon_client.get("/admin/import-validation/reports")
    assert response.status_code == 401


# --- backup integration --------------------------------------------------


def test_backup_includes_validation_reports(client, db_session):
    card = make_card(db_session)
    validate(client, "collection", [{"card_code": card.card_code, "quantity": "1"}])

    backup = export_backup(db_session, include_validation_reports=True)
    assert len(backup["tables"]["import_validation_reports"]) == 1

    backup_default = export_backup(db_session)
    assert "import_validation_reports" not in backup_default["tables"]


# --- CLI -----------------------------------------------------------------


def test_cli_exits_1_on_invalid_file(db_session, tmp_path, monkeypatch):
    from app import validate_import_csv as cli

    csv_path = tmp_path / "cards.csv"
    csv_path.write_text("card_code,name_en\n,Luffy\n")

    monkeypatch.setattr(cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(sys, "argv", ["validate_import_csv", str(csv_path), "--type", "card_catalog"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 1


def test_cli_exits_0_on_valid_file(db_session, tmp_path, monkeypatch, capsys):
    from app import validate_import_csv as cli

    csv_path = tmp_path / "cards.csv"
    csv_path.write_text("card_code,name_en\nOP01-050,Franky\n")

    monkeypatch.setattr(cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(sys, "argv", ["validate_import_csv", str(csv_path), "--type", "card_catalog"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 0

    reports = db_session.query(ImportValidationReport).all()
    assert len(reports) == 1

    captured = capsys.readouterr()
    assert "valid: True" in captured.out
