"""The card-code grammar and the probe's parsing/bounding rules.

No network anywhere in this file: the probe's page object is faked, so these
tests assert the logic that decides what a discovered product IS and when the
probe must stop - never the source's behaviour, which only staging can answer.
"""

import pytest

from yuyutei_collector.discover import CARD_CODE_RE
from yuyutei_collector import discovery_probe
from yuyutei_collector.discovery_probe import (
    PRODUCT_PATH_RE,
    SourceDenied,
    _DENIAL_STATUSES,
    _normalize,
    _parse_product,
    probe_slug,
    run_probe,
)


# --------------------------------------------------------------------------
# Card-code grammar - every shape derived from canonical_cards, not guessed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "OP01-001",  # OP##-###   2,033 codes
        "OP17-119",
        "ST01-001",  # ST##-###     382
        "ST36-005",
        "EB01-001",  # EB##-###     245
        "EB04-061",
        "PRB01-001",  # PRB##-###     19
        "PRB02-018",
        "P-014",  # P-###          31 (no set number)
        "P-107",
    ],
)
def test_every_real_atlas_code_shape_is_matched(code):
    assert CARD_CODE_RE.findall(code) == [code]


def test_the_five_shapes_are_the_whole_grammar():
    # Guards against someone "simplifying" the pattern later: these are the
    # only five shapes present across all 2,710 canonical codes.
    text = "OP01-001 ST36-005 EB04-061 PRB02-018 P-107"
    assert CARD_CODE_RE.findall(text) == [
        "OP01-001",
        "ST36-005",
        "EB04-061",
        "PRB02-018",
        "P-107",
    ]


def test_prb_is_never_read_as_a_promo():
    # PRB shares its leading P with the promo branch; the alternation order
    # must not let "PRB01-001" degrade into a P-### match.
    assert CARD_CODE_RE.findall("PRB01-001") == ["PRB01-001"]


@pytest.mark.parametrize(
    "text", ["OP1-001", "OPX1-001", "P-12", "P-1234", "ZZ01-001", "OP01-0011", "OP011-001"]
)
def test_near_miss_shapes_are_rejected(text):
    # A wrong code is worse than no code: it would attach a product to the
    # wrong card. Everything that is not exactly a known shape is refused.
    assert CARD_CODE_RE.findall(text) == []


def test_a_code_is_found_inside_a_real_listing_label():
    label = "SR シュガー OP04-024 販売"
    assert CARD_CODE_RE.search(label).group(0) == "OP04-024"


# --------------------------------------------------------------------------
# Product identity
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "href,expected",
    [
        ("https://yuyu-tei.jp/sell/opc/card/op04/10028", ("op04", "10028")),
        ("/sell/opc/card/promo-op10/10001", ("promo-op10", "10001")),
        ("https://yuyu-tei.jp/sell/opc/card/eb01/9?x=1", ("eb01", "9")),
    ],
)
def test_product_identity_is_series_plus_opaque_id(href, expected):
    assert _parse_product(href) == expected


@pytest.mark.parametrize(
    "href",
    [
        "https://yuyu-tei.jp/sell/opc/s/op01",  # a category, not a product
        "https://yuyu-tei.jp/sell/opc/card/op01",  # no id
        "https://yuyu-tei.jp/",
    ],
)
def test_non_product_links_are_not_products(href):
    assert _parse_product(href) is None
    assert PRODUCT_PATH_RE.search(href) is None


def test_normalize_builds_a_canonical_url_and_reads_the_code():
    item = _normalize(
        {
            "href": "https://yuyu-tei.jp/sell/opc/card/op04/10028?ref=x",
            "text": "SR シュガー",
            "card_text": "SR シュガー OP04-024 120円",
            "img_alt": "",
            "img_src": "https://card.yuyu-tei.jp/opc/front/op04/10028.jpg",
        }
    )
    assert item["series"] == "op04"
    assert item["product_id"] == "10028"
    # Canonical form, query string dropped - so the same product discovered
    # via two different links is one product.
    assert item["url"] == "https://yuyu-tei.jp/sell/opc/card/op04/10028"
    assert item["card_code"] == "OP04-024"


def test_normalize_keeps_a_product_whose_code_cannot_be_read():
    # Reported as products_without_code rather than dropped: a listing anchor
    # with no visible code is a real product and a real measurement.
    item = _normalize(
        {"href": "/sell/opc/card/op04/10028", "text": "", "card_text": "", "img_alt": "", "img_src": ""}
    )
    assert item is not None and item["card_code"] is None


# --------------------------------------------------------------------------
# Bounding and source posture
# --------------------------------------------------------------------------


class FakePage:
    """Stands in for a Playwright page. Records every URL navigated."""

    def __init__(self, pages: dict[str, dict], status: int = 200):
        self.pages = pages
        self.status = status
        self.visited: list[str] = []

    def goto(self, url, **kwargs):
        self.visited.append(url)
        self._current = url
        return type("R", (), {"status": self.pages.get(url, {}).get("status", self.status)})()

    def wait_for_timeout(self, ms):
        return None

    def content(self):
        return "<html></html>"

    def eval_on_selector_all(self, selector, script):
        entry = self.pages.get(self._current, {})
        if "page=" in selector or "pagination" in selector:
            return entry.get("pagination", [])
        return entry.get("anchors", [])


