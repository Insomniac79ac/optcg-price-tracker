"""Unit tests for app.core.client_ip, the one rule for the client key used by
the request rate limiter and the admin login counters."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.core.client_ip import (
    DEVELOPMENT_PEER,
    PLATFORM_HEADER,
    UNVERIFIED,
    UNVERIFIED_KEY,
    resolve_client,
)
from app.settings import settings


def _request(headers: dict[str, str] | None = None, peer: str = "198.51.100.77") -> Request:
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/cards", "headers": raw, "client": (peer, 5000)})


@pytest.fixture(autouse=True)
def _not_development(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(settings, "APP_ENV", None)


def test_other_forwarding_headers_do_not_change_the_client_key():
    keys = {
        resolve_client(_request({"X-Real-IP": "203.0.113.5", "X-Forwarded-For": forwarded})).key
        for forwarded in ("198.51.100.1", "203.0.113.9, 10.0.0.1", "junk", "")
    }
    assert keys == {"203.0.113.5"}


def test_missing_client_header_outside_development_uses_the_shared_unverified_key():
    client = resolve_client(_request({"X-Forwarded-For": "203.0.113.9"}))

    assert client.key == UNVERIFIED_KEY
    assert client.source == UNVERIFIED
    assert "198.51.100.77" not in client.key


@pytest.mark.parametrize(
    "value",
    ["203.0.113.9, 10.0.0.1", "1.2.3.4:80", "", "   ", "user:abc", "1" * 65, "fe80::1%eth0", "not-an-ip"],
)
def test_invalid_client_header_is_treated_as_missing(value):
    client = resolve_client(_request({"X-Real-IP": value}))

    assert client.key == UNVERIFIED_KEY
    assert client.source == UNVERIFIED
    assert client.mismatch is False


def test_ipv6_addresses_in_one_slash_64_share_a_key():
    first = resolve_client(_request({"X-Real-IP": "2001:db8:1:2::1"})).key
    same_64 = resolve_client(_request({"X-Real-IP": "2001:db8:1:2:ffff:ffff:ffff:ffff"})).key
    other_64 = resolve_client(_request({"X-Real-IP": "2001:db8:1:3::1"})).key

    assert first == same_64 == "2001:db8:1:2::/64"
    assert other_64 != first


def test_ipv4_mapped_ipv6_uses_the_ipv4_key():
    assert resolve_client(_request({"X-Real-IP": "::ffff:203.0.113.5"})).key == "203.0.113.5"


def test_a_valid_client_header_is_trimmed_and_used():
    client = resolve_client(_request({"X-Real-IP": " 203.0.113.5 "}))

    assert client.key == "203.0.113.5"
    assert client.source == PLATFORM_HEADER


def test_development_uses_the_connection_address_when_the_header_is_missing(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    client = resolve_client(_request(peer="127.0.0.1"))

    assert client.key == "127.0.0.1"
    assert client.source == DEVELOPMENT_PEER


def test_development_still_prefers_a_valid_client_header(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    assert resolve_client(_request({"X-Real-IP": "203.0.113.5"}, peer="127.0.0.1")).key == "203.0.113.5"


@pytest.mark.parametrize(
    "platform, forwarded, mismatch",
    [
        ("203.0.113.5", "198.51.100.1", True),
        ("203.0.113.5", "203.0.113.5, 10.0.0.1", False),
        ("2001:db8::1", "2001:0db8:0000:0000:0000:0000:0000:0001", False),
        ("2001:db8::1", "2001:db8::2", True),
        ("203.0.113.5", "junk", False),
        ("203.0.113.5", None, False),
    ],
)
def test_mismatch_compares_parsed_addresses(platform, forwarded, mismatch):
    headers = {"X-Real-IP": platform}
    if forwarded is not None:
        headers["X-Forwarded-For"] = forwarded

    assert resolve_client(_request(headers)).mismatch is mismatch
