"""Mock bodies, real transactions/FKs; never a live source or staging database."""

from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import random
import string
import time
import uuid
import sys

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from opcg_source_identity.raw_payload import (
    PREFIX,
    RawContentAccess,
    RawPayloadError,
    sha256,
)
from app.services import raw_dictionary_storage as storage

sys.path.insert(0, str(Path(__file__).parents[3] / "scripts"))
import apply_staging_raw_dependency as delivery


class FixtureBase(DeclarativeBase):
    pass


class Snapshot(RawContentAccess, FixtureBase):
    __tablename__ = "raw_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str] = mapped_column(String(1024))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(32))
    _stored_raw_content: Mapped[str] = mapped_column("raw_content", Text)


def migration(connection):
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/e8c2d4f6a901_protect_raw_dictionary_dependencies.py"
    )
    spec = importlib.util.spec_from_file_location(
        "raw_dictionary_fixture_migration", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    return module


@pytest.fixture
def database(monkeypatch):
    # This test intentionally cannot be redirected to an arbitrary DB URL.
    engine = create_engine("postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test")
    schema = "raw_dictionary_test_" + uuid.uuid4().hex
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    except OperationalError:
        engine.dispose()
        pytest.skip("disposable localhost PostgreSQL unavailable")
    engine.dispose()
    engine = create_engine(
        "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test",
        connect_args={"options": f"-csearch_path={schema}"},
    )
    with engine.begin() as connection:
        FixtureBase.metadata.create_all(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration(connection).upgrade()
    monkeypatch.setenv("RAW_DICTIONARY_STORAGE_ENABLED", "true")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", storage.PROJECT)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", storage.STAGING_ENVIRONMENT)
    monkeypatch.setenv("APP_ENV", "staging")
    try:
        yield engine
    finally:
        engine.dispose()
        cleanup = create_engine(
            "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test"
        )
        with cleanup.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        cleanup.dispose()


def mock_body():
    generator = random.Random(713)
    return (
        "<html><body>"
        + "".join(generator.choices(string.ascii_letters + string.digits, k=100000))
        + "</body></html>"
    )


def row(body=None, **changes):
    body = body or mock_body()
    values = dict(
        source_id=1,
        source_url="https://mock.invalid/card/1",
        fetched_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
        http_status=200,
        content_hash=sha256(body.encode()),
        raw_content=body,
        parser_version="yuyutei-collector-v3",
    )
    values.update(changes)
    return Snapshot(**values)


def base_row(session):
    base = row()
    session.add(base)
    session.commit()
    return base


def test_exact_original_before_parser_and_portable_plaintext_recovery(
    database, monkeypatch
):
    with Session(database) as session:
        base = base_row(session)
        original = mock_body().replace("</body>", "PRICE-CHANGED</body>")
        child = row(original)
        session.add(child)
        assert storage.encode_new_snapshot(session, child)
        session.commit()  # persistence precedes any parser, even if it fails
        child_id, base_id = child.id, base.id
        before = (
            child.content_hash,
            child.fetched_at,
            child.source_id,
            child.source_url,
            child.parser_version,
        )
        assert child._stored_raw_content.startswith(PREFIX)
        assert child.raw_content == original
        assert len(child._stored_raw_content) < len(original) / 10
    with Session(database) as session:
        retained = session.get(Snapshot, child_id)
        assert retained.raw_content == original
        # Portable backups use column names, not private storage attributes.
        portable = {
            column.name: getattr(retained, column.name)
            for column in Snapshot.__table__.columns
        }
        assert portable["raw_content"] == original
        assert not Snapshot(**portable)._stored_raw_content.startswith(PREFIX)
        assert session.get(Snapshot, base_id).raw_content == mock_body()
        with pytest.raises(RawPayloadError, match="disable"):
            storage.expand_snapshot(session, Snapshot, child_id)
        monkeypatch.setenv("RAW_DICTIONARY_STORAGE_ENABLED", "false")
        assert storage.expand_snapshot(session, Snapshot, child_id)
        session.commit()
        assert retained._stored_raw_content == original
        assert (
            retained.content_hash,
            retained.fetched_at,
            retained.source_id,
            retained.source_url,
            retained.parser_version,
        ) == before
        assert not storage.expand_snapshot(session, Snapshot, child_id)
        assert (
            session.scalar(
                text("SELECT expanded_at FROM raw_snapshot_dictionaries WHERE id=:id"),
                {"id": child_id},
            )
            is not None
        )


@pytest.mark.parametrize("delete_child", [False, True])
def test_retention_cannot_delete_either_dependency(database, delete_child):
    with Session(database) as session:
        base = base_row(session)
        child = row()
        session.add(child)
        assert storage.encode_new_snapshot(session, child)
        session.commit()
        target = child.id if delete_child else base.id
        with pytest.raises(IntegrityError):
            session.execute(
                text("DELETE FROM raw_snapshots WHERE id=:id"), {"id": target}
            )
            session.commit()
        session.rollback()
        assert session.get(Snapshot, child.id).raw_content == mock_body()


def test_existing_evidence_cannot_be_rewritten(database):
    with Session(database) as session:
        base = base_row(session)
        with pytest.raises(RawPayloadError, match="pending new"):
            storage.encode_new_snapshot(session, base)


@pytest.mark.parametrize(
    "change",
    [
        {"source_id": 2},
        {"source_url": "https://mock.invalid/card/2"},
        {"parser_version": "yuyutei-identity-evidence-v1"},
        {"http_status": 403},
    ],
)
def test_missing_dictionary_or_non_html_evidence_remains_plaintext(database, change):
    with Session(database) as session:
        base_row(session)
        child = row(**change)
        session.add(child)
        assert not storage.encode_new_snapshot(session, child)
        session.commit()
        assert child._stored_raw_content == mock_body()
        assert (
            session.scalar(text("SELECT count(*) FROM raw_snapshot_dictionaries")) == 0
        )


def test_disabled_has_no_schema_dependency(database, monkeypatch):
    monkeypatch.setenv("RAW_DICTIONARY_STORAGE_ENABLED", "false")
    with database.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration(connection).downgrade()
    with Session(database) as session:
        child = row()
        session.add(child)
        assert not storage.encode_new_snapshot(session, child)
        session.commit()


@pytest.mark.parametrize("environment", ["production", "", "other"])
def test_misconfigured_environment_fails_before_writes(
    database, monkeypatch, environment
):
    monkeypatch.setenv("APP_ENV", environment)
    with Session(database) as session:
        child = row()
        session.add(child)
        with pytest.raises(RawPayloadError, match="pinned staging"):
            storage.encode_new_snapshot(session, child)
        assert child.id is None


def test_corrupt_base_fails_closed_without_child_commit(database):
    with Session(database) as session:
        base = base_row(session)
        base._stored_raw_content = "corrupt retained bytes"
        session.commit()
        child = row()
        session.add(child)
        with pytest.raises(RawPayloadError, match="dictionary hash"):
            storage.encode_new_snapshot(session, child)
        session.rollback()
        assert session.scalar(select(func.count()).select_from(Snapshot)) == 1


def test_used_migration_refuses_destructive_reversal(database):
    with Session(database) as session:
        base_row(session)
        child = row()
        session.add(child)
        assert storage.encode_new_snapshot(session, child)
        session.commit()
    with database.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="retain used"):
                migration(connection).downgrade()


