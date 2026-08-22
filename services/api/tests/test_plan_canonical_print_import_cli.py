"""Coverage for the planner CLI (app.plan_canonical_print_import).

Two things are proven here that the planner's own tests cannot:

  * the command has no route to a write, by flag or by session; and
  * `--staging` refuses to plan unless the established fail-closed
    verification passes first.

The read-only half runs against PostgreSQL, because it is the server that
enforces it - sqlite has no read-only transaction to violate, so proving it
there would prove nothing. Skips outright if no server answers on 5544, the
same disposable instance the other *_postgres tests use.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError, OperationalError, ProgrammingError

from app import plan_canonical_print_import as cli
from app.db import Base
from app.models import CanonicalCard

TEST_POSTGRES_URL = os.environ.get(
    "TEST_POSTGRES_URL", "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test"
)


# --- no write path -----------------------------------------------------------


def test_the_parser_offers_only_read_options():
    options = {
        option for action in cli.build_parser()._actions for option in action.option_strings
    }
    assert "--card-code" in options
    assert "--series" in options
    assert "--json" in options
    for forbidden in ("--apply", "--write", "--persist", "--commit", "--force", "--yes"):
        assert forbidden not in options, forbidden


def test_a_target_is_required_and_the_two_targets_are_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--card-code", "OP01-001", "--series", "550101"])


def test_the_cli_module_never_imports_a_writer():
    """The planner is the only domain module this CLI is allowed to drive."""
    from pathlib import Path

    source = Path(cli.__file__).read_text()
    code = "\n".join(l for l in source.splitlines() if not l.strip().startswith("#"))
    for forbidden in ("session.add(", ".commit()", "session.merge", "session.delete"):
        assert forbidden not in code, forbidden


# --- --staging is gated on the fail-closed verification ----------------------


class _FakeResult:
    def __init__(self, ok: bool) -> None:
        self.name = "fingerprint D - alembic revision"
        self.ok = ok
        self.detail = "found=['wrong'] expected=['right']"


class _FakeChecker:
    """Stands in for scripts/staging_db_read_check.py."""

    DEFAULT_SERVICE = "Postgres"

    def __init__(self, ok: bool) -> None:
        self._ok = ok
        self.tunnels_opened = 0

    def open_tunnel(self, service, environment):
        assert environment == "staging"
        self.tunnels_opened += 1

        class _Process:
            def terminate(self):
                return None

        return _Process(), "postgresql://u:p@127.0.0.1:1/railway"

    def collect_facts(self, connection):
        return object()

    def expected_revisions_from_repo(self, root):
        return frozenset({"right"})

    def evaluate(self, facts, expected):
        return [_FakeResult(self._ok)]

    def redacted_target(self, url):
        return "127.0.0.1:1/railway"


def test_staging_is_refused_when_verification_fails(monkeypatch):
    checker = _FakeChecker(ok=False)
    monkeypatch.setattr(cli, "_load_staging_checker", lambda: checker)
    class _Connection:
        read_only = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: _Connection())

    with pytest.raises(RuntimeError, match="verification FAILED"):
        cli.verified_staging_url()
    # It refused before opening a second tunnel to plan through.
    assert checker.tunnels_opened == 1


def test_staging_proceeds_only_after_every_fingerprint_passes(monkeypatch):
    checker = _FakeChecker(ok=True)
    monkeypatch.setattr(cli, "_load_staging_checker", lambda: checker)

    class _Connection:
        read_only = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: _Connection())

    try:
        url = cli.verified_staging_url()
    finally:
        for process in cli._KEEP_ALIVE:
            process.terminate()
        cli._KEEP_ALIVE.clear()
    assert url.startswith("postgresql://")
    # One tunnel to verify, a second, fresh one to plan through.
    assert checker.tunnels_opened == 2


# --- the session really is read-only (PostgreSQL) -----------------------------


@pytest.fixture()
def postgres_ready():
    from sqlalchemy import create_engine

    engine = create_engine(TEST_POSTGRES_URL)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except (OperationalError, InternalError):
        pytest.skip("no PostgreSQL server on 5544")
    CanonicalCard.__table__.create(bind=engine, checkfirst=True)
    yield engine
    engine.dispose()


def test_a_planning_session_cannot_write_even_if_asked(postgres_ready):
    """The server rejects the write - not a convention, an enforced state."""
    factory, engine = cli.read_only_sessionmaker(TEST_POSTGRES_URL)
    session = factory()
    try:
        # Reads are fine.
        session.execute(text("SELECT count(*) FROM canonical_cards")).scalar_one()
        with pytest.raises((InternalError, ProgrammingError, OperationalError)) as caught:
            session.execute(
                text(
                    "INSERT INTO canonical_cards "
                    "(card_code, name_jp, original_set_code, rarity, card_type) "
                    "VALUES ('ZZ99-999', 'x', 'ZZ-99', 'C', 'Character')"
                )
            )
            session.commit()
        assert "read-only" in str(caught.value).lower()
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def test_the_read_only_session_still_reads(postgres_ready):
    factory, engine = cli.read_only_sessionmaker(TEST_POSTGRES_URL)
    session = factory()
    try:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        session.close()
        engine.dispose()


def test_the_url_is_normalized_to_the_installed_driver():
    """A bare postgresql:// tunnel URL must not route to the absent psycopg2."""
    factory, engine = cli.read_only_sessionmaker("postgresql://u:p@127.0.0.1:1/x")
    try:
        assert engine.dialect.driver == "psycopg"
    finally:
        engine.dispose()
