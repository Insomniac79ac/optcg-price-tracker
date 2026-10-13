"""Every state-changing backend route must require an authenticated caller.

An inventory guard walks the whole application and fails if any
POST/PUT/PATCH/DELETE route lacks an admin or user auth dependency, so a new
unauthenticated write route cannot ship silently. The only exemption is the
admin login endpoint, which establishes an identity rather than consuming one
(see app.api.admin_login's module docstring).

The /market/signal-events write routes this file used to exercise were
removed with the legacy market signals in Collector v1 S1; see
tests/test_legacy_routes_removed.py.
"""

from fastapi.routing import APIRoute

from app.main import app


# --- Inventory guard ---------------------------------------------------------

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Dependencies that authenticate the caller. require_admin_actor and
# file_job_access call require_admin_token/require_current_user directly
# rather than through Depends, so they are recognized by name too.
AUTH_DEPENDENCIES = {
    "require_admin_token",
    "require_admin_actor",
    "require_current_user",
    "file_job_access",
}

# (method, path) pairs that are intentionally unauthenticated.
UNAUTHENTICATED_WRITE_ALLOWLIST = {
    # Admin Credentials login: establishes the admin identity; throttled.
    ("POST", "/auth/admin/verify"),
}


def _iter_api_routes(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            # FastAPI >= 0.140 wraps included routers; include_router() in
            # app.main passes no include-time dependencies or prefixes.
            yield from _iter_api_routes(route.original_router.routes)


def _dependency_names(dependant, names):
    if dependant.call is not None:
        names.add(getattr(dependant.call, "__name__", ""))
    for sub in dependant.dependencies:
        _dependency_names(sub, names)
    return names


def test_inventory_walker_sees_every_router():
    paths = {route.path for route in _iter_api_routes(app.routes)}
    # One representative per kind of router, so a walker that silently stops
    # descending cannot make the guard below vacuous.
    assert "/collector/notes/{note_id}" in paths
    assert "/admin/cache/clear" in paths
    assert "/collection" in paths
    assert "/auth/admin/verify" in paths


def test_every_mutating_route_requires_auth():
    unauthenticated = []
    for route in _iter_api_routes(app.routes):
        for method in sorted(route.methods & MUTATING_METHODS):
            if (method, route.path) in UNAUTHENTICATED_WRITE_ALLOWLIST:
                continue
            if not _dependency_names(route.dependant, set()) & AUTH_DEPENDENCIES:
                unauthenticated.append(f"{method} {route.path}")

    assert unauthenticated == []
