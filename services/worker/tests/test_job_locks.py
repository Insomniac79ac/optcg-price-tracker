from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from worker.job_locks import (
    LockHeldError,
    acquire_lock,
    make_owner_id,
    release_lock,
    with_job_lock,
)
from worker.models import JobLock


def expire_lock(db_session, lock_name: str) -> None:
    db_session.execute(
        update(JobLock)
        .where(JobLock.lock_name == lock_name)
        .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        .execution_options(synchronize_session=False)
    )
    db_session.commit()


def test_acquire_lock_succeeds_when_none_exists(db_session):
    lock = acquire_lock(db_session, "price_refresh", "price_refresh:a", 1800)

    assert lock.lock_name == "price_refresh"
    assert lock.owner_id == "price_refresh:a"
    assert lock.status == "active"


def test_acquire_lock_fails_while_active(db_session):
    acquire_lock(db_session, "price_refresh", "price_refresh:a", 1800)

    with pytest.raises(LockHeldError) as exc_info:
        acquire_lock(db_session, "price_refresh", "price_refresh:b", 1800)

    assert exc_info.value.lock_name == "price_refresh"
    assert exc_info.value.owner_id == "price_refresh:a"


def test_expired_lock_can_be_reacquired(db_session):
    acquire_lock(db_session, "market_workflow", "market_workflow:old", ttl_seconds=1)
    expire_lock(db_session, "market_workflow")

    lock = acquire_lock(db_session, "market_workflow", "market_workflow:new", 3600)

    assert lock.owner_id == "market_workflow:new"
    assert lock.status == "active"


def test_release_requires_owner_id_match(db_session):
    acquire_lock(db_session, "price_refresh", "price_refresh:a", 1800)

    assert release_lock(db_session, "price_refresh", "price_refresh:wrong") is False
    assert release_lock(db_session, "price_refresh", "price_refresh:a") is True

    # A subsequent acquire should succeed now that it's released.
    lock = acquire_lock(db_session, "price_refresh", "price_refresh:b", 1800)
    assert lock.owner_id == "price_refresh:b"


def test_with_job_lock_acquires_and_releases(db_session):
    with with_job_lock(db_session, "market_workflow") as owner_id:
        assert owner_id is not None
        with pytest.raises(LockHeldError):
            acquire_lock(db_session, "market_workflow", "market_workflow:other", 3600)

    # Released after the with-block - a fresh acquire now succeeds.
    lock = acquire_lock(db_session, "market_workflow", "market_workflow:after", 3600)
    assert lock.owner_id == "market_workflow:after"


def test_with_job_lock_skip_lock_never_touches_the_table(db_session):
    with with_job_lock(db_session, "market_workflow", skip_lock=True) as owner_id:
        assert owner_id is None

    assert db_session.query(JobLock).count() == 0


def test_with_job_lock_nested_distinct_locks_do_not_conflict(db_session):
    """market_workflow held while price_refresh is acquired beneath it -
    different lock names, so this must never raise (see the module
    docstring's deadlock-freedom argument)."""
    with with_job_lock(db_session, "market_workflow"):
        with with_job_lock(db_session, "price_refresh") as inner_owner:
            assert inner_owner is not None


def test_make_owner_id_is_unique_per_call():
    assert make_owner_id("price_refresh") != make_owner_id("price_refresh")
