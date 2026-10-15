"""Read routes that return private or user-derived data require an
authenticated caller.

An inventory guard walks the whole application: every GET route without an
auth dependency must be on an explicit public allowlist, and no public
route's response model may carry a user-derived field. A new public route
that returns collection, wishlist, portfolio or ownership data fails here.

The admin-only market-intelligence and analytics-digest reads this file used
to exercise were removed with the legacy features in Collector v1 S1; see
tests/test_legacy_routes_removed.py.
"""

import re
import typing

from pydantic import BaseModel

from app.main import app
from tests.test_mutating_route_auth import _dependency_names, _iter_api_routes

# Private reads that carry user-derived fields, as FastAPI declares them.
# They anchor the inventory guard and keep the field check honest.
PRIVATE_READ_TEMPLATES = {
    "/me/collection",
    "/me/watchlist",
}


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
    "/cards/{card_id}/print-destination",  # retired /cards/{id} redirect target (S6)
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


def test_private_reads_are_authenticated():
    by_path = {route.path: route for route in _get_routes()}
    assert PRIVATE_READ_TEMPLATES <= set(by_path)
    for path in PRIVATE_READ_TEMPLATES:
        assert _is_authenticated(by_path[path]), path


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


def test_user_derived_field_check_flags_the_private_reads():
    """Keeps the field check honest: it must recognise the known private
    reads, or it would not catch the next public route that leaks one."""
    by_path = {route.path: route for route in _get_routes()}
    for path in PRIVATE_READ_TEMPLATES:
        assert _user_derived_fields(by_path[path].response_model), path
