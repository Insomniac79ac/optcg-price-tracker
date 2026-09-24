"""Full Alembic cycle on a disposable local PostgreSQL database."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from test_release_chronology import accepted_mapping

API = Path(__file__).resolve().parents[1]
PARENT = "f2c7d91b6a40"
REVISION = "c4e9a2b7816d"
FIELDS = "id,source_catalogue,official_code,display_name,first_seen_name,source_series_id,source_url,verification_status,created_at,updated_at"


def test_chronology_upgrade_downgrade_upgrade():
    host = os.environ.get("TEST_POSTGRES_HOST", "localhost")
    port = os.environ.get("TEST_POSTGRES_PORT", "5544")
    user = os.environ.get("TEST_POSTGRES_USER", "opcg")
    password = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
    prefix = f"postgresql+psycopg://{user}:{password}@{host}:{port}/"
    name = "opcg_test_chronology_" + uuid.uuid4().hex[:12]
    admin = create_engine(prefix + "postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip("Disposable PostgreSQL unavailable")
    engine = create_engine(prefix + name)

    def migrate(action, revision):
        result = subprocess.run([sys.executable, "-m", "alembic", action, revision], cwd=API,
                                env=dict(os.environ, DATABASE_URL=prefix + name), capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr

    def protected_rows():
        with engine.connect() as conn:
            return conn.execute(text(f"SELECT {FIELDS} FROM release_products ORDER BY id")).all()

    try:
        migrate("upgrade", PARENT)
        with engine.begin() as conn:
            for row in reversed(accepted_mapping()):
                # Existing parent revisions seed OP01-04; leave their data intact.
                conn.execute(text("INSERT INTO release_products (source_catalogue,official_code,display_name,first_seen_name,source_series_id,source_url,verification_status,created_at,updated_at) "
                                  "SELECT CAST(:catalogue AS varchar),CAST(:code AS varchar),CAST(:code AS varchar),CAST(:code AS varchar),CAST(:code AS varchar),'https://example.test/evidence','verified','2020-01-01'::timestamptz,'2021-01-01'::timestamptz "
                                  "WHERE NOT EXISTS (SELECT 1 FROM release_products WHERE source_catalogue=:catalogue AND official_code=:code)"),
                             {"catalogue": row["source_catalogue"], "code": row["official_code"]})
            for i in range(6):
                conn.execute(text("INSERT INTO release_products (source_catalogue,display_name,first_seen_name,source_series_id,source_url,verification_status) "
                                  "VALUES ('bandai_jp',:name,:name,:series,'https://example.test/special','verified')"),
                             {"name": f"Special {i}", "series": f"special-{i}"})
        before = protected_rows()
        assert len(before) == 65
        with engine.connect() as conn:
            columns_before = conn.execute(text("SELECT table_name,column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position")).all()
            constraints_before = conn.execute(text("SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY conname,oid")).all()
        expected = {(r["source_catalogue"], r["official_code"]): (r["release_date"], r["classification"]) for r in accepted_mapping()}
        for cycle in range(2):
            migrate("upgrade", REVISION)
            assert protected_rows() == before
            with engine.connect() as conn:
                assert conn.execute(text("SELECT version_num FROM alembic_version")).all() == [(REVISION,)]
                rows = conn.execute(text("SELECT source_catalogue,official_code,released_on,release_date_source FROM release_products")).all()
                dated = {(r[0],r[1]): (r[2].isoformat(),r[3]) for r in rows if r[2] is not None}
                assert dated == expected
                assert sum(r[2] is None and r[3] is None for r in rows) == 6
            for source in (None, "", " ", "\t\n", "inferred"):
                with pytest.raises(IntegrityError), engine.begin() as conn:
                    conn.execute(text("UPDATE release_products SET release_date_source=:source WHERE official_code='OP-17'"), {"source": source})
            if cycle == 0:
                migrate("downgrade", PARENT)
                assert protected_rows() == before
                with engine.connect() as conn:
                    assert conn.execute(text("SELECT version_num FROM alembic_version")).all() == [(PARENT,)]
                    assert conn.execute(text("SELECT table_name,column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position")).all() == columns_before
                    assert conn.execute(text("SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY conname,oid")).all() == constraints_before
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
