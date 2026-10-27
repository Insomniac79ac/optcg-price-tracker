"""A product snapshot waits for the page's own condition-price request (2026-10-26 change).

SNKRDUNK now renders every condition chip as 出品待ち and fills the prices in from
GET /v2/products/<id>/size-chips after load. A snapshot before that response is placeholders,
which would read as "nothing listed". No browser, no socket: a fake page replays responses and
re-renders its HTML after a given number of waits.

The size-chips body schema is not known from stored evidence; the bodies below are illustrative
and the classifier (browser.body_listings) only relies on keys that name a price."""

import json
from types import SimpleNamespace

import pytest

from snkrdunk_collector import browser

PID = "142630"
PRODUCT = f"https://snkrdunk.com/apparels/{PID}"
LABELS = ("A", "B", "C", "D", "PSA10")
NAMES = f'<script>self.__next_f.push([1,"/v2/products/{PID}/size-chips"])</script>'
AWAITING = {label: None for label in LABELS}
RENDERED = {"A": "¥ 3,500 ~", "B": None, "C": None, "D": None, "PSA10": "¥ 41,000 ~"}
PSA_ONLY = {"A": None, "B": None, "C": None, "D": None, "PSA10": "¥ 41,000 ~"}
BODY_PRICES = json.dumps({"sizeChips": [{"name": "A", "minPrice": 3500}, {"name": "B", "minPrice": None}]})
BODY_NONE = json.dumps({"sizeChips": [{"name": label, "minPrice": None} for label in LABELS]})


def page_html(prices, *, names=NAMES):
    chips = "".join(
        f'<button class="c__chip"><p class="c__variant">{label}</p>'
        + (f'<p class="c__price">{value}</p>' if value else '<p class="c__awaiting">出品待ち</p>')
        + "</button>"
        for label, value in prices.items()
    )
    return f"<html><head><title>OP01-001</title></head><body><div>{chips}</div>{names}</body></html>"


class FakeResponse:
    def __init__(self, pid=PID, status=200, body=BODY_PRICES, raises=None):
        self.url = f"https://snkrdunk.com/v2/products/{pid}/size-chips"
        self.status, self._body, self._raises = status, body, raises

    def body(self):
        if self._raises:
            raise self._raises
        return self._body.encode()


class FakePage:
    """`responses`: (response, after_n_waits) fired to listeners. `renders`: (after_n_waits,
    html); content() returns the latest html due. Records the call order."""

    def __init__(self, *, status=200, responses=(), renders=((0, page_html(AWAITING)),), goto_raises=None,
                 title="OP01-001"):
        self.status, self.responses, self.renders = status, list(responses), list(renders)
        self.goto_raises, self._title = goto_raises, title
        self.listeners, self.calls, self.waits = [], [], 0
        self.url = None

    def on(self, event, callback):
        assert event == "response"
        self.listeners.append(callback)

    def remove_listener(self, event, callback):
        self.listeners.remove(callback)

    def _fire(self):
        for response, after in list(self.responses):
            if after <= self.waits:
                self.responses.remove((response, after))
                for listener in self.listeners:
                    listener(response)

    def goto(self, url, **kwargs):
        self.url = url
        self.calls.append("goto")
        if self.goto_raises:
            raise self.goto_raises
        self._fire()
        return SimpleNamespace(status=self.status)

    def wait_for_timeout(self, ms):
        self.waits += 1
        self.calls.append(f"wait:{ms}")
        self._fire()

    def content(self):
        self.calls.append("content")
        return [html for after, html in self.renders if after <= self.waits][-1]

    def title(self):
        return self._title


@pytest.fixture(autouse=True)
def fake_clock(monkeypatch):
    # Bounded by the fake page's own waits, not wall time.
    state = {"t": 0.0}
    monkeypatch.setattr(browser.time, "monotonic", lambda: state["t"])
    original = FakePage.wait_for_timeout

    def wait(self, ms):
        state["t"] += ms / 1000
        original(self, ms)

    monkeypatch.setattr(FakePage, "wait_for_timeout", wait)


def capture(page, url=PRODUCT, **kwargs):
    kept = []
    step = browser.goto_and_capture(page, url, condition_prices=True, before_parse=kept.append, **kwargs)
    return step, (kept[0] if kept else None)


def test_the_snapshot_is_taken_only_after_the_price_response_and_its_render():
    page = FakePage(responses=[(FakeResponse(), 3)], renders=[(0, page_html(AWAITING)), (4, page_html(RENDERED))])
    step, kept = capture(page)
    assert step["classification"] == "normal_page"
    prices = step["condition_prices"]
    assert (prices["status"], prices["product_id"], prices["dom"], prices["body_listings"]) == (
        "loaded", PID, "rendered", "prices")
    assert step["html"] == page_html(RENDERED) == kept["html"]
    render = page.calls.index(f"wait:{browser.PRICE_CHIPS_RENDER_MS}")
    assert render < len(page.calls) - 1 - page.calls[::-1].index("content")
    assert kept["condition_prices"] == prices and "price_chips" not in kept  # body kept only when it decides
    assert page.listeners == []  # the listener is removed whatever happens


