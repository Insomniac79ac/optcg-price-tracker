"""Canonical listing identity for the new sources (new-sources plan §2.3, amended 2026-10-19).

Kept here, not in packages/opcg_source_identity: every file of that package is a runtime input of
both existing collectors, so a change there would redeploy them. The identities follow the same
`<source>:<product id>` shape.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

DORASUTA_HOSTS = frozenset({"dorasuta.jp", "www.dorasuta.jp"})
CARDRUSH_HOSTS = frozenset({"www.cardrush-op.jp", "cardrush-op.jp"})


class NotAListing(ValueError):
    pass


def canonical_listing_identity(url: str) -> str:
    """`dorasuta:<pid>` or `cardrush:<product id>`; raises NotAListing for anything else."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"}:
        raise NotAListing(url)
    host = (parts.hostname or "").lower()
    if host in DORASUTA_HOSTS:
        pids = parse_qs(parts.query).get("pid", [])
        if len(pids) == 1 and pids[0].isdigit() and parts.path.rstrip("/").endswith("/product"):
            return f"dorasuta:{int(pids[0])}"
        raise NotAListing(url)
    if host in CARDRUSH_HOSTS:
        segments = [s for s in parts.path.split("/") if s]
        if len(segments) == 2 and segments[0] == "product" and segments[1].isdigit():
            return f"cardrush:{int(segments[1])}"
        raise NotAListing(url)
    raise NotAListing(url)