def test_global_admission_is_nonblocking_and_count_ceiling_survives_recovery(
    database, monkeypatch
):
    monkeypatch.setattr(storage, "CANARY_LIMIT", 1)
    with Session(database) as one, Session(database) as two:
        base_row(one)
        first, second = row(), row()
        one.add(first)
        two.add(second)
        assert storage.encode_new_snapshot(one, first)
        start = time.monotonic()
        assert not storage.encode_new_snapshot(two, second)
        assert time.monotonic() - start < 1
        one.commit()
        assert not storage.encode_new_snapshot(two, second)  # cap now consumed
        two.commit()
        assert not second._stored_raw_content.startswith(PREFIX)
        monkeypatch.setenv("RAW_DICTIONARY_STORAGE_ENABLED", "false")
        assert storage.expand_snapshot(one, Snapshot, first.id)
        one.commit()
        monkeypatch.setenv("RAW_DICTIONARY_STORAGE_ENABLED", "true")
        third = row()
        two.add(third)
        assert not storage.encode_new_snapshot(two, third)


def test_caller_ownership_refusal_rolls_back_new_evidence_and_ledger(database):
    with Session(database) as session:
        base_row(session)
        child = row()
        session.add(child)
        assert storage.encode_new_snapshot(session, child)
        session.rollback()  # equivalent to existing pre-commit source lease refusal
        assert (
            session.scalar(text("SELECT count(*) FROM raw_snapshot_dictionaries")) == 0
        )
        assert session.scalar(select(func.count()).select_from(Snapshot)) == 1


