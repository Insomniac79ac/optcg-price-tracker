"""Alembic cycle for the OP-18 release date on a disposable local PostgreSQL database."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from tests.pg_url import admin_url, postgres_unavailable, postgres_url, server_label

API = Path(__file__).resolve().parents[1]
PARENT = "001d92ba8eb9"
REVISION = "cb7419af37e9"
INSERT = ("INSERT INTO release_products (source_catalogue,official_code,display_name,first_seen_name,"
          "source_series_id,source_url,verification_status) VALUES ('bandai_jp',:code,:code,:code,:code,"
          "'https://example.test/evidence','verified')")


def test_op18_upgrade_downgrade_upgrade_and_absent_product():
    name = "opcg_test_op18_date_" + uuid.uuid4().hex[:12]
    admin = create_engine(admin_url(), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        admin.dispose()
        postgres_unavailable(f"Disposable PostgreSQL unavailable at {server_label()}")
    engine = create_engine(postgres_url(name))

    def migrate(action, revision):
        result = subprocess.run([sys.executable, "-m", "alembic", action, revision], cwd=API,
                                env=dict(os.environ, DATABASE_URL=postgres_url(name)),
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr

    def dates():
        with engine.connect() as conn:
            return {r[0]: (str(r[1]) if r[1] else None, r[2], str(r[3])) for r in conn.execute(text(
                "SELECT official_code,released_on,release_date_source,updated_at FROM release_products "
                "WHERE official_code IN ('OP-17','OP-18','EB-05') ORDER BY official_code"))}

    try:
        # Before the import the product does not exist: the revision changes no rows and does not fail.
        migrate("upgrade", PARENT)
        migrate("upgrade", REVISION)
        assert "OP-18" not in dates()
        migrate("downgrade", PARENT)

        with engine.begin() as conn:
            for code in ("OP-17", "OP-18", "EB-05"):
                conn.execute(text(INSERT + " ON CONFLICT DO NOTHING"), {"code": code})
            conn.execute(text("UPDATE release_products SET released_on='2026-08-22',"
                              "release_date_source='DATE_VERIFIED_CORROBORATED' WHERE official_code='OP-17'"))
        before = dates()
        assert before["OP-18"][:2] == (None, None)

        migrate("upgrade", REVISION)
        after = dates()
        assert after["OP-18"][:2] == ("2026-11-21", "DATE_VERIFIED_SINGLE_SOURCE")
        assert after["OP-18"][2] == before["OP-18"][2]  # updated_at preserved
        assert after["OP-17"] == before["OP-17"] and after["EB-05"] == before["EB-05"]

        migrate("downgrade", PARENT)
        assert dates() == before
        migrate("upgrade", REVISION)
        assert dates() == after
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
