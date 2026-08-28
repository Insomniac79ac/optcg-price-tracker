"""PostgreSQL-backed coverage confirming refresh_prices' worker-side print
lineage writes are accepted under the real constraints the api's
b858237e3706 migration adds (composite FK on price_observations plus the
paired-lineage check constraint) - the rest of the worker suite runs on
SQLite (see conftest.py), which never enables foreign key enforcement, so it
can't prove a print-linked observation is actually accepted at the database
level, only that the ORM sets the right Python attributes.

worker/models.py deliberately mirrors these columns as plain nullable
integers (see its docstring comments) rather than redeclaring the
migration's constraints, so this test layers the real constraint DDL - taken
directly from b858237e3706, not reinvented - onto worker's own
Base.metadata tables instead of importing the api service's app package
(the two services are separate installs; only worker's own models are
importable here).

Points at TEST_POSTGRES_URL (falling back to a local disposable instance on
port 5544, matching services/api/tests/test_print_lineage_postgres.py's
convention) and skips outright if no server answers, so the rest of the
suite (which runs on sqlite) is unaffected."""

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from worker.adapters.base import PriceObservationData, RawSnapshotData
from worker.db import Base
from worker.jobs.refresh_prices import refresh_prices
from worker.models import Card, PriceObservation, Source, SourceCardMapping

TEST_POSTGRES_URL = os.environ.get(
    "TEST_POSTGRES_URL", "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test"
)


class StubAdapter:
    """Minimal SourceAdapter stand-in - same shape as the one in
    test_refresh_prices.py, duplicated locally so this file stays runnable
    on its own against just a bare Postgres server."""

    source_name = "yuyutei"

    def fetch_card(self, mapping):
        return RawSnapshotData(
            source_url=mapping.source_url or "",
            fetched_at=datetime.now(timezone.utc),
            http_status=200,
            content_hash="deadbeef",
            raw_content="<html></html>",
            parser_version="stub-v1",
        )

    def parse_snapshot(self, snapshot):
        return [
            PriceObservationData(
                price_type="sell",
                price_jpy=1000,
                observed_at=snapshot.fetched_at,
                stock_status="in_stock",
            )
        ]


@pytest.fixture()
def postgres_session():
    engine = create_engine(TEST_POSTGRES_URL)
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip(f"No PostgreSQL server reachable at {TEST_POSTGRES_URL}")

    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        # Minimal stand-in for the api's card_prints table - only the FK
        # target (id) matters for this test, not canonical_cards/card_prints'
        # full column set.
        conn.execute(text("CREATE TABLE card_prints (id SERIAL PRIMARY KEY)"))
        # The exact constraint DDL the api's migrations leave in place -
        # b858237e3706 as narrowed by c9f31e2a7d04, which dropped the legacy
        # card_id from both the unique key and the composite FK - layered
        # onto worker's own (plain-column) tables so this proves acceptance
        # under the real schema rather than worker's lighter ORM mirror of
        # it.
        conn.execute(
            text(
                "ALTER TABLE source_card_mappings "
                "ADD CONSTRAINT fk_source_card_mappings_card_print_id_card_prints "
                "FOREIGN KEY (card_print_id) REFERENCES card_prints (id) ON DELETE RESTRICT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE source_card_mappings "
                "ADD CONSTRAINT uq_source_card_mappings_print_lineage_identity "
                "UNIQUE (id, card_print_id, source_id)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE price_observations "
                "ADD CONSTRAINT fk_price_observations_mapping_print_source "
                "FOREIGN KEY (source_card_mapping_id, card_print_id, source_id) "
                "REFERENCES source_card_mappings (id, card_print_id, source_id) "
                "ON DELETE RESTRICT"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE price_observations "
                "ADD CONSTRAINT ck_price_observations_lineage_paired "
                "CHECK ((source_card_mapping_id IS NULL AND card_print_id IS NULL) OR "
                "(source_card_mapping_id IS NOT NULL AND card_print_id IS NOT NULL))"
            )
        )

    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        with engine.begin() as conn:
            # Drop the two FK constraints explicitly first - worker's
            # Base.metadata doesn't know about them (they're plain Integer
            # columns, not declared ForeignKeys), so drop_all's own
            # dependency ordering would otherwise conflict with the real
            # cross-table FKs added above.
            conn.execute(
                text(
                    "ALTER TABLE price_observations "
                    "DROP CONSTRAINT fk_price_observations_mapping_print_source"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE source_card_mappings "
                    "DROP CONSTRAINT fk_source_card_mappings_card_print_id_card_prints"
                )
            )
        Base.metadata.drop_all(bind=engine)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS card_prints"))
        engine.dispose()


