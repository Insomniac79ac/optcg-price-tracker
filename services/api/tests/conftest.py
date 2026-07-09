import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (registers models on Base.metadata)
from app.db import Base, get_db
from app.main import app
from app.settings import settings

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


@pytest.fixture()
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    test_client = TestClient(app)
    test_client.headers.update({"X-Admin-Token": TEST_ADMIN_TOKEN})
    return test_client
