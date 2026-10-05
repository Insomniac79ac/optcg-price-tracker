"""Replay source boundary failures without network, browser or database."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.services.freshness_integration import Attempt, AdmissionStopped


def boundary(
    url="https://yuyu-tei.jp/", kind="document", navigation=True, method="GET"
):
    attempt = Attempt(None, SimpleNamespace(work_id=1))
    attempt.admit = Mock()

    def deny():
        attempt.denied = True
        attempt.stopped = "source_denial"

    attempt.deny = Mock(side_effect=deny)
    context = Mock()
    attempt.install_browser(context)
    handler = context.route.call_args.args[1]
    frame = SimpleNamespace()
    frame.page = SimpleNamespace(main_frame=frame)
    request = SimpleNamespace(
        url=url,
        resource_type=kind,
        method=method,
        headers={"Cookie": "private", "Authorization": "private"},
        frame=frame,
        is_navigation_request=lambda: navigation,
    )
    route = Mock(request=request)
    return attempt, handler, route


@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://snkrdunk.com/v1/accounts/me", "fetch"),
        ("https://bbc.bibian.co.jp/widget", "script"),
        ("https://snkrdunk.com/art.jpg", "image"),
    ],
)
def test_presentation_requests_never_dispatch_or_pause(url, kind):
    attempt, handler, route = boundary(url, kind, False)
    handler(route)
    route.abort.assert_called_once()
    route.fetch.assert_not_called()
    attempt.admit.assert_not_called()
    attempt.deny.assert_not_called()
    assert attempt.stopped is None


def test_optional_redirect_failure_does_not_poison_product_navigation():
    attempt, handler, route = boundary("https://assets.example/widget", "script", False)
    route.fetch.return_value = SimpleNamespace(status=302, headers={})
    handler(route)
    assert attempt.stopped is None and attempt.health["optional_resource"] == 1
    attempt.check()
    route.abort.assert_called_once()


def test_optional_transport_failure_does_not_poison_product_navigation():
    attempt, handler, route = boundary("https://assets.example/widget", "script", False)
    route.fetch.side_effect = RuntimeError("asset unavailable")
    handler(route)
    assert attempt.stopped is None
    attempt.check()


@pytest.mark.parametrize("status", [403, 429])
def test_required_document_denial_still_pauses_source(status):
    attempt, handler, route = boundary("https://snkrdunk.com/apparels/123")
    route.fetch.return_value = SimpleNamespace(status=status, headers={})
    handler(route)
    assert attempt.denied and attempt.health[f"http_{status}"] == 1
    attempt.deny.assert_called_once()
    with pytest.raises(AdmissionStopped):
        attempt.check()


def test_main_product_redirect_is_not_followed_or_hidden():
    attempt, handler, route = boundary("https://snkrdunk.com/apparels/123")
    route.fetch.return_value = SimpleNamespace(
        status=302, headers={"location": "/apparels/456"}
    )
    handler(route)
    assert attempt.stopped == "unsupported browser redirect"
    assert route.fetch.call_count == 1
    route.abort.assert_called_once()


def test_asset_redirect_is_bounded_metered_and_strips_cross_origin_secrets():
    attempt, handler, route = boundary("https://assets.example/widget", "script", False)
    route.fetch.side_effect = [
        SimpleNamespace(status=302, headers={"location": "https://cdn.example/widget"}),
        SimpleNamespace(status=200, headers={}),
    ]
    handler(route)
    assert attempt.admit.call_count == 2
    assert route.fetch.call_args.kwargs["headers"] == {}
    assert route.fetch.call_args.kwargs["max_redirects"] == 0
    assert route.fetch.call_args.kwargs["max_retries"] == 0
    assert attempt.stopped is None
    route.fulfill.assert_called_once()


def test_optional_asset_cannot_hide_admission_refusal():
    attempt, handler, route = boundary("https://assets.example/widget", "script", False)

    def refused():
        attempt.stopped = "budget exhausted"
        raise AdmissionStopped(attempt.stopped)

    attempt.admit.side_effect = refused
    handler(route)
    route.fetch.assert_not_called()
    with pytest.raises(AdmissionStopped):
        attempt.check()


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_conversion_measurement_never_dispatches_or_degrades(method):
    attempt, handler, route = boundary(
        "https://www.google.com/measurement/conversion?opaque=redacted",
        "fetch",
        False,
        method,
    )
    route.fetch.return_value = SimpleNamespace(status=302, headers={})
    handler(route)
    route.abort.assert_called_once()
    route.fetch.assert_not_called()
    attempt.admit.assert_not_called()
    attempt.deny.assert_not_called()
    assert attempt.health["optional_resource"] == 0
    assert attempt.stopped is None


@pytest.mark.parametrize(
    "url,navigation",
    [
        ("https://www.google.com/measurement/conversion", True),
        ("https://yuyu-tei.jp/measurement/conversion", False),
        ("https://snkrdunk.com/measurement/conversion", False),
        ("https://www.google.com/measurement/conversion/product", False),
    ],
)
def test_conversion_exclusion_preserves_navigation_and_other_endpoints(url, navigation):
    attempt, handler, route = boundary(
        url, "document" if navigation else "fetch", navigation
    )
    route.fetch.return_value = SimpleNamespace(status=403, headers={})
    handler(route)
    attempt.admit.assert_called_once()
    route.fetch.assert_called_once()
    attempt.deny.assert_called_once()
    assert attempt.stopped == "source_denial"
