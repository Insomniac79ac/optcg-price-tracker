"""The product page carries its own size-chips response (seen live 2026-10-30).

SNKRDUNK now fetches /v2/products/<id>/size-chips on the server and dehydrates it into a React
Query stream script; no price request follows on the client, so the network wait never sees
one. The shapes below copy the live pages /apparels/93511 (Yamato SEC-P, A ¥3,700, B ¥3,480,
PSA10 ¥13,000) and /apparels/142630 (Penguin C, nothing listed). No browser, no socket."""

import json
from types import SimpleNamespace

import pytest

from snkrdunk_collector import browser
from snkrdunk_collector.extractor import extract_raw_conditions
from bs4 import BeautifulSoup

PID = "93511"
URL = f"https://snkrdunk.com/apparels/{PID}"
CODES = {"A": "trading_card_single_nearly_unused", "B": "trading_card_single_little_scratches",
         "C": "trading_card_single_medium_scratches", "D": "trading_card_single_large_damages",
         "PSA10": "trading_card_single_psa10"}
YAMATO = {"A": 3700, "B": 3480, "C": None, "D": None, "PSA10": 13000}
PENGUIN = {"A": None, "B": None, "C": None, "D": None, "PSA10": None}


def chips_json(prices):
    out = []
    for label, price in prices.items():
        chip = {"conditionCode": CODES[label], "text": label, "hasListing": price is not None}
        if price is not None:
            chip["usedMinPrice"] = price
        out.append(chip)
    return out


def rq_script(prices, pid=PID, *, status="success", http=200, chips=None):
    payload = {"mutations": [], "queries": [{
        "queryKey": [f"/v2/products/{pid}/size-chips", {"type": "apparel"}],
        "queryHash": json.dumps([f"/v2/products/{pid}/size-chips", {"type": "apparel"}]),
        "state": {"status": status, "data": {"status": http, "headers": {},
                                              "data": {"chips": chips if chips is not None else chips_json(prices)}}},
    }]}
    return ('<script>window["__RQ_R_1tb_"] = window["__RQ_R_1tb_"] || [];'
            f'window["__RQ_R_1tb_"].push({json.dumps(payload, ensure_ascii=False)});</script>')


def chip_html(label, price, *, disabled=None):
    disabled = price is None if disabled is None else disabled
    cls = "YOqw-G_chip  YOqw-G_disabled" if disabled else "YOqw-G_chip  "
    attr = ' disabled=""' if disabled else ""
    value = ('<p class="YOqw-G_awaiting">出品待ち</p>' if price is None else
             f'<p class="YOqw-G_price"><span class="YOqw-G_priceUnit">¥</span>{price:,}<!-- -->~</p>')
    return f'<button type="button" class="{cls}"{attr}><p class="YOqw-G_variant">{label}</p>{value}</button>'


def page(rendered, embedded=None, **kwargs):
    chips = "".join(chip_html(label, price) for label, price in rendered.items())
    script = rq_script(rendered if embedded is None else embedded, **kwargs)
    return f"<html><head><title>ヤマト</title></head><body><div class=\"YOqw-G_container\">{chips}</div>{script}</body></html>"


class OnePage:
    """A page whose HTML is complete at load; records every wait."""

    def __init__(self, html, url=URL):
        self.html, self.url_target, self.url, self.waits, self.handlers = html, url, None, 0, {}

    def on(self, event, callback):
        self.handlers.setdefault(event, []).append(callback)

    def remove_listener(self, event, callback):
        self.handlers[event].remove(callback)

    def goto(self, url, **kwargs):
        self.url = url
        return SimpleNamespace(status=200)

    def wait_for_timeout(self, ms):
        self.waits += 1

    def content(self):
        return self.html

    def title(self):
        return "ヤマト"

    def evaluate(self, script):
        return {}


@pytest.fixture(autouse=True)
def fake_clock(monkeypatch):
    # The fallback network wait is bounded by these fake waits, not wall time.
    state = {"t": 0.0}
    monkeypatch.setattr(browser.time, "monotonic", lambda: state["t"])
    original = OnePage.wait_for_timeout

    def wait(self, ms):
        state["t"] += ms / 1000
        original(self, ms)

    monkeypatch.setattr(OnePage, "wait_for_timeout", wait)


def capture(html):
    pg = OnePage(html)
    kept = []
    step = browser.goto_and_capture(pg, URL, condition_prices=True, before_parse=kept.append)
    return step, pg


def test_embedded_prices_are_read_without_waiting_for_a_request():
    step, pg = capture(page(YAMATO))
    assert step["classification"] == "normal_page"
    assert step["condition_prices"]["status"] == "loaded"
    assert step["condition_prices"]["source"] == "embedded"
    assert step["condition_prices"]["listed"] == ["A", "B", "PSA10"]
    assert pg.waits == 1  # only the fixed settle after navigation, never the 15 s price wait


