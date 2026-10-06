"""Both collector close paths must settle admitted browser callbacks first."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from snkrdunk_collector import collect, due
from app.services.freshness_integration import CaptureResult, AdmissionStopped


@pytest.mark.parametrize("homepage_ok", [True, False])
@pytest.mark.parametrize("settle_failed", [True, False])
def test_metered_close_settles_before_context_disposal_or_result_writer(
    monkeypatch, homepage_ok, settle_failed
):
    events = []
    page, context, browser = Mock(), Mock(), Mock()
    context.new_page.return_value = page
    browser.new_context.return_value = context
    context.close.side_effect = lambda: events.append("context_closed")
    browser.close.side_effect = lambda: events.append("browser_closed")
    playwright = Mock()
    playwright.chromium.launch.return_value = browser

    @contextmanager
    def fake_playwright():
        yield playwright

    monkeypatch.setattr(collect, "sync_playwright", fake_playwright)
    mapping = SimpleNamespace(
        id=1,
        source_id=2,
        source_url="https://snkrdunk.com/apparels/104428",
        source_card_id="OP01-001",
        card_print_id=1,
    )
    monkeypatch.setattr(
        collect,
        "_load_mapping",
        lambda *args: (
            mapping,
            SimpleNamespace(name="snkrdunk"),
            SimpleNamespace(
                treatment="parallel",
                image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png",
            ),
            [],
        ),
    )
    html = (Path(__file__).parent / "fixtures/product_page_reduced.html").read_text()

    def capture(page, url, *, before_parse):
        step = dict(
            html=html,
            http_status=200 if homepage_ok else 403,
            classification="normal_page" if homepage_ok else "challenge_or_captcha",
            final_url=url,
        )
        before_parse(step)
        return step

    monkeypatch.setattr(collect, "goto_and_capture", capture)
    monkeypatch.setattr(collect, "compare_artwork", lambda *args: {"match": True})
    writer = Mock(
        side_effect=lambda *args: events.append("writer")
        or CaptureResult("identity_refusal", failure="fixture refusal")
    )
    monkeypatch.setattr(due, "write_capture", writer)
    freshness = Mock()
    freshness.denied = False
    freshness.request_bytes.return_value = b"image"
    freshness.snapshot.return_value = 7

    def settle(actual_page):
        assert actual_page is page
        events.append("settled")
        if settle_failed:
            raise AdmissionStopped("late_required_denial")

    freshness.settle_browser.side_effect = settle
    outcome = collect.run_one_mapping_detailed(Mock(), 1, freshness=freshness)
    freshness.settle_browser.assert_called_once_with(page)
    if settle_failed:
        assert events == ["settled"]
        writer.assert_not_called()
        assert outcome.stage == "operational_error"
    else:
        assert events[:3] == ["settled", "context_closed", "browser_closed"]
        assert events[3:] == (["writer"] if homepage_ok else [])
