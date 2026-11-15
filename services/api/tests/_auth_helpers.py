"""Shared bearer-token test constants/helpers.

Deliberately NOT part of conftest.py: importing conftest.py under a
qualified name (e.g. `from tests.conftest import ...`) makes Python execute
it a *second* time as a distinct module object (pytest itself loads it as a
bare top-level `conftest` module, not `tests.conftest`, since tests/ has no
__init__.py). That second execution re-runs
`app.dependency_overrides[get_db] = override_get_db`, pointing the app at a
second, empty in-memory engine that no fixture ever creates tables on -
every request through `client` then fails with "no such table". Keeping
these in their own module lets test files import them safely.
"""

import time

import jwt

TEST_API_JWT_SECRET = "test-api-jwt-secret"
TEST_USER_GOOGLE_SUB = "test-google-sub"
TEST_USER_EMAIL = "test@example.com"
TEST_USER_ID = 1


def make_bearer_token(
    *, google_sub: str = TEST_USER_GOOGLE_SUB, email: str = TEST_USER_EMAIL, name: str | None = "Test User"
) -> str:
    # Same shape as the website's mintApiToken: iat plus a 5-minute exp.
    now = int(time.time())
    return jwt.encode(
        {"sub": google_sub, "email": email, "name": name, "iat": now, "exp": now + 300},
        TEST_API_JWT_SECRET,
        algorithm="HS256",
    )


def timed_claims(**claims) -> dict:
    """claims plus iat now and exp 60 s later (the website probe's shape)."""
    now = int(time.time())
    return {"iat": now, "exp": now + 60, **claims}
