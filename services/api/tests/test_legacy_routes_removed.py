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
        "/analytics/market-value",
        "/admin/actions/refresh-prices",
        "/admin/actions/full-market-refresh",
    ):
        assert path in paths, path


# Collector v1 S8 removed the legacy collection, wishlist, grading, tags,
# groups, notes and activity routers, the per-user collection and wishlist
# analytics and the admin collection snapshot. The v1 accounts API (/me/...)
# replaces them.
S8_REMOVED = [
    ("GET", "/collection"),
    ("POST", "/collection"),
    ("GET", "/collection/summary"),
    ("GET", "/collection/valuation"),
    ("GET", "/collection/valuation/history"),
    ("GET", "/collection/export.csv"),
    ("POST", "/collection/export.csv/job"),
    ("POST", "/collection/import.csv"),
    ("GET", "/collection/1"),
    ("PATCH", "/collection/1"),
    ("DELETE", "/collection/1"),
    ("POST", "/collection/1/tags/1"),
    ("POST", "/collection/1/groups/1"),
    ("GET", "/wishlist"),
    ("POST", "/wishlist"),
    ("GET", "/wishlist/summary"),
    ("GET", "/wishlist/export.csv"),
    ("POST", "/wishlist/import.csv"),
    ("PATCH", "/wishlist/1"),
    ("POST", "/wishlist/1/mark-purchased"),
    ("POST", "/wishlist/1/convert-to-collection"),
    ("GET", "/grading/submissions"),
    ("POST", "/grading/submissions"),
    ("GET", "/grading/summary"),
    ("GET", "/collector/tags"),
    ("POST", "/collector/groups"),
    ("GET", "/collector/notes"),
    ("GET", "/collector/activity"),
    ("POST", "/cards/1/tags/1"),
    ("DELETE", "/cards/1/tags/1"),
    ("GET", "/analytics/collection"),
    ("GET", "/analytics/wishlist"),
    ("POST", "/admin/actions/snapshot-portfolio"),
]

S8_PREFIXES = ("/collection", "/wishlist", "/grading", "/collector", "/analytics/collection", "/analytics/wishlist")


@pytest.mark.parametrize("method,path", S8_REMOVED)
def test_s8_removed_route_is_not_found(client, method, path):
    response = client.request(method, path, json={})

    assert response.status_code == 404
    assert not any(
        getattr(route, "path", "") == path and method in getattr(route, "methods", ())
        for route in app.routes
    )


def test_s8_removed_routes_are_absent_from_openapi():
    paths = app.openapi()["paths"]
    assert not [p for p in paths if p.startswith(S8_PREFIXES)]
    assert not [p for p in paths if p.startswith("/cards/") and "/tags/" in p]
    assert "/admin/actions/snapshot-portfolio" not in paths
