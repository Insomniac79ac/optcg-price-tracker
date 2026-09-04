"""Yuyu-Tei listing discovery persistence: identity, classification, upsert.

No network anywhere in this file - the Playwright page is faked and the
database is in-memory SQLite built from the collector's own ORM mirrors, so
every constraint asserted here (composite identity, the match vocabulary, the
rule that only print_matched may carry a print id) is the real one.

What these tests are protecting is not "does it store rows" but the two things
that would be unsafe later: that one source product can never become two
candidates or two source products one candidate, and that a card code can only
carry a print id when it is 1:1 on BOTH sides - one own-series Yuyu-Tei product
and one active Atlas print.
"""

import ast
import pathlib

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from yuyutei_collector import discovery, discovery_listing, discovery_match, discovery_probe
from yuyutei_collector.browser import HOMEPAGE_URL
from yuyutei_collector.db import Base
from yuyutei_collector.discovery_listing import parse_listing_row
from yuyutei_collector.discovery_match import classify_card_code
from yuyutei_collector.discovery_probe import SourceDenied
from yuyutei_collector.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    SourceCardMapping,
    YuyuteiCandidate,
    YuyuteiDiscoveryRun,
)


# --------------------------------------------------------------------------
# Fixtures: a real database, a fake page
# --------------------------------------------------------------------------


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    db = Session()
    yield db
    db.close()


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(discovery.time, "sleep", lambda _s: None)


def listing(slug):
    return f"https://yuyu-tei.jp/sell/opc/s/{slug}"


def row(series, product_id, *, label=None, card_text=None, img=None, price_texts=None):
    """One listing anchor in the shape _scrape_listing yields.

    `price_texts` is the DOM-scoped current-price node text - one entry per
    `strong.d-block.text-end` in the product block. It defaults to [] (no
    price node), which is the fail-closed case, so a test that wants a price
    has to say which NODE carried it rather than hiding it in `card_text`.
    """
    return {
        "href": f"https://yuyu-tei.jp/sell/opc/card/{series}/{product_id}",
        "text": label or "",
        "card_text": card_text if card_text is not None else (label or ""),
        "img_alt": "",
        "img_src": img or "",
        "price_texts": list(price_texts or []),
    }


def product_row(series, product_id, code, rarity, name, price, stock, img=""):
    """A row shaped exactly like the real measured ones, e.g.
    label       'OP13-118 P-SEC モンキー・D・ルフィ(パラレル)'
    card_text   'OP13-118 モンキー・D・ルフィ(パラレル) 12,800 円 在庫 : 3 点 - + カートへ'
    price_texts ['12,800 円']

    The price appears in BOTH, exactly as on the real page: `card_text` is the
    flattened block (audit trail) and `price_texts` is the price node the
    parser actually reads.
    """
    return row(
        series,
        product_id,
        label=f"{code} {rarity} {name}",
        card_text=f"{code} {name} {price} 円 在庫 : {stock} - + カートへ",
        img=img,
        price_texts=[f"{price} 円"],
    )


def sale_row(series, product_id, code, rarity, name, price, former, stock, img=""):
    """A SALE row, as measured live on 2026-09-02.

    The block renders the current price in `strong.d-block.text-end.text-danger`
    and the FORMER price inside a `<del>`. The `<del>` is not matched by
    PRICE_NODE_SELECTOR, so it never reaches `price_texts` - but it IS part of
    the flattened block text, which is what used to make these rows ambiguous.
    """
    return row(
        series,
        product_id,
        label=f"{code} {rarity} {name}",
        card_text=f"{code} {name} {price} 円 在庫 : {stock} {former} 円 - + カートへ",
        img=img,
        price_texts=[f"{price} 円"],
    )


# A homepage body that classify_page will call `normal_product`: HTTP 200,
# over 500 bytes, carrying the expected marker and no denial evidence. Built
# here rather than fetched so these tests stay offline.
HOMEPAGE_HTML = "<html><body>遊々亭 " + ("トレカ通販 " * 120) + "</body></html>"


class FakePage:
    """Stands in for a Playwright page. Records every URL navigated.

    Serves the homepage as a normal page by default, so a test that says
    nothing about the warm-up gets a successful one and goes on to enumerate -
    the same shape a real run has. `homepage_status` / `homepage_html` /
    `homepage_title` let a test refuse it instead.
    """

    def __init__(
        self,
        pages,
        status=200,
        homepage_status=200,
        homepage_html=HOMEPAGE_HTML,
        homepage_title="遊々亭",
    ):
        self.pages = pages
        self.status = status
        self.homepage_status = homepage_status
        self.homepage_html = homepage_html
        self.homepage_title = homepage_title
        self.visited = []
        self._current = None

    def goto(self, url, **kwargs):
        self.visited.append(url)
        self._current = url
        if url == HOMEPAGE_URL:
            status = self.homepage_status
        else:
            status = self.pages.get(url, {}).get("status", self.status)
        # `ok` as Playwright defines it (2xx). `_scrape_listing` only reads
        # `status`; browser.capture(), which the warm-up goes through, reads
        # both.
        return type("R", (), {"status": status, "ok": 200 <= status < 300})()

    def wait_for_timeout(self, ms):
        return None

    @property
    def url(self):
        # browser.capture() reports the FINAL url of a navigation; nothing here
        # redirects, so it is the one just requested.
        return self._current

    def title(self):
        return self.homepage_title if self._current == HOMEPAGE_URL else ""

    def content(self):
        if self._current == HOMEPAGE_URL:
            return self.homepage_html
        return "<html></html>"

    def eval_on_selector_all(self, selector, script):
        entry = self.pages.get(self._current, {})
        if "page=" in selector or "pagination" in selector:
            return entry.get("pagination", [])
        return entry.get("anchors", [])


def make_family(session, card_code, print_count, *, active=True, start_id=1):
    """A canonical card plus `print_count` prints carrying its identity."""
    canonical = CanonicalCard(card_code=card_code)
    session.add(canonical)
    session.flush()
    prints = []
    for _ in range(print_count):
        card_print = CardPrint(
            canonical_card_id=canonical.id,
            treatment=None,
            verification_status="verified",
            is_active=active,
        )
        session.add(card_print)
        prints.append(card_print)
    session.flush()
    return canonical, prints


# --------------------------------------------------------------------------
# Source identity is composite
# --------------------------------------------------------------------------


def test_the_same_product_id_in_two_series_is_two_candidates(session):
    # Measured on 2026-09-01: ids 10152-10154 exist in BOTH op01 and op13 and
    # denote different cards. A product_id-only key would merge them.
    page = FakePage(
        {
            listing("op01"): {"anchors": [row("op01", "10152", label="OP01-120 SEC シャンクス")]},
            listing("op13"): {"anchors": [row("op13", "10152", label="OP13-118 P-SEC ルフィ")]},
        }
    )
    discovery.discover_and_persist(session, page, ["op01", "op13"])

    candidates = session.scalars(select(YuyuteiCandidate).order_by(YuyuteiCandidate.set_slug)).all()
    assert [(c.set_slug, c.product_id) for c in candidates] == [
        ("op01", "10152"),
        ("op13", "10152"),
    ]
    assert candidates[0].detected_card_code == "OP01-120"
    assert candidates[1].detected_card_code == "OP13-118"


