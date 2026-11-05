"""The collector consults owner photo confirmations after a refused comparison (owner 2026-11-04,
plan B): exactly the mapping, print, listing and the photo its own extractor read."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from app.services.freshness_integration import CaptureResult
from snkrdunk_collector import collect, due, extractor, models, owner_artwork

HTML = (Path(__file__).parent / "fixtures/product_page_reduced.html").read_text()
REFUSED = {"match": False, "hash_distances": {"average_hash": 24, "dhash": 9, "phash": 14}}


def run(monkeypatch, entries):
    page, context, browser = Mock(), Mock(), Mock()
    context.new_page.return_value = page
    browser.new_context.return_value = context
    playwright = Mock()
    playwright.chromium.launch.return_value = browser

    @contextmanager
    def fake_playwright():
        yield playwright

    monkeypatch.setattr(collect, "sync_playwright", fake_playwright)
    # The collector's own mapping model, not a stand-in: on 2026-11-04 a SimpleNamespace carried an
    # attribute the real model lacked, and production skipped every confirmation.
    mapping = models.SourceCardMapping(id=4456, source_id=2, source_url="https://snkrdunk.com/apparels/104428",
                                       source_card_id="OP01-001", card_print_id=5862,
                                       canonical_source_listing_identity="104428")
    monkeypatch.setattr(collect, "_load_mapping", lambda *args: (
        mapping, SimpleNamespace(name="snkrdunk"),
        SimpleNamespace(treatment="parallel",
                        image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png"), []))

    def capture(page, url, *, before_parse, **kwargs):
        step = dict(html=HTML, http_status=200, classification="normal_page", final_url=url)
        before_parse(step)
        return step

    monkeypatch.setattr(collect, "goto_and_capture", capture)
    monkeypatch.setattr(collect, "compare_artwork", lambda *args: dict(REFUSED))
    seen = []

    def spy(comparison, **kwargs):
        out = owner_artwork.confirm(comparison, entries=entries, **kwargs)
        seen.append((kwargs, out))
        return out

    monkeypatch.setattr(collect, "confirm_owner_artwork", spy)
    monkeypatch.setattr(due, "write_capture", Mock(return_value=CaptureResult("identity_refusal", failure="x")))
    freshness = Mock()
    freshness.denied = False
    freshness.request_bytes.return_value = b"image"
    freshness.snapshot.return_value = 7
    collect.run_one_mapping_detailed(Mock(), 4456, freshness=freshness)
    assert len(seen) == 1
    return seen[0]


def fixture_photo():
    url, _ = extractor.find_main_product_image(BeautifulSoup(HTML, "html.parser"))
    assert url
    return url


def test_the_exact_confirmed_photo_becomes_an_owner_match(monkeypatch):
    photo = fixture_photo()
    entries = {(4456, 5862, "104428"): {"photo_url": photo, "confirmed_on": "2026-11-03"}}
    kwargs, out = run(monkeypatch, entries)
    assert kwargs == {"mapping_id": 4456, "card_print_id": 5862, "listing": "104428", "photo_url": photo}
    assert out["match"] is True and out["owner_confirmed"]["photo_url"] == photo


def test_without_a_confirmation_the_refusal_stands(monkeypatch):
    _, out = run(monkeypatch, {})
    assert out == REFUSED


def test_the_collector_mapping_model_reads_the_stored_listing_identity():
    column = models.SourceCardMapping.__table__.c.canonical_source_listing_identity
    assert column.nullable
