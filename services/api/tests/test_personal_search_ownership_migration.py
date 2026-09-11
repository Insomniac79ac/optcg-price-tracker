"""Execute the real ownership migration on disposable local SQLite tables."""
import importlib.util
import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def migration():
    path=Path(__file__).resolve().parents[1]/'alembic/versions/a8b2c4d6e901_personal_search_ownership.py'
    spec=importlib.util.spec_from_file_location('personal_search_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.fixture(params=['sqlite', 'postgresql'])
def legacy(request):
    url='sqlite:///:memory:'
    if request.param=='postgresql':
        url=os.environ.get('SEC8B_TEST_POSTGRES_URL')
        if not url:
            pytest.skip('Set SEC8B_TEST_POSTGRES_URL to a disposable local PostgreSQL database')
        host=sa.engine.make_url(url).query.get('host') or sa.engine.make_url(url).host
        if host not in ('localhost', '127.0.0.1') and not str(host).startswith('/tmp/'):
            pytest.fail('Migration tests require an explicitly local PostgreSQL server')
    engine=sa.create_engine(url)
    with engine.connect() as conn:
        transaction=conn.begin()
        if request.param=='postgresql':
            schema='sec8b_'+uuid.uuid4().hex
            conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
        conn.execute(sa.text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
        conn.execute(sa.text('INSERT INTO users VALUES (1), (2)'))
        conn.execute(sa.text('CREATE TABLE search_history (id INTEGER PRIMARY KEY, query TEXT, result_count INTEGER)'))
        conn.execute(sa.text('CREATE TABLE saved_views (id INTEGER PRIMARY KEY, route_path TEXT, view_type TEXT, name TEXT, notes TEXT, CONSTRAINT uq_saved_views_route_type_name UNIQUE(route_path,view_type,name))'))
        conn.execute(sa.text("INSERT INTO search_history VALUES (1, 'legacy history', 2)"))
        conn.execute(sa.text("INSERT INTO saved_views VALUES (1, '/collection','table','Legacy','preserved')"))
        try:
            yield conn
        finally:
            transaction.rollback()
    engine.dispose()


def test_upgrade_preserves_legacy_null_owners_and_roundtrip(legacy):
    ops=Operations(MigrationContext.configure(legacy));m=migration()
    with patch.object(m,'op',ops):
        m.upgrade()
        for table in ['search_history','saved_views']:
            columns={c['name']:c for c in sa.inspect(legacy).get_columns(table)}
            assert columns['user_id']['nullable']
            assert legacy.execute(sa.text(f'SELECT user_id FROM {table}')).scalar() is None
            assert any(f['referred_table']=='users' for f in sa.inspect(legacy).get_foreign_keys(table))
            assert any(i['column_names']==['user_id'] for i in sa.inspect(legacy).get_indexes(table))
        assert legacy.execute(sa.text('SELECT notes FROM saved_views')).scalar()=='preserved'
        m.downgrade()
        assert 'user_id' not in {c['name'] for c in sa.inspect(legacy).get_columns('saved_views')}
        assert legacy.execute(sa.text('SELECT notes FROM saved_views')).scalar()=='preserved'
        assert legacy.execute(sa.text('SELECT query FROM search_history')).scalar()=='legacy history'
        m.upgrade()
        assert legacy.execute(sa.text('SELECT user_id FROM saved_views')).scalar() is None


def test_per_owner_uniqueness_and_non_destructive_downgrade_guard(legacy):
    ops=Operations(MigrationContext.configure(legacy));m=migration()
    with patch.object(m,'op',ops):
        m.upgrade()
        legacy.execute(sa.text("INSERT INTO saved_views (id,user_id,route_path,view_type,name) VALUES (2,1,'/collection','table','Same'),(3,2,'/collection','table','Same')"))
        with pytest.raises(sa.exc.IntegrityError):
            with legacy.begin_nested():
                legacy.execute(sa.text("INSERT INTO saved_views (id,user_id,route_path,view_type,name) VALUES (4,1,'/collection','table','Same')"))
        before=legacy.execute(sa.text('SELECT * FROM saved_views ORDER BY id')).all()
        with pytest.raises(RuntimeError,match='overlap across owners'):
            m.downgrade()
        assert legacy.execute(sa.text('SELECT * FROM saved_views ORDER BY id')).all()==before
        assert 'user_id' in {c['name'] for c in sa.inspect(legacy).get_columns('search_history')}


def test_postgresql_upgrade_ddl_has_owners_and_no_backfill():
    from io import StringIO
    output=StringIO()
    ops=Operations(MigrationContext.configure(dialect_name='postgresql', opts={'as_sql':True,'output_buffer':output}))
    m=migration()
    with patch.object(m,'op',ops):
        m.upgrade()
    sql=output.getvalue()
    for table in ['saved_views','search_history']:
        assert f'ALTER TABLE {table} ADD COLUMN user_id INTEGER' in sql
        assert f'CREATE INDEX ix_{table}_user_id' in sql
        assert f'FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL' in sql
    assert 'UNIQUE (user_id, route_path, view_type, name)' in sql
    assert not any(word in sql for word in ['INSERT INTO','UPDATE ', 'DELETE FROM'])
