import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import worker.models  # noqa: F401  (registers models on Base.metadata)
from worker.db import Base

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _app_logging_uses_test_db(monkeypatch):
    """worker.app_logging.record_app_log opens its own short-lived session
    (by design - a log row must survive the caller's own transaction rolling
    back), so it doesn't go through db_session above. Redirect it to the same
    in-memory sqlite engine, or every test that exercises a code path calling
    record_app_log would attempt a real connection to worker.settings.settings
    .DATABASE_URL instead."""
    import worker.app_logging as app_logging_module

    monkeypatch.setattr(app_logging_module, "SessionLocal", TestingSessionLocal)
