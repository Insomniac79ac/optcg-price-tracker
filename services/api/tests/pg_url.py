"""The one place real-PostgreSQL tests get their database URLs from.

TEST_POSTGRES_URL names the disposable server (and its default database);
when unset it falls back to the local disposable instance every Postgres test
has always defaulted to. Tests derive every other URL they need - the admin
`postgres` database used for CREATE/DROP DATABASE, a per-test throwaway
database, or another driver form - from it here, rather than each reading
TEST_POSTGRES_* environment variables or hard-coding hosts and ports.

Availability policy: without REQUIRE_POSTGRES=1 an unreachable server skips
the test (local runs without Docker stay green). With REQUIRE_POSTGRES=1
(CI, where a postgres service is provisioned) the same condition FAILS the
test, so a misconfigured or missing database cannot silently turn the
Postgres suite into skips.

services/worker/tests/pg_url.py is a byte-identical copy (the worker image
has no services/api); tests/test_pg_url_parity.py keeps the two in step.
"""

from __future__ import annotations

import os
from typing import NoReturn

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError

DEFAULT_TEST_POSTGRES_URL = "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test"
DRIVER = "postgresql+psycopg"


def _base_url() -> URL:
    return make_url(os.environ.get("TEST_POSTGRES_URL") or DEFAULT_TEST_POSTGRES_URL)


def postgres_url(database: str | None = None, *, drivername: str = DRIVER) -> str:
    """TEST_POSTGRES_URL, optionally pointed at another database on the same
    server and/or rendered with another driver name. Password included - pass
    it to create_engine/subprocess env, never to a message."""
    url = _base_url().set(drivername=drivername)
    if database is not None:
        url = url.set(database=database)
    return url.render_as_string(hide_password=False)


def admin_url() -> str:
    """The server's maintenance database, for CREATE/DROP DATABASE."""
    return postgres_url("postgres")


def server_label() -> str:
    """host:port/database for skip/fail messages - never credentials."""
    url = _base_url()
    return f"{url.host}:{url.port}/{url.database}"


def is_local() -> bool:
    """True when TEST_POSTGRES_URL points at this machine - for tests that
    refuse to run anywhere but a local throwaway server."""
    return _base_url().host in {"localhost", "127.0.0.1"}


def postgres_required() -> bool:
    return os.environ.get("REQUIRE_POSTGRES") == "1"


def postgres_unavailable(reason: str) -> NoReturn:
    """Skip locally; fail when REQUIRE_POSTGRES=1."""
    if postgres_required():
        pytest.fail(
            f"{reason} [REQUIRE_POSTGRES=1: unavailable PostgreSQL fails instead of skipping]",
            pytrace=False,
        )
    pytest.skip(reason)


def require_reachable(url: str | None = None) -> None:
    """Connect once to `url` (default TEST_POSTGRES_URL) or apply the policy."""
    engine = create_engine(url or postgres_url())
    try:
        with engine.connect():
            pass
    except OperationalError:
        postgres_unavailable(f"No PostgreSQL server reachable at {server_label()}")
    finally:
        engine.dispose()


def ensure_database(name: str) -> str:
    """Create database `name` on the test server if it does not exist yet and
    return its URL (for tests that use a fixed, reusable database name)."""
    admin = create_engine(admin_url(), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            )
            if exists is None:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        postgres_unavailable(f"No PostgreSQL server reachable at {server_label()}")
    finally:
        admin.dispose()
    return postgres_url(name)
