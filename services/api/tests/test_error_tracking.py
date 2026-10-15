"""Sentry error tracking for the API (Collector v1 S2, plan §F2 and §A rule 5).

``sentry_sdk`` is replaced by a fake module in every test, so the suite needs
no extra dependency and proves the no-op path imports nothing.
"""

from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import error_tracking
from app.error_tracking import init_error_tracking, init_options, scrub_event
from app.main import app

REPO = Path(__file__).resolve().parents[3]
DSN = "https://publickey@o123.ingest.us.sentry.io/456"


@pytest.fixture()
def fake_sdk(monkeypatch):
    calls: list[dict] = []
    module = types.ModuleType("sentry_sdk")
    module.init = lambda **kwargs: calls.append(kwargs)
    monkeypatch.setitem(sys.modules, "sentry_sdk", module)
    return calls


def test_no_dsn_is_a_no_op_and_never_imports_the_sdk(monkeypatch):
    imported: list[str] = []
    real_import = builtins.__import__

    def spy(name, *args, **kwargs):
        if name.startswith("sentry_sdk"):
            imported.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", spy)
    assert init_error_tracking({}) is False
    assert init_error_tracking({"SENTRY_DSN": "   "}) is False
    assert imported == []


def test_dsn_without_the_package_logs_and_stays_off(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)  # import raises ImportError
    assert init_error_tracking({"SENTRY_DSN": DSN}) is False
    assert "sentry-sdk is not installed" in caplog.text


def test_dsn_initialises_without_pii_tracing_bodies_or_locals(fake_sdk):
    environ = {"SENTRY_DSN": DSN, "RAILWAY_GIT_COMMIT_SHA": "a" * 40, "GIT_COMMIT": "unknown"}
    assert init_error_tracking(environ) is True
    assert fake_sdk == [
        {
            "dsn": DSN,
            "environment": "staging",
            "release": "a" * 40,
            "send_default_pii": False,
            "include_local_variables": False,
            "max_request_body_size": "never",
            "traces_sample_rate": 0.0,
            "auto_session_tracking": False,
            "before_send": scrub_event,
        }
    ]


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"RAILWAY_GIT_COMMIT_SHA": "abc1234"}, "abc1234"),
        ({"GIT_COMMIT": "def5678"}, "def5678"),
        ({"GIT_COMMIT": "unknown"}, None),
        ({}, None),
    ],
)
def test_release_is_the_git_sha(environ, expected):
    assert init_options(DSN, environ)["release"] == expected


def test_environment_override():
    assert init_options(DSN, {"SENTRY_ENVIRONMENT": "staging"})["environment"] == "staging"


def test_scrub_event_removes_credentials_cookies_bodies_queries_and_user():
    event = {
        "request": {
            "url": "https://api.example/me/collection?token=abc#frag",
            "query_string": "token=abc",
            "cookies": {"session": "secret"},
            "data": {"paid_jpy_per_card": 1200},
            "headers": {
                "Authorization": "Bearer eyJhbGciOi",
                "cookie": "session=secret",
                "Set-Cookie": "a=b",
                "X-Admin-Token": "admin-secret",
                "X-Admin-Actor-Assertion": "signed",
                "Proxy-Authorization": "Basic x",
                "User-Agent": "pytest",
            },
        },
        "user": {"id": 42, "email": "a@b.co", "ip_address": "1.2.3.4"},
        "breadcrumbs": {"values": [{"data": {"url": "/x?email=a@b.co", "method": "GET"}}, {"message": "m"}]},
    }
    out = scrub_event(event, hint=None)
    assert out["request"] == {"url": "https://api.example/me/collection", "headers": {"User-Agent": "pytest"}}
    assert "user" not in out
    assert out["breadcrumbs"]["values"][0]["data"] == {"url": "/x", "method": "GET"}
    flat = repr(out)
    for secret in ("secret", "Bearer", "a@b.co", "1200", "token=", "eyJ"):
        assert secret not in flat


def test_scrub_event_tolerates_minimal_events():
    assert scrub_event({}) == {}
    assert scrub_event({"request": {}, "breadcrumbs": []}) == {"request": {}, "breadcrumbs": []}


