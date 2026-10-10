"""Read routes that return private or user-derived data require an
authenticated caller.

Two layers:

- The market-intelligence and analytics-digest read routes (signal events,
  signals, opportunities, market reports, stored analytics digests) are
  admin-only: they are market-wide and carry the global owned quantity, the
  portfolio snapshot and wishlist/collection aggregates summed across every
  user. A missing/wrong token, or a signed-in collector without it, gets 401;
  a valid admin token gets 200. A cached copy primed by an admin is never
  served to an unauthenticated caller.
- An inventory guard walks the whole application: every GET route without an
  auth dependency must be on an explicit public allowlist, and no public
  route's response model may carry a user-derived field. A new public route
  that returns collection, wishlist, portfolio or ownership data fails here.
"""

import re
import typing

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.main import app
from app.services import cache as cache_module
from app.services.analytics_digest import generate_analytics_digest
from app.services.market_report import generate_market_report
from app.settings import settings
from tests._auth_helpers import make_bearer_token
from tests.test_market_signal_events import make_event
from tests.test_mutating_route_auth import _dependency_names, _iter_api_routes

ADMIN_TOKEN = "secret-token"

# path template -> fixture key that supplies the {id}, if any.
ADMIN_ONLY_READS = [
    "/market/signals",
    "/market/signal-events",
    "/market/signal-events/{event}",
    "/market/opportunities",
    "/market/report/latest",
    "/market/reports",
    "/market/reports/{market_report}",
    "/analytics/digest/latest",
    "/analytics/digest/reports",
    "/analytics/digest/reports/{digest_report}",
]

# The same routes as FastAPI declares them, for the inventory guard below.
ADMIN_ONLY_READ_TEMPLATES = {
    "/market/signals",
    "/market/signal-events",
    "/market/signal-events/{event_id}",
    "/market/opportunities",
    "/market/report/latest",
    "/market/reports",
    "/market/reports/{report_id}",
    "/analytics/digest/latest",
    "/analytics/digest/reports",
    "/analytics/digest/reports/{report_id}",
}


