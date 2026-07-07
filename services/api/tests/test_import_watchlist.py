import csv

from app.import_watchlist import import_watchlist
from app.models import Card, Source, SourceCardMapping

FIELDNAMES = [
    "card_code",
    "name_en",
    "name_jp",
    "set_code",
    "rarity",
    "variant",
    "language",
    "image_url",
    "yuyutei_url",
    "snkrdunk_url",
    "manual_verified",
]


def write_csv(tmp_path, rows):
    path = tmp_path / "watchlist.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return str(path)


def base_row(**overrides):
    row = {
        "card_code": "OP01-001",
        "name_en": "Monkey D. Luffy",
        "name_jp": "モンキー・D・ルフィ",
        "set_code": "OP01",
        "rarity": "L",
        "variant": "base",
        "language": "jp",
        "image_url": "",
        "yuyutei_url": "",
        "snkrdunk_url": "",
        "manual_verified": "",
    }
    row.update(overrides)
    return row


def test_import_creates_new_cards(tmp_path, db_session):
    csv_path = write_csv(tmp_path, [base_row()])

    summary = import_watchlist(csv_path, db=db_session)

    assert summary.cards_created == 1
    assert summary.cards_updated == 0
    assert summary.skipped_rows == 0

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    assert card.name_en == "Monkey D. Luffy"
    assert card.set_code == "OP01"
    assert card.rarity == "L"


def test_import_updates_existing_card(tmp_path, db_session):
    db_session.add(
        Card(
            card_code="OP01-001",
            name_en="Old Name",
            name_jp="旧名前",
            set_code="OP01",
            rarity="L",
            variant="base",
            language="jp",
        )
    )
    db_session.commit()

    csv_path = write_csv(tmp_path, [base_row(name_en="Monkey D. Luffy (Updated)")])

    summary = import_watchlist(csv_path, db=db_session)

    assert summary.cards_created == 0
    assert summary.cards_updated == 1

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    assert card.name_en == "Monkey D. Luffy (Updated)"


def test_import_creates_source_mappings(tmp_path, db_session):
    csv_path = write_csv(
        tmp_path,
        [
            base_row(
                yuyutei_url="https://yuyu-tei.jp/sell/opc/card/OP01-001",
                snkrdunk_url="https://snkrdunk.com/cards/OP01-001",
                manual_verified="true",
            )
        ],
    )

    summary = import_watchlist(csv_path, db=db_session)

    assert summary.mappings_created == 2
    assert summary.mappings_updated == 0

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    mappings = db_session.query(SourceCardMapping).filter_by(card_id=card.id).all()
    assert len(mappings) == 2
    assert all(m.manual_verified for m in mappings)

    sources = {s.name for s in db_session.query(Source).all()}
    assert sources == {"yuyutei", "snkrdunk"}


def test_import_skips_empty_source_urls(tmp_path, db_session):
    csv_path = write_csv(
        tmp_path,
        [
            base_row(
                yuyutei_url="https://yuyu-tei.jp/sell/opc/card/OP01-001",
                snkrdunk_url="",
            )
        ],
    )

    summary = import_watchlist(csv_path, db=db_session)

    assert summary.mappings_created == 1

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    mappings = db_session.query(SourceCardMapping).filter_by(card_id=card.id).all()
    assert len(mappings) == 1

    sources = {s.name for s in db_session.query(Source).all()}
    assert sources == {"yuyutei"}
