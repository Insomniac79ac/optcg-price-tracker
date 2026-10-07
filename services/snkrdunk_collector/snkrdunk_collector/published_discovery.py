"""Pure planning from published URLs and retained pages; never source I/O.

The runtime adapter must retain each response before calling these parsers.
Only publisher-listed neighbours are eligible; numeric IDs are lookup keys.
"""

from dataclasses import dataclass
import gzip
import io
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from opcg_source_identity import canonical_source_listing_identity
from snkrdunk_collector.discovery_evidence.snkrdunk_listing_evidence import (
    parse_listing,
)
from snkrdunk_collector.discovery_evidence.non_target_tcg import identify_non_target_tcg

INDEX = (
    "https://snkrdunk.com/en/sitemap/sitemap-index-en-product-trading-card-single.xml"
)
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_LOCATIONS = 100_000


def listing_identity(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "snkrdunk.com"
        or parsed.query
        or parsed.fragment
    ):
        return None
    if not re.fullmatch(r"/en/trading-cards/(?:single/)?[1-9][0-9]*/?", parsed.path):
        return None
    return canonical_source_listing_identity("snkrdunk", url)


def sitemap_url(url):
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "snkrdunk.com"
        and not parsed.query
        and not parsed.fragment
        and bool(
            re.fullmatch(
                r"/en/sitemap/sitemap-[A-Za-z0-9_-]+\.xml(?:\.gz)?", parsed.path
            )
        )
    )


def locations(retained_body, *, index):
    if (
        not isinstance(retained_body, bytes)
        or not 0 < len(retained_body) <= MAX_XML_BYTES
    ):
        raise ValueError("bounded complete retained XML response required")
    body = retained_body
    if body.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
            body = stream.read(MAX_XML_BYTES + 1)
    if (
        len(body) > MAX_XML_BYTES
        or b"<!DOCTYPE" in body.upper()
        or b"<!ENTITY" in body.upper()
    ):
        raise ValueError("bounded entity-free sitemap required")
    root = ET.fromstring(body)
    expected = "sitemapindex" if index else "urlset"
    if root.tag.split("}")[-1] != expected:
        raise ValueError("wrong published sitemap document type")
    values = []
    seen = set()
    for child in root:
        expected_child = "sitemap" if index else "url"
        if child.tag.split("}")[-1] != expected_child:
            raise ValueError("unexpected sitemap child")
        locs = [
            e.text.strip() for e in child if e.tag.split("}")[-1] == "loc" and e.text
        ]
        if len(locs) != 1:
            raise ValueError("one advertised location per entry required")
        value = locs[0]
        if not (sitemap_url(value) if index else listing_identity(value)):
            raise ValueError("advertised URL outside approved public paths")
        if value not in seen:
            seen.add(value)
            values.append(value)
        if len(values) > (12 if index else MAX_LOCATIONS):
            raise ValueError("published document count bound exceeded")
    return values


@dataclass(frozen=True)
class PublishedNeighbour:
    source_url: str
    identity: str
    anchor_identity: str
    shard_url: str
    offset: int
    radius: int


def neighbours(shards, anchors, excluded, *, radius_start, radius_end, limit):
    if (
        not 1 <= len(anchors) <= 12
        or not 1 <= radius_start <= radius_end <= 48
        or not 1 <= limit <= 20
    ):
        raise ValueError("bounded explicit published neighbourhood required")
    if not 1 <= len(shards) <= 12:
        raise ValueError("bounded current published shards required")
    wanted = set(anchors)
    result = []
    seen = set(excluded) | wanted
    positions = []
    for shard_url, urls in shards.items():
        if not sitemap_url(shard_url):
            raise ValueError("unadvertised shard path")
        identities = [listing_identity(url) for url in urls]
        if any(v is None for v in identities):
            raise ValueError("listing outside public namespace")
        positions.extend(
            (shard_url, urls, identities, offset, identity)
            for offset, identity in enumerate(identities)
            if identity in wanted
        )
    # Source order and complete radius rounds; no generated IDs or relevance rank.
    for radius in range(radius_start, radius_end + 1):
        for shard_url, urls, identities, offset, anchor in positions:
            for candidate_offset in (offset - radius, offset + radius):
                if not 0 <= candidate_offset < len(urls):
                    continue
                identity = identities[candidate_offset]
                if identity in seen:
                    continue
                seen.add(identity)
                result.append(
                    PublishedNeighbour(
                        urls[candidate_offset],
                        identity,
                        anchor,
                        shard_url,
                        candidate_offset,
                        radius,
                    )
                )
                if len(result) == limit:
                    return result
    return result


def candidate_evidence(source_url, retained_html):
    if not listing_identity(source_url):
        raise ValueError("published public listing URL required")
    evidence = parse_listing(source_url, retained_html)
    if (
        not evidence.is_one_piece
        or evidence.is_english
        or identify_non_target_tcg(evidence.image_url)
    ):
        return None
    return evidence
