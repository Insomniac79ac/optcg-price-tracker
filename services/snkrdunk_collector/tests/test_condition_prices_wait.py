"""A product snapshot waits for the page's own condition-price request (2026-10-26 change).

SNKRDUNK now renders every condition chip as 出品待ち and fills the prices in from
GET /v2/products/<id>/size-chips after load. A snapshot before that response is placeholders,
which would read as "nothing listed". No browser, no socket: a fake page replays responses and
re-renders its HTML after a given number of waits.

The size-chips body schema is not known from stored evidence, so a body never vouches for
"nothing listed": a snapshot counts only when a chip shows a rendered price. The bodies below
are illustrative (browser.body_listings is telemetry only)."""

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
    def value(v):
        if v is None:
            return '<p class="c__awaiting">出品待ち</p>'
        if v.startswith("<"):
            return v  # any other chip state, verbatim
        return f'<p class="c__price">{v}</p>'

    chips = "".join(
        f'<button class="c__chip"><p class="c__variant">{label}</p>{value(v)}</button>'
        for label, v in prices.items()
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
    assert (prices["status"], prices["product_id"], prices["body_listings"]) == ("loaded", PID, "prices")
    assert step["html"] == page_html(RENDERED) == kept["html"]
    render = page.calls.index(f"wait:{browser.PRICE_CHIPS_RENDER_MS}")
    assert render < len(page.calls) - 1 - page.calls[::-1].index("content")
    assert kept["condition_prices"] == prices and "price_chips" not in kept  # body kept only when no price shows
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
    assert step["classification_evidence"][0] == "condition_prices:dom_not_rendered"
    # the extra render wait is bounded
    assert page.calls.count(f"wait:{browser.PRICE_CHIPS_POLL_MS}") <= (
        1 + browser.PRICE_CHIPS_WAIT_S * 1000 / browser.PRICE_CHIPS_POLL_MS
        + browser.PRICE_CHIPS_RENDER_MAX_S * 1000 / browser.PRICE_CHIPS_POLL_MS)


def test_a_late_render_inside_the_bound_is_captured():
    page = FakePage(responses=[(FakeResponse(body=BODY_PRICES), 1)],
                    renders=[(0, page_html(AWAITING)), (6, page_html(RENDERED))])
    step, _ = capture(page)
    assert step["classification"] == "normal_page" and step["condition_prices"]["status"] == "loaded"


@pytest.mark.parametrize(
    "response,expected",
    [
        (FakeResponse(body=BODY_NONE), "body_unconfirmed"),  # even a body that looks empty
        (FakeResponse(body='{"sizeChips": [{"name": "A"}]}'), "body_unconfirmed"),
        (FakeResponse(body="<html>error</html>"), "body_not_json"),
        (FakeResponse(raises=RuntimeError("evicted")), "body_unavailable"),
    ],
)
def test_a_page_with_no_rendered_price_is_never_no_listing_and_its_body_is_kept(response, expected):
    page = FakePage(responses=[(response, 1)])
    step, kept = capture(page)
    assert step["classification"] == browser.PRICES_NOT_LOADED
    assert step["condition_prices"]["status"] == expected
    assert step["classification_evidence"][0] == f"condition_prices:{expected}"
    if expected == "body_unavailable":
        assert "price_chips" not in kept
    else:
        assert kept["price_chips"] == {"url": response.url, "body": response._body}
        assert step["classification_evidence"][1].startswith("size_chips_sha256:")


@pytest.mark.parametrize("other", [
    '<p class="c__skeleton"></p>',  # a loading skeleton
    '<p class="c__price"></p>',  # an empty price slot
    '<p class="c__price">---</p>',
    '<p class="c__price">¥ 0</p>',
    '<p class="c__unknown">SOLD</p>',
])
def test_a_chip_in_any_other_state_is_not_proof_of_a_render(other):
    page = FakePage(responses=[(FakeResponse(raises=RuntimeError("evicted")), 1)],
                    renders=[(0, page_html({**AWAITING, "PSA10": other}))])
    step, _ = capture(page)
    assert step["classification"] == browser.PRICES_NOT_LOADED


def test_graded_prices_alone_show_the_page_rendered():
    # One response fills every chip: raw A-D 出品待ち next to a priced PSA10 is a genuine raw no-listing.
    page = FakePage(responses=[(FakeResponse(body=BODY_PRICES), 1)],
                    renders=[(0, page_html(AWAITING)), (2, page_html(PSA_ONLY))])
    step, kept = capture(page)
    assert step["classification"] == "normal_page" and step["condition_prices"]["status"] == "loaded"
    assert "price_chips" not in kept


def test_a_page_without_a_picker_goes_on_to_extraction_as_a_structure_problem():
    # Extraction reports it as a parsing failure; without a coherent picker nothing reads as no listing.
    no_picker = f"<html><title>OP01-001</title><body><div>moved</div>{NAMES}</body></html>"
    page = FakePage(responses=[(FakeResponse(), 1)], renders=[(0, no_picker)])
    step, kept = capture(page)
    assert step["classification"] == "normal_page"
    assert step["condition_prices"]["status"] == browser.PRICES_NO_PICKER and "price_chips" not in kept


def test_a_rendered_page_does_not_need_its_body():
    page = FakePage(responses=[(FakeResponse(raises=RuntimeError("evicted")), 1)],
                    renders=[(0, page_html(AWAITING)), (2, page_html(RENDERED))])
    step, _ = capture(page)
    assert step["classification"] == "normal_page" and step["condition_prices"]["status"] == "loaded"


def test_a_challenge_in_the_price_response_is_a_denial():
    body = '<html><title>Just a moment...</title><div id="challenge-form"></div></html>'
    page = FakePage(responses=[(FakeResponse(body=body), 1)])
    step, kept = capture(page)
    assert step["classification"] == "challenge_or_captcha"
    assert step["classification_evidence"][0] == "condition_prices:challenge_body"
    assert kept["price_chips"]["body"] == body


def test_a_stopped_attempt_ends_the_wait():
    page = FakePage()
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 2

    step, _ = capture(page, should_stop=stop)
    assert step["condition_prices"]["status"] == "attempt_stopped"
    assert step["classification"] == browser.PRICES_NOT_LOADED and page.waits == 3


def test_only_a_200_json_response_keeps_the_warmed_browser():
    assert browser.WARM_SAFE_PRICE_STATUSES == {"dom_not_rendered", "body_unconfirmed"}


def test_the_product_deadline_covers_every_wait_with_margin():
    from snkrdunk_collector.config import settings

    waits = 30 + 1.5 + browser.PRICE_CHIPS_WAIT_S + browser.PRICE_CHIPS_RENDER_MS / 1000 \
        + browser.PRICE_CHIPS_RENDER_MAX_S + browser.PRICE_CHIPS_POLL_MS / 1000
    assert settings.PRODUCT_NAV_TIMEOUT_S - waits >= 5


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
    "body,priced",
    [
        ({"a": [{"price": 3500}]}, 1),
        ({"a": [{"minPrice": "¥3,500"}, {"minPrice": None}]}, 1),
        ({"chips": [{"price": {"amount": 3500}}, {"usedPrice": None}]}, 1),  # inside a price object
        ({"a": [{"price": None}, {"lowestPrice": 0}, {"price": ""}, {"price": True}]}, 0),
        ({"chips": [{"minPrice": 0, "lowest": 3500}]}, 0),
        ({"priceUpdatedAt": "2026-10-26T08:00:00Z"}, 0),
    ],
)
def test_body_listings_is_telemetry_and_never_says_nothing_is_listed(body, priced):
    found = browser.body_listings(json.dumps(body))
    assert found["body_json"] and found["body_priced"] == priced
    assert found["body_listings"] == ("prices" if priced else "unconfirmed")


@pytest.mark.parametrize("text", ["<html>", "", None, "[" * 100_000])
def test_body_listings_rejects_non_json(text):
    assert browser.body_listings(text) == {"body_json": False, "body_listings": "unconfirmed"}