def anchor(series, pid, code=""):
    return {
        "href": f"https://yuyu-tei.jp/sell/opc/card/{series}/{pid}",
        "text": f"SR name {code}".strip(),
        "card_text": f"SR name {code}".strip(),
        "img_alt": "",
        "img_src": "",
    }


def test_a_denial_raises_and_is_never_retried():
    page = FakePage({}, status=403)
    with pytest.raises(SourceDenied):
        probe_slug(page, "op01", max_pages=3, remaining_budget=200, timeout_s=5)
    # Exactly one navigation. No second attempt, no varied request.
    assert len(page.visited) == 1


@pytest.mark.parametrize("status", sorted(_DENIAL_STATUSES))
def test_every_denial_status_stops_the_probe(status):
    page = FakePage({}, status=status)
    with pytest.raises(SourceDenied):
        probe_slug(page, "op01", max_pages=3, remaining_budget=200, timeout_s=5)


def test_pagination_is_followed_only_up_to_the_page_budget():
    base = "https://yuyu-tei.jp/sell/opc/s/op01"
    pages = {
        base: {"anchors": [anchor("op01", "1", "OP01-001")], "pagination": [f"{base}?page=2"]},
        f"{base}?page=2": {"anchors": [anchor("op01", "2", "OP01-002")], "pagination": [f"{base}?page=3"]},
        f"{base}?page=3": {"anchors": [anchor("op01", "3", "OP01-003")], "pagination": []},
    }
    page = FakePage(pages)
    result = probe_slug(page, "op01", max_pages=2, remaining_budget=200, timeout_s=5)

    assert result["page_count"] == 2
    assert result["pagination_seen"] is True
    assert result["pagination_followed"] == 1
    assert len(page.visited) == 2  # page 3 never fetched


def test_absent_pagination_is_reported_not_fabricated():
    base = "https://yuyu-tei.jp/sell/opc/s/op01"
    page = FakePage({base: {"anchors": [anchor("op01", "1", "OP01-001")], "pagination": []}})
    result = probe_slug(page, "op01", max_pages=3, remaining_budget=200, timeout_s=5)

    assert result["pagination_seen"] is False
    assert result["page_count"] == 1
    # The probe never invents ?page=2 to see what happens.
    assert page.visited == [base]


def test_the_product_budget_binds():
    base = "https://yuyu-tei.jp/sell/opc/s/op01"
    page = FakePage({base: {"anchors": [anchor("op01", str(i)) for i in range(50)], "pagination": []}})
    result = probe_slug(page, "op01", max_pages=3, remaining_budget=10, timeout_s=5)

    assert result["products_discovered"] == 10
    assert result["budget_exhausted"] is True


def test_duplicate_links_to_one_product_collapse_and_are_counted():
    base = "https://yuyu-tei.jp/sell/opc/s/op01"
    anchors = [anchor("op01", "1", "OP01-001"), anchor("op01", "1", "OP01-001"), anchor("op01", "2")]
    page = FakePage({base: {"anchors": anchors, "pagination": []}})
    result = probe_slug(page, "op01", max_pages=3, remaining_budget=200, timeout_s=5)

    assert result["products_discovered"] == 2
    assert result["duplicate_product_links"] == 1


def test_products_from_another_series_are_surfaced():
    # Listing pages cross-link into other sets; counting those as this set's
    # products would over-report it.
    base = "https://yuyu-tei.jp/sell/opc/s/op01"
    page = FakePage(
        {base: {"anchors": [anchor("op01", "1", "OP01-001"), anchor("eb02", "9", "EB02-001")], "pagination": []}}
    )
    result = probe_slug(page, "op01", max_pages=3, remaining_budget=200, timeout_s=5)

    assert result["products_from_other_series"] == 1
    assert result["other_series_seen"] == ["eb02"]


def test_distinct_codes_and_missing_codes_are_counted_separately():
    base = "https://yuyu-tei.jp/sell/opc/s/op01"
    anchors = [anchor("op01", "1", "OP01-001"), anchor("op01", "2", "OP01-001"), anchor("op01", "3")]
    page = FakePage({base: {"anchors": anchors, "pagination": []}})
    result = probe_slug(page, "op01", max_pages=3, remaining_budget=200, timeout_s=5)

    assert result["products_discovered"] == 3
    assert result["distinct_card_codes"] == 1  # two products, one code
    assert result["products_without_code"] == 1


# --------------------------------------------------------------------------
# The product budget is PER SLUG
#
# A shared pool made coverage depend on slug order: the first big category ate
# it and every later slug reported zero products - output that is
# indistinguishable from a category that really is empty. These tests pin the
# per-slug contract so that regression cannot come back silently.
# --------------------------------------------------------------------------


