"""app.services.job_locks and the GET/POST /admin/job-locks endpoints - see
'Worker job concurrency locking' in docs/operations.md."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.main import app
from app.models import AppLogEvent, JobLock
from app.services.job_locks import (
    LockHeldError,
    acquire_lock,
    force_release_expired_locks,
    force_release_lock,
    get_active_locks,
    get_lock_counts,
    make_owner_id,
    release_lock,
    with_job_lock,
)

NOW = datetime.now(timezone.utc)


def events_by_type(db_session, event_type: str) -> list[AppLogEvent]:
    return (
        db_session.query(AppLogEvent)
        .filter(AppLogEvent.event_type == event_type)
        .order_by(AppLogEvent.id)
        .all()
    )


def expire_lock(db_session, lock_name: str) -> None:
    """Forces lock_name's expires_at into the past, via the test's own
    db_session - job_locks itself opens a separate short-lived session
    (monkeypatched to the same in-memory-sqlite engine by the autouse
    _job_locks_uses_test_db fixture in conftest.py), but both share the same
    underlying StaticPool connection, so a write here is immediately visible
    to it."""
    db_session.execute(
        update(JobLock)
        .where(JobLock.lock_name == lock_name)
        .values(expires_at=NOW - timedelta(seconds=1))
        .execution_options(synchronize_session=False)
    )
    db_session.commit()


# --- service layer -----------------------------------------------------------


def test_acquire_lock_succeeds_when_none_exists(db_session):
    lock = acquire_lock("price_refresh", "price_refresh:a", 1800)

    assert lock.lock_name == "price_refresh"
    assert lock.owner_id == "price_refresh:a"
    assert lock.status == "active"
    assert events_by_type(db_session, "lock_acquired")


def test_acquire_lock_fails_while_active(db_session):
    acquire_lock("price_refresh", "price_refresh:a", 1800)

    with pytest.raises(LockHeldError) as exc_info:
        acquire_lock("price_refresh", "price_refresh:b", 1800)

    assert exc_info.value.lock_name == "price_refresh"
    assert exc_info.value.owner_id == "price_refresh:a"
    assert events_by_type(db_session, "lock_acquire_failed")


def test_acquire_lock_does_not_spam_logs_for_repeated_conflict_against_same_owner(db_session):
    acquire_lock("price_refresh", "price_refresh:a", 1800)

    for _ in range(3):
        with pytest.raises(LockHeldError):
            acquire_lock("price_refresh", "price_refresh:b", 1800)

    # Same still-active holder each time - only the first conflict logs.
    assert len(events_by_type(db_session, "lock_acquire_failed")) == 1


def test_expired_lock_can_be_reacquired(db_session):
    acquire_lock("market_workflow", "market_workflow:old", ttl_seconds=1)
    expire_lock(db_session, "market_workflow")

    lock = acquire_lock("market_workflow", "market_workflow:new", 3600)

    assert lock.owner_id == "market_workflow:new"
    assert lock.status == "active"


def test_release_requires_owner_id_match(db_session):
    acquire_lock("telegram_market_digest", "telegram_market_digest:a", 300)

    assert release_lock("telegram_market_digest", "telegram_market_digest:wrong") is False
    assert release_lock("telegram_market_digest", "telegram_market_digest:a") is True
    assert events_by_type(db_session, "lock_released")

    active = get_active_locks()
    assert not any(lock.lock_name == "telegram_market_digest" for lock in active)


def test_force_release_lock_releases_regardless_of_owner(db_session):
    acquire_lock("backup_restore", "backup_restore:a", 3600)

    released = force_release_lock("backup_restore")

    assert released is not None
    assert released.status == "released"
    warnings = events_by_type(db_session, "lock_force_released")
    assert len(warnings) == 1
    assert warnings[0].level == "warning"


def test_force_release_lock_returns_none_when_no_active_lock(db_session):
    assert force_release_lock("backup_restore") is None


def test_force_release_expired_locks_marks_expired_only(db_session):
    acquire_lock("data_retention_prune", "data_retention_prune:a", ttl_seconds=1)
    acquire_lock("portfolio_snapshot", "portfolio_snapshot:a", ttl_seconds=3600)
    expire_lock(db_session, "data_retention_prune")

    count = force_release_expired_locks()

    assert count == 1
    active_names = {lock.lock_name for lock in get_active_locks()}
    assert "data_retention_prune" not in active_names
    assert "portfolio_snapshot" in active_names
    assert events_by_type(db_session, "lock_expired_cleanup")


def test_get_lock_counts(db_session):
    acquire_lock("market_report_generation", "market_report_generation:a", ttl_seconds=1)
    acquire_lock("market_signal_snapshot", "market_signal_snapshot:a", ttl_seconds=3600)
    expire_lock(db_session, "market_report_generation")

    counts = get_lock_counts()
    assert counts.active == 2
    assert counts.expired_active == 1


def test_with_job_lock_acquires_and_releases(db_session):
    owner_holder = {}
    with with_job_lock("portfolio_snapshot") as owner_id:
        owner_holder["owner_id"] = owner_id
        assert any(lock.lock_name == "portfolio_snapshot" for lock in get_active_locks())

    assert owner_holder["owner_id"] is not None
    assert not any(lock.lock_name == "portfolio_snapshot" for lock in get_active_locks())


def test_with_job_lock_skip_lock_never_touches_the_table(db_session):
    with with_job_lock("portfolio_snapshot", skip_lock=True) as owner_id:
        assert owner_id is None
        assert get_active_locks() == []


def test_with_job_lock_raises_when_already_held(db_session):
    acquire_lock("portfolio_snapshot", "portfolio_snapshot:other", 600)

    with pytest.raises(LockHeldError):
        with with_job_lock("portfolio_snapshot"):
            raise AssertionError("should never enter the with-block body")


def test_make_owner_id_is_unique_per_call():
    assert make_owner_id("price_refresh") != make_owner_id("price_refresh")


# --- GET/POST /admin/job-locks ------------------------------------------------


def test_job_locks_list_requires_admin_token(db_session):
    plain_client = TestClient(app)
    response = plain_client.get("/admin/job-locks")
    assert response.status_code == 401


def test_job_locks_cleanup_requires_admin_token(db_session):
    plain_client = TestClient(app)
    response = plain_client.post("/admin/job-locks/cleanup-expired")
    assert response.status_code == 401


def test_job_locks_force_release_requires_admin_token(db_session):
    plain_client = TestClient(app)
    response = plain_client.post(
        "/admin/job-locks/market_workflow/force-release", json={"confirm": "RELEASE"}
    )
    assert response.status_code == 401


def test_list_job_locks_empty(client, db_session):
    response = client.get("/admin/job-locks")
    assert response.status_code == 200
    assert response.json() == {"locks": []}


def test_list_job_locks_returns_active_lock(client, db_session):
    acquire_lock("market_workflow", "market_workflow:abc", 3600, metadata={"source": "yuyutei"})

    response = client.get("/admin/job-locks")

    assert response.status_code == 200
    locks = response.json()["locks"]
    assert len(locks) == 1
    assert locks[0]["lock_name"] == "market_workflow"
    assert locks[0]["owner_id"] == "market_workflow:abc"
    assert locks[0]["status"] == "active"
    assert locks[0]["metadata"] == {"source": "yuyutei"}


def test_cleanup_expired_endpoint_returns_count(client, db_session):
    acquire_lock("data_retention_prune", "data_retention_prune:a", ttl_seconds=1)
    expire_lock(db_session, "data_retention_prune")

    response = client.post("/admin/job-locks/cleanup-expired")

    assert response.status_code == 200
    assert response.json() == {"cleaned_up_count": 1}


def test_cleanup_expired_endpoint_returns_zero_when_nothing_expired(client, db_session):
    response = client.post("/admin/job-locks/cleanup-expired")

    assert response.status_code == 200
    assert response.json() == {"cleaned_up_count": 0}


def test_force_release_requires_confirm(client, db_session):
    acquire_lock("market_workflow", "market_workflow:abc", 3600)

    response = client.post("/admin/job-locks/market_workflow/force-release", json={})

    assert response.status_code == 400


def test_force_release_rejects_wrong_confirm(client, db_session):
    acquire_lock("market_workflow", "market_workflow:abc", 3600)

    response = client.post(
        "/admin/job-locks/market_workflow/force-release", json={"confirm": "wrong"}
    )

    assert response.status_code == 400


def test_force_release_with_correct_confirm_releases_and_logs_warning(client, db_session):
    acquire_lock("market_workflow", "market_workflow:abc", 3600)

    response = client.post(
        "/admin/job-locks/market_workflow/force-release", json={"confirm": "RELEASE"}
    )

    assert response.status_code == 200
    assert response.json() == {"released": True, "lock_name": "market_workflow"}

    warnings = events_by_type(db_session, "lock_force_released")
    assert len(warnings) == 1
    assert warnings[0].level == "warning"
    assert warnings[0].context_json["lock_name"] == "market_workflow"


def test_force_release_returns_false_when_nothing_active(client, db_session):
    response = client.post(
        "/admin/job-locks/market_workflow/force-release", json={"confirm": "RELEASE"}
    )

    assert response.status_code == 200
    assert response.json() == {"released": False, "lock_name": "market_workflow"}


def test_force_release_unknown_lock_name_returns_404(client, db_session):
    response = client.post(
        "/admin/job-locks/not_a_real_lock/force-release", json={"confirm": "RELEASE"}
    )

    assert response.status_code == 404
