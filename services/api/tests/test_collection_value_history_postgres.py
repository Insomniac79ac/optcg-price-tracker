"""PostgreSQL proofs for the S4 collection value stage (migrated schema).

The table, its constraints and the pipeline's producer guard are the real
ones from ``alembic upgrade head``. Skips if no local PostgreSQL answers.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import DateTime, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app import market_index_daily_pipeline as pipeline
from app.accounts import valuation, value_history
from app.accounts.models import CollectionValuePoint
from app.models import User
from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.market_value_point import MarketValuePoint
from app.snapshot_market_index import SnapshotRunResult
from tests import test_market_index_completion_postgres as completion_postgres
from tests._market_value_publication_helpers import D28, D29, seed, stamp
from tests.accounts_helpers import hold

pg_engine = completion_postgres.pg_engine
db_session = completion_postgres.db_session


def _users(db, count):
    ids = []
    for n in range(count):
        user = User(google_sub=f"s4-{n}", email=f"s4-{n}@example.com", name=f"s4 {n}")
        db.add(user)
        db.commit()
        ids.append(user.id)
    return ids


@pytest.fixture
def prepared(db_session, pg_engine, monkeypatch):
    seed(db_session, repeating=True)
    valuation.clear_receipt_cache()
    monkeypatch.setattr(pipeline, "SessionLocal", sessionmaker(bind=pg_engine, autoflush=False))
    monkeypatch.setattr(
        pipeline.snapshot_market_index,
        "snapshot_market_index",
        lambda db: SnapshotRunResult(
            snapshot_date=D29,
            calculated_at=datetime(2026, 9, 29, 12, tzinfo=timezone.utc),
            prints_selected=4,
            rows_created=0,
            rows_skipped_existing=4,
            dry_run=False,
            completion_status="verified_existing",
            completion_verified=True,
        ),
    )
    yield db_session
    valuation.clear_receipt_cache()


def _index_outputs(engine):
    out = {}
    with engine.connect() as connection:
        for name, model in (("mv", MarketValuePoint), ("cpi", CardPirateIndexPoint)):
            columns = [c for c in model.__table__.columns if not isinstance(c.type, DateTime)]
            out[name] = tuple(
                tuple(row) for row in connection.execute(select(*columns).order_by(model.id))
            )
    return out


def test_stage_writes_points_under_the_producer_guard(prepared, pg_engine, monkeypatch):
    first, second = _users(prepared, 2)
    hold(prepared, first, 1, 2, stamp(D28) - timedelta(hours=1))
    hold(prepared, second, 3, 1, stamp(D29) - timedelta(hours=1))
    real_stage = value_history.run_stage
    observed = []

    def stage(db, day, **kwargs):
        # The producer cannot start while this stage runs either.
        with pg_engine.connect() as producer:
            producer.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                producer.execute(
                    text("UPDATE job_locks SET status='active' WHERE lock_name='market_index_snapshot'")
                )
            producer.rollback()
        result = real_stage(db, day, **kwargs)
        observed.append(db.scalar(text("SELECT 1")))  # session still usable after commit
        return result

    monkeypatch.setattr(value_history, "run_stage", stage)
    result = pipeline.run_pipeline()
    assert result.exit_code == 0, result.report()
    assert result.collection_value.status == "succeeded"
    assert result.collection_value.inserted == 2
    assert observed == [1]
    with pg_engine.connect() as connection:
        rows = connection.execute(
            select(CollectionValuePoint).order_by(CollectionValuePoint.user_id)
        ).all()
        locks = dict(connection.execute(text("SELECT lock_name, status FROM job_locks")).all())
    assert [(r.user_id, r.point_date, r.value_jpy, r.priced_cards) for r in rows] == [
        (first, D29, 2 * 910, 2),
        (second, D29, 930, 1),
    ]
    # D28 has no receipt in this fixture, so the first step is a break.
    assert {r.step_reason for r in rows} == {"prior_day_missing"}
    assert locks[value_history.LOCK_NAME] == "released"

    rerun = pipeline.run_pipeline()
    assert rerun.collection_value.status == "no_op" and rerun.exit_code == 0


def test_stage_presence_or_failure_leaves_index_outputs_identical(prepared, pg_engine, monkeypatch):
    (user,) = _users(prepared, 1)
    hold(prepared, user, 2, 3, stamp(D29) - timedelta(hours=2))

    real_stage = value_history.run_stage

    def broken(db, day, **kwargs):
        db.execute(text("SELECT 1"))
        raise RuntimeError("stage down")

    monkeypatch.setattr(value_history, "run_stage", broken)
    failed = pipeline.run_pipeline()
    failed_outputs = _index_outputs(pg_engine)
    assert failed.collection_value.status == "failed" and failed.exit_code == 1
    assert failed.market_value.inserted == 2 and failed.card_pirate_index.inserted > 0

    # Undo only the index writers' rows, then run again with the real stage.
    with pg_engine.begin() as connection:
        connection.execute(text("DELETE FROM card_pirate_index_points"))
        connection.execute(
            text("DELETE FROM market_value_points WHERE point_date > :d"), {"d": D28}
        )
    monkeypatch.setattr(value_history, "run_stage", real_stage)
    valuation.clear_receipt_cache()
    present = pipeline.run_pipeline()
    assert present.collection_value.status == "succeeded", present.report()
    assert (present.market_value.status, present.market_value.inserted, present.market_value.dates) == (
        failed.market_value.status,
        failed.market_value.inserted,
        failed.market_value.dates,
    )
    assert present.card_pirate_index.inserted == failed.card_pirate_index.inserted
    after = _index_outputs(pg_engine)
    # Sequences moved on after the delete; compare everything but the id.
    for name in ("mv", "cpi"):
        assert [row[1:] for row in after[name]] == [row[1:] for row in failed_outputs[name]]


def test_value_constraints_reject_a_zero_value(db_session):
    (user,) = _users(db_session, 1)
    db_session.add(
        CollectionValuePoint(
            user_id=user,
            point_date=D29,
            methodology_version=value_history.METHODOLOGY_VERSION,
            value_jpy=0,
            priced_cards=1,
            total_cards=1,
            priced_entries=1,
            total_entries=1,
            step_publishable=False,
            step_reason="prior_day_missing",
            segment_number=1,
        )
    )
    with pytest.raises(IntegrityError, match="ck_collection_value_points_value"):
        db_session.commit()
    db_session.rollback()


def test_stage_transaction_is_repeatable_read(prepared, pg_engine):
    seen = []
    real_plan = value_history.plan_points

    def plan(db, day):
        seen.append(db.scalar(text("SHOW transaction_isolation")))
        return real_plan(db, day)

    value_history.plan_points = plan
    try:
        with sessionmaker(bind=pg_engine)() as db:
            value_history.run_stage(db, D29)
    finally:
        value_history.plan_points = real_plan
    assert seen == ["repeatable read"]