def test_a_page_with_nothing_listed_and_every_chip_disabled_goes_on_to_extraction():
    step, _ = capture(page(PENGUIN))
    assert step["classification"] == "normal_page"
    assert step["condition_prices"]["status"] == "loaded"
    assert step["condition_prices"]["listed"] == []
    conditions = extract_raw_conditions(BeautifulSoup(step["html"], "html.parser"))["conditions"]
    assert all(conditions[g]["price_jpy"] is None and conditions[g]["raw_text"] == "出品待ち" for g in "ABCD")


@pytest.mark.parametrize("rendered,embedded", [
    ({**YAMATO, "A": 3600}, YAMATO),                 # rendered price differs from the data
    ({**YAMATO, "C": 900}, YAMATO),                  # rendered listed, data says nothing listed
    (YAMATO, {**YAMATO, "B": None}),                 # data says nothing listed, page shows a price
])
def test_embedded_data_and_rendered_chips_must_agree(rendered, embedded):
    step, _ = capture(page(rendered, embedded))
    assert step["classification"] == browser.PRICES_NOT_LOADED
    assert step["condition_prices"]["status"] == "embedded_dom_mismatch"
    assert "condition_prices:embedded_dom_mismatch" in step["classification_evidence"]


def test_an_unlisted_grade_that_is_still_clickable_is_not_no_listing():
    chips = "".join(chip_html(g, None, disabled=(g != "A")) for g in PENGUIN)
    html = f"<html><body><div>{chips}</div>{rq_script(PENGUIN)}</body></html>"
    step, _ = capture(html)
    assert step["condition_prices"]["status"] == "embedded_dom_mismatch"
    assert step["condition_prices"]["mismatched"] == ["A"]


def test_only_this_products_embedded_response_counts():
    step, pg = capture(page(YAMATO, pid="11111"))
    # Not ours: treated as absent, so the older network wait runs (and sees nothing).
    assert step["condition_prices"]["status"] == "not_seen"
    assert pg.waits > 1


@pytest.mark.parametrize("kwargs", [
    {"status": "error"},
    {"http": 500},
    {"chips": []},
    {"chips": [{"text": "A", "hasListing": True}]},                       # listed without a price
    {"chips": [{"text": "A", "hasListing": False, "usedMinPrice": 100}]},  # unlisted with a price
    {"chips": [{"text": "A", "hasListing": "yes"}]},
    {"chips": [{"text": "A", "hasListing": False}, {"text": "A", "hasListing": False}]},
])
def test_an_unusable_embedded_response_is_refused_not_guessed(kwargs):
    step, _ = capture(page(YAMATO, **kwargs))
    assert step["classification"] == browser.PRICES_NOT_LOADED
    assert step["condition_prices"]["status"] == "embedded_unusable"


def test_two_embedded_responses_for_one_product_are_refused():
    html = page(YAMATO).replace("</body>", rq_script(YAMATO) + "</body>")
    step, _ = capture(html)
    assert step["condition_prices"]["status"] == "embedded_ambiguous"


def test_the_evidence_names_the_embedded_response_hash_not_the_chips():
    step, _ = capture(page({**YAMATO, "A": 3600}, YAMATO))
    assert any(e.startswith("embedded_size_chips_sha256:") for e in step["classification_evidence"])
    assert "chips" not in step["condition_prices"]


def test_only_grade_a_is_a_raw_price_for_now():
    """Owner 2026-10-30: A only until the spliced cutover adds B to D with their labels."""
    html = page({**YAMATO, "A": None})
    raw = extract_raw_conditions(BeautifulSoup(html, "html.parser"))
    assert raw["raw_floor_jpy"] is None and raw["raw_floor_condition"] is None
    assert raw["conditions"]["B"]["price_jpy"] == 3480  # kept as evidence, not a price


@pytest.mark.parametrize("prices,unlisted", [
    (PENGUIN, True),                                        # nothing listed at all
    ({**YAMATO, "A": None}, True),                          # B listed, no grade-A listing
    (YAMATO, False),                                        # A listed
    ({"A": None, "B": None, "C": None}, False),             # incomplete picker
])
def test_no_grade_a_listing_is_a_confident_no_listing(prices, unlisted):
    from snkrdunk_collector.extractor import raw_price_grades_unlisted

    conditions = extract_raw_conditions(BeautifulSoup(page(prices), "html.parser"))["conditions"]
    assert raw_price_grades_unlisted(conditions) is unlisted


def test_best_grade_is_a_even_when_b_is_cheaper():
    raw = extract_raw_conditions(BeautifulSoup(page(YAMATO), "html.parser"))
    assert (raw["raw_floor_jpy"], raw["raw_floor_condition"]) == (3700, "A")


def test_log_lines_carry_a_readable_message(capsys):
    browser.log_event("product_result", mapping_id=230, classification="normal_page", extra=1)
    line = json.loads(capsys.readouterr().out)
    assert line["message"] == "product_result mapping_id=230 classification=normal_page"
    assert line["event"] == "product_result" and line["extra"] == 1
