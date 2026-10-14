"""Collector v1 S5 (PLAN §D1, §D4; owner decision Q2): API side.

- CORS is restricted to the staging origin and refuses other origins;
  outside development an unset CORS_ALLOWED_ORIGINS no longer means "*".
- GET /me/profile for the account page.
- None of it is a collector runtime input (import-graph check).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app import web_cors
from app.accounts.config import FLAG
from app.main import app as api_app
from app.settings import settings
from tests._auth_helpers import make_bearer_token

STAGING = "https://optcg-price-tracker-staging.vercel.app"
EVIL = "https://evil.example"
REPO = Path(__file__).resolve().parents[3]


def _cors_client() -> TestClient:
    """A tiny app wearing exactly the middleware options the API uses."""
    probe = FastAPI()
    probe.add_middleware(CORSMiddleware, **web_cors.cors_options())

    @probe.get("/health")
    def health():
        return {"ok": True}

    @probe.delete("/me")
    def delete_me():
        return {"ok": True}

    return TestClient(probe)


@pytest.fixture
def environment(monkeypatch):
    def set_env(app_env, origins=None, regex=None):
        monkeypatch.setattr(settings, "ENVIRONMENT", None)
        monkeypatch.setattr(settings, "APP_ENV", app_env)
        monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", origins)
        monkeypatch.setattr(settings, "CORS_ALLOW_ORIGIN_REGEX", regex)

    return set_env


# --------------------------------------------------------------------------
# CORS policy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "app_env, origins, expected",
    [
        ("staging", STAGING, [STAGING]),
        ("staging", f"{STAGING}, https://other.example", [STAGING, "https://other.example"]),
        ("staging", None, [STAGING]),
        ("staging", "", [STAGING]),
        ("development", None, ["*"]),
        ("production", None, []),
        (None, None, []),
        ("", None, []),
    ],
)
def test_allowed_origins(environment, app_env, origins, expected):
    environment(app_env, origins)
    assert web_cors.allowed_origins() == expected


def test_credentials_are_never_allowed_cross_origin(environment):
    environment("staging", STAGING)
    assert web_cors.cors_options()["allow_credentials"] is False


@pytest.mark.parametrize("origins", [STAGING, None])
def test_staging_refuses_another_origin_and_allows_its_own(environment, origins):
    environment("staging", origins)
    client = _cors_client()

    allowed = client.get("/health", headers={"Origin": STAGING})
    assert allowed.headers.get("access-control-allow-origin") == STAGING

    refused = client.get("/health", headers={"Origin": EVIL})
    assert "access-control-allow-origin" not in refused.headers

    preflight = client.options(
        "/me",
        headers={
            "Origin": EVIL,
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers

    own_preflight = client.options(
        "/me",
        headers={"Origin": STAGING, "Access-Control-Request-Method": "DELETE"},
    )
    assert own_preflight.status_code == 200
    assert own_preflight.headers["access-control-allow-origin"] == STAGING


def test_production_without_the_variable_allows_no_browser_origin(environment):
    environment("production", None)
    client = _cors_client()
    for origin in (STAGING, EVIL):
        assert "access-control-allow-origin" not in client.get("/health", headers={"Origin": origin}).headers


def test_the_api_app_uses_the_web_cors_policy():
    cors = [m for m in api_app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1
    assert cors[0].kwargs["allow_credentials"] is False
    assert set(cors[0].kwargs) == set(web_cors.cors_options())


# --------------------------------------------------------------------------
# GET /me/profile
# --------------------------------------------------------------------------


def test_profile_returns_the_google_identity_and_member_since(client, db_session, monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    token = make_bearer_token(google_sub="s5-sub", email="nami@example.com", name="Nami")
    response = client.get("/me/profile", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "nami@example.com"
    assert body["name"] == "Nami"
    assert body["member_since"]
    assert set(body) == {"email", "name", "member_since"}
    assert response.headers["cache-control"] == "private, no-store"


def test_profile_needs_a_token_and_the_flag(client, db_session, monkeypatch):
    client.headers.pop("Authorization", None)
    monkeypatch.delenv(FLAG, raising=False)
    assert client.get("/me/profile").status_code == 404
    monkeypatch.setenv(FLAG, "true")
    assert client.get("/me/profile").status_code == 401


# --------------------------------------------------------------------------
# Collector import graph: S5 is not a collector release
# --------------------------------------------------------------------------

S5_API_PATHS = [
    "services/api/app/web_cors.py",
    "services/api/app/main.py",
    "services/api/app/accounts/router.py",
    "services/api/app/accounts/schemas.py",
]


@pytest.fixture(scope="module")
def graph():
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git checkout unavailable")
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import collector_runtime_inputs as tool
    finally:
        sys.path.remove(str(REPO / "scripts"))
    return tool, {name: tool.runtime_inputs(head, name) for name in tool.COLLECTORS}


@pytest.mark.parametrize("collector", ["snkrdunk", "yuyutei"])
def test_no_collector_reaches_the_s5_files(graph, collector):
    tool, inputs = graph
    reached = inputs[collector]
    assert "services/api/app/models/__init__.py" in reached  # the graph is real
    for path in S5_API_PATHS:
        assert (REPO / path).is_file(), path
        assert path not in reached, f"{collector} imports {path}"
        assert not tool.counts(path, reached), f"{path} would be a {collector} release"
    # The API image's Dockerfile is not one of the collector's paths at all.
    assert not any(
        "deploy/railway/api.Dockerfile".startswith(prefix) for prefix in tool.full_paths(collector)
    )
