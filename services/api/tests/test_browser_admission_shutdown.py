from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.freshness_integration import Attempt, AdmissionStopped


def attempt():
    return Attempt(Mock(), SimpleNamespace(work_id=1))


def test_settle_fences_new_requests_without_grants_and_retains_interception():
    a = attempt()
    context = Mock()
    a.install_browser(context)
    handler = context.route.call_args.args[1]
    a.admit = Mock()
    a.active_routes = 1
    new_route = Mock()
    def finish_pending(_):
        handler(new_route)
        a.active_routes -= 1
    page = Mock()
    page.wait_for_timeout.side_effect = finish_pending
    a.settle_browser(page)
    a.admit.assert_not_called()
    new_route.fetch.assert_not_called()
    new_route.abort.assert_called_once()
    context.unroute_all.assert_not_called()
    context.unroute.assert_not_called()
    assert a.active_routes == 0


def test_late_required_denial_still_refuses_result():
    a = attempt()
    a.active_routes = 1
    def deny(_):
        a.active_routes = 0
        a.denied = True
        a.stopped = 'source_denial'
    page = Mock()
    page.wait_for_timeout.side_effect = deny
    with pytest.raises(AdmissionStopped, match='source_denial'):
        a.settle_browser(page)
    assert a.denied


def test_settle_is_bounded_and_does_not_overwrite_existing_failure():
    a = attempt()
    a.active_routes = 1
    a.stopped = 'required_document_failed'
    clock = Mock(side_effect=[0, 32])
    with pytest.raises(AdmissionStopped, match='required_document_failed'):
        a.settle_browser(Mock(), monotonic=clock)


def test_route_counter_released_on_network_failure():
    a = attempt()
    context = Mock()
    a.install_browser(context)
    a.admit = Mock()
    route = Mock()
    route.request.resource_type = 'fetch'
    route.request.url = 'https://snkrdunk.com/required'
    route.request.is_navigation_request.return_value = False
    route.fetch.side_effect = RuntimeError('network failed')
    context.route.call_args.args[1](route)
    assert a.active_routes == 0
    assert a.stopped == 'network failed'