def make_source_and_card(session, source_name="yuyutei", card_code="OP01-001"):
    source = Source(name=source_name, base_url=f"https://{source_name}.example")
    card = Card(
        card_code=card_code, name_en="Test Card", name_jp=None,
        set_code="OP01", rarity="L", variant=None, language="jp",
    )
    session.add(source)
    session.add(card)
    session.commit()
    session.refresh(source)
    session.refresh(card)
    return source, card


def make_print(session) -> int:
    result = session.execute(text("INSERT INTO card_prints DEFAULT VALUES RETURNING id"))
    print_id = result.scalar_one()
    session.commit()
    return print_id


def test_legacy_refresh_observation_accepted_with_null_lineage(postgres_session):
    source, card = make_source_and_card(postgres_session)
    mapping = SourceCardMapping(
        card_id=card.id, source_id=source.id, source_card_id="OP01-001",
        source_url="https://yuyu-tei.jp/sell/opc/card/op01/OP01-001",
    )
    postgres_session.add(mapping)
    postgres_session.commit()

    summary = refresh_prices(
        limit=10, db=postgres_session, adapters={"yuyutei": StubAdapter()}
    )

    assert summary.status == "completed"
    observation = postgres_session.query(PriceObservation).one()
    assert observation.source_card_mapping_id is None
    assert observation.card_print_id is None


def test_print_linked_refresh_observation_is_accepted_by_real_constraints(postgres_session):
    source, card = make_source_and_card(postgres_session)
    print_id = make_print(postgres_session)
    mapping = SourceCardMapping(
        card_id=card.id, source_id=source.id, source_card_id="OP01-001",
        source_url="https://yuyu-tei.jp/sell/opc/card/op01/OP01-001",
        card_print_id=print_id,
    )
    postgres_session.add(mapping)
    postgres_session.commit()

    summary = refresh_prices(
        limit=10, db=postgres_session, adapters={"yuyutei": StubAdapter()}
    )

    assert summary.status == "completed"
    observation = postgres_session.query(PriceObservation).one()
    assert observation.source_card_mapping_id == mapping.id
    assert observation.card_print_id == print_id
    assert observation.card_id == card.id
    assert observation.source_id == source.id


def test_mismatched_lineage_would_be_rejected_by_the_real_composite_fk(postgres_session):
    """Sanity check that the layered-on constraints are actually live (not a
    silent no-op) - refresh_prices itself never produces mismatched lineage,
    but a hand-built mismatched row must still be rejected."""
    source, card = make_source_and_card(postgres_session)
    print_id = make_print(postgres_session)
    other_print_id = make_print(postgres_session)
    mapping = SourceCardMapping(
        card_id=card.id, source_id=source.id, source_card_id="OP01-001",
        card_print_id=print_id,
    )
    postgres_session.add(mapping)
    postgres_session.commit()

    postgres_session.add(
        PriceObservation(
            card_id=card.id, source_id=source.id, price_type="sell", price_jpy=1000,
            source_card_mapping_id=mapping.id, card_print_id=other_print_id,
        )
    )
    with pytest.raises(IntegrityError):
        postgres_session.commit()
    postgres_session.rollback()
