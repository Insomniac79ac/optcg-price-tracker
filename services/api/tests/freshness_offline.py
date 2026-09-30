"""Transport guard for the offline scheduling/collector regression boundary."""

import socket
import httpx
import pytest
import os

URL = os.environ.get(
    "TEST_POSTGRES_URL", "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test"
)


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """No real HTTP/browser transport; only the configured disposable DB socket."""
    from sqlalchemy.engine import make_url
    import urllib.request
    from playwright.sync_api import PlaywrightContextManager
    from playwright.async_api import PlaywrightContextManager as AsyncContextManager

    parsed = make_url(URL)
    assert parsed.host in {"localhost", "127.0.0.1"}
    assert parsed.database == "opcg_test"
    port = parsed.port or 5432
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    db_connect = psycopg.Connection.connect.__func__

    def local_db(cls, conninfo="", **kwargs):
        params = conninfo_to_dict(
            conninfo,
            **{k: v for k, v in kwargs.items() if k in {"host", "port", "dbname"}},
        )
        assert params.get("host") in {
            "localhost",
            "127.0.0.1",
        }, "offline test blocked external DB"
        assert (
            int(params.get("port", 5432)) == port
        ), "offline test blocked other DB port"
        name = params.get("dbname", "")
        assert name in {"opcg_test", "postgres"} or name.startswith(
            "freshness_migration_"
        ), "offline test blocked non-disposable DB"
        return db_connect(cls, conninfo, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "connect", classmethod(local_db))
    monkeypatch.setattr(psycopg, "connect", psycopg.Connection.connect)
    resolve = socket.getaddrinfo

    def local_resolve(host, port_number, *args, **kwargs):
        assert host in {
            "localhost",
            "127.0.0.1",
            "::1",
        }, "offline test blocked external DNS"
        return resolve(host, port_number, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", local_resolve)
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def allowed(address):
        if (
            not isinstance(address, tuple)
            or address[0] not in {"127.0.0.1", "::1", "localhost"}
            or address[1] != port
        ):
            raise AssertionError(f"offline test blocked socket: {address}")

    def guarded_connect(sock, address):
        allowed(address)
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        allowed(address)
        return connect_ex(sock, address)

    def blocked(*args, **kwargs):
        raise AssertionError("offline test blocked real HTTP/browser transport")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(PlaywrightContextManager, "start", blocked)
    monkeypatch.setattr(PlaywrightContextManager, "__enter__", blocked)
    monkeypatch.setattr(AsyncContextManager, "start", blocked)
    monkeypatch.setattr(AsyncContextManager, "__aenter__", blocked)