def test_serialized_migration_is_additive_and_idempotent(database, monkeypatch):
    from alembic import op

    def refuse_global_facade(*args, **kwargs):
        raise AssertionError("serialized migration must use its pinned connection")

    for name in ("create_table", "create_index", "get_bind", "execute"):
        monkeypatch.setattr(op, name, refuse_global_facade)
    with database.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration(connection).downgrade()
        connection.execute(
            text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
        )
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": delivery.PARENT},
        )
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/e8c2d4f6a901_protect_raw_dictionary_dependencies.py"
    )
    with database.begin() as connection:
        assert delivery.migrate(connection, path)
    with database.begin() as connection:
        assert not delivery.migrate(connection, path)
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == delivery.REVISION
        )
        assert (
            connection.scalar(text("SELECT count(*) FROM raw_snapshot_dictionaries"))
            == 0
        )


def install_daily_indexes(database):
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/f9e5b4a8c012_index_bounded_raw_storage.py"
    )
    spec = importlib.util.spec_from_file_location("daily_index_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with database.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        delivery.validate_indexes(connection)
    return module


def test_daily_mode_requires_indexes_and_refuses_unknown_mode(database, monkeypatch):
    with Session(database) as session:
        base_row(session)
        child = row()
        session.add(child)
        monkeypatch.setenv("RAW_DICTIONARY_STORAGE_MODE", "daily-v1")
        with pytest.raises(RawPayloadError, match="installed lookup indexes"):
            storage.encode_new_snapshot(session, child)
        session.rollback()
        monkeypatch.setenv("RAW_DICTIONARY_STORAGE_MODE", "unknown")
        session.add(row())
        with pytest.raises(RawPayloadError, match="unknown dictionary"):
            storage.encode_new_snapshot(session, next(iter(session.new)))


def test_daily_renewal_is_utc_and_recovery_never_releases_admission(
    database, monkeypatch
):
    install_daily_indexes(database)
    monkeypatch.setenv("RAW_DICTIONARY_STORAGE_MODE", "daily-v1")
    monkeypatch.setattr(storage, "DAILY_ROWS", 1)
    with Session(database) as session:
        base_row(session)
        first = row()
        session.add(first)
        assert storage.encode_new_snapshot(session, first)
        session.commit()
        monkeypatch.setenv("RAW_DICTIONARY_STORAGE_ENABLED", "false")
        assert storage.expand_snapshot(session, Snapshot, first.id)
        session.commit()
        monkeypatch.setenv("RAW_DICTIONARY_STORAGE_ENABLED", "true")
        second = row()
        session.add(second)
        assert not storage.encode_new_snapshot(session, second)
        session.rollback()
        # Only fixture time changes; archived admission remains charged to its
        # original UTC day despite the database/session display timezone.
        session.execute(text("SET TIME ZONE 'Pacific/Honolulu'"))
        session.execute(text("""UPDATE raw_snapshot_dictionaries SET created_at =
            (date_trunc('day', CURRENT_TIMESTAMP AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
            - interval '1 microsecond'"""))
        session.commit()
        third = row()
        session.add(third)
        assert storage.encode_new_snapshot(session, third)
        session.commit()
        assert (
            session.scalar(text("SELECT count(*) FROM raw_snapshot_dictionaries")) == 2
        )


def test_daily_bytes_bound_is_atomic_and_transaction_rollback_restores_room(
    database, monkeypatch
):
    install_daily_indexes(database)
    monkeypatch.setenv("RAW_DICTIONARY_STORAGE_MODE", "daily-v1")
    with Session(database) as first, Session(database) as second:
        base_row(first)
        child = row()
        first.add(child)
        assert storage.encode_new_snapshot(first, child)
        size = first.scalar(text("SELECT encoded_bytes FROM raw_snapshot_dictionaries"))
        monkeypatch.setattr(storage, "DAILY_BYTES", size)
        other = row()
        second.add(other)
        assert not storage.encode_new_snapshot(second, other)  # lock held
        first.rollback()
        assert storage.encode_new_snapshot(second, other)  # exact byte bound fits
        second.commit()
        final = row()
        first.add(final)
        monkeypatch.setattr(storage, "DAILY_BYTES", size * 2 - 1)
        assert not storage.encode_new_snapshot(first, final)  # positive room is too small
        monkeypatch.setattr(storage, "DAILY_BYTES", size)
        assert not storage.encode_new_snapshot(first, final)
        first.commit()
        assert final._stored_raw_content == mock_body()
        assert (
            first.scalar(
                text("SELECT sum(encoded_bytes) FROM raw_snapshot_dictionaries")
            )
            == size
        )


def test_bounded_recent_lookup_reuses_old_anchor_and_adapts_changed_page(
    database, monkeypatch
):
    install_daily_indexes(database)
    monkeypatch.setenv("RAW_DICTIONARY_STORAGE_MODE", "daily-v1")
    monkeypatch.setattr(storage, "RECENT_BASE_ROWS", 2)
    with Session(database) as session:
        base = base_row(session)
        for _ in range(4):
            child = row()
            session.add(child)
            assert storage.encode_new_snapshot(session, child)
            session.commit()
            assert child.raw_content == mock_body()
        assert set(
            session.execute(
                text("SELECT base_snapshot_id FROM raw_snapshot_dictionaries")
            ).scalars()
        ) == {base.id}
        # An unrelated retained page version becomes plaintext when compression
        # would not save space, and becomes the next exact-scope recent anchor.
        changed = "".join(random.Random(719).choices(string.ascii_letters, k=100000))
        new_base = row(changed)
        session.add(new_base)
        assert not storage.encode_new_snapshot(session, new_base)
        session.commit()
        following = row(changed)
        session.add(following)
        assert storage.encode_new_snapshot(session, following)
        session.commit()
        assert (
            session.scalar(
                text(
                    "SELECT base_snapshot_id FROM raw_snapshot_dictionaries WHERE id=:id"
                ),
                {"id": following.id},
            )
            == new_base.id
        )


def test_index_migration_with_used_ledger_is_additive_idempotent_and_reversible(
    database,
):
    with Session(database) as session:
        base_row(session)
        child = row()
        session.add(child)
        assert storage.encode_new_snapshot(session, child)
        session.commit()
        original = child.raw_content
        before = session.execute(text("SELECT * FROM raw_snapshot_dictionaries")).all()
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/f9e5b4a8c012_index_bounded_raw_storage.py"
    )
    with database.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
        )
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": delivery.REVISION},
        )
        assert delivery.migrate(connection, path)
        assert not delivery.migrate(connection, path)
        assert (
            connection.execute(text("SELECT * FROM raw_snapshot_dictionaries")).all()
            == before
        )
        spec = importlib.util.spec_from_file_location("index_rollback_fixture", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.op = Operations(MigrationContext.configure(connection))
        module.downgrade()
        delivery.validate_schema(connection)
    with Session(database) as session:
        assert session.get(Snapshot, child.id).raw_content == original