def test_a_response_already_back_during_navigation_needs_no_polling():
    page = FakePage(responses=[(FakeResponse(), 0)], renders=[(0, page_html(AWAITING)), (2, page_html(RENDERED))])
    step, _ = capture(page)
    assert step["condition_prices"]["status"] == "loaded"
    assert page.calls == ["goto", "wait:1500", "content", f"wait:{browser.PRICE_CHIPS_RENDER_MS}", "content"]


def test_another_products_response_does_not_end_the_wait():
    page = FakePage(responses=[(FakeResponse(pid="999999"), 0), (FakeResponse(), 4)],
                    renders=[(0, page_html(AWAITING)), (5, page_html(RENDERED))])
    step, _ = capture(page)
    assert step["condition_prices"]["status"] == "loaded" and step["condition_prices"]["waited_s"] > 0


@pytest.mark.parametrize(
    "responses,expected",
    [
        ([], "not_seen"),
        ([(FakeResponse(pid="999999"), 1)], "not_seen"),
        ([(FakeResponse(status=500), 1)], "http_500"),
    ],
)
def test_without_this_products_price_response_the_page_is_not_a_normal_capture(responses, expected):
    page = FakePage(responses=responses)
    step, kept = capture(page)
    assert step["classification"] == browser.PRICES_NOT_LOADED
    assert step["condition_prices"]["status"] == expected
    assert step["classification_evidence"] == [f"condition_prices:{expected}"]
    assert step["html"] == page_html(AWAITING) == kept["html"]  # the snapshot is still kept as evidence


def test_a_response_with_prices_the_page_never_rendered_is_not_no_listing():
    page = FakePage(responses=[(FakeResponse(body=BODY_PRICES), 1)])
    step, _ = capture(page)
    assert step["classification"] == browser.PRICES_NOT_LOADED
    assert step["condition_prices"]["status"] == "dom_not_rendered"
    assert step["classification_evidence"] == ["condition_prices:dom_not_rendered"]
    # the extra render wait is bounded
    assert page.calls.count(f"wait:{browser.PRICE_CHIPS_POLL_MS}") <= (
        1 + browser.PRICE_CHIPS_WAIT_S * 1000 / browser.PRICE_CHIPS_POLL_MS
        + browser.PRICE_CHIPS_RENDER_MAX_S * 1000 / browser.PRICE_CHIPS_POLL_MS)


def test_a_late_render_inside_the_bound_is_captured():
    page = FakePage(responses=[(FakeResponse(body=BODY_PRICES), 1)],
                    renders=[(0, page_html(AWAITING)), (6, page_html(RENDERED))])
    step, _ = capture(page)
    assert step["classification"] == "normal_page" and step["condition_prices"]["dom"] == "rendered"


def test_all_awaiting_is_no_listing_only_when_the_body_has_no_price_and_the_body_is_kept():
    page = FakePage(responses=[(FakeResponse(body=BODY_NONE), 1)])
    step, kept = capture(page)
    assert step["classification"] == "normal_page"
    assert (step["condition_prices"]["status"], step["condition_prices"]["dom"]) == (
        "loaded", "all_awaiting_body_confirms")
    assert kept["price_chips"] == {"url": f"https://snkrdunk.com/v2/products/{PID}/size-chips", "body": BODY_NONE}


@pytest.mark.parametrize(
    "response,expected",
    [
        (FakeResponse(body='{"sizeChips": [{"name": "A"}]}'), "body_unrecognised"),
        (FakeResponse(body="<html>error</html>"), "body_unrecognised"),
        (FakeResponse(raises=RuntimeError("evicted")), "body_unavailable"),
    ],
)
def test_all_awaiting_with_a_body_that_cannot_confirm_it_is_not_no_listing(response, expected):
    page = FakePage(responses=[(response, 1)])
    step, _ = capture(page)
    assert step["classification"] == browser.PRICES_NOT_LOADED
    assert step["condition_prices"]["status"] == expected


def test_graded_prices_alone_show_the_page_rendered():
    # Raw A-D all 出品待ち next to a priced PSA10 chip is a genuine raw no-listing.
    page = FakePage(responses=[(FakeResponse(body=BODY_PRICES), 1)],
                    renders=[(0, page_html(AWAITING)), (2, page_html(PSA_ONLY))])
    step, kept = capture(page)
    assert step["classification"] == "normal_page" and step["condition_prices"]["dom"] == "rendered"
    assert "price_chips" not in kept


