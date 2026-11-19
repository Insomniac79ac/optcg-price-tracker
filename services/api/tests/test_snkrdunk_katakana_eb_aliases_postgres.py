"""Alembic cycle for the SNKRDUNK katakana EB renderings on a disposable local PostgreSQL database."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from tests.pg_url import admin_url, postgres_unavailable, postgres_url, server_label

API = Path(__file__).resolve().parents[1]
PARENT = "cb7419af37e9"
REVISION = "7d2f9b4e1a63"
INSERT = ("INSERT INTO release_products (source_catalogue,official_code,display_name,first_seen_name,"
          "source_series_id,source_url,verification_status) VALUES ('bandai_jp',:code,:code,:code,:code,"
          "'https://example.test/evidence','verified') ON CONFLICT DO NOTHING")


def test_upgrade_downgrade_upgrade_missing_product_and_existing_row():
    name = "opcg_test_katakana_eb_" + uuid.uuid4().hex[:12]
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

    def rows():
        with engine.connect() as conn:
            return [tuple(r) for r in conn.execute(text(
                "SELECT p.official_code, a.alias_name, a.alias_kind, a.source_url, s.name "
                "FROM release_product_aliases a JOIN release_products p ON p.id = a.product_id "
                "LEFT JOIN sources s ON s.id = a.source_id "
                "WHERE a.alias_kind = 'source_rendering' AND p.official_code IN ('EB-02','EB-03','EB-04') "
                "ORDER BY p.official_code, a.alias_name"))]

    try:
        migrate("upgrade", PARENT)
        before_missing = rows()
        migrate("upgrade", REVISION)  # products may not exist yet: no rows, no failure
        assert rows() == before_missing
        migrate("downgrade", PARENT)

        with engine.begin() as conn:
            for code in ("EB-02", "EB-03", "EB-04"):
                conn.execute(text(INSERT), {"code": code})
        before = rows()
        migrate("upgrade", REVISION)
        after = rows()
        added = sorted(set(after) - set(before))
        assert added == sorted([
            ("EB-02", "アニメ 25th コレクション", "source_rendering", None, "snkrdunk"),
            ("EB-03", "ワンピース ヒロインズエディション", "source_rendering", None, "snkrdunk"),
            ("EB-04", "エッグヘッドクライシス", "source_rendering", None, "snkrdunk"),
        ])
        migrate("downgrade", PARENT)
        assert rows() == before
        migrate("upgrade", REVISION)
        assert rows() == after
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
