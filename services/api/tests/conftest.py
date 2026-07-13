import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers models on Base.metadata)
from app.db import Base, get_db
from app.main import app
from app.models import User
from app.settings import settings
from tests._auth_helpers import (
    TEST_API_JWT_SECRET,
    TEST_USER_EMAIL,
    TEST_USER_GOOGLE_SUB,
    TEST_USER_ID,
    make_bearer_token,
)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Most tests exercise application logic, not admin auth itself - auth behavior
# gets its own coverage in tests/test_admin_auth.py, which builds its own
# TestClient(app) rather than using the `client` fixture below.
TEST_ADMIN_TOKEN = "test-admin-token"

# Every test gets the same signed-in user by default (id always 1, since it's
# the first row inserted into a freshly created in-memory DB each test) - test
# helpers across the suite hardcode user_id=1 on the CollectionItem rows they
# create directly, matching this. Multi-user isolation gets its own coverage
# in tests/test_auth_user.py, which mints tokens for other google_sub values.
# (TEST_API_JWT_SECRET/TEST_USER_* live in tests/_auth_helpers.py, not here -
# see that module's docstring for why other test files must import from
# there, never `from tests.conftest import ...`.)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", TEST_ADMIN_TOKEN)


@pytest.fixture(autouse=True)
def _api_jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "API_JWT_SECRET", TEST_API_JWT_SECRET)


@pytest.fixture()
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    session.add(
        User(id=TEST_USER_ID, google_sub=TEST_USER_GOOGLE_SUB, email=TEST_USER_EMAIL, name="Test User")
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    test_client = TestClient(app)
    test_client.headers.update(
        {
            "X-Admin-Token": TEST_ADMIN_TOKEN,
            "Authorization": f"Bearer {make_bearer_token()}",
        }
    )
    return test_client
