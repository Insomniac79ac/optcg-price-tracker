"""Read-only staging Postgres connection for runbooks (from the session 13 handoff tools/db.py).

Destination: the pinned staging project/environment (generate_staging_state.staging_environment)
and the Postgres service's one TCP proxy. Identity: the schema fingerprint of
staging_db_read_check must pass before any query (a wrong database that answers is refused).
Every session runs with default_transaction_read_only=on and a statement timeout; the
password is masked in the Actions log and never written anywhere.
"""
from __future__ import annotations

from ops import common  # noqa: F401  (import paths)

READ_ONLY_OPTION = "-c default_transaction_read_only=on"


def options(statement_timeout_ms=60000):
    return f"{READ_ONLY_OPTION} -c statement_timeout={int(statement_timeout_ms)} -c search_path=public"


def connect_kwargs(proxy, variables, statement_timeout_ms=60000):
    """psycopg.connect keyword arguments; read-only is not optional."""
    return dict(host=proxy["domain"], port=proxy["proxyPort"], user=variables["PGUSER"],
                password=variables["PGPASSWORD"], dbname=variables["PGDATABASE"], connect_timeout=15,
                options=options(statement_timeout_ms))


def resolve():
    """(proxy, variables) for the pinned staging Postgres. Caller must clear variables."""
    import generate_staging_state as state

    state.staging_environment()
    proxies = state.railway(
        f'query {{ tcpProxies(environmentId:"{state.ENVIRONMENT}", serviceId:"{state.POSTGRES}") '
        "{ domain proxyPort applicationPort } }")["tcpProxies"]
    if len(proxies) != 1 or proxies[0]["applicationPort"] != 5432:
        raise common.Refused("staging Postgres proxy is not uniquely identified")
    variables = state.service_variables(state.POSTGRES)
    common.register_secret(variables.get("PGPASSWORD"))
    return proxies[0], variables


def verify(connection, guard=None):
    """Fingerprint and read-only checks on a fresh connection (tuple rows)."""
    import staging_db_read_check as default_guard

    guard = guard or default_guard
    checks = guard.evaluate(guard.collect_facts(connection),
                            guard.expected_revisions_from_repo(str(common.ROOT)))
    failed = [c.name for c in checks if not c.ok]
    if failed:
        raise common.Refused("staging database fingerprint failed: " + ", ".join(failed))
    if connection.execute("show transaction_read_only").fetchone()[0] != "on":
        raise common.Refused("session is not read-only")
    connection.rollback()


def connection(row_factory=None, statement_timeout_ms=60000):
    """A verified read-only psycopg connection to staging."""
    import psycopg
    from psycopg.rows import dict_row

    proxy, variables = resolve()
    try:
        kwargs = connect_kwargs(proxy, variables, statement_timeout_ms)
    finally:
        variables.clear()
    try:
        conn = psycopg.connect(**kwargs)
    except Exception as error:
        # Driver errors can carry host and user; never echo them. Class, type and SQLSTATE only.
        import generate_staging_state as state
        raise common.Refused(f"staging database connection failed ({state.db_failure_class(error)})") from None
    finally:
        kwargs.clear()
    conn.read_only = True
    verify(conn)
    conn.row_factory = row_factory or dict_row
    return conn


def engine(statement_timeout_ms=60000):
    """SQLAlchemy engine over verified read-only connections (one per checkout, no pool)."""
    import sqlalchemy
    from psycopg.rows import tuple_row

    return sqlalchemy.create_engine(
        "postgresql+psycopg://",
        creator=lambda: connection(row_factory=tuple_row, statement_timeout_ms=statement_timeout_ms),
        poolclass=sqlalchemy.pool.NullPool)
