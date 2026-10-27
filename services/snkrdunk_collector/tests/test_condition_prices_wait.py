"""A product snapshot waits for the page's own condition-price request (2026-10-26 change).

SNKRDUNK now renders every condition chip as 出品待ち and fills the prices in from
GET /v2/products/<id>/size-chips after load. A snapshot before that response is placeholders,
which would read as "nothing listed". No browser, no socket: a fake page replays responses."""

from types import SimpleNamespace

import pytest

from snkrdunk_collector import browser

PRODUCT = "https://snkrdunk.com/apparels/142630"
NAMED = '<html><title>OP01-001</title><body><div>A ¥ 3,500 ~</div>' \
        '<script>self.__next_f.push([1,"/v2/products/142630/size-chips"])</script></body></html>'


class FakePage:
    """Fires `responses` (url, status, after_n_waits) to listeners; records the call order."""

    def __init__(self, *, status=200, responses=(), html=NAMED):
        self.status, self.responses, self.html = status, list(responses), html
        self.listeners, self.calls, self.waits = [], [], 0
        self.url = None

    def on(self, event, callback):
        assert event == "response"
        self.listeners.append(callback)

    def remove_listener(self, event, callback):
        self.listeners.remove(callback)

    def _fire(self):
        for url, status, after in list(self.responses):
            if after <= self.waits:
                self.responses.remove((url, status, after))
                for listener in self.listeners:
                    listener(SimpleNamespace(url=url, status=status))

    def goto(self, url, **kwargs):
        self.url = url
        self.calls.append("goto")
        self._fire()
        return SimpleNamespace(status=self.status)

    def wait_for_timeout(self, ms):
        self.waits += 1
        self.calls.append(f"wait:{ms}")
        self._fire()

    def content(self):
        self.calls.append("content")
        return self.html

    def title(self):
        return "OP01-001"


@pytest.fixture(autouse=True)
def short_wait(monkeypatch):
    # Bounded by the fake page's own waits, not wall time.
    state = {"t": 0.0}

    def tick(ms):
        state["t"] += ms / 1000

    monkeypatch.setattr(browser.time, "monotonic", lambda: state["t"])
    original = FakePage.wait_for_timeout

    def wait(self, ms):
        tick(ms)
        original(self, ms)

    monkeypatch.setattr(FakePage, "wait_for_timeout", wait)


def chips(pid="142630", status=200, after=3):
    return (f"https://snkrdunk.com/v2/products/{pid}/size-chips", status, after)


def test_the_snapshot_is_taken_only_after_the_price_response_and_its_render():
    page = FakePage(responses=[chips(after=3)])
    step = browser.goto_and_capture(page, PRODUCT, condition_prices=True)
    assert step["classification"] == "normal_page"
    assert step["condition_prices"]["status"] == "loaded"
    assert step["condition_prices"]["product_id"] == "142630"
    # goto, the usual 1.5s settle, polls until the response, the render wait, then the snapshot
    assert page.calls[0] == "goto" and page.calls[-1] == "content"
    assert f"wait:{browser.PRICE_CHIPS_RENDER_MS}" in page.calls
    assert page.calls.index(f"wait:{browser.PRICE_CHIPS_RENDER_MS}") < page.calls.index("content")
    assert page.listeners == []  # the listener is removed whatever happens


def test_a_response_already_back_during_navigation_needs_no_polling():
    page = FakePage(responses=[chips(after=0)])
    step = browser.goto_and_capture(page, PRODUCT, condition_prices=True)
    assert step["condition_prices"]["status"] == "loaded"
    assert page.calls == ["goto", "wait:1500", f"wait:{browser.PRICE_CHIPS_RENDER_MS}", "content"]


@pytest.mark.parametrize(
    "responses,expected",
    [
        ([], "not_seen"),
        ([chips(status=500, after=1)], "http_500"),
        ([chips(pid="999999", after=1)], "not_named_by_page"),
    ],
)
def test_without_this_products_price_response_the_page_is_not_a_normal_capture(responses, expected):
    page = FakePage(responses=responses)
    step = browser.goto_and_capture(page, PRODUCT, condition_prices=True)
    assert step["classification"] == browser.PRICES_NOT_LOADED
    assert step["condition_prices"]["status"] == expected
    assert step["classification_evidence"] == [f"condition_prices:{expected}"]
    assert step["html"] == NAMED  # the snapshot is still kept as evidence


def test_the_wait_is_bounded():
    page = FakePage()
    step = browser.goto_and_capture(page, PRODUCT, condition_prices=True)
    assert step["condition_prices"]["waited_s"] <= browser.PRICE_CHIPS_WAIT_S + 0.5
    assert page.waits <= 1 + browser.PRICE_CHIPS_WAIT_S * 1000 / browser.PRICE_CHIPS_POLL_MS + 1


def test_a_denied_page_keeps_its_denial_classification_and_does_not_wait():
    page = FakePage(status=403, html="<html><title>403 Forbidden</title></html>")
    step = browser.goto_and_capture(page, PRODUCT, condition_prices=True)
    assert step["classification"] == "challenge_or_captcha" or step["classification"] == "static_403"
    assert step["condition_prices"]["status"] == "page_not_200"
    assert page.waits == 1  # only the usual settle


def test_pages_without_condition_prices_are_captured_as_before():
    page = FakePage(html="<html><title>Home</title></html>")
    step = browser.goto_and_capture(page, "https://snkrdunk.com/")
    assert step["classification"] == "normal_page" and "condition_prices" not in step
    assert page.listeners == [] and page.calls == ["goto", "wait:1500", "content"]


def test_only_snkrdunk_size_chips_responses_count():
    assert browser._price_chips_response(SimpleNamespace(url="https://snkrdunk.com/v2/products/1/size-chips", status=200)) == ("1", 200)
    for url in ("https://evil.test/v2/products/1/size-chips", "https://snkrdunk.com/v2/products/1/size-guide",
                "https://snkrdunk.com/v2/products/1/size-chips/extra"):
        assert browser._price_chips_response(SimpleNamespace(url=url, status=200)) is None