@pytest.fixture
def no_delay(monkeypatch):
    """Skip the inter-request delay. The delay itself is asserted separately by
    reading settings; sleeping through it here would only slow the suite."""
    monkeypatch.setattr(discovery_probe.time, "sleep", lambda _s: None)


@pytest.fixture
def fake_playwright(monkeypatch):
    """Install a FakePage behind run_probe's Playwright bootstrap.

    Returns the page, so a test can inspect exactly which URLs were navigated -
    the only reliable evidence that a later slug was, or was not, reached.
    """

    def install(page):
        class FakeContext:
            def new_page(self):
                return page

            def close(self):
                page.closed = True

        class FakeBrowser:
            def new_context(self, **kwargs):
                return FakeContext()

            def close(self):
                page.browser_closed = True

        class FakePlaywright:
            chromium = type("C", (), {"launch": staticmethod(lambda **kw: FakeBrowser())})()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(discovery_probe, "sync_playwright", lambda: FakePlaywright())
        return page

    return install


def listing(slug):
    return f"https://yuyu-tei.jp/sell/opc/s/{slug}"


def test_a_slug_that_hits_its_cap_does_not_starve_the_next_slug(no_delay, fake_playwright):
    # The exact failure the shared budget caused: op01 filled the pool and the
    # remaining slugs were never fetched at all.
    page = fake_playwright(
        FakePage(
            {
                listing("op01"): {
                    "anchors": [anchor("op01", str(i), "OP01-001") for i in range(50)],
                    "pagination": [],
                },
                listing("eb01"): {
                    "anchors": [anchor("eb01", str(i), "EB01-001") for i in range(7)],
                    "pagination": [],
                },
            }
        )
    )
    report = run_probe(["op01", "eb01"], max_products_per_slug=10, max_pages_per_slug=1)

    first, second = report["sets"]
    assert first["products_discovered"] == 10 and first["budget_exhausted"] is True
    # The point of the fix: the capped slug did not consume the second slug's
    # allowance, and the second listing really was fetched.
    assert second["slug"] == "eb01"
    assert second["products_discovered"] == 7
    assert listing("eb01") in page.visited
    assert report["stopped_reason"] is None


def test_each_slug_gets_its_own_cap(no_delay, fake_playwright):
    # Two slugs, each over the cap: the total is len(slugs) * cap, not cap.
    fake_playwright(
        FakePage(
            {
                listing("op13"): {
                    "anchors": [anchor("op13", str(i)) for i in range(30)],
                    "pagination": [],
                },
                listing("eb01"): {
                    "anchors": [anchor("eb01", str(i)) for i in range(30)],
                    "pagination": [],
                },
            }
        )
    )
    report = run_probe(["op13", "eb01"], max_products_per_slug=5, max_pages_per_slug=1)

    assert [s["products_discovered"] for s in report["sets"]] == [5, 5]
    assert all(s["budget_exhausted"] for s in report["sets"])
    assert report["total_products_discovered"] == 10


def test_a_denial_still_stops_the_whole_probe_not_just_one_slug(no_delay, fake_playwright):
    # Per-slug budgets must not turn a denial into a per-slug problem that the
    # loop shrugs off and carries on past.
    page = fake_playwright(FakePage({}, status=403))
    report = run_probe(["op13", "eb01"], max_products_per_slug=200, max_pages_per_slug=3)

    assert report["sets"] == []
    assert report["stopped_reason"].startswith("source_denied: 403")
    # One navigation total: the first slug's listing. No retry, and eb01 never
    # attempted after the source declined.
    assert page.visited == [listing("op13")]


def test_dedupe_is_still_by_series_and_product_id_across_slugs(no_delay, fake_playwright):
    # Identity is unchanged by the budget fix: duplicates collapse within a
    # slug, and the same product_id under a different series stays distinct.
    fake_playwright(
        FakePage(
            {
                listing("op13"): {
                    "anchors": [
                        anchor("op13", "77", "OP13-001"),
                        anchor("op13", "77", "OP13-001"),
                        anchor("op13", "78", "OP13-002"),
                    ],
                    "pagination": [],
                },
                listing("eb01"): {
                    "anchors": [anchor("eb01", "77", "EB01-001")],
                    "pagination": [],
                },
            }
        )
    )
    report = run_probe(["op13", "eb01"], max_products_per_slug=200, max_pages_per_slug=1)

    first, second = report["sets"]
    assert first["products_discovered"] == 2
    assert first["duplicate_product_links"] == 1
    # product_id 77 exists in both categories and is two products, not one.
    assert second["products_discovered"] == 1
    assert second["duplicate_product_links"] == 0


def test_the_report_records_the_per_slug_budget_it_ran_under(no_delay, fake_playwright):
    fake_playwright(FakePage({listing("eb01"): {"anchors": [], "pagination": []}}))
    report = run_probe(["eb01"], max_products_per_slug=42, max_pages_per_slug=1)

    assert report["max_products_per_slug"] == 42
    assert "max_products" not in report

