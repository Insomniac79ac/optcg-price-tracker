import csv
from pathlib import Path

import pytest

from worker.jobs.import_snkrdunk_candidates import import_snkrdunk_candidates
from worker.models import (
    Card,
    SnkrdunkCandidate,
    SnkrdunkDiscoveryRun,
    Source,
    SourceCardMapping,
)

FIELDNAMES = [
    "source_url",
    "title",
    "price_jpy",
    "image_url",
    "listing_count",
    "condition_label",
    "raw_text",
]


def write_csv(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "snkrdunk_candidates.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def base_row(**overrides) -> dict:
    row = {
        "source_url": "https://snkrdunk.com/trading-cards/op01-001-luffy-l",
        "title": "ONE PIECEカードゲーム OP01-001 モンキー・D・ルフィ L",
        "price_jpy": "1200",
        "image_url": "https://img.snkrdunk.com/op01-001.jpg",
        "listing_count": "12",
        "condition_label": "中古",
        "raw_text": "",
    }
    row.update(overrides)
    return row


def seed_source_and_cards(db_session):
    db_session.add(Source(name="snkrdunk", base_url="https://snkrdunk.com"))
    db_session.add(
        Card(
            card_code="OP01-001", name_en="Monkey D. Luffy", name_jp="モンキー・D・ルフィ",
            set_code="OP01", rarity="L", variant=None, language="jp",
        )
    )
    db_session.flush()


def test_import_creates_new_candidates(db_session, tmp_path):
    seed_source_and_cards(db_session)
    csv_path = write_csv(tmp_path, [base_row()])

    summary = import_snkrdunk_candidates(csv_path, db=db_session)

    assert summary.candidates_imported == 1
    assert summary.candidates_updated == 0
    assert summary.skipped_rows == 0

    candidate = db_session.query(SnkrdunkCandidate).one()
    assert candidate.source_url == "https://snkrdunk.com/trading-cards/op01-001-luffy-l"
    assert candidate.price_jpy == 1200
    assert candidate.listing_count == 12
    assert candidate.condition_label == "中古"

    run = db_session.query(SnkrdunkDiscoveryRun).one()
    assert run.status == "manual_import"
    assert run.seed_url == str(csv_path)


def test_import_deduplicates_existing_candidates_by_source_url(db_session, tmp_path):
    seed_source_and_cards(db_session)
    csv_path = write_csv(tmp_path, [base_row()])

    import_snkrdunk_candidates(csv_path, db=db_session)

    updated_csv_path = write_csv(tmp_path, [base_row(price_jpy="1500", listing_count="20")])
    summary = import_snkrdunk_candidates(updated_csv_path, db=db_session)

    assert summary.candidates_imported == 0
    assert summary.candidates_updated == 1
    assert db_session.query(SnkrdunkCandidate).count() == 1

    candidate = db_session.query(SnkrdunkCandidate).one()
    assert candidate.price_jpy == 1500
    assert candidate.listing_count == 20


def test_import_auto_matches_exact_card_code(db_session, tmp_path):
    seed_source_and_cards(db_session)
    csv_path = write_csv(tmp_path, [base_row()])

    summary = import_snkrdunk_candidates(csv_path, db=db_session)

    assert summary.candidates_auto_matched == 1
    assert summary.candidates_needing_review == 0

    candidate = db_session.query(SnkrdunkCandidate).one()
    assert candidate.match_status == "auto_matched"
    assert candidate.detected_card_code == "OP01-001"

    card = db_session.query(Card).filter_by(card_code="OP01-001").one()
    mapping = db_session.query(SourceCardMapping).filter_by(card_id=card.id).one()
    assert mapping.manual_verified is False
    assert mapping.source_url == candidate.source_url
    assert mapping.review_status == "needs_review"
    assert mapping.is_active is True


def test_import_marks_unclear_candidate_as_needs_review(db_session, tmp_path):
    seed_source_and_cards(db_session)
    csv_path = write_csv(tmp_path, [
        base_row(
            source_url="https://snkrdunk.com/trading-cards/some-unrelated-listing",
            title="謎のリスティング",
        )
    ])

    summary = import_snkrdunk_candidates(csv_path, db=db_session)

    assert summary.candidates_auto_matched == 0
    assert summary.candidates_needing_review == 1

    candidate = db_session.query(SnkrdunkCandidate).one()
    assert candidate.match_status == "needs_review"
    assert db_session.query(SourceCardMapping).count() == 0


def test_import_skips_rows_missing_source_url(db_session, tmp_path):
    seed_source_and_cards(db_session)
    csv_path = write_csv(tmp_path, [base_row(source_url="")])

    summary = import_snkrdunk_candidates(csv_path, db=db_session)

    assert summary.candidates_imported == 0
    assert summary.skipped_rows == 1
    assert db_session.query(SnkrdunkCandidate).count() == 0


def test_import_does_not_override_manual_mapping(db_session, tmp_path):
    seed_source_and_cards(db_session)
    source = db_session.query(Source).filter_by(name="snkrdunk").one()
    card = db_session.query(Card).filter_by(card_code="OP01-001").one()

    manual_mapping = SourceCardMapping(
        card_id=card.id,
        source_id=source.id,
        source_card_id="manual-OP01-001",
        source_url="https://snkrdunk.com/trading-cards/manually-verified-listing",
        manual_verified=True,
    )
    db_session.add(manual_mapping)
    db_session.flush()

    csv_path = write_csv(tmp_path, [base_row()])
    import_snkrdunk_candidates(csv_path, db=db_session)

    db_session.refresh(manual_mapping)
    assert manual_mapping.manual_verified is True
    assert manual_mapping.source_url == "https://snkrdunk.com/trading-cards/manually-verified-listing"
    assert (
        db_session.query(SourceCardMapping).filter_by(card_id=card.id, source_id=source.id).count()
        == 1
    )


def test_import_raises_for_missing_csv_file(db_session, tmp_path):
    missing_path = tmp_path / "does_not_exist.csv"
    with pytest.raises(FileNotFoundError):
        import_snkrdunk_candidates(missing_path, db=db_session)
