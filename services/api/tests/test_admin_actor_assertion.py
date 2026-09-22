from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import jwt
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.admin_actor import (
    ADMIN_ACTOR_AUDIENCE,
    ADMIN_ACTOR_ISSUER,
    ADMIN_ACTOR_PURPOSE,
    AdminActor,
    derive_admin_actor_key,
    require_admin_actor,
)
from app.settings import settings


TOKEN = "actor-test-admin-token"
PATH = "/bound"
BODY = b'{"selected_alternative_id":7}'


actor_app = FastAPI()


@actor_app.post(PATH)
async def actor_bound_route(
    request: Request, actor: AdminActor = Depends(require_admin_actor)
):
    return {"id": actor.id, "email": actor.email, "body": (await request.body()).decode()}


client = TestClient(actor_app)


@pytest.fixture(autouse=True)
def configured_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", TOKEN)


def assertion(*, body: bytes = BODY, path: str = PATH, method: str = "POST", **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ADMIN_ACTOR_ISSUER,
        "aud": ADMIN_ACTOR_AUDIENCE,
        "purpose": ADMIN_ACTOR_PURPOSE,
        "sub": "authjs-admin",
        "email": " Reviewer@Example.COM ",
        "iat": now,
        "exp": now + 60,
        "jti": "test-jti",
        "method": method,
        "path": path,
        "body_sha256": hashlib.sha256(body).hexdigest(),
    }
    claims.update(overrides)
    return jwt.encode(claims, derive_admin_actor_key(TOKEN), algorithm="HS256")


def post(token: str | None, *, body: bytes = BODY):
    headers = {"X-Admin-Token": TOKEN, "Content-Type": "application/json"}
    if token is not None:
        headers["X-Admin-Actor-Assertion"] = token
    return client.post(PATH, content=body, headers=headers)


def error_code(response) -> str:
    return response.json()["detail"]["code"]


def test_valid_assertion_passes_and_returns_normalized_verified_actor():
    response = post(assertion())
    assert response.status_code == 200
    assert response.json() == {
        "id": "authjs-admin",
        "email": "reviewer@example.com",
        "body": BODY.decode(),
    }


def test_missing_and_malformed_assertions_fail():
    missing = post(None)
    malformed = post("not-a-jwt")
    assert missing.status_code == malformed.status_code == 401
    assert error_code(missing) == "admin_actor_assertion_required"
    assert error_code(malformed) == "admin_actor_assertion_invalid"


def test_expired_assertion_has_specific_error():
    now = int(time.time())
    response = post(assertion(iat=now - 120, exp=now - 60))
    assert response.status_code == 401
    assert error_code(response) == "admin_actor_assertion_expired"


def test_non_hs256_and_overlong_lifetime_fail():
    now = int(time.time())
    claims = {
        "iss": ADMIN_ACTOR_ISSUER,
        "aud": ADMIN_ACTOR_AUDIENCE,
        "purpose": ADMIN_ACTOR_PURPOSE,
        "sub": "authjs-admin",
        "email": "reviewer@example.com",
        "iat": now,
        "exp": now + 60,
        "jti": "test-jti",
        "method": "POST",
        "path": PATH,
        "body_sha256": hashlib.sha256(BODY).hexdigest(),
    }
    hs384 = jwt.encode(claims, derive_admin_actor_key(TOKEN), algorithm="HS384")
    too_long = assertion(iat=now, exp=now + 61)
    assert error_code(post(hs384)) == "admin_actor_assertion_invalid"
    assert error_code(post(too_long)) == "admin_actor_assertion_invalid"


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "wrong-issuer"),
        ("aud", "wrong-audience"),
        ("purpose", "wrong-purpose"),
        ("sub", "  "),
        ("email", ""),
    ],
)
def test_invalid_identity_or_trust_claims_fail(claim, value):
    response = post(assertion(**{claim: value}))
    assert response.status_code == 401
    assert error_code(response) == "admin_actor_assertion_invalid"


@pytest.mark.parametrize(
    "token",
    [
        assertion(method="PATCH"),
        assertion(path="/other"),
        assertion(body=b"{}"),
    ],
)
def test_method_path_and_body_are_bound(token):
    response = post(token)
    assert response.status_code == 401
    assert error_code(response) == "admin_actor_assertion_request_mismatch"


def test_absent_admin_token_fails_closed_even_with_development_bypass(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", None)
    monkeypatch.setattr("app.auth.is_development_environment", lambda: True)
    response = client.post(PATH, content=BODY, headers={"X-Admin-Actor-Assertion": "anything"})
    assert response.status_code == 401
    assert error_code(response) == "admin_actor_assertion_invalid"


def test_cross_language_contract_vector():
    vector = json.loads(
        (Path(__file__).parents[3] / "docs/contracts/admin-actor-assertion-v1.json").read_text()
    )
    key = derive_admin_actor_key(vector["admin_token"])
    assert key.hex() == vector["derived_key_hex"]
    assert hashlib.sha256(vector["body_utf8"].encode()).hexdigest() == vector["body_sha256"]
    claims = jwt.decode(
        vector["jwt"],
        key,
        algorithms=["HS256"],
        audience=vector["claims"]["audience"],
        issuer=vector["claims"]["issuer"],
        options={"verify_exp": False},
    )
    assert claims["purpose"] == vector["claims"]["purpose"]
    assert claims["body_sha256"] == vector["body_sha256"]