def test_sentry_test_endpoint_requires_the_admin_token():
    response = TestClient(app).get("/admin/observability/sentry-test")
    assert response.status_code == 401


def _admin_token(client) -> str:
    # The conftest `client` fixture carries the test admin token. Importing
    # tests.conftest directly would re-run it as a second module.
    return client.headers["X-Admin-Token"]


def test_sentry_test_endpoint_fails_on_purpose_for_an_admin(client):
    token = _admin_token(client)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/admin/observability/sentry-test", headers={"X-Admin-Token": token})
    assert response.status_code == 500


def test_sentry_test_endpoint_is_get_only_and_hidden_from_openapi(client):
    token = _admin_token(client)
    client = TestClient(app, raise_server_exceptions=False)
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/admin/observability/sentry-test", headers={"X-Admin-Token": token})
        assert response.status_code == 405, method
    assert "/admin/observability/sentry-test" not in app.openapi()["paths"]


# --- delivery (plan §A rule 5) ------------------------------------------------


def test_sdk_is_only_in_the_observability_requirements():
    observability = (REPO / "services/api/requirements-observability.txt").read_text()
    assert "sentry-sdk==" in observability
    for path in [
        "services/api/requirements.txt",
        "services/api/pyproject.toml",
        "services/snkrdunk_collector/requirements.txt",
        "services/yuyutei_collector/requirements.txt",
        "services/worker/requirements.txt",
    ]:
        file = REPO / path
        if file.exists():
            assert "sentry" not in file.read_text().lower(), path


def test_only_the_api_railway_image_installs_it():
    installers = sorted(
        str(path.relative_to(REPO))
        for path in [*REPO.glob("deploy/**/*Dockerfile*"), *REPO.glob("services/**/Dockerfile*")]
        if "requirements-observability" in path.read_text()
    )
    assert installers == ["deploy/railway/api.Dockerfile"]


def test_only_main_imports_error_tracking():
    importers = sorted(
        str(path.relative_to(REPO / "services/api"))
        for path in (REPO / "services/api/app").rglob("*.py")
        if "error_tracking" in path.read_text() and path.name != "error_tracking.py"
    )
    assert importers == ["app/main.py"]
    assert "import sentry_sdk" not in Path(error_tracking.__file__).read_text().split("def init_error_tracking")[0]


def _integrity_error_text():
    """The real text of a unique-constraint failure on the users table."""
    from sqlalchemy import create_engine
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from app.db import Base
    from app.models import User

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__])
    with Session(engine) as db:
        db.add(User(google_sub="sub-1", email="collector@example.com", name="Collector Name"))
        db.commit()
        db.add(User(google_sub="sub-1", email="collector@example.com", name="Collector Name"))
        try:
            db.commit()
        except IntegrityError as error:
            return str(error)
    raise AssertionError("expected an IntegrityError")


def test_scrub_event_redacts_sql_parameters_and_emails_from_messages():
    text = _integrity_error_text()
    assert "collector@example.com" in text and "Collector Name" in text  # the leak being fixed
    pg = 'duplicate key value violates unique constraint "users_email_key"\nDETAIL:  Key (email)=(collector@example.com) already exists.'
    event = {
        "exception": {"values": [{"type": "IntegrityError", "value": text}, {"type": "UniqueViolation", "value": pg}]},
        "logentry": {"message": "lookup for %s failed", "params": ["collector@example.com"]},
        "message": "user collector@example.com",
        "breadcrumbs": {"values": [{"message": "INSERT ... [parameters: ('sub-1', 'collector@example.com', 'Collector Name')]"}]},
    }

    out = repr(scrub_event(event))

    assert "collector@example.com" not in out
    assert "Collector Name" not in out
    assert "sub-1" not in out
    assert "IntegrityError" in out and "UNIQUE constraint failed" in out  # the useful part stays


def test_redact_text_leaves_ordinary_messages_alone():
    from app.error_tracking import redact_text

    assert redact_text("Rate limit exceeded for group 'admin'") == "Rate limit exceeded for group 'admin'"
    assert redact_text(None) is None
