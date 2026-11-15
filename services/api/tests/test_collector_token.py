"""F2 delivery (a): the shared collector-token verifier (app.core.collector_token),
used by require_current_user and by the /me rate-limit key."""

import time

import jwt
import pytest

from app.core.collector_token import (
    AUDIENCE,
    ISSUER,
    LEEWAY_SECONDS,
    MAX_LIFETIME_SECONDS,
    verify_collector_token,
)
from tests._auth_helpers import TEST_API_JWT_SECRET, make_bearer_token

SECRET = TEST_API_JWT_SECRET


def _token(claims, *, secret=SECRET, algorithm="HS256"):
    return jwt.encode(claims, secret, algorithm=algorithm)


def _claims(**overrides):
    now = int(time.time())
    claims = {"sub": "google-sub", "email": "a@example.com", "iat": now, "exp": now + 300}
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def test_todays_website_token_is_accepted():
    payload = verify_collector_token(make_bearer_token(), SECRET)
    assert payload["sub"]


def test_probe_shaped_token_is_accepted():
    now = int(time.time())
    assert verify_collector_token(_token({"sub": "collector-token-check", "iat": now, "exp": now + 60}), SECRET)


def test_future_iss_and_aud_are_accepted():
    assert verify_collector_token(_token(_claims(iss=ISSUER, aud=AUDIENCE)), SECRET)
    assert verify_collector_token(_token(_claims(aud=[AUDIENCE, "other"])), SECRET)


@pytest.mark.parametrize("missing", ["exp", "iat", "sub"])
def test_missing_required_claim_is_refused(missing):
    claims = _claims()
    del claims[missing]
    with pytest.raises(jwt.InvalidTokenError):
        verify_collector_token(_token(claims), SECRET)


def test_lifetime_over_ten_minutes_is_refused():
    now = int(time.time())
    with pytest.raises(jwt.InvalidTokenError):
        verify_collector_token(_token(_claims(iat=now, exp=now + MAX_LIFETIME_SECONDS + 1)), SECRET)
    assert verify_collector_token(_token(_claims(iat=now, exp=now + MAX_LIFETIME_SECONDS)), SECRET)


def test_future_iat_beyond_leeway_is_refused_within_leeway_accepted():
    now = int(time.time())
    with pytest.raises(jwt.InvalidTokenError):
        verify_collector_token(_token(_claims(iat=now + LEEWAY_SECONDS + 60, exp=now + LEEWAY_SECONDS + 300)), SECRET)
    assert verify_collector_token(_token(_claims(iat=now + 10, exp=now + 300)), SECRET)


def test_expired_token_is_refused():
    now = int(time.time())
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_collector_token(_token(_claims(iat=now - 600, exp=now - LEEWAY_SECONDS - 1)), SECRET)


def test_wrong_issuer_or_audience_is_refused():
    with pytest.raises(jwt.InvalidIssuerError):
        verify_collector_token(_token(_claims(iss="someone-else")), SECRET)
    with pytest.raises(jwt.InvalidAudienceError):
        verify_collector_token(_token(_claims(aud="card-pirate-admin")), SECRET)
    with pytest.raises(jwt.InvalidAudienceError):
        verify_collector_token(_token(_claims(aud=["other"])), SECRET)


def test_other_algorithms_and_wrong_secret_are_refused():
    with pytest.raises(jwt.InvalidTokenError):
        verify_collector_token(_token(_claims(), algorithm="HS384"), SECRET)
    unsigned = jwt.encode(_claims(), None, algorithm="none")
    with pytest.raises(jwt.InvalidTokenError):
        verify_collector_token(unsigned, SECRET)
    with pytest.raises(jwt.InvalidSignatureError):
        verify_collector_token(_token(_claims(), secret="another-secret-of-enough-length!!"), SECRET)


@pytest.mark.parametrize("claim", ["exp", "iat"])
@pytest.mark.parametrize("kind", ["numeric_string", "bool"])
def test_non_numeric_exp_or_iat_is_refused_not_a_server_error(claim, kind):
    now = int(time.time())
    good = {"exp": now + 300, "iat": now}[claim]
    value = str(good) if kind == "numeric_string" else True
    with pytest.raises(jwt.InvalidTokenError):
        verify_collector_token(_token(_claims(**{claim: value})), SECRET)

def test_rate_limit_key_refuses_what_auth_refuses(monkeypatch):
    from starlette.requests import Request

    from app.core import rate_limit
    from app.settings import settings

    monkeypatch.setattr(settings, "API_JWT_SECRET", SECRET)

    def key_for(token):
        scope = {"type": "http", "method": "GET", "path": "/me", "headers": [(b"authorization", f"Bearer {token}".encode())]}
        return rate_limit._collector_key(Request(scope))

    assert key_for(make_bearer_token()).startswith("user:")
    no_exp = _claims()
    del no_exp["exp"]
    assert key_for(_token(no_exp)) is None
    now = int(time.time())
    assert key_for(_token(_claims(iat=now, exp=now + 3600))) is None
    assert key_for(_token(_claims(iss="someone-else"))) is None


def test_auth_route_refuses_a_token_without_exp(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    claims = _claims()
    del claims["exp"]
    response = TestClient(app).get("/saved-views", headers={"Authorization": f"Bearer {_token(claims)}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or expired token"}
