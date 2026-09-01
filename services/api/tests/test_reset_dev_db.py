from datetime import datetime, timezone

import pytest

from app.models import Card, PriceObservation, RawSnapshot, Source, SourceCardMapping
from app.reset_dev_db import reset_dev_db
from app.settings import settings


@pytest.fixture(autouse=True)
def _development_environment(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "APP_ENV", None)


def seed_all_tables(db_session):
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    db_session.add(source)
    db_session.flush()

    card = Card(
        card_code="OP01-001", name_en="Test Card", name_jp=None,
        set_code="OP01", rarity="L", variant="base", language="jp",
    )
    db_session.add(card)
    db_session.flush()

    mapping = SourceCardMapping(
        card_id=card.id, source_id=source.id, source_card_id="OP01-001",
        source_url="https://yuyu-tei.jp/sell/opc/card/OP01-001",
    )
    db_session.add(mapping)

    snapshot = RawSnapshot(
        source_id=source.id, source_url="https://yuyu-tei.jp/sell/opc/card/OP01-001",
        fetched_at=datetime.now(timezone.utc), http_status=200,
        content_hash="deadbeef", raw_content="<html></html>",
    )
    db_session.add(snapshot)
    db_session.flush()

    db_session.add(
        PriceObservation(
            card_id=card.id, source_id=source.id, observed_at=datetime.now(timezone.utc),
            price_type="sell", price_jpy=1000, raw_snapshot_id=snapshot.id,
        )
    )
    db_session.commit()
    return source, card


def test_reset_dev_db_refuses_without_confirm(db_session):
    seed_all_tables(db_session)

    with pytest.raises(RuntimeError, match="confirm"):
        reset_dev_db(db_session, confirm=False)

    # Nothing was deleted.
    assert db_session.query(Card).count() == 1


def test_reset_dev_db_refuses_outside_development(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "APP_ENV", None)
    seed_all_tables(db_session)

    with pytest.raises(RuntimeError, match="development"):
        reset_dev_db(db_session, confirm=True)

    assert db_session.query(Card).count() == 1


def test_reset_dev_db_accepts_app_env_development(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", "development")
    seed_all_tables(db_session)

    summary = reset_dev_db(db_session, confirm=True)

    assert db_session.query(Card).count() == 0
    assert summary.deleted["cards"] == 1


def test_reset_dev_db_deletes_dev_data_and_keeps_sources(db_session):
    source, card = seed_all_tables(db_session)

    summary = reset_dev_db(db_session, confirm=True)

    assert db_session.query(PriceObservation).count() == 0
    assert db_session.query(RawSnapshot).count() == 0
    assert db_session.query(SourceCardMapping).count() == 0
    assert db_session.query(Card).count() == 0

    # Sources survive the reset (kept, then reconfirmed via app.seed).
    assert db_session.query(Source).filter_by(name="yuyutei").count() == 1
    assert summary.sources_reseeded is True

    assert summary.deleted["price_observations"] == 1
    assert summary.deleted["raw_snapshots"] == 1
    assert summary.deleted["source_card_mappings"] == 1
    assert summary.deleted["cards"] == 1

    # The Yuyu-Tei discovery tables now exist (migration b7d31e5c9a24), so they
    # are cleared like any other dev table rather than skipped as absent. They
    # are still reached through OPTIONAL_TABLES, so this test also proves that
    # path handles a table that IS present.
    assert summary.skipped_missing_tables == []
    assert summary.deleted["yuyutei_candidates"] == 0
    assert summary.deleted["yuyutei_discovery_runs"] == 0


def test_reset_dev_db_does_not_delete_user_csv_files(db_session, tmp_path):
    csv_path = tmp_path / "opcg_watchlist.csv"
    csv_path.write_text("card_code,set_code,rarity,language\nOP01-001,OP01,L,jp\n")
    seed_all_tables(db_session)

    reset_dev_db(db_session, confirm=True)

    assert csv_path.exists()
