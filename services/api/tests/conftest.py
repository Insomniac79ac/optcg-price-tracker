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


@pytest.fixture(autouse=True)
def _app_logging_uses_test_db(monkeypatch):
    """app.services.app_logging.record_app_log opens its own short-lived
    session (by design - a log row must survive the caller's own transaction
    rolling back), so it doesn't go through the get_db dependency override
    above. Redirect it to the same in-memory sqlite engine as db_session/
    client, or every test that exercises a code path calling record_app_log
    would attempt a real connection to settings.DATABASE_URL instead."""
    import app.services.app_logging as app_logging_module

    monkeypatch.setattr(app_logging_module, "SessionLocal", TestingSessionLocal)


@pytest.fixture(autouse=True)
def _file_jobs_uses_test_db(monkeypatch):
    """app.services.file_jobs.process_file_job opens its own short-lived
    session (same reasoning as app.services.job_locks/app_logging - it may
    run well after the request that created the job has closed its own
    session, especially when dispatched via FastAPI BackgroundTasks), so it
    doesn't go through the get_db dependency override above. Redirect it to
    the same in-memory sqlite engine as db_session/client, or every
    background-processed file job would attempt a real connection to
    settings.DATABASE_URL instead."""
    import app.services.file_jobs as file_jobs_module

    monkeypatch.setattr(file_jobs_module, "SessionLocal", TestingSessionLocal)


@pytest.fixture(autouse=True)
def _job_locks_uses_test_db(monkeypatch):
    """app.services.job_locks (acquire_lock/release_lock/...) opens its own
    short-lived session per call, same rationale and same fix as
    _app_logging_uses_test_db above - see that module's docstring for why
    sharing the caller's session would be actively harmful, not just
    unnecessary."""
    import app.services.job_locks as job_locks_module

    monkeypatch.setattr(job_locks_module, "SessionLocal", TestingSessionLocal)


@pytest.fixture(autouse=True)
def _cache_disabled_by_default(monkeypatch):
    """app.services.cache defaults to CACHE_BACKEND=redis, which would make
    every cached endpoint (dashboard overview, market opportunities, ...)
    attempt a real connection to REDIS_URL on its first request in every
    test that touches one - slow, noisy (throttled warning logs), and an
    unnecessary dependency on a running Redis for tests that aren't about
    caching at all. Off by default here, same pattern as
    _rate_limit_disabled_by_default above; tests/test_cache.py explicitly
    re-enables it (CACHE_BACKEND=memory) to exercise real cache behavior."""
    from app.services import cache as cache_module

    monkeypatch.setattr(settings, "CACHE_ENABLED", False)
    cache_module.reset_state_for_tests()
    yield
    cache_module.reset_state_for_tests()


@pytest.fixture(autouse=True)
def _file_job_storage_uses_tmp_dir(tmp_path, monkeypatch):
    """app.services.file_job_storage defaults to data/file_jobs (relative to
    cwd) - redirected to a per-test tmp_path here so tests never write into
    the real local dev directory or leave files behind."""
    monkeypatch.setattr(settings, "FILE_JOB_STORAGE_DIR", str(tmp_path / "file_jobs"))


@pytest.fixture(autouse=True)
def _rate_limit_disabled_by_default(monkeypatch):
    """RateLimitMiddleware runs on every request (see app/main.py), and its
    counters are process-global - without this, the hundreds of requests
    the rest of this suite makes within a single test run would eventually
    trip a group's limit and start failing unrelated tests with 429s. Off
    by default here; tests/test_rate_limit.py explicitly re-enables it
    (and sets small limits) to exercise the 429 behavior in isolation."""
    from app.core.rate_limit import reset_rate_limits

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    reset_rate_limits()
    yield
    reset_rate_limits()


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
