import csv
import io

import pytest

from app.models import Card
from app.services import card_image_import as image_import_module


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant=None,
        language="jp",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def csv_text(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(image_import_module.TEMPLATE_COLUMNS))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def upload(client, rows: list[dict[str, str]], **params):
    return client.post(
        "/admin/cards/import-images.csv",
        params=params,
        files={"file": ("images.csv", csv_text(rows).encode("utf-8"), "text/csv")},
    )


@pytest.fixture(autouse=True)
def _stub_image_validation(monkeypatch):
    """No real network calls in this test suite - approve any https URL
    that doesn't contain 'broken', reject ones that do, so tests can
    exercise both the success and validation-failure paths deterministically."""

    def fake_validate(image_url: str, *, client=None):
        if "broken" in image_url:
            return "image_url returned content-type 'text/html', not an image"
        return None

    monkeypatch.setattr(image_import_module, "_validate_image_url", fake_validate)


def row(**overrides) -> dict[str, str]:
    fields = dict(
        card_code="OP01-001",
        set_code="OP01",
        rarity="L",
        variant="",
        language="jp",
        image_url="https://card.yuyu-tei.jp/opc/front/op01/10001.jpg",
        image_source="yuyutei",
        image_source_url="https://yuyu-tei.jp/sell/opc/card/op01/10001",
    )
    fields.update(overrides)
    return fields


# --- dry-run / apply ---------------------------------------------------------


def test_dry_run_does_not_write(client, db_session):
    card = make_card(db_session)

    response = upload(client, [row()], dry_run="true")

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["summary"]["applied"] == 0
    assert body["preview"][0]["action"] == "would_apply"

    db_session.refresh(card)
    assert card.image_url is None


def test_apply_sets_image_and_provenance(client, db_session):
    card = make_card(db_session)

    response = upload(client, [row()], dry_run="false")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["applied"] == 1
    assert body["preview"][0]["action"] == "applied"

    db_session.refresh(card)
    assert card.image_url == "https://card.yuyu-tei.jp/opc/front/op01/10001.jpg"
    assert card.image_source == "yuyutei"
    assert card.image_source_url == "https://yuyu-tei.jp/sell/opc/card/op01/10001"
    assert card.image_status == "verified"
    assert card.image_last_verified_at is not None


# --- ambiguity / matching safety ---------------------------------------------


def test_no_matching_card_is_a_row_error_and_never_creates_one(client, db_session):
    response = upload(client, [row()], dry_run="false")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert body["summary"]["applied"] == 0
    assert "never creates a card" in body["errors"][0]["error"]
    assert db_session.query(Card).count() == 0


def test_wrong_variant_never_receives_another_variants_image(client, db_session):
    """The exact scenario the redesign brief calls out: a Parallel printing
    of OP01-001 must never receive the base-rarity printing's image, and
    vice versa."""
    base_card = make_card(db_session, rarity="L", variant=None)
    parallel_card = make_card(db_session, rarity="Parallel", variant="Leader")

    response = upload(client, [row(rarity="L", variant="")], dry_run="false")

    assert response.status_code == 200
    assert response.json()["summary"]["applied"] == 1

    db_session.refresh(base_card)
    db_session.refresh(parallel_card)
    assert base_card.image_url is not None
    assert parallel_card.image_url is None


def test_missing_rarity_column_is_a_hard_error(client, db_session):
    make_card(db_session)

    rows = [row()]
    for r in rows:
        del r["rarity"]
    # Build the CSV by hand since csv_text() always writes every template
    # column - simulate a genuinely malformed upload missing the column.
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[c for c in image_import_module.TEMPLATE_COLUMNS if c != "rarity"])
    writer.writeheader()
    writer.writerows(rows)

    response = client.post(
        "/admin/cards/import-images.csv",
        params={"dry_run": "true"},
        files={"file": ("images.csv", buf.getvalue().encode("utf-8"), "text/csv")},
    )

    assert response.status_code == 400
    assert "rarity" in response.json()["detail"]


# --- image URL content validation -------------------------------------------


def test_broken_image_url_is_a_row_error_and_not_applied(client, db_session):
    card = make_card(db_session)

    response = upload(
        client,
        [row(image_url="https://card.yuyu-tei.jp/opc/front/op01/broken.jpg")],
        dry_run="false",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert body["summary"]["applied"] == 0
    assert "not an image" in body["errors"][0]["error"]

    db_session.refresh(card)
    assert card.image_url is None


def test_non_https_image_url_rejected(client, db_session):
    make_card(db_session)

    response = upload(client, [row(image_url="http://card.yuyu-tei.jp/opc/front/op01/10001.jpg")], dry_run="true")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert "https" in body["errors"][0]["error"]


def test_unapproved_image_source_rejected(client, db_session):
    make_card(db_session)

    response = upload(client, [row(image_source="cardrush")], dry_run="true")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["error_rows"] == 1
    assert "image_source" in body["errors"][0]["error"]


# --- template ------------------------------------------------------------


def test_template_endpoint_returns_expected_columns(client):
    response = client.get("/admin/cards/import-images-template.csv")

    assert response.status_code == 200
    header = response.text.splitlines()[0]
    assert header == ",".join(image_import_module.TEMPLATE_COLUMNS)


def test_import_requires_admin_token(client, db_session):
    client.headers.pop("X-Admin-Token", None)
    response = upload(client, [row()], dry_run="true")
    assert response.status_code in (401, 403)
