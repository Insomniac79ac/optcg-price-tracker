from datetime import datetime, timezone

from app.models import PriceRefreshRun


def make_run(db_session, **overrides) -> PriceRefreshRun:
    fields = dict(
        status="completed",
        scraping_mode="mock",
        source_filter="yuyutei",
        limit_count=10,
        dry_run=False,
        mappings_checked=5,
        snapshots_created=5,
        observations_parsed=8,
        observations_inserted=8,
        observations_skipped_duplicate=0,
        mappings_failed=0,
        error_message=None,
    )
    fields.update(overrides)
    run = PriceRefreshRun(**fields)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def test_list_refresh_runs_empty(client, db_session):
    response = client.get("/admin/refresh-runs")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_list_refresh_runs_returns_runs(client, db_session):
    run = make_run(db_session)

    response = client.get("/admin/refresh-runs")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == run.id
    assert item["status"] == "completed"
    assert item["scraping_mode"] == "mock"
    assert item["source_filter"] == "yuyutei"
    assert item["limit_count"] == 10
    assert item["dry_run"] is False
    assert item["mappings_checked"] == 5
    assert item["snapshots_created"] == 5
    assert item["observations_parsed"] == 8
    assert item["observations_inserted"] == 8
    assert item["observations_skipped_duplicate"] == 0
    assert item["mappings_failed"] == 0
    assert item["error_message"] is None
    assert item["started_at"] is not None


def test_list_refresh_runs_orders_newest_first(client, db_session):
    older = make_run(db_session, started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    newer = make_run(db_session, started_at=datetime(2026, 1, 2, tzinfo=timezone.utc))

    response = client.get("/admin/refresh-runs")
    body = response.json()

    assert [item["id"] for item in body["items"]] == [newer.id, older.id]


def test_list_refresh_runs_filters_by_status(client, db_session):
    make_run(db_session, status="completed")
    make_run(db_session, status="failed", error_message="boom")

    response = client.get("/admin/refresh-runs", params={"status": "failed"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "failed"
    assert body["items"][0]["error_message"] == "boom"


def test_list_refresh_runs_filters_by_source_filter(client, db_session):
    make_run(db_session, source_filter="yuyutei")
    make_run(db_session, source_filter="snkrdunk")

    response = client.get("/admin/refresh-runs", params={"source_filter": "snkrdunk"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["source_filter"] == "snkrdunk"


def test_list_refresh_runs_rejects_invalid_status(client, db_session):
    response = client.get("/admin/refresh-runs", params={"status": "bogus"})
    assert response.status_code == 400


def test_list_refresh_runs_pagination(client, db_session):
    for _ in range(5):
        make_run(db_session)

    response = client.get("/admin/refresh-runs", params={"limit": 2, "offset": 0})
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2

    response = client.get("/admin/refresh-runs", params={"limit": 2, "offset": 4})
    body = response.json()
    assert len(body["items"]) == 1


def test_get_refresh_run_returns_run(client, db_session):
    run = make_run(db_session, mappings_failed=2, status="completed_with_warnings")

    response = client.get(f"/admin/refresh-runs/{run.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == run.id
    assert body["status"] == "completed_with_warnings"
    assert body["mappings_failed"] == 2


def test_get_refresh_run_not_found(client, db_session):
    response = client.get("/admin/refresh-runs/999999")
    assert response.status_code == 404
