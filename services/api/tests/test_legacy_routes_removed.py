"""Collector v1 S1 removed the legacy analyst, dashboard, search and market
workflow endpoints. Every one of them must now be absent: 404 even for a
caller holding both the admin token and a collector session, so nothing is
merely hidden behind auth."""

import pytest

from app.main import app

REMOVED = [
    ("GET", "/admin/market-workflow-runs"),
    ("GET", "/admin/market-workflow-runs/1"),
    ("GET", "/analytics/buy-decisions"),
    ("GET", "/analytics/digest"),
    ("GET", "/analytics/digest/latest"),
    ("GET", "/analytics/digest/reports"),
    ("GET", "/analytics/digest/reports/1"),
    ("GET", "/analytics/grading"),
    ("GET", "/analytics/portfolio-risk"),
    ("GET", "/analytics/sell-decisions"),
    ("GET", "/collector/activity/summary"),
    ("GET", "/dashboard/overview"),
    ("GET", "/dashboard/preferences"),
    ("PATCH", "/dashboard/preferences"),
    ("GET", "/market/opportunities"),
    ("GET", "/market/report/latest"),
    ("GET", "/market/reports"),
    ("GET", "/market/reports/1"),
    ("GET", "/market/signal-events"),
    ("GET", "/market/signal-events/1"),
    ("PATCH", "/market/signal-events/1"),
    ("POST", "/market/signal-events/1/dismiss"),
    ("POST", "/market/signal-events/1/resolve"),
    ("POST", "/market/signal-events/1/watch"),
    ("GET", "/market/signals"),
    ("GET", "/search"),
    ("GET", "/search/suggestions"),
    ("POST", "/admin/actions/generate-analytics-digest"),
    ("POST", "/admin/actions/generate-market-report"),
    ("POST", "/admin/actions/run-market-workflow"),
    ("POST", "/admin/actions/send-market-report-digest"),
    ("POST", "/admin/actions/snapshot-market-signals"),
]


@pytest.mark.parametrize("method,path", REMOVED)
def test_removed_route_is_not_found(client, method, path):
    response = client.request(method, path, json={})

    assert response.status_code == 404


def test_removed_routes_are_absent_from_openapi():
    paths = app.openapi()["paths"]
    for method, path in REMOVED:
        template = path.replace("/1", "/{id}")
        assert not any(
            p.rstrip("/").replace("{report_id}", "{id}").replace("{run_id}", "{id}").replace(
                "{event_id}", "{id}"
            )
            == template
            and method.lower() in ops
            for p, ops in paths.items()
        ), f"{method} {path}"


def test_kept_neighbours_remain():
    paths = app.openapi()["paths"]
    for path in (
        "/market/movers",
        "/analytics/collection",
        "/analytics/wishlist",
        "/analytics/market-value",
        "/collector/activity",
        "/admin/actions/refresh-prices",
        "/admin/actions/snapshot-portfolio",
        "/admin/actions/full-market-refresh",
    ):
        assert path in paths, path
