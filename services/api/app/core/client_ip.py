"""One shared rule for which client address the API uses, for the request
rate limiter (app.core.rate_limit) and the admin login counters
(app.api.admin_login).

The client address comes only from the platform client-IP header that the
hosting edge sets (CLIENT_IP_HEADER). The value must parse as a single IP
address. Other forwarding headers never choose the address. Outside
development, a missing or invalid value maps to one strict shared key
(UNVERIFIED_KEY) instead of the socket peer, so a request is never left
without a key. In development only, the socket peer is used as a fallback.

IPv6 addresses are grouped by /64, since one client usually holds a whole
/64.

This module only classifies; it keeps no counters. app.core.rate_limit
counts each classified request once (see ClientKeyCounts there).
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from starlette.requests import Request

from app.env import is_development_environment

# Header names are matched case-insensitively by Starlette.
CLIENT_IP_HEADER = "x-real-ip"
# Read only to report a disagreement count; never used to choose the key.
FORWARDED_HEADER = "x-forwarded-for"

UNVERIFIED_KEY = "unverified"
IPV6_GROUP_PREFIX = 64
MAX_HEADER_LENGTH = 64

PLATFORM_HEADER = "platform_header"
UNVERIFIED = "unverified"
DEVELOPMENT_PEER = "development_peer"

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass(frozen=True)
class ClientAddress:
    # Address string (IPv4), "<network>/64" (IPv6), or UNVERIFIED_KEY.
    key: str
    # PLATFORM_HEADER, UNVERIFIED or DEVELOPMENT_PEER.
    source: str
    # True only when both header values parse and the parsed addresses differ.
    mismatch: bool = False


def parse_ip(value: str | None) -> IPAddress | None:
    """One IP address, or None. Rejects empty values, lists, ports, zone ids,
    anything over MAX_HEADER_LENGTH and anything else ipaddress rejects."""
    if value is None:
        return None
    value = value.strip()
    if not value or len(value) > MAX_HEADER_LENGTH or "," in value or "%" in value:
        return None
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def address_key(address: IPAddress) -> str:
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        network = ipaddress.IPv6Network((address, IPV6_GROUP_PREFIX), strict=False)
        return str(network)
    return str(address)


def _first_forwarded(request: Request) -> IPAddress | None:
    forwarded = request.headers.get(FORWARDED_HEADER)
    if not forwarded:
        return None
    return parse_ip(forwarded.split(",")[0])


def resolve_client(request: Request) -> ClientAddress:
    platform = parse_ip(request.headers.get(CLIENT_IP_HEADER))
    if platform is not None:
        forwarded = _first_forwarded(request)
        mismatch = forwarded is not None and forwarded != platform
        return ClientAddress(key=address_key(platform), source=PLATFORM_HEADER, mismatch=mismatch)
    if is_development_environment():
        peer = parse_ip(request.client.host if request.client else None)
        if peer is not None:
            return ClientAddress(key=address_key(peer), source=DEVELOPMENT_PEER)
    return ClientAddress(key=UNVERIFIED_KEY, source=UNVERIFIED)
