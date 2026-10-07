import gzip
import pytest
import xml.etree.ElementTree as ET

from snkrdunk_collector.published_discovery import (
    INDEX,
    MAX_XML_BYTES,
    candidate_evidence,
    listing_identity,
    locations,
    neighbours,
    sitemap_url,
)

SHARD = (
    "https://snkrdunk.com/en/sitemap/sitemap-en-product-trading-card-single-0.xml.gz"
)


def listing(n):
    return f"https://snkrdunk.com/en/trading-cards/{n}"


def xml(values, *, index=False):
    root, child = ("sitemapindex", "sitemap") if index else ("urlset", "url")
    return (
        f'<{root} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<{child}><loc>{v}</loc></{child}>" for v in values)
        + f"</{root}>"
    ).encode()


def test_only_publisher_locations_and_gzip_are_parsed():
    assert locations(xml([SHARD], index=True), index=True) == [SHARD]
    assert locations(
        gzip.compress(xml([listing(10), listing(98765)])), index=False
    ) == [listing(10), listing(98765)]


@pytest.mark.parametrize(
    "url",
    [
        "http://snkrdunk.com/en/trading-cards/1",
        "https://snkrdunk.com.evil.invalid/en/trading-cards/1",
        "https://snkrdunk.com/en/v1/trading-cards/1",
        "https://snkrdunk.com/en/trading-cards/1?next=2",
        "https://snkrdunk.com/en/trading-cards/1#2",
        "https://snkrdunk.com/en/trading-cards/01",
    ],
)
def test_forbidden_or_ambiguous_urls_are_rejected(url):
    assert listing_identity(url) is None
    with pytest.raises(ValueError):
        locations(xml([url]), index=False)


def test_index_cannot_advertise_api_or_foreign_shards():
    assert sitemap_url(INDEX)
    for url in (
        "https://other.invalid/en/sitemap/sitemap-0.xml",
        "https://snkrdunk.com/en/v1/sitemap-0.xml",
    ):
        with pytest.raises(ValueError):
            locations(xml([url], index=True), index=True)


def test_bad_document_and_entities_refuse_before_planning():
    for body in (
        b"<html>not XML sitemap</html>",
        b"<urlset>",
        b'<!DOCTYPE urlset [<!ENTITY data "x">]><urlset/>',
    ):
        with pytest.raises((ValueError, ET.ParseError)):
            locations(body, index=False)


def test_compressed_expansion_is_bounded():
    with pytest.raises(ValueError):
        locations(gzip.compress(b"x" * (MAX_XML_BYTES + 1)), index=False)


def test_neighbours_follow_published_positions_without_constructing_ids():
    urls = [listing(700), listing(40001), listing(12), listing(888888)]
    anchor = listing_identity(listing(40001))
    result = neighbours(
        {SHARD: urls}, [anchor], set(), radius_start=1, radius_end=2, limit=20
    )
    assert [r.source_url for r in result] == [
        listing(700),
        listing(12),
        listing(888888),
    ]
    assert [r.offset for r in result] == [0, 2, 3]
    assert [r.radius for r in result] == [1, 1, 2]
    assert all(r.anchor_identity == anchor for r in result)


def test_known_and_duplicate_products_are_not_replanned():
    urls = [listing(10), listing(20), listing(10), listing(30)]
    anchor = listing_identity(listing(20))
    result = neighbours(
        {SHARD: urls},
        [anchor],
        {listing_identity(listing(10))},
        radius_start=1,
        radius_end=2,
        limit=20,
    )
    assert [r.source_url for r in result] == [listing(30)]


def test_missing_anchor_does_not_fall_back_to_id_probing():
    assert (
        neighbours(
            {SHARD: [listing(10)]},
            [listing_identity(listing(99))],
            set(),
            radius_start=1,
            radius_end=2,
            limit=20,
        )
        == []
    )


@pytest.mark.parametrize(
    "start,end,limit", [(0, 1, 20), (1, 49, 20), (3, 1, 20), (1, 2, 21), (1, 2, 0)]
)
def test_bounds_are_fail_closed(start, end, limit):
    with pytest.raises(ValueError):
        neighbours(
            {SHARD: [listing(10)]},
            [listing_identity(listing(10))],
            set(),
            radius_start=start,
            radius_end=end,
            limit=limit,
        )


def page(title, image):
    return f'<html><title>{title} | SNKRDUNK</title><meta property="og:image" content="{image}"></html>'


def test_metadata_keeps_exact_asset_and_authoritative_release_separate():
    evidence = candidate_evidence(
        listing(10),
        page(
            "Roronoa Zoro L-P [OP01-001] (Booster Pack ROMANCE DAWN)",
            "https://cdn.snkrdunk.com/uploads/media/OPC-EN-TCG-OP01-001_p1-of.webp",
        ),
    )
    assert evidence.card_code == "OP01-001"
    assert evidence.asset_variant == "p1"
    assert evidence.resolved_product_code == "OP-01"
    assert evidence.price_jpy is None


def test_timestamp_parallel_and_unknown_release_do_not_become_exact_variants():
    evidence = candidate_evidence(
        listing(10),
        page(
            "Roronoa Zoro L-P [OP01-001] (Unknown release)",
            "https://cdn.snkrdunk.com/uploads/media/20220903005802-0.webp",
        ),
    )
    assert evidence.asset_variant is None and evidence.resolved_product_code is None
    assert evidence.parallel_family


def test_english_and_positive_foreign_game_evidence_are_excluded():
    assert (
        candidate_evidence(
            listing(10),
            page(
                "Roronoa Zoro L [OP01-001] [EN] (Booster Pack ROMANCE DAWN)",
                "https://cdn.snkrdunk.com/uploads/media/OPC-EN-TCG-OP01-001-of.webp",
            ),
        )
        is None
    )
    assert (
        candidate_evidence(
            listing(10),
            page(
                "Foreign L [BP08-117] (Unknown release)",
                "https://cdn.snkrdunk.com/uploads/media/SVE-TCG-bp08-117.webp",
            ),
        )
        is None
    )
