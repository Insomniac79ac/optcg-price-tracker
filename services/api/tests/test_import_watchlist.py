import csv

import pytest
from sqlalchemy.exc import IntegrityError

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


def test_import_creates_active_needs_review_mappings_when_manual_verified(tmp_path, db_session):
    """A curated watchlist row activates the mapping but cannot approve it.

    The CSV identifies its target by card_code alone, and a card code spans
    several printings - so the row cannot say which item a price belongs to.
    It lands active and `needs_review`, and reaches `approved` only through a
    path that runs the exact-print gate."""
    csv_path = write_csv(
        tmp_path,
        [
            base_row(
                yuyutei_url="https://yuyu-tei.jp/sell/opc/card/OP01-001",
                manual_verified="true",
            )
        ],
    )

    import_watchlist(csv_path, db=db_session)

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    mapping = db_session.query(SourceCardMapping).filter_by(card_id=card.id).one()
    assert mapping.is_active is True
    assert mapping.review_status == "needs_review"
    assert mapping.card_print_id is None


def test_reimporting_as_manual_verified_reactivates_a_rejected_mapping(tmp_path, db_session):
    """Re-activation still works; the row comes back for review, not approved."""
    csv_path = write_csv(
        tmp_path,
        [
            base_row(
                yuyutei_url="https://yuyu-tei.jp/sell/opc/card/OP01-001",
                manual_verified="false",
            )
        ],
    )
    import_watchlist(csv_path, db=db_session)

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    mapping = db_session.query(SourceCardMapping).filter_by(card_id=card.id).one()
    mapping.is_active = False
    mapping.review_status = "rejected"
    db_session.commit()

    reimport_csv = write_csv(
        tmp_path,
        [
            base_row(
                yuyutei_url="https://yuyu-tei.jp/sell/opc/card/OP01-001",
                manual_verified="true",
            )
        ],
    )
    import_watchlist(reimport_csv, db=db_session)

    db_session.expire_all()
    updated = db_session.query(SourceCardMapping).filter_by(card_id=card.id).one()
    assert updated.is_active is True
    assert updated.review_status == "needs_review"


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
    assert summary.mappings_skipped_empty_url == 1

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    mappings = db_session.query(SourceCardMapping).filter_by(card_id=card.id).all()
    assert len(mappings) == 1

    sources = {s.name for s in db_session.query(Source).all()}
    assert sources == {"yuyutei"}


def test_import_allows_multiple_yuyutei_urls_for_same_card(tmp_path, db_session):
    csv_path = write_csv(
        tmp_path,
        [
            base_row(yuyutei_url="https://yuyu-tei.jp/sell/opc/card/OP01-001-raw"),
            base_row(yuyutei_url="https://yuyu-tei.jp/sell/opc/card/OP01-001-graded"),
        ],
    )

    summary = import_watchlist(csv_path, db=db_session)

    assert summary.mappings_created == 2
    assert summary.mappings_updated == 0
    assert summary.duplicate_urls_skipped == 0

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    mappings = db_session.query(SourceCardMapping).filter_by(card_id=card.id).all()
    assert len(mappings) == 2
    assert {m.source_url for m in mappings} == {
        "https://yuyu-tei.jp/sell/opc/card/OP01-001-raw",
        "https://yuyu-tei.jp/sell/opc/card/OP01-001-graded",
    }


def test_import_allows_multiple_snkrdunk_urls_for_same_card(tmp_path, db_session):
    csv_path = write_csv(
        tmp_path,
        [
            base_row(snkrdunk_url="https://snkrdunk.com/cards/op01-001-listing-a"),
            base_row(snkrdunk_url="https://snkrdunk.com/cards/op01-001-listing-b"),
        ],
    )

    summary = import_watchlist(csv_path, db=db_session)

    assert summary.mappings_created == 2
    assert summary.mappings_updated == 0

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    mappings = db_session.query(SourceCardMapping).filter_by(card_id=card.id).all()
    assert len(mappings) == 2
    assert {m.source_url for m in mappings} == {
        "https://snkrdunk.com/cards/op01-001-listing-a",
        "https://snkrdunk.com/cards/op01-001-listing-b",
    }


def test_reimport_same_csv_does_not_create_duplicate_mappings(tmp_path, db_session):
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

    first = import_watchlist(csv_path, db=db_session)
    assert first.mappings_created == 2
    assert first.mappings_updated == 0

    second = import_watchlist(csv_path, db=db_session)
    assert second.mappings_created == 0
    assert second.mappings_updated == 2

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    mappings = db_session.query(SourceCardMapping).filter_by(card_id=card.id).all()
    assert len(mappings) == 2


def test_duplicate_source_url_rows_in_csv_do_not_crash(tmp_path, db_session):
    csv_path = write_csv(
        tmp_path,
        [
            base_row(yuyutei_url="https://yuyu-tei.jp/sell/opc/card/OP01-001"),
            base_row(yuyutei_url="https://yuyu-tei.jp/sell/opc/card/OP01-001"),
        ],
    )

    summary = import_watchlist(csv_path, db=db_session)

    assert summary.mappings_created == 1
    assert summary.mappings_updated == 0
    assert summary.duplicate_urls_skipped == 1

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    mappings = db_session.query(SourceCardMapping).filter_by(card_id=card.id).all()
    assert len(mappings) == 1


def test_source_card_mappings_no_longer_unique_on_card_id_and_source_id(db_session):
    card = Card(
        card_code="OP01-001", name_en="Monkey D. Luffy", name_jp=None,
        set_code="OP01", rarity="L", variant="base", language="jp",
    )
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    db_session.add_all([card, source])
    db_session.flush()

    db_session.add(
        SourceCardMapping(
            card_id=card.id, source_id=source.id, source_card_id="OP01-001",
            source_url="https://yuyu-tei.jp/sell/opc/card/OP01-001-raw",
        )
    )
    db_session.add(
        SourceCardMapping(
            card_id=card.id, source_id=source.id, source_card_id="OP01-001",
            source_url="https://yuyu-tei.jp/sell/opc/card/OP01-001-graded",
        )
    )

    # Same (card_id, source_id) pair, different source_url: must not raise.
    db_session.commit()

    mappings = db_session.query(SourceCardMapping).filter_by(card_id=card.id, source_id=source.id).all()
    assert len(mappings) == 2


def test_source_card_mappings_unique_on_source_id_and_source_url(db_session):
    card_a = Card(
        card_code="OP01-001", name_en="Card A", name_jp=None,
        set_code="OP01", rarity="L", variant="a", language="jp",
    )
    card_b = Card(
        card_code="OP01-002", name_en="Card B", name_jp=None,
        set_code="OP01", rarity="L", variant="b", language="jp",
    )
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    db_session.add_all([card_a, card_b, source])
    db_session.flush()

    db_session.add(
        SourceCardMapping(
            card_id=card_a.id, source_id=source.id, source_card_id="OP01-001",
            source_url="https://yuyu-tei.jp/sell/opc/card/OP01-001",
        )
    )
    db_session.commit()

    db_session.add(
        SourceCardMapping(
            card_id=card_b.id, source_id=source.id, source_card_id="OP01-002",
            source_url="https://yuyu-tei.jp/sell/opc/card/OP01-001",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
