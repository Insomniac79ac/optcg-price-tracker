"""Real PostgreSQL migration cycle; isolated schema, no application/source calls."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def pg_connection():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL must explicitly identify disposable PostgreSQL")
    engine = create_engine(url)
    schema = "identity_test_" + uuid4().hex
    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET search_path TO "{schema}"'))
        connection.commit()
        try:
            yield connection
        finally:
            connection.rollback()
            connection.execute(text("SET search_path TO public"))
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.commit()
    engine.dispose()


def test_upgrade_downgrade_upgrade_preserves_duplicate_rows(pg_connection):
    c = pg_connection
    c.execute(text("CREATE TABLE sources (id integer PRIMARY KEY, name text NOT NULL)"))
    c.execute(text("CREATE TABLE source_card_mappings (id integer PRIMARY KEY, source_id integer REFERENCES sources(id), source_url varchar(1024), is_active boolean NOT NULL DEFAULT true, review_status text DEFAULT 'approved', updated_at timestamptz DEFAULT now())"))
    c.execute(text("INSERT INTO sources VALUES (1,'yuyutei'), (2,'snkrdunk')"))
    fixtures = [
        (12, 2, "https://snkrdunk.com/en/trading-cards/104428?q=1", "104428"),
        (35, 2, "https://snkrdunk.com/apparels/104428", "104428"),
        (16, 2, "https://snkrdunk.com/en/trading-cards/93522#x", "93522"),
        (36, 2, "https://snkrdunk.com/apparels/93522", "93522"),
        (1158, 1, "https://yuyu-tei.jp/sell/opc/card/st11/10004", "st11:10004"),
        (1159, 1, "https://yuyu-tei.jp/sell/opc/card/st11/10002", "st11:10002"),
        (1160, 2, "https://snkrdunk.com/apparels/142632", "142632"),
        (99, 1, "https://yuyu-tei.jp/sell/opc/card/OP01-001", None),
    ]
    for id_, source, url, _ in fixtures:
        c.execute(text("INSERT INTO source_card_mappings (id,source_id,source_url) VALUES (:id,:source,:url)"), dict(id=id_, source=source, url=url))
    before = c.execute(text("SELECT id,source_id,source_url,is_active,review_status,updated_at FROM source_card_mappings ORDER BY id")).all()
    file = Path(__file__).resolve().parents[1] / "alembic/versions/b8e04219d6c3_mapping_listing_identity.py"
    spec = importlib.util.spec_from_file_location("identity_migration", file)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(c)):
        migration.upgrade()
        migration.downgrade()
        migration.upgrade()
    after = c.execute(text("SELECT id,source_id,source_url,is_active,review_status,updated_at FROM source_card_mappings ORDER BY id")).all()
    assert after == before
    identities = dict(c.execute(text("SELECT id,canonical_source_listing_identity FROM source_card_mappings")).all())
    assert identities == {id_: expected for id_, _, _, expected in fixtures}
    assert c.scalar(text("SELECT count(*) FROM source_card_mappings WHERE superseded_at IS NOT NULL OR superseded_by_mapping_id IS NOT NULL OR supersession_reason IS NOT NULL")) == 0
    assert c.scalar(text("SELECT count(*) FROM (SELECT source_id,canonical_source_listing_identity FROM source_card_mappings WHERE canonical_source_listing_identity IS NOT NULL GROUP BY 1,2 HAVING count(*)>1) d")) == 2
    # Both identity pairs coexist: operational index is intentionally nonunique.
    for statement in (
        "UPDATE source_card_mappings SET superseded_at=now() WHERE id=12",
        "UPDATE source_card_mappings SET superseded_at=now(),superseded_by_mapping_id=12,supersession_reason='why',is_active=false WHERE id=12",
        "UPDATE source_card_mappings SET superseded_at=now(),superseded_by_mapping_id=35,supersession_reason=' ',is_active=false WHERE id=12",
        "UPDATE source_card_mappings SET superseded_at=now(),superseded_by_mapping_id=35,supersession_reason='why' WHERE id=12",
    ):
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(text(statement))
    c.execute(text("UPDATE source_card_mappings SET superseded_at=now(),superseded_by_mapping_id=35,supersession_reason='test only',is_active=false WHERE id=12"))
    with pytest.raises(IntegrityError), c.begin_nested():
        c.execute(text("DELETE FROM source_card_mappings WHERE id=35"))


@pytest.mark.parametrize("case", ["lookup", "v12", "v13", "chain"])
def test_postgres_lookup_reporting_and_backup_contract(pg_connection, case):
    from sqlalchemy.orm import Session
    from app.db import Base
    from tests.test_mapping_listing_foundation import (
        test_lookup_duplicate_history_and_report as check_lookup,
        test_backup_duplicates_unparseable_and_old_archive as check_archive,
        test_backup_supersession_chain as check_chain,
    )
    Base.metadata.create_all(pg_connection)
    pg_connection.commit()
    with Session(bind=pg_connection, autoflush=False) as session:
        if case == "lookup":
            check_lookup(session)
        elif case == "chain":
            check_chain(session)
        else:
            check_archive(session, case == "v12")