@pytest.fixture()
def raw_client(db_session, monkeypatch):
    """No default headers; a configured ADMIN_TOKEN outside development, so
    require_admin_token's dev-mode bypass cannot mask a missing guard. The
    memory cache is on so a primed cache entry is actually in play."""
    monkeypatch.setattr(settings, "ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    cache_module.reset_state_for_tests()
    yield TestClient(app)
    cache_module.reset_state_for_tests()


@pytest.fixture()
def seeded(db_session):
    return {
        "event": make_event(db_session, status="open").id,
        "market_report": generate_market_report(db_session).id,
        "digest_report": generate_analytics_digest(db_session).id,
    }


def _url(template, seeded):
    return template.format(**seeded)


@pytest.mark.parametrize("template", ADMIN_ONLY_READS)
def test_private_read_rejects_missing_token(raw_client, seeded, template):
    assert raw_client.get(_url(template, seeded)).status_code == 401


@pytest.mark.parametrize("template", ADMIN_ONLY_READS)
def test_private_read_rejects_invalid_token(raw_client, seeded, template):
    response = raw_client.get(_url(template, seeded), headers={"X-Admin-Token": "wrong-token"})
    assert response.status_code == 401


@pytest.mark.parametrize("template", ADMIN_ONLY_READS)
def test_private_read_rejects_collector_session_without_admin_token(raw_client, seeded, template):
    response = raw_client.get(
        _url(template, seeded), headers={"Authorization": f"Bearer {make_bearer_token()}"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("template", ADMIN_ONLY_READS)
def test_private_read_accepts_admin_token(raw_client, seeded, template):
    response = raw_client.get(_url(template, seeded), headers={"X-Admin-Token": ADMIN_TOKEN})
    assert response.status_code == 200


@pytest.mark.parametrize("template", ADMIN_ONLY_READS)
def test_cached_private_read_is_not_served_unauthenticated(raw_client, seeded, template):
    url = _url(template, seeded)
    admin = {"X-Admin-Token": ADMIN_TOKEN}
    assert raw_client.get(url, headers=admin).status_code == 200
    assert raw_client.get(url, headers=admin).status_code == 200

    response = raw_client.get(url)

    assert response.status_code == 401
    assert "X-Cache" not in response.headers


def test_dashboard_overview_withholds_admin_only_widgets(client, db_session):
    """The collector dashboard must not become a side door to the same data."""
    make_event(db_session, status="open")
    generate_market_report(db_session)

    widgets = client.get("/dashboard/overview").json()["widgets"]

    assert widgets["top_opportunities"]["opportunities"] == []
    assert widgets["market_report"]["report_id"] is None
    assert widgets["market_report"]["deterministic_summary_lines"] == []
    assert widgets["recent_signal_events"]["events"] == []


# --- Inventory guard ---------------------------------------------------------

AUTH_DEPENDENCIES = {
    "require_admin_token",
    "require_admin_actor",
    "require_current_user",
    "file_job_access",
}

# Every GET route that answers without authentication, grouped by why that is
# safe. Adding a route here is a deliberate review that it returns nothing
# derived from any user's collection, wishlist, grading, notes or ownership.
PUBLIC_READ_ALLOWLIST = {
    # Catalogue and per-print market data (public collector product).
    "/cards",  # optional session: the caller's own tags only
    "/cards/catalogue",
    "/cards/{card_id}",  # optional session: the caller's own tags only
    "/cards/{card_id}/market-index",
    "/cards/{card_id}/prices",
    "/prints",
    "/prints/{print_id}",
    "/prints/{print_id}/analytics",
    "/prints/{print_id}/market-index",
    "/prints/{print_id}/prices",
    "/prints/{print_id}/series",
    "/releases",
    "/market/movers",
    # Market landscape, Market Index and Market Value (public /analytics page).
    "/analytics/index",
    "/analytics/index/composition",
    "/analytics/index/movers",
    "/analytics/market-value",
    "/analytics/market-value/most-valuable",
    "/analytics/market-value/movers",
    "/analytics/market-value/releases",
    "/analytics/market/bases",
    "/analytics/market/filters",
    "/analytics/market/overview",
    # Operational.
    "/health",
    "/version",
    "/auth/admin/status",  # reports only whether this caller's session is admin
}

# Public routes whose untyped response cannot be field-checked below.
UNTYPED_PUBLIC_READS = {"/health", "/auth/admin/status"}

# A field name that suggests data derived from users' private records.
USER_DERIVED_FIELD = re.compile(
    r"owned|user|collection|wishlist|portfolio|notes?\b|purchase|grading_sub|email|pnl|holding",
    re.IGNORECASE,
)
# Field names that match the pattern but are not user-derived.
NOT_USER_DERIVED = {
    # Whether the displayed image is an asset Card Pirate stores itself.
    ("DisplayImageOut", "owned_asset_selected"),
}

def _response_models(annotation, seen):
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return
        seen.add(annotation)
        for field in annotation.model_fields.values():
            _response_models(field.annotation, seen)
    for arg in typing.get_args(annotation):
        _response_models(arg, seen)


def _user_derived_fields(response_model):
    seen = set()
    _response_models(response_model, seen)
    return sorted(
        f"{model.__name__}.{name}"
        for model in seen
        for name in model.model_fields
        if USER_DERIVED_FIELD.search(name) and (model.__name__, name) not in NOT_USER_DERIVED
    )


def _get_routes():
    return [route for route in _iter_api_routes(app.routes) if "GET" in route.methods]


def _is_authenticated(route):
    return bool(_dependency_names(route.dependant, set()) & AUTH_DEPENDENCIES)


def test_every_unauthenticated_read_is_explicitly_public():
    unauthenticated = {route.path for route in _get_routes() if not _is_authenticated(route)}

    assert sorted(unauthenticated - PUBLIC_READ_ALLOWLIST) == []
    # A stale allowlist entry would silently pre-approve a future route.
    assert sorted(PUBLIC_READ_ALLOWLIST - unauthenticated) == []


def test_admin_only_reads_are_authenticated():
    by_path = {route.path: route for route in _get_routes()}
    assert ADMIN_ONLY_READ_TEMPLATES <= set(by_path)
    for path in ADMIN_ONLY_READ_TEMPLATES:
        names = _dependency_names(by_path[path].dependant, set())
        assert "require_admin_token" in names, path


def test_public_reads_return_no_user_derived_fields():
    leaks = {}
    for route in _get_routes():
        if route.path not in PUBLIC_READ_ALLOWLIST or route.path in UNTYPED_PUBLIC_READS:
            continue
        model = route.response_model
        assert model is not None, f"{route.path} needs a response_model to be field-checked"
        fields = _user_derived_fields(model)
        if fields:
            leaks[route.path] = fields

    assert leaks == {}


def test_user_derived_field_check_flags_the_admin_only_reads():
    """Keeps the field check honest: it must recognise every route this
    change moved behind admin auth, or it would not catch the next one."""
    by_path = {route.path: route for route in _get_routes()}
    for path in ADMIN_ONLY_READ_TEMPLATES:
        assert _user_derived_fields(by_path[path].response_model), path
