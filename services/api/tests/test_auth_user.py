import jwt

from app.models import User
from tests._auth_helpers import TEST_API_JWT_SECRET, TEST_USER_EMAIL, TEST_USER_GOOGLE_SUB, make_bearer_token


def test_missing_bearer_token_returns_401(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    unauth_client = TestClient(app)
    response = unauth_client.get("/collection")
    assert response.status_code == 401


def test_malformed_authorization_header_returns_401(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    unauth_client = TestClient(app)
    unauth_client.headers.update({"Authorization": "Token not-a-bearer-token"})
    response = unauth_client.get("/collection")
    assert response.status_code == 401


def test_invalid_signature_returns_401(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    bad_token = jwt.encode(
        {"sub": TEST_USER_GOOGLE_SUB, "email": TEST_USER_EMAIL}, "wrong-secret", algorithm="HS256"
    )
    unauth_client = TestClient(app)
    unauth_client.headers.update({"Authorization": f"Bearer {bad_token}"})
    response = unauth_client.get("/collection")
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
    response = unauth_client.get("/collection")
    assert response.status_code == 401


def test_token_missing_required_claims_returns_401(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    token = jwt.encode({"sub": TEST_USER_GOOGLE_SUB}, TEST_API_JWT_SECRET, algorithm="HS256")
    unauth_client = TestClient(app)
    unauth_client.headers.update({"Authorization": f"Bearer {token}"})
    response = unauth_client.get("/collection")
    assert response.status_code == 401


def test_valid_token_jit_provisions_new_user(client, db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    new_user_client = TestClient(app)
    token = make_bearer_token(
        google_sub="another-google-sub", email="second@example.com", name="Second User"
    )
    new_user_client.headers.update({"Authorization": f"Bearer {token}"})

    response = new_user_client.get("/collection")
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

    reused_client.get("/collection")
    reused_client.get("/collection")

    count = db_session.query(User).filter_by(google_sub="another-google-sub").count()
    assert count == 1


def test_two_users_do_not_see_each_others_collection_items(client, db_session):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import Card

    card = Card(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp=None,
        set_code="OP01",
        rarity="L",
        variant="leader",
        language="en",
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    # `client` fixture is signed in as the default test user (id 1).
    create_response = client.post("/collection", json={"card_id": card.id, "quantity": 1})
    assert create_response.status_code == 201

    other_client = TestClient(app)
    other_token = make_bearer_token(google_sub="another-google-sub", email="second@example.com")
    other_client.headers.update({"Authorization": f"Bearer {other_token}"})

    other_response = other_client.get("/collection")
    assert other_response.status_code == 200
    assert other_response.json()["items"] == []
