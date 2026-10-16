import jwt
from sqlalchemy import func, select

from app.models import User

# Any signed-in route will do; the legacy /collection router went in Collector v1 S8.
AUTHED = "/saved-views"
from tests._auth_helpers import (
    TEST_API_JWT_SECRET,
    TEST_USER_EMAIL,
    TEST_USER_GOOGLE_SUB,
    make_bearer_token,
)


def test_missing_bearer_token_returns_401(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    unauth_client = TestClient(app)
    response = unauth_client.get(AUTHED)
    assert response.status_code == 401


def test_malformed_authorization_header_returns_401(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    unauth_client = TestClient(app)
    unauth_client.headers.update({"Authorization": "Token not-a-bearer-token"})
    response = unauth_client.get(AUTHED)
    assert response.status_code == 401


def test_invalid_signature_returns_401(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    bad_token = jwt.encode(
        {"sub": TEST_USER_GOOGLE_SUB, "email": TEST_USER_EMAIL}, "wrong-secret", algorithm="HS256"
    )
    unauth_client = TestClient(app)
    unauth_client.headers.update({"Authorization": f"Bearer {bad_token}"})
    response = unauth_client.get(AUTHED)
    assert response.status_code == 401


def test_expired_token_returns_401(db_session):
    from datetime import datetime, timedelta, timezone

    from fastapi.testclient import TestClient

    from app.main import app

    expired_token = jwt.encode(
        {
            "sub": TEST_USER_GOOGLE_SUB,
            "email": TEST_USER_EMAIL,
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        },
        TEST_API_JWT_SECRET,
        algorithm="HS256",
    )
    unauth_client = TestClient(app)
    unauth_client.headers.update({"Authorization": f"Bearer {expired_token}"})
    response = unauth_client.get(AUTHED)
    assert response.status_code == 401


def test_token_missing_required_claims_returns_401(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    token = jwt.encode({"sub": TEST_USER_GOOGLE_SUB}, TEST_API_JWT_SECRET, algorithm="HS256")
    unauth_client = TestClient(app)
    unauth_client.headers.update({"Authorization": f"Bearer {token}"})
    response = unauth_client.get(AUTHED)
    assert response.status_code == 401


def test_valid_token_jit_provisions_new_user(client, db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    new_user_client = TestClient(app)
    token = make_bearer_token(
        google_sub="another-google-sub", email="second@example.com", name="Second User"
    )
    new_user_client.headers.update({"Authorization": f"Bearer {token}"})

    response = new_user_client.get(AUTHED)
    assert response.status_code == 200
    assert response.json()["items"] == []

    user = db_session.query(User).filter_by(google_sub="another-google-sub").one()
    assert user.email == "second@example.com"
    assert user.name == "Second User"


def test_valid_token_reuses_existing_user_on_second_request(client, db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    reused_client = TestClient(app)
    token = make_bearer_token(google_sub="another-google-sub", email="second@example.com")
    reused_client.headers.update({"Authorization": f"Bearer {token}"})

    reused_client.get(AUTHED)
    reused_client.get(AUTHED)

    count = db_session.query(User).filter_by(google_sub="another-google-sub").count()
    assert count == 1


def test_two_users_do_not_see_each_others_rows(client, db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    # `client` fixture is signed in as the default test user (id 1).
    create_response = client.post(
        AUTHED,
        json={"name": "Mine", "route_path": "/cards", "view_type": "cards", "scope": "collector", "filters_json": {}},
    )
    assert create_response.status_code == 201

    other_client = TestClient(app)
    other_token = make_bearer_token(google_sub="another-google-sub", email="second@example.com")
    other_client.headers.update({"Authorization": f"Bearer {other_token}"})

    other_response = other_client.get(AUTHED)
    assert other_response.status_code == 200
    assert other_response.json()["items"] == []


def test_website_token_check_pass_is_told_apart_without_provisioning(db_session):
    """The website's /api/collector-token-check (apps/web) signs a pass with no
    email and reads these two exact details to tell "the website and the API
    share API_JWT_SECRET" from "they do not". Rejecting the pass must happen
    before JIT provisioning, so the check never creates a user."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    for secret, detail in ((TEST_API_JWT_SECRET, "Token missing required claims"), ("diverged-secret", "Invalid or expired token")):
        token = jwt.encode({"sub": "collector-token-check"}, secret, algorithm="HS256")
        response = client.get(AUTHED, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json() == {"detail": detail}
    assert db_session.query(User).filter_by(google_sub="collector-token-check").count() == 0


def test_concurrent_first_requests_share_one_new_user(db_session):
    """A new collector's first page sends several /me requests at once; each
    finds no row and inserts one. The losers must use the winner's row, not
    fail with a 500 whose message carries the email (2026-10-16 audit F1)."""
    from app.auth import _get_or_create_user

    db_session.add(User(google_sub="race-sub", email="race@example.com", name="Race"))
    db_session.commit()
    winner_id = db_session.scalar(select(User.id).where(User.google_sub == "race-sub"))

    real_scalar = db_session.scalar
    calls = {"n": 0}

    def miss_first_lookup(statement, *args, **kwargs):
        # Simulates the lookup running before the other request committed.
        calls["n"] += 1
        return None if calls["n"] == 1 else real_scalar(statement, *args, **kwargs)

    db_session.scalar = miss_first_lookup
    user = _get_or_create_user(db_session, google_sub="race-sub", email="race@example.com", name="Race")

    assert user.id == winner_id
    db_session.scalar = real_scalar
    assert db_session.scalar(select(func.count()).select_from(User).where(User.google_sub == "race-sub")) == 1


def test_an_email_held_by_another_account_is_a_409_without_details(client, db_session, monkeypatch):
    monkeypatch.setenv("COLLECTOR_ACCOUNTS_ENABLED", "true")
    db_session.add(User(google_sub="first-sub", email="shared@example.com", name="First"))
    db_session.commit()
    token = make_bearer_token(google_sub="second-sub", email="shared@example.com")

    response = client.get("/me/profile", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 409
    assert "shared@example.com" not in response.text
