"""Every state-changing backend route must require an authenticated caller.

Two layers:

- The four /market/signal-events write routes (previously unauthenticated)
  now require X-Admin-Token: a missing/wrong token, or a signed-in user
  without it, gets 401 and the event row is left untouched; a valid admin
  token still succeeds.
- An inventory guard walks the whole application and fails if any
  POST/PUT/PATCH/DELETE route lacks an admin or user auth dependency, so a
  new unauthenticated write route cannot ship silently. The only exemption
  is the admin login endpoint, which establishes an identity rather than
  consuming one (see app.api.admin_login's module docstring).
"""

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app
from app.models import MarketSignalEvent
from app.settings import settings
from tests._auth_helpers import make_bearer_token
from tests.test_market_signal_events import make_event

ADMIN_TOKEN = "secret-token"

SIGNAL_EVENT_WRITES = [
    ("PATCH", "/market/signal-events/{id}", {"status": "watching", "notes": "x"}),
    ("POST", "/market/signal-events/{id}/dismiss", None),
    ("POST", "/market/signal-events/{id}/watch", None),
    ("POST", "/market/signal-events/{id}/resolve", None),
]


@pytest.fixture()
def raw_client(db_session, monkeypatch):
    """No default headers; a configured ADMIN_TOKEN outside development, so
    require_admin_token's dev-mode bypass cannot mask a missing guard."""
    monkeypatch.setattr(settings, "ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)
    return TestClient(app)


def _send(client, method, path, body, headers=None):
    return client.request(method, path, json=body, headers=headers or {})


def _assert_unchanged(db_session, event_id):
    db_session.expire_all()
    event = db_session.get(MarketSignalEvent, event_id)
    assert event.status == "open"
    assert event.notes is None
    assert event.dismissed_at is None
    assert event.resolved_at is None


@pytest.mark.parametrize("method,path,body", SIGNAL_EVENT_WRITES)
def test_signal_event_write_rejects_missing_token(raw_client, db_session, method, path, body):
    event = make_event(db_session, status="open")

    response = _send(raw_client, method, path.format(id=event.id), body)

    assert response.status_code == 401
    _assert_unchanged(db_session, event.id)


@pytest.mark.parametrize("method,path,body", SIGNAL_EVENT_WRITES)
def test_signal_event_write_rejects_invalid_token(raw_client, db_session, method, path, body):
    event = make_event(db_session, status="open")

    response = _send(
        raw_client, method, path.format(id=event.id), body, {"X-Admin-Token": "wrong-token"}
    )

    assert response.status_code == 401
    _assert_unchanged(db_session, event.id)


@pytest.mark.parametrize("method,path,body", SIGNAL_EVENT_WRITES)
def test_signal_event_write_rejects_user_session_without_admin_token(
    raw_client, db_session, method, path, body
):
    event = make_event(db_session, status="open")

    response = _send(
        raw_client,
        method,
        path.format(id=event.id),
        body,
        {"Authorization": f"Bearer {make_bearer_token()}"},
    )

    assert response.status_code == 401
    _assert_unchanged(db_session, event.id)


@pytest.mark.parametrize("method,path,body", SIGNAL_EVENT_WRITES)
def test_signal_event_write_accepts_admin_token(raw_client, db_session, method, path, body):
    event = make_event(db_session, status="open")

    response = _send(
        raw_client, method, path.format(id=event.id), body, {"X-Admin-Token": ADMIN_TOKEN}
    )

    assert response.status_code == 200
    assert response.json()["id"] == event.id


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
    assert "/market/signal-events/{event_id}/dismiss" in paths
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
