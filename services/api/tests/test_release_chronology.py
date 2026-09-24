"""Chronology stays tied to the durable receipt, never to card-code families."""

import hashlib
import json
import runpy
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from app.models import ReleaseProduct
from app.models.release_product import RELEASE_DATE_SOURCES
from test_public_catalogue_contract import _items, _print_for_release, _release

ROOT = Path(__file__).resolve().parents[3]
RECEIPT = ROOT / "docs/evidence/public-ux-1a-release-dates-2026-09-24.json"
MIGRATION = ROOT / "services/api/alembic/versions/c4e9a2b7816d_release_chronology.py"


def accepted_mapping():
    return json.loads(RECEIPT.read_text())["accepted_mapping"]


def test_frozen_migration_matches_durable_receipt_and_linear_head():
    receipt = json.loads(RECEIPT.read_text())
    migration = runpy.run_path(str(MIGRATION))
    assert receipt["verification_status"] == "DURABLE_GET_AND_RECOVERY_VERIFIED"
    assert receipt["recovery"]["result"] == "passed"
    assert receipt["accepted_product_count"] == receipt["accepted_date_count"] == 59
    assert receipt["conflict_count"] == 0
    assert receipt["archive_sha256"] == receipt["get_back_sha256"] == migration["ARCHIVE_SHA256"]
    assert receipt["archive_sha256"] in receipt["object_key"]
    assert receipt["storage"]["public_delivery"] is False
    mapping = receipt["accepted_mapping"]
    canonical = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == receipt["mapping_sha256"]
    assert receipt["mapping_sha256"] == migration["RECEIPT_MAPPING_SHA256"] == receipt["recovery"]["mapping_sha256"]
    assert tuple((r["source_catalogue"], r["official_code"], r["release_date"], r["classification"])
                 for r in mapping) == migration["ACCEPTED_RELEASE_DATES"]
    assert set(RELEASE_DATE_SOURCES) == {r["classification"] for r in mapping}
    constraints = {c.name: str(c.sqltext) for c in ReleaseProduct.__table__.constraints if hasattr(c, "sqltext")}
    assert migration["CONSTRAINTS"].items() <= constraints.items()
    config = Config()
    config.set_main_option("script_location", str(ROOT / "services/api/alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [migration["revision"]]
    assert migration["down_revision"] == "f2c7d91b6a40"


@pytest.mark.parametrize("source", [None, "", " ", "\t\n", "inferred"])
def test_dated_model_requires_accepted_nonblank_provenance(db_session, source):
    product = _release(db_session, code="OP-17", name="OP17", series="550117")
    product.released_on = date(2026, 8, 22)
    product.release_date_source = source
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_evidence_chronology_same_day_ties_and_undated_fallback(client, db_session):
    # Reverse insertion order proves chronology is not ingestion/row order.
    mapping = accepted_mapping()
    for index, row in enumerate(reversed(mapping)):
        product = _release(db_session, code=row["official_code"], name=row["official_code"], series=str(index))
        product.released_on = date.fromisoformat(row["release_date"])
        product.release_date_source = row["classification"]
        db_session.commit()
        _print_for_release(db_session, product, card_code=f"OP01-{index:03d}")
    special_ids = []
    for index, name in enumerate(["Z special", "A special", "A special"]):
        product = _release(db_session, code=None, name=name, series=f"special-{index}")
        special_ids.append(product.id)
        _print_for_release(db_session, product, card_code=f"OP01-{index+100:03d}")
    first = _items(client.get("/releases"))
    assert first == _items(client.get("/releases"))
    assert first["chronology_available"] is True
    assert first["ordering_basis"] == "released_on_desc_then_deterministic_fallback"
    items = first["items"]
    expected = sorted(mapping, key=lambda r: (-date.fromisoformat(r["release_date"]).toordinal(), r["source_catalogue"], r["official_code"]))
    assert [(r["official_code"], r["released_on"], r["release_date_source"]) for r in items[:59]] == [
        (r["official_code"], r["release_date"], r["classification"]) for r in expected
    ]
    assert [r["official_code"] for r in items[:11]] == [
        "OP-17", "ST-31", "ST-32", "ST-33", "ST-34", "ST-35", "ST-36", "OP-16", "ST-30", "OP-15", "EB-04"
    ]
    assert all(r["chronology_available"] for r in items[:59])
    assert [r["release_product_id"] for r in items[59:]] == [special_ids[1], special_ids[2], special_ids[0]]
    assert all(r["released_on"] is None and r["release_date_source"] is None and not r["chronology_available"] for r in items[59:])
    assert all("source_url" not in r for r in items)


def test_release_date_does_not_change_membership_or_recent_finds(client, db_session):
    releases = {}
    for row in accepted_mapping():
        if row["official_code"] not in {"OP-01", "OP-17"}:
            continue
        product = _release(db_session, code=row["official_code"], name=row["official_code"], series=row["official_code"])
        product.released_on = date.fromisoformat(row["release_date"])
        product.release_date_source = row["classification"]
        db_session.commit()
        releases[row["official_code"]] = product
    mixed = _print_for_release(db_session, releases["OP-17"], card_code="OP01-099",
                               created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    recent = _print_for_release(db_session, releases["OP-01"], card_code="OP01-098",
                                created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    by_release = _items(client.get("/prints", params={"release_product_id": releases["OP-17"].id}))
    assert [r["card_print_id"] for r in by_release["items"]] == [mixed.id]
    finds = _items(client.get("/prints", params={"sort": "created_desc"}))
    assert [r["card_print_id"] for r in finds["items"]] == [recent.id, mixed.id]
    assert [r["official_code"] for r in _items(client.get("/releases"))["items"]] == ["OP-17", "OP-01"]