def test_a_rendered_page_does_not_need_its_body():
    page = FakePage(responses=[(FakeResponse(raises=RuntimeError("evicted")), 1)],
                    renders=[(0, page_html(AWAITING)), (2, page_html(RENDERED))])
    step, _ = capture(page)
    assert step["classification"] == "normal_page" and step["condition_prices"]["status"] == "loaded"


def test_a_response_the_page_does_not_name_is_not_trusted():
    page = FakePage(responses=[(FakeResponse(), 1)], renders=[(0, page_html(RENDERED, names=""))])
    step, _ = capture(page)
    assert step["classification"] == browser.PRICES_NOT_LOADED
    assert step["condition_prices"]["status"] == "not_named_by_page"


def test_a_page_that_is_not_a_product_url_is_not_waited_on():
    page = FakePage(responses=[(FakeResponse(), 0)], renders=[(0, page_html(RENDERED))])
    step, _ = capture(page, url="https://snkrdunk.com/products/abc")
    assert step["condition_prices"]["status"] == "no_product_id"
    assert step["classification"] == browser.PRICES_NOT_LOADED and page.waits == 1


@pytest.mark.parametrize("status", [403, 429])
def test_a_denied_price_request_is_a_source_denial(status):
    page = FakePage(responses=[(FakeResponse(status=status), 1)])
    step, _ = capture(page)
    assert step["classification"] == f"static_{status}"
    assert step["classification_evidence"] == [f"condition_prices:http_{status}"]


def test_the_wait_is_bounded():
    page = FakePage()
    step, _ = capture(page)
    assert step["condition_prices"]["waited_s"] <= browser.PRICE_CHIPS_WAIT_S + 0.5
    assert page.waits <= 1 + browser.PRICE_CHIPS_WAIT_S * 1000 / browser.PRICE_CHIPS_POLL_MS + 1


def test_a_denied_page_keeps_its_denial_classification_and_does_not_wait():
    page = FakePage(status=403, renders=[(0, "<html><title>Error</title></html>")], title="Error")
    step, _ = capture(page)
    assert step["classification"] == "static_403"
    assert step["condition_prices"]["status"] == "page_not_normal"
    assert page.waits == 1  # only the usual settle


def test_a_200_challenge_page_is_not_waited_on():
    challenge = '<html><title>Just a moment...</title><div id="challenge-form"></div></html>'
    page = FakePage(renders=[(0, challenge)], title="Just a moment...")
    step, _ = capture(page)
    assert step["classification"] == "challenge_or_captcha"
    assert step["condition_prices"]["status"] == "page_not_normal" and page.waits == 1


def test_a_navigation_error_still_removes_the_listener():
    page = FakePage(goto_raises=TimeoutError("nav"))
    step, kept = capture(page)
    assert step["error"].startswith("TimeoutError") and kept is None and page.listeners == []


def test_pages_without_condition_prices_are_captured_as_before():
    page = FakePage(renders=[(0, "<html><title>Home</title></html>")], title="Home")
    step = browser.goto_and_capture(page, "https://snkrdunk.com/")
    assert step["classification"] == "normal_page" and "condition_prices" not in step
    assert page.listeners == [] and page.calls == ["goto", "wait:1500", "content"]


def test_only_snkrdunk_size_chips_responses_count():
    ok = SimpleNamespace(url="https://snkrdunk.com/v2/products/1/size-chips", status=200)
    assert browser._price_chips_response(ok) == ("1", 200)
    for url in ("https://evil.test/v2/products/1/size-chips", "https://snkrdunk.com/v2/products/1/size-guide",
                "https://snkrdunk.com/v2/products/1/size-chips/extra"):
        assert browser._price_chips_response(SimpleNamespace(url=url, status=200)) is None


def test_the_expected_product_comes_from_the_page_url():
    assert browser.expected_price_product(PRODUCT) == PID
    assert browser.expected_price_product(PRODUCT + "/") == PID
    for url in ("https://evil.test/apparels/1", "https://snkrdunk.com/apparels/1/sales", None, ""):
        assert browser.expected_price_product(url) is None


@pytest.mark.parametrize(
    "body,verdict",
    [
        ({"a": [{"price": 3500}]}, "prices"),
        ({"a": [{"minPrice": "¥3,500"}, {"minPrice": None}]}, "prices"),
        ({"a": [{"price": None}, {"lowestPrice": 0}, {"price": ""}, {"price": "出品待ち"}]}, "none"),
        ({"a": [{"name": "A"}]}, "unrecognised"),
        ({"price": {"value": 1}}, "unrecognised"),  # a nested price object is walked, its keys are not prices
        ({"a": [{"price": True}]}, "unrecognised"),
        ([], "unrecognised"),
    ],
)
def test_body_listings_reads_only_keys_that_name_a_price(body, verdict):
    assert browser.body_listings(json.dumps(body))["body_listings"] == verdict


def test_body_listings_rejects_non_json():
    assert browser.body_listings("<html>")["body_listings"] == "unrecognised"