def test_the_database_refuses_a_second_row_for_one_source_product(session):
    # The uniqueness is enforced by the schema, not only by the upsert path -
    # so a future writer that forgets to check cannot create a duplicate.
    for _ in range(2):
        session.add(
            YuyuteiCandidate(
                set_slug="op01",
                product_id="10152",
                source_url="https://yuyu-tei.jp/sell/opc/card/op01/10152",
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()


def test_duplicate_anchors_for_one_product_collapse(session):
    # Every listing row links its product twice (image + text): 128-216
    # duplicate links per measured set.
    anchors = [
        row("op01", "1", label="OP01-001 C ルフィ"),
        row("op01", "1", label="OP01-001 C ルフィ"),
        row("op01", "2", label="OP01-002 R ゾロ"),
    ]
    page = FakePage({listing("op01"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op01"])

    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 2
    assert report["per_slug"]["op01"]["duplicate_products"] == 1
    assert report["per_slug"]["op01"]["raw_product_anchors"] == 3


def test_foreign_series_products_are_filtered_not_stored(session):
    # 12-38% of a measured listing page cross-links into other sets. Storing
    # those under the requested slug would file another set's products here.
    anchors = [
        row("eb01", "1", label="EB01-001 C ルフィ"),
        row("op17", "9", label="OP17-001 C エース"),
        row("op12", "8", label="OP12-050 R ロー"),
    ]
    page = FakePage({listing("eb01"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["eb01"])

    stored = session.scalars(select(YuyuteiCandidate)).all()
    assert [(c.set_slug, c.product_id) for c in stored] == [("eb01", "1")]
    metrics = report["per_slug"]["eb01"]
    assert metrics["foreign_series_filtered"] == 2
    assert metrics["foreign_series_seen"] == ["op12", "op17"]
    assert metrics["own_series_products"] == 1


# --------------------------------------------------------------------------
# Card-code grammar - all five real Atlas shapes survive into a candidate
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug,code",
    [
        ("op01", "OP01-001"),
        ("st01", "ST01-005"),
        ("eb01", "EB01-061"),
        ("prb01", "PRB01-001"),
        ("promo-op10", "P-014"),
    ],
)
def test_every_card_code_shape_reaches_the_candidate(session, slug, code):
    page = FakePage({listing(slug): {"anchors": [row(slug, "1", label=f"{code} SEC 名前")]}})
    discovery.discover_and_persist(session, page, [slug])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.detected_card_code == code
    assert candidate.detected_rarity == "SEC"


def test_a_row_with_no_readable_code_is_stored_and_counted(session):
    # 2-3 products per measured set carry no parseable code. They are real
    # products and are kept - dropping them would hide them from review.
    page = FakePage({listing("op01"): {"anchors": [row("op01", "1", label="ノーコード商品")]}})
    report = discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.detected_card_code is None
    assert candidate.match_status == "unmatched"
    assert report["per_slug"]["op01"]["unparseable_codes"] == 1


# --------------------------------------------------------------------------
# Classification: catalogue cardinality only
# --------------------------------------------------------------------------


def test_a_code_atlas_does_not_know_is_unmatched(session):
    result = classify_card_code(
        session, "OP99-999", source_product_count=1, source_listing_complete=True
    )
    assert result.match_status == "unmatched"
    assert result.matched_card_print_id is None


def test_a_code_with_exactly_one_active_print_is_print_matched(session):
    _, prints = make_family(session, "OP01-001", 1)
    result = classify_card_code(
        session, "OP01-001", source_product_count=1, source_listing_complete=True
    )

    assert result.match_status == "print_matched"
    assert result.matched_card_print_id == prints[0].id
    assert result.explanation["active_print_count"] == 1


def test_a_code_with_several_active_prints_is_family_matched_with_no_print(session):
    _, prints = make_family(session, "OP01-120", 3)
    result = classify_card_code(
        session, "OP01-120", source_product_count=1, source_listing_complete=True
    )

    assert result.match_status == "family_matched"
    # The whole point: no representative printing is chosen.
    assert result.matched_card_print_id is None
    assert result.explanation["reason"] == "multiple_active_prints"
    # The alternatives are RECORDED for a human, which is not the same as
    # picking one.
    assert result.explanation["candidate_card_print_ids"] == sorted(p.id for p in prints)


def test_inactive_prints_do_not_count_toward_the_cardinality(session):
    canonical, _ = make_family(session, "OP01-002", 1)
    session.add(
        CardPrint(
            canonical_card_id=canonical.id,
            treatment=None,
            verification_status="verified",
            is_active=False,
        )
    )
    session.flush()
    # Two prints exist; only one is active, so the code still implies it.
    result = classify_card_code(
        session, "OP01-002", source_product_count=1, source_listing_complete=True
    )
    assert result.match_status == "print_matched"


def test_a_family_with_no_active_print_is_family_matched_not_unmatched(session):
    make_family(session, "OP01-003", 1, active=False)
    result = classify_card_code(
        session, "OP01-003", source_product_count=1, source_listing_complete=True
    )

    # "unmatched" would claim Atlas has never heard of the card, which is false.
    assert result.match_status == "family_matched"
    assert result.matched_card_print_id is None
    assert result.explanation["reason"] == "canonical_card_without_active_prints"


def test_duplicate_canonical_identity_fails_closed(session):
    # uq_canonical_cards_card_code makes this unreachable in the real schema.
    # If it ever happens, identity is unprovable and discovery must not choose.
    session.add_all([CanonicalCard(card_code="OP01-004"), CanonicalCard(card_code="OP01-004")])
    session.flush()
    result = classify_card_code(
        session, "OP01-004", source_product_count=1, source_listing_complete=True
    )

    assert result.match_status == "identity_conflict"
    assert result.matched_card_print_id is None
    assert result.explanation["reason"] == "canonical_card_code_not_unique"


def test_the_database_forbids_a_print_id_on_anything_but_print_matched(session):
    # Belt and braces: even a future bug that assigned a "representative"
    # print to a family_matched candidate cannot be committed.
    _, prints = make_family(session, "OP01-120", 2)
    session.add(
        YuyuteiCandidate(
            set_slug="op01",
            product_id="1",
            source_url="https://yuyu-tei.jp/sell/opc/card/op01/1",
            match_status="family_matched",
            matched_card_print_id=prints[0].id,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_classification_uses_only_the_code_not_the_annotation(session):
    # Two products of the same multi-print card, one plainly annotated as the
    # parallel. The annotation is preserved but must NOT resolve the print.
    make_family(session, "OP13-118", 3)
    anchors = [
        product_row("op13", "10151", "OP13-118", "SEC", "ルフィ", "500", "3 点"),
        product_row("op13", "10152", "OP13-118", "P-SEC", "ルフィ(パラレル)", "12,800", "3 点"),
    ]
    page = FakePage({listing("op13"): {"anchors": anchors}})
    discovery.discover_and_persist(session, page, ["op13"])

    for candidate in session.scalars(select(YuyuteiCandidate)).all():
        assert candidate.match_status == "family_matched"
        assert candidate.matched_card_print_id is None


# --------------------------------------------------------------------------
# print_matched requires 1:1 on BOTH sides
#
# The source side is a real cardinality too. Yuyu-Tei sells base, parallel and
# super-parallel as SEPARATE products under ONE card code, so a code with two
# products cannot imply one printing even when Atlas holds exactly one active
# print - both candidates would otherwise claim it. Each case below fixes one
# corner of the 2x2 (source products x active prints).
# --------------------------------------------------------------------------


def test_one_source_product_and_one_active_print_is_print_matched(session):
    # Case A - the only shape in which the code implies a printing.
    _, prints = make_family(session, "OP01-001", 1)
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.match_status == "print_matched"
    assert candidate.matched_card_print_id == prints[0].id
    assert candidate.match_explanation_json["reason"] == "unique_source_product_and_active_print"
    assert candidate.match_explanation_json["source_product_count"] == 1
    assert candidate.match_explanation_json["active_print_count"] == 1


def test_two_source_products_sharing_a_code_never_claim_one_print(session):
    # Case B - the bug this rule closes. Base and parallel are two products;
    # Atlas knows one active print. Handing that print to BOTH would assert an
    # identity the listing does not support, and handing it to either one would
    # be a guess about which is which.
    _, prints = make_family(session, "OP13-118", 1)
    anchors = [
        product_row("op13", "10151", "OP13-118", "SEC", "ルフィ", "500", "3 点"),
        product_row("op13", "10152", "OP13-118", "P-SEC", "ルフィ(パラレル)", "12,800", "3 点"),
    ]
    page = FakePage({listing("op13"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op13"])

    candidates = session.scalars(
        select(YuyuteiCandidate).order_by(YuyuteiCandidate.product_id)
    ).all()
    assert len(candidates) == 2
    for candidate in candidates:
        assert candidate.match_status == "family_matched"
        assert candidate.matched_card_print_id is None
        explanation = candidate.match_explanation_json
        assert explanation["reason"] == "multiple_source_products"
        assert explanation["source_product_count"] == 2
        assert explanation["active_print_count"] == 1
        # The one print is recorded for the reviewer, not assigned.
        assert explanation["candidate_card_print_ids"] == [prints[0].id]
    assert report["per_slug"]["op13"]["print_matched"] == 0
    assert report["per_slug"]["op13"]["family_matched"] == 2


def test_one_source_product_and_two_active_prints_is_family_matched(session):
    # Case C - unchanged by this rule, and re-asserted end to end.
    make_family(session, "OP01-120", 2)
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-120", "SEC", "シャンクス", "9,800", "3 点")]}}
    )
    discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.match_status == "family_matched"
    assert candidate.matched_card_print_id is None
    assert candidate.match_explanation_json["reason"] == "multiple_active_prints"
    assert candidate.match_explanation_json["source_product_count"] == 1


def test_two_source_products_and_two_active_prints_is_family_matched(session):
    # Case D - plural on both sides. Pairing them off 1:1 by order, rarity or
    # price would be the guess; there is no evidence here for any pairing.
    make_family(session, "OP13-118", 2)
    anchors = [
        product_row("op13", "10151", "OP13-118", "SEC", "ルフィ", "500", "3 点"),
        product_row("op13", "10152", "OP13-118", "P-SEC", "ルフィ(パラレル)", "12,800", "3 点"),
    ]
    page = FakePage({listing("op13"): {"anchors": anchors}})
    discovery.discover_and_persist(session, page, ["op13"])

    candidates = session.scalars(select(YuyuteiCandidate)).all()
    assert len(candidates) == 2
    for candidate in candidates:
        assert candidate.match_status == "family_matched"
        assert candidate.matched_card_print_id is None
        explanation = candidate.match_explanation_json
        assert explanation["reason"] == "multiple_source_products_and_active_prints"
        assert explanation["source_product_count"] == 2
        assert explanation["active_print_count"] == 2


def test_a_foreign_series_row_with_the_same_code_does_not_block_a_1_to_1_match(session):
    # Case E - the source-side count is over the OWN-SERIES result only. A
    # cross-link carrying the same code is another category's product; letting
    # it inflate the count would suppress a legitimate print match.
    _, prints = make_family(session, "OP01-001", 1)
    anchors = [
        product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点"),
        product_row("op17", "9", "OP01-001", "C", "ルフィ", "320", "3 点"),
    ]
    page = FakePage({listing("op01"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.set_slug == "op01"
    assert candidate.match_status == "print_matched"
    assert candidate.matched_card_print_id == prints[0].id
    assert candidate.match_explanation_json["source_product_count"] == 1
    assert report["per_slug"]["op01"]["foreign_series_filtered"] == 1


def test_rediscovery_keeps_the_pair_family_matched(session):
    # Case F - the correction is a property of every run, not a first-run
    # accident. The second pass re-reads both rows and must reach the same
    # answer rather than upgrading either one in place.
    make_family(session, "OP13-118", 1)
    anchors = [
        product_row("op13", "10151", "OP13-118", "SEC", "ルフィ", "500", "3 点"),
        product_row("op13", "10152", "OP13-118", "P-SEC", "ルフィ(パラレル)", "12,800", "3 点"),
    ]
    page = FakePage({listing("op13"): {"anchors": anchors}})
    for _ in range(3):
        discovery.discover_and_persist(session, page, ["op13"])

    candidates = session.scalars(select(YuyuteiCandidate)).all()
    assert len(candidates) == 2
    assert {c.match_status for c in candidates} == {"family_matched"}
    assert all(c.matched_card_print_id is None for c in candidates)


def test_a_sibling_product_appearing_later_demotes_an_earlier_print_match(session):
    # The same rule read from the other direction: a code that was genuinely
    # 1:1 stops being so the day Yuyu-Tei lists the parallel, and the stored
    # print id must be given up on the next discovery.
    _, prints = make_family(session, "OP13-118", 1)
    first = FakePage(
        {listing("op13"): {"anchors": [product_row("op13", "10151", "OP13-118", "SEC", "ルフィ", "500", "3 点")]}}
    )
    discovery.discover_and_persist(session, first, ["op13"])
    assert session.scalars(select(YuyuteiCandidate)).one().matched_card_print_id == prints[0].id

    second = FakePage(
        {
            listing("op13"): {
                "anchors": [
                    product_row("op13", "10151", "OP13-118", "SEC", "ルフィ", "500", "3 点"),
                    product_row("op13", "10152", "OP13-118", "P-SEC", "ルフィ(パラレル)", "12,800", "3 点"),
                ]
            }
        }
    )
    discovery.discover_and_persist(session, second, ["op13"])

    candidates = session.scalars(select(YuyuteiCandidate)).all()
    assert len(candidates) == 2
    assert {c.match_status for c in candidates} == {"family_matched"}
    assert all(c.matched_card_print_id is None for c in candidates)


def test_the_source_side_inputs_have_no_defaults(session):
    # A caller that has not measured the source side cannot fall through to
    # "assume one product, whole listing" - that assumption IS the over-claim.
    make_family(session, "OP01-001", 1)
    with pytest.raises(TypeError):
        classify_card_code(session, "OP01-001")
    with pytest.raises(TypeError):
        classify_card_code(session, "OP01-001", source_product_count=1)
    with pytest.raises(TypeError):
        classify_card_code(session, "OP01-001", source_listing_complete=True)


# --------------------------------------------------------------------------
# A truncated enumeration cannot prove source-side uniqueness
#
# Observing one product with a code is only evidence that no sibling exists if
# the whole slug was read. When a product or page cap stopped the enumeration,
# the parallel may be sitting on the page that was never fetched, so the slug
# fails closed to family_matched. The signal is the enumeration's own
# completeness flag - NEVER "the count looked small enough".
# --------------------------------------------------------------------------


def test_a_complete_slug_still_reaches_print_matched(session):
    # Case A - the control. Nothing about failing closed may cost a real 1:1.
    _, prints = make_family(session, "OP01-001", 1)
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    report = discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.match_status == "print_matched"
    assert candidate.matched_card_print_id == prints[0].id
    assert candidate.match_explanation_json["source_listing_complete"] is True
    metrics = report["per_slug"]["op01"]
    assert metrics["enumeration_complete"] is True
    assert metrics["budget_exhausted"] is False
    assert metrics["page_budget_exhausted"] is False


def test_the_product_cap_blocks_an_apparent_1_to_1(session):
    # Case B - the code is observed once and Atlas holds one active print, so
    # this is precisely the shape that would otherwise be print_matched. The
    # product cap stopped the read, so the count is a floor, not a total.
    make_family(session, "OP01-001", 1)
    anchors = [
        product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点"),
        product_row("op01", "2", "OP01-002", "R", "ゾロ", "480", "3 点"),
    ]
    page = FakePage({listing("op01"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op01"], max_products_per_slug=1)

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.detected_card_code == "OP01-001"
    assert candidate.match_status == "family_matched"
    assert candidate.matched_card_print_id is None
    explanation = candidate.match_explanation_json
    assert explanation["reason"] == "source_listing_truncated"
    assert explanation["source_listing_complete"] is False
    # The observed count is reported honestly as what it is: one seen so far.
    assert explanation["source_product_count"] == 1
    assert explanation["active_print_count"] == 1
    metrics = report["per_slug"]["op01"]
    assert metrics["budget_exhausted"] is True
    assert metrics["enumeration_complete"] is False
    assert metrics["print_matched"] == 0


def test_the_page_cap_blocks_an_apparent_1_to_1(session):
    # Case C - the same failure by the other route. Page 2 exists and was never
    # fetched; the parallel that would make this a pair could be on it.
    make_family(session, "OP01-001", 1)
    base = listing("op01")
    page = FakePage(
        {
            base: {
                "anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")],
                "pagination": [f"{base}?page=2"],
            },
            f"{base}?page=2": {
                "anchors": [product_row("op01", "2", "OP01-001", "P-C", "ルフィ(パラレル)", "9,800", "3 点")]
            },
        }
    )
    report = discovery.discover_and_persist(session, page, ["op01"], max_pages_per_slug=1)

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.match_status == "family_matched"
    assert candidate.matched_card_print_id is None
    explanation = candidate.match_explanation_json
    assert explanation["reason"] == "source_listing_truncated"
    assert explanation["source_listing_complete"] is False
    metrics = report["per_slug"]["op01"]
    assert metrics["page_budget_exhausted"] is True
    assert metrics["unfetched_pages"] == 1
    assert metrics["enumeration_complete"] is False
    # Only the fetched page was navigated - failing closed is not a reason to
    # go and fetch more. The homepage warm-up precedes it and is the only
    # other navigation.
    assert page.visited == [HOMEPAGE_URL, base]


def test_exhausting_the_page_budget_with_nothing_left_is_still_complete(session):
    # The flag is about outstanding pages, not about the cap being reached. A
    # set whose last page links back to page 1 has been read to the end.
    _, prints = make_family(session, "OP01-002", 1)
    base = listing("op01")
    page = FakePage(
        {
            base: {
                "anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")],
                "pagination": [f"{base}?page=2"],
            },
            f"{base}?page=2": {
                "anchors": [product_row("op01", "2", "OP01-002", "R", "ゾロ", "480", "3 点")],
                "pagination": [base],
            },
        }
    )
    report = discovery.discover_and_persist(session, page, ["op01"], max_pages_per_slug=2)

    metrics = report["per_slug"]["op01"]
    assert metrics["pages_fetched"] == 2
    assert metrics["unfetched_pages"] == 0
    assert metrics["enumeration_complete"] is True
    zoro = session.scalars(
        select(YuyuteiCandidate).where(YuyuteiCandidate.detected_card_code == "OP01-002")
    ).one()
    assert zoro.match_status == "print_matched"
    assert zoro.matched_card_print_id == prints[0].id


def test_a_truncated_slug_with_a_sibling_product_is_family_matched_as_before(session):
    # Case D - two source products AND a truncated read. Both reasons to refuse
    # apply; the plural one is reported because it is decisive on its own, and
    # the completeness flag is recorded beside it.
    make_family(session, "OP13-118", 1)
    anchors = [
        product_row("op13", "10151", "OP13-118", "SEC", "ルフィ", "500", "3 点"),
        product_row("op13", "10152", "OP13-118", "P-SEC", "ルフィ(パラレル)", "12,800", "3 点"),
        product_row("op13", "10153", "OP13-119", "SEC", "エース", "500", "3 点"),
    ]
    page = FakePage({listing("op13"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op13"], max_products_per_slug=2)

    candidates = session.scalars(select(YuyuteiCandidate)).all()
    assert len(candidates) == 2
    for candidate in candidates:
        assert candidate.match_status == "family_matched"
        assert candidate.matched_card_print_id is None
        assert candidate.match_explanation_json["reason"] == "multiple_source_products"
        assert candidate.match_explanation_json["source_listing_complete"] is False
    assert report["per_slug"]["op13"]["enumeration_complete"] is False


def test_foreign_series_rows_do_not_make_a_complete_slug_look_truncated(session):
    # Case E - cross-links are dropped before the product budget is charged, so
    # a page that is mostly other sets is still a complete read of this one.
    _, prints = make_family(session, "OP01-001", 1)
    anchors = [row("op17", str(i), label=f"OP17-{i:03d} C n") for i in range(1, 20)]
    anchors.append(product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点"))
    page = FakePage({listing("op01"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op01"], max_products_per_slug=5)

    metrics = report["per_slug"]["op01"]
    assert metrics["foreign_series_filtered"] == 19
    assert metrics["budget_exhausted"] is False
    assert metrics["enumeration_complete"] is True

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.match_status == "print_matched"
    assert candidate.matched_card_print_id == prints[0].id


def test_a_later_complete_enumeration_may_upgrade_the_candidate(session):
    # Case F - failing closed is provisional, not permanent. Once the slug is
    # read to the end and the 1:1 is actually proven, the same candidate row
    # earns the print id it was refused before.
    _, prints = make_family(session, "OP01-001", 1)
    anchors = [
        product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点"),
        product_row("op01", "2", "OP01-002", "R", "ゾロ", "480", "3 点"),
    ]
    page = FakePage({listing("op01"): {"anchors": anchors}})

    discovery.discover_and_persist(session, page, ["op01"], max_products_per_slug=1)
    truncated = session.scalars(select(YuyuteiCandidate)).one()
    original_id = truncated.id
    assert truncated.match_status == "family_matched"
    assert truncated.matched_card_print_id is None

    discovery.discover_and_persist(session, page, ["op01"])

    upgraded = session.scalars(
        select(YuyuteiCandidate).where(YuyuteiCandidate.detected_card_code == "OP01-001")
    ).one()
    assert upgraded.id == original_id
    assert upgraded.match_status == "print_matched"
    assert upgraded.matched_card_print_id == prints[0].id
    assert upgraded.match_explanation_json["source_listing_complete"] is True


# --------------------------------------------------------------------------
# Listing facts are persisted, and source text is preserved verbatim
# --------------------------------------------------------------------------


def test_price_availability_image_and_name_are_persisted(session):
    anchors = [
        product_row(
            "op13", "10152", "OP13-118", "P-SEC", "モンキー・D・ルフィ(パラレル)",
            "12,800", "3 点", img="https://card.yuyu-tei.jp/opc/100_140/op13/10152.jpg",
        )
    ]
    page = FakePage({listing("op13"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op13"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.price_jpy == 12800
    assert candidate.availability == "in_stock"
    assert candidate.image_url == "https://card.yuyu-tei.jp/opc/100_140/op13/10152.jpg"
    assert candidate.detected_rarity == "P-SEC"
    assert candidate.source_url == "https://yuyu-tei.jp/sell/opc/card/op13/10152"

    metrics = report["per_slug"]["op13"]
    assert metrics["candidates_with_price"] == 1
    assert metrics["candidates_with_image"] == 1
    assert metrics["candidates_with_rarity"] == 1
    assert metrics["candidates_with_name_jp"] == 1
    assert metrics["candidates_with_availability"] == 1


@pytest.mark.parametrize(
    "annotation",
    ["(パラレル)", "(パラレル)(スーパーパラレル)", "(パラレル)(レッドスーパーパラレル)", "(刻印なし)"],
)
def test_variant_annotations_survive_verbatim(session, annotation):
    # This text is the ONLY listing-level evidence separating the prints behind
    # a family_matched code. Normalising it away would destroy the later
    # matcher's input before it is ever built.
    name = f"モンキー・D・ルフィ{annotation}"
    page = FakePage(
        {listing("op13"): {"anchors": [product_row("op13", "1", "OP13-118", "P-SEC", name, "500", "×")]}}
    )
    discovery.discover_and_persist(session, page, ["op13"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.name_jp == name
    assert annotation in candidate.raw_listing_text


@pytest.mark.parametrize(
    "stock,expected",
    [("3 点", "in_stock"), ("×", "out_of_stock"), ("◯", "in_stock"), ("0 点", "out_of_stock")],
)
def test_availability_vocabulary_matches_the_source(session, stock, expected):
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", stock)]}}
    )
    discovery.discover_and_persist(session, page, ["op01"])
    assert session.scalars(select(YuyuteiCandidate)).one().availability == expected


def test_two_current_price_nodes_on_one_block_store_no_price(session):
    # Two CURRENT-price nodes: the block does not say which governs, so no
    # price is recorded rather than a guessed one.
    #
    # This replaces an earlier test that used a struck former price beside a
    # current one as its example of ambiguity. That example is no longer
    # ambiguous - the former price sits in a <del> the selector cannot match
    # (see test_sale_row_takes_the_current_price_not_the_struck_former_one) -
    # so the ambiguity case is now stated with the shape that genuinely is
    # ambiguous: more than one matching price node.
    anchors = [
        row(
            "op01",
            "1",
            label="OP01-001 C ルフィ",
            card_text="OP01-001 ルフィ 1,200 円 980 円 在庫 : 3 点",
            price_texts=["1,200 円", "980 円"],
        )
    ]
    page = FakePage({listing("op01"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op01"])

    assert session.scalars(select(YuyuteiCandidate)).one().price_jpy is None
    assert report["per_slug"]["op01"]["candidates_with_ambiguous_price"] == 1


def test_one_price_node_holding_two_numbers_is_still_refused(session):
    # parse_price's own ambiguity branch is still live: DOM scoping narrows
    # WHICH text is examined, it does not relax the numeric check applied to it.
    anchors = [
        row(
            "op01",
            "1",
            label="OP01-001 C ルフィ",
            card_text="OP01-001 ルフィ 在庫 : 3 点",
            price_texts=["1,200 円 980 円"],
        )
    ]
    page = FakePage({listing("op01"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op01"])

    assert session.scalars(select(YuyuteiCandidate)).one().price_jpy is None
    assert report["per_slug"]["op01"]["candidates_with_ambiguous_price"] == 1


# --------------------------------------------------------------------------
# Homepage session warm-up
#
# Discovery used to open with a cold navigation straight to the first category
# page. On staging 2026-09-02 that was answered 403 (run 3, denied, zero
# candidates) while the warmed posture the price collector already used had
# reached the same pages with 200 minutes earlier. These tests pin the
# warm-up's position, its session sharing, and both fail-closed paths.
# --------------------------------------------------------------------------


def test_the_homepage_is_navigated_before_any_listing_url(session):
    # A: order, not merely presence.
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    discovery.discover_and_persist(session, page, ["op01"])

    assert page.visited[0] == HOMEPAGE_URL
    assert page.visited == [HOMEPAGE_URL, listing("op01")]


def test_the_warm_up_and_the_listings_share_one_page_and_session(session):
    # B: the session state the homepage establishes lives in the context behind
    # THIS page, so a warm-up on any other page would be worthless. Every
    # navigation must arrive on the object discovery was handed.
    page = FakePage(
        {
            listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]},
            listing("op13"): {"anchors": [product_row("op13", "2", "OP13-001", "C", "ゾロ", "50", "2 点")]},
        }
    )
    seen_by = []
    original_goto = page.goto

    def recording_goto(url, **kwargs):
        seen_by.append(id(page))
        return original_goto(url, **kwargs)

    page.goto = recording_goto
    discovery.discover_and_persist(session, page, ["op01", "op13"])

    assert page.visited == [HOMEPAGE_URL, listing("op01"), listing("op13")]
    assert seen_by == [id(page)] * 3


def test_a_successful_warm_up_proceeds_to_normal_enumeration(session):
    # C + H: everything the run measures is what it measured before; the only
    # difference is the extra navigation, which `pages_fetched` excludes.
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    report = discovery.discover_and_persist(session, page, ["op01"])

    metrics = report["per_slug"]["op01"]
    assert report["status"] == "completed"
    assert metrics["pages_fetched"] == 1
    assert metrics["own_series_products"] == 1
    assert metrics["candidates_written"] == 1
    assert metrics["enumeration_complete"] is True
    assert report["totals"]["pages_fetched"] == 1

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.price_jpy == 320
    assert candidate.availability == "in_stock"
    run = session.scalars(select(YuyuteiDiscoveryRun)).one()
    assert run.status == "completed"
    assert run.pages_fetched == 1


def test_a_denied_homepage_stops_before_any_listing_url_is_requested(session):
    # D + E + G: the run is `denied`, no listing was ever requested, nothing was
    # written, and exactly one navigation happened - no retry of the homepage
    # and no attempt to proceed anyway.
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}},
        homepage_status=403,
    )
    report = discovery.discover_and_persist(session, page, ["op01", "op13", "eb01"])

    assert page.visited == [HOMEPAGE_URL]
    assert not any("/sell/opc/s/" in url for url in page.visited)
    assert report["status"] == "denied"
    assert report["stopped_reason"] == f"source_denied: 403 at {HOMEPAGE_URL}"
    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 0

    # per_slug used to be empty here. It now carries an explicit unvisited
    # entry per requested slug, which says the same thing without relying on
    # absence: nothing was enumerated, and each slug names why. Silence and
    # "enumerated, found nothing" were indistinguishable before, and with a
    # catalogue-wide scope that ambiguity is what would let a denial at slug 7
    # of 60 read as full coverage.
    assert set(report["per_slug"]) == {"op01", "op13", "eb01"}
    assert all(m["visited"] is False for m in report["per_slug"].values())
    assert all(m["outcome"] == "not_visited_session_denied" for m in report["per_slug"].values())
    assert all(m["candidates_written"] == 0 for m in report["per_slug"].values())
    assert all(m["enumeration_complete"] is False for m in report["per_slug"].values())
    assert report["slugs_visited"] == []
    assert report["slugs_not_visited"] == ["eb01", "op01", "op13"]

    run = session.scalars(select(YuyuteiDiscoveryRun)).one()
    assert run.status == "denied"
    assert run.candidates_written == 0
    assert run.pages_fetched == 0
    assert run.finished_at is not None


def test_a_challenge_page_served_with_200_is_also_a_denial(session):
    # The case a status check alone cannot see: HTTP 200 carrying a challenge.
    page = FakePage(
        {listing("op01"): {"anchors": []}},
        homepage_status=200,
        homepage_html="<html><body>" + ("x" * 600) + " Just a moment... </body></html>",
        homepage_title="Just a moment...",
    )
    report = discovery.discover_and_persist(session, page, ["op01"])

    assert page.visited == [HOMEPAGE_URL]
    assert report["status"] == "denied"
    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 0


def test_an_unexpected_homepage_is_a_failed_run_not_a_denial(session):
    # Not a refusal - a fault. It takes the existing unexpected-failure path:
    # run recorded `failed` with an error_message, and the exception surfaces
    # rather than being swallowed. Still no listing URL, still nothing written.
    page = FakePage({listing("op01"): {"anchors": []}}, homepage_status=404)

    with pytest.raises(RuntimeError, match="did not establish a usable session"):
        discovery.discover_and_persist(session, page, ["op01"])

    assert page.visited == [HOMEPAGE_URL]
    run = session.scalars(select(YuyuteiDiscoveryRun)).one()
    assert run.status == "failed"
    assert run.error_message is not None
    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 0


def test_a_listing_denial_after_a_good_warm_up_is_unchanged(session):
    # F: the pre-existing behaviour. The warm-up succeeds, op01 is refused, the
    # whole run stops there - eb01 is never attempted and op01 is not retried.
    page = FakePage(
        {
            listing("op01"): {"status": 403, "anchors": []},
            listing("eb01"): {"anchors": [product_row("eb01", "1", "EB01-001", "C", "ゾロ", "50", "1 点")]},
        }
    )
    report = discovery.discover_and_persist(session, page, ["op01", "eb01"])

    assert page.visited == [HOMEPAGE_URL, listing("op01")]
    assert report["status"] == "denied"
    assert report["stopped_reason"].startswith("source_denied: 403")
    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 0


def test_discovery_and_the_collector_share_one_warm_up_implementation():
    # Anti-drift: both callers must go through browser.warm_up_homepage, and
    # neither may restate the gate. This is the check that would have caught
    # the original gap - discovery simply had no warm-up at all.
    import inspect

    from yuyutei_collector import browser, collect

    for module in (discovery, collect):
        src = inspect.getsource(module)
        assert "warm_up_homepage(" in src, f"{module.__name__} must use the shared warm-up"
        assert "homepage_session_ok(" in src, f"{module.__name__} must use the shared gate"
        # The distinctive opener of the old inline gate. Narrow on purpose:
        # collect.py still gates the PRODUCT page on its own classification,
        # which is a different check and must stay.
        assert '"error" not in homepage_step' not in src, (
            f"{module.__name__} restates the homepage gate instead of calling "
            "browser.homepage_session_ok"
        )
    assert browser.HOMEPAGE_URL == "https://yuyu-tei.jp/"
    assert browser.HOMEPAGE_EXPECTED_MARKERS == ["遊々亭"]


def test_the_warm_up_creates_no_second_browser_session():
    # A warm-up on a context of its own would leave the real navigation exactly
    # as cold as before, so the helper must only ever use the page it is given.
    import inspect

    from yuyutei_collector import browser

    src = inspect.getsource(browser.warm_up_homepage)
    for forbidden in ("new_context", "new_page", "chromium", "launch"):
        assert forbidden not in src, f"warm_up_homepage must not call {forbidden}"


# --------------------------------------------------------------------------
# DOM-scoped price selection
#
# Every shape below was measured on the live listing pages for op01, op13 and
# eb01 on 2026-09-02 (homepage warm-up + three listing navigations, all 200).
# The price is read from `strong.d-block.text-end` and from nothing else.
# --------------------------------------------------------------------------


def test_ordinary_one_price_block_is_unchanged(session):
    # A: the common shape. One price node, one price, no ambiguity - exactly
    # what this row produced before DOM scoping.
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    report = discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.price_jpy == 320
    assert report["per_slug"]["op01"]["candidates_with_price"] == 1
    assert report["per_slug"]["op01"]["candidates_with_ambiguous_price"] == 0


def test_sale_row_takes_the_current_price_not_the_struck_former_one(session):
    # B + F: the 45-row class. `<del>` holds the former price and is not
    # matched by PRICE_NODE_SELECTOR, so only the current price is offered.
    # The former price is still visible in raw_listing_text and must never be
    # the value chosen.
    page = FakePage(
        {
            listing("op01"): {
                "anchors": [sale_row("op01", "10007", "OP01-004", "R", "ウソップ", "80", "120", "◯")]
            }
        }
    )
    report = discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.price_jpy == 80
    assert "120 円" in candidate.raw_listing_text
    assert report["per_slug"]["op01"]["candidates_with_ambiguous_price"] == 0


def test_price_node_beats_a_yen_initial_card_name_colliding_with_the_code(session):
    # C: OP01-027 円卓. Flattened, `OP01-027 円卓 80 円 ...` lets PRICE_RE match
    # "027 円" and the row reads as two prices; the price NODE says 80 and
    # never contains the code.
    anchors = [
        row(
            "op01",
            "10035",
            label="OP01-027 C 円卓",
            card_text="OP01-027 円卓 80 円 在庫 : 10 点 - + カートへ",
            price_texts=["80 円"],
        )
    ]
    page = FakePage({listing("op01"): {"anchors": anchors}})
    discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.price_jpy == 80
    assert candidate.price_jpy != 27
    # The collision is still present in the audit trail; it just no longer
    # reaches the price.
    assert discovery_listing.parse_price(candidate.raw_listing_text) == (None, True)


def test_no_price_node_stores_no_price_even_when_the_text_shows_one(session):
    # D + the anti-regression guarantee: a perfectly good price in the
    # flattened text must NOT be used when no price node was scraped. If a
    # future change reintroduces a flattened-text fallback, this fails.
    anchors = [
        row(
            "op01",
            "1",
            label="OP01-001 C ルフィ",
            card_text="OP01-001 ルフィ 320 円 在庫 : 3 点 - + カートへ",
            price_texts=[],
        )
    ]
    page = FakePage({listing("op01"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.price_jpy is None
    # Absence, not disagreement.
    assert report["per_slug"]["op01"]["candidates_with_ambiguous_price"] == 0
    assert candidate.raw_listing_text == "OP01-001 ルフィ 320 円 在庫 : 3 点 - + カートへ"


def test_raw_listing_text_is_the_flattened_block_and_is_unchanged(session):
    # G: the audit trail keeps the whole row verbatim, price node or not.
    page = FakePage(
        {
            listing("op01"): {
                "anchors": [sale_row("op01", "10007", "OP01-004", "R", "ウソップ", "80", "120", "◯")]
            }
        }
    )
    discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.raw_listing_text == (
        "OP01-004 ウソップ 80 円 在庫 : ◯ 120 円 - + カートへ"
    )


def test_a_foreign_series_block_cannot_lend_its_price_to_an_own_series_row(session):
    # H: price_texts is scoped to the anchor's own block, so a neighbouring
    # foreign-series product (the shared B>STRONG carousel on every page)
    # cannot leak a value. The foreign row is filtered out entirely and the
    # own-series row keeps its own price.
    anchors = [
        product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点"),
        product_row("op17", "10106", "OP17-001", "P-L", "モンキー・D・ルフィ", "9,800", "◯"),
    ]
    page = FakePage({listing("op01"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.set_slug == "op01"
    assert candidate.price_jpy == 320
    assert report["per_slug"]["op01"]["foreign_series_filtered"] == 1


def test_select_listing_price_counts_nodes_and_never_picks_one(session):
    # E, stated directly on the selector so the rule is pinned independently
    # of the persistence path.
    select_price = discovery_listing.select_listing_price
    assert select_price(["320 円"]) == (320, False)
    assert select_price([]) == (None, False)
    assert select_price(None) == (None, False)
    assert select_price(["  "]) == (None, False)
    # More than one node: refused, and NOT resolved to the first, last,
    # lowest or highest.
    assert select_price(["80 円", "120 円"]) == (None, True)
    assert select_price(["120 円", "80 円"]) == (None, True)
    assert select_price(["80 円", "120 円", "220 円"]) == (None, True)
    # Two nodes that agree are still two nodes - the block offered the price
    # twice and this function does not adjudicate.
    assert select_price(["80 円", "80 円"]) == (None, True)


def test_the_listing_parser_never_scans_flattened_text_for_a_price():
    # Structural guard. `parse_listing_row` must obtain its price ONLY through
    # `select_listing_price`; a direct `parse_price(...)` call inside it would
    # mean some flattened string is being scanned again, which is exactly the
    # regression that reintroduces 円卓 and the struck former price.
    source = pathlib.Path(discovery_listing.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "parse_listing_row"
    )
    called = {
        node.func.id
        for node in ast.walk(func)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "select_listing_price" in called
    assert "parse_price" not in called, (
        "parse_listing_row must not call parse_price directly - the price has to "
        "come from the DOM-scoped price nodes via select_listing_price, never "
        "from a flattened row string."
    )


def test_the_scrape_selects_all_price_nodes_not_just_the_first():
    # The probe side of the contract: querySelectorAll (a count the parser can
    # act on), the subset class selector, and no `text-danger` in it.
    source = pathlib.Path(discovery_probe.__file__).read_text(encoding="utf-8")
    js_selector = "card.querySelectorAll('strong.d-block.text-end')"
    assert js_selector in source
    assert "card.querySelector('strong" not in source, (
        "querySelector would silently take the first of several price nodes and "
        "destroy the evidence select_listing_price fails closed on."
    )
    assert "strong.d-block.text-end.text-danger" not in source, (
        "text-danger is only on SALE rows; including it would stop pricing "
        "every ordinary row."
    )
    assert discovery_listing.PRICE_NODE_SELECTOR == "strong.d-block.text-end"


def test_an_ascii_name_is_not_swallowed_as_a_rarity(session):
    # 'Mr.2・ボン・クレー(ベンサム)' is a real EB01 name. The rarity token must
    # be the short all-caps one, never the name.
    parsed = parse_listing_row(
        row("eb01", "10079", label="EB01-061 SEC Mr.2・ボン・クレー(ベンサム)")
    )
    assert parsed.detected_rarity == "SEC"
    assert parsed.name_jp == "Mr.2・ボン・クレー(ベンサム)"


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


def test_rediscovering_the_same_product_updates_it_in_place(session):
    first = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    discovery.discover_and_persist(session, first, ["op01"])
    original_id = session.scalars(select(YuyuteiCandidate)).one().id

    second = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ(改)", "480", "×")]}}
    )
    discovery.discover_and_persist(session, second, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.id == original_id
    # Mutable listing facts move with the source...
    assert candidate.price_jpy == 480
    assert candidate.availability == "out_of_stock"
    assert candidate.name_jp == "ルフィ(改)"
    # ...and the second run is the one that now owns it.
    runs = session.scalars(select(YuyuteiDiscoveryRun).order_by(YuyuteiDiscoveryRun.id)).all()
    assert len(runs) == 2
    assert candidate.discovery_run_id == runs[1].id


def test_rediscovery_refreshes_classification_when_the_catalogue_changes(session):
    make_family(session, "OP01-001", 1)
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    discovery.discover_and_persist(session, page, ["op01"])
    assert session.scalars(select(YuyuteiCandidate)).one().match_status == "print_matched"

    # A second print is added to the same canonical card: the code no longer
    # implies one printing, and the stale print id must be given up.
    canonical = session.scalars(select(CanonicalCard)).one()
    session.add(
        CardPrint(
            canonical_card_id=canonical.id,
            treatment=None,
            verification_status="verified",
            is_active=True,
        )
    )
    session.commit()
    discovery.discover_and_persist(session, page, ["op01"])

    candidate = session.scalars(select(YuyuteiCandidate)).one()
    assert candidate.match_status == "family_matched"
    assert candidate.matched_card_print_id is None


def test_rediscovery_creates_no_second_candidate_across_many_runs(session):
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    for _ in range(3):
        discovery.discover_and_persist(session, page, ["op01"])
    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 1


# --------------------------------------------------------------------------
# Bounding and source posture
# --------------------------------------------------------------------------


def test_the_product_cap_is_independent_per_slug(session):
    page = FakePage(
        {
            listing("op01"): {"anchors": [row("op01", str(i), label=f"OP01-{i:03d} C n") for i in range(1, 9)]},
            listing("eb01"): {"anchors": [row("eb01", str(i), label=f"EB01-{i:03d} C n") for i in range(1, 9)]},
        }
    )
    report = discovery.discover_and_persist(session, page, ["op01", "eb01"], max_products_per_slug=5)

    assert report["per_slug"]["op01"]["own_series_products"] == 5
    assert report["per_slug"]["eb01"]["own_series_products"] == 5
    assert report["per_slug"]["op01"]["budget_exhausted"] is True
    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 10
    assert report["stopped_reason"] == "max_products_per_slug_reached: op01,eb01"


def test_foreign_links_do_not_consume_a_slugs_budget(session):
    anchors = [row("op17", str(i), label=f"OP17-{i:03d} C n") for i in range(1, 20)]
    anchors += [row("op01", "1", label="OP01-001 C ルフィ")]
    page = FakePage({listing("op01"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op01"], max_products_per_slug=5)

    assert report["per_slug"]["op01"]["own_series_products"] == 1
    assert report["per_slug"]["op01"]["budget_exhausted"] is False


def test_a_denial_stops_the_whole_run_and_is_recorded(session):
    page = FakePage({}, status=403)
    report = discovery.discover_and_persist(session, page, ["op01", "eb01"])

    run = session.scalars(select(YuyuteiDiscoveryRun)).one()
    assert run.status == "denied"
    assert run.stopped_reason.startswith("source_denied: 403")
    assert run.finished_at is not None
    # One LISTING navigation: no retry, and eb01 never attempted. The
    # homepage warm-up succeeded first, which is what makes the 403 that
    # follows a listing denial rather than a refused session.
    assert page.visited == [HOMEPAGE_URL, listing("op01")]
    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 0
    assert report["status"] == "denied"


def test_a_denial_keeps_the_slugs_already_enumerated(session):
    page = FakePage(
        {
            listing("op01"): {"anchors": [row("op01", "1", label="OP01-001 C ルフィ")], "status": 200},
            listing("eb01"): {"status": 429},
        },
        status=200,
    )
    discovery.discover_and_persist(session, page, ["op01", "eb01"])

    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 1
    assert session.scalars(select(YuyuteiDiscoveryRun)).one().status == "denied"


def test_pagination_is_followed_only_within_the_page_budget(session):
    base = listing("op01")
    page = FakePage(
        {
            base: {"anchors": [row("op01", "1", label="OP01-001 C a")], "pagination": [f"{base}?page=2"]},
            f"{base}?page=2": {
                "anchors": [row("op01", "2", label="OP01-002 C b")],
                "pagination": [f"{base}?page=3"],
            },
            f"{base}?page=3": {"anchors": [row("op01", "3", label="OP01-003 C c")]},
        }
    )
    report = discovery.discover_and_persist(session, page, ["op01"], max_pages_per_slug=2)

    assert report["per_slug"]["op01"]["pages_fetched"] == 2
    assert report["per_slug"]["op01"]["pagination_seen"] is True
    # Two LISTING navigations within the budget, plus the homepage warm-up.
    # `pages_fetched` counts listing pages only and is unaffected by it.
    assert page.visited == [HOMEPAGE_URL, base, f"{base}?page=2"]


# --------------------------------------------------------------------------
# What discovery must never touch
# --------------------------------------------------------------------------


def test_discovery_writes_only_candidates_and_run_records(session):
    make_family(session, "OP01-001", 1)
    page = FakePage(
        {listing("op01"): {"anchors": [product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点")]}}
    )
    discovery.discover_and_persist(session, page, ["op01"])

    assert session.scalar(select(func.count()).select_from(YuyuteiCandidate)) == 1
    assert session.scalar(select(func.count()).select_from(YuyuteiDiscoveryRun)) == 1
    # The two tables a discovery pass must never write into.
    assert session.scalar(select(func.count()).select_from(SourceCardMapping)) == 0
    assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0


def test_the_discovery_modules_do_not_even_import_the_mapping_or_price_models():
    # A structural guard, not a behavioural one: these modules cannot create a
    # mapping or an observation because the names are not in scope at all.
    for module in (discovery, discovery_match):
        names = set(vars(module))
        assert "SourceCardMapping" not in names
        assert "PriceObservation" not in names
    # Read from the AST rather than the text, so a docstring that NAMES the
    # tables it refuses to write cannot pass or fail this check.
    forbidden = {"SourceCardMapping", "PriceObservation", "RawSnapshot", "MarketIndexSnapshot"}
    for module in (discovery, discovery_listing, discovery_match):
        tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
        imported = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not (imported & forbidden), f"{module.__name__} imports {imported & forbidden}"
        assert "yuyutei_collector.writer" not in imported


def test_a_run_records_its_request_and_its_measurements(session):
    page = FakePage(
        {
            listing("op01"): {
                "anchors": [
                    product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点"),
                    product_row("op01", "1", "OP01-001", "C", "ルフィ", "320", "3 点"),
                    row("op17", "9", label="OP17-001 C エース"),
                    row("op01", "2", label="コードなし"),
                ]
            }
        }
    )
    discovery.discover_and_persist(session, page, ["op01"])

    run = session.scalars(select(YuyuteiDiscoveryRun)).one()
    assert run.status == "completed"
    assert run.requested_set_slugs == ["op01"]
    assert run.pages_fetched == 1
    assert run.products_seen == 2
    assert run.candidates_written == 2
    assert run.foreign_series_filtered == 1
    assert run.duplicate_products == 1
    assert run.unparseable_codes == 1
    assert run.finished_at is not None
    metrics = run.per_slug_metrics_json["op01"]
    assert metrics["distinct_card_codes"] == 1
    assert metrics["codes_with_multiple_products"] == 0


def test_codes_shared_by_several_products_are_counted(session):
    # 15-23% of measured products share a code with a sibling product.
    anchors = [
        product_row("op13", "1", "OP13-118", "SEC", "ルフィ", "500", "3 点"),
        product_row("op13", "2", "OP13-118", "P-SEC", "ルフィ(パラレル)", "12,800", "×"),
        product_row("op13", "3", "OP13-119", "SEC", "エース", "500", "3 点"),
    ]
    page = FakePage({listing("op13"): {"anchors": anchors}})
    report = discovery.discover_and_persist(session, page, ["op13"])

    metrics = report["per_slug"]["op13"]
    assert metrics["distinct_card_codes"] == 2
    assert metrics["codes_with_multiple_products"] == 1
