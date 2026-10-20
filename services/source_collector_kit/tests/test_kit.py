"""The kit with a fake transport and an in-memory database. No network."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import RawSnapshot, Source, SourceDispatchBudget
from source_collector_kit import budget as budgets
from source_collector_kit import registry
from source_collector_kit.etiquette import EtiquetteError, stop_reason, user_agent
from source_collector_kit.fetch import PoliteFetcher, RequestLimitReached, Response, SourceDenied
from source_collector_kit.listing_run import run_list_pages
from source_collector_kit.registry import ListingRow, ParsedPage, ParserUnavailable
from source_collector_kit.robots import RobotsGate, RobotsRefused

NOW = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)
ROBOTS = "https://shop.example.test/robots.txt"
PAGES = ["https://shop.example.test/list?sid=1", "https://shop.example.test/list?sid=2"]
OPEN_ROBOTS = b"User-agent: GPTBot\nDisallow:\n"
PAGE = "<html><body>" + "row " * 50 + "</body></html>"
VERSION = "kit-test-v1"


@registry.register(VERSION)
def _parse(html, url):
    if "broken" in html:
        raise ValueError("no product table")
    return ParsedPage(
        rows=(ListingRow("1", url, "ナミ(R)(OP01-016)", "状態A", 400, 11),),
        group_key=url.rsplit("=", 1)[-1],
        header_total=1,
    )


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def transport_for(answers):
    calls = []

    def transport(url, headers, timeout):
        calls.append((url, headers["User-Agent"]))
        status, body = answers.get(url, (200, PAGE.encode()))
        return Response(url, status, {"Content-Type": "text/html; charset=utf-8"}, body)

    transport.calls = calls
    return transport


def fetcher(answers=None, max_requests=10, clock=None):
    clock = clock or FakeClock()
    transport = transport_for({ROBOTS: (200, OPEN_ROBOTS), **(answers or {})})
    f = PoliteFetcher(
        user_agent=user_agent("bot@cardpirate.test.dev"), allowed_hosts={"shop.example.test"},
        max_requests=max_requests, transport=transport, clock=clock, sleep=clock.sleep, jitter=lambda: 0.5,
    )
    return f, transport, clock


# --- etiquette ----------------------------------------------------------------------------------


def test_user_agent_is_honest_and_needs_a_real_contact():
    assert user_agent("bot@cardpirate.test.dev") == "CardPirateBot/1.0 (+bot@cardpirate.test.dev)"
    assert user_agent("https://cardpirate.test.dev/bot") == "CardPirateBot/1.0 (+https://cardpirate.test.dev/bot)"
    for bad in (None, "", "  ", "【owner email】", "owner email", "not an address", "bot@example.com"):
        with pytest.raises(EtiquetteError):
            user_agent(bad)


@pytest.mark.parametrize(
    "status, body, reason",
    [
        (403, b"", "http_403"),
        (429, b"slow down", "http_429"),
        (200, b"<script src='/cdn-cgi/challenge-platform/x'></script>", "challenge_page"),
        (503, b"<title>Just a moment...</title>", "challenge_page"),
        (503, b"please solve the captcha", "challenge_page"),
        (200, b"<script src='https://www.google.com/recaptcha/api.js'></script>", None),
        (200, b"<html>ok</html>", None),
        (500, b"server error", None),
    ],
)
def test_stop_rule(status, body, reason):
    assert stop_reason(status, body) == reason


# --- robots -------------------------------------------------------------------------------------


def test_robots_without_a_star_group_allows_us_and_fails_closed_otherwise():
    assert RobotsGate.from_response(200, OPEN_ROBOTS).allows(PAGES[0])
    closed = RobotsGate.from_response(200, b"User-agent: CardPirateBot\nDisallow: /list\n")
    assert not closed.allows(PAGES[0])
    with pytest.raises(RobotsRefused):
        closed.require(PAGES)
    for status in (404, 500):
        with pytest.raises(RobotsRefused):
            RobotsGate.from_response(status, b"")


# --- fetcher ------------------------------------------------------------------------------------


def test_fetcher_reads_robots_first_spaces_requests_and_keeps_to_its_hosts():
    f, transport, clock = fetcher()
    with pytest.raises(RobotsRefused):
        f.get(PAGES[0])
    f.load_robots(ROBOTS)
    f.get(PAGES[0])
    f.get(PAGES[1])
    assert clock.slept == [pytest.approx(6.0), pytest.approx(6.0)]  # 5 s + 0.5 x 2 s jitter
    assert all(ua.startswith("CardPirateBot/1.0") for _, ua in transport.calls)
    with pytest.raises(ValueError):
        f.get("https://elsewhere.example.test/list")
    assert f.requests_made == 3


def test_fetcher_stops_on_denial_and_on_its_request_limit():
    f, _, _ = fetcher({PAGES[0]: (429, b"")}, max_requests=2)
    f.load_robots(ROBOTS)
    with pytest.raises(SourceDenied) as denied:
        f.get(PAGES[0])
    assert denied.value.reason == "http_429"
    with pytest.raises(RequestLimitReached):
        f.get(PAGES[1])


# --- budget -------------------------------------------------------------------------------------


def _source(db, *, enabled=True, limit=200, used=0, pause=None, until=None):
    source = Source(name="shop", base_url="https://shop.example.test")
    db.add(source)
    db.flush()
    db.add(SourceDispatchBudget(
        source_id=source.id, enabled=enabled, request_limit=limit, window_seconds=86400,
        window_started_at=NOW - timedelta(hours=1), used_requests=used, reserved_requests=0,
        pause_reason=pause, paused_until=until, claim_sequence=0,
    ))
    db.commit()
    return source


def _budget(db, source):
    db.expire_all()
    return db.query(SourceDispatchBudget).filter_by(source_id=source.id).one()


def test_budget_reserves_settles_and_rolls_its_window(db):
    source = _source(db, used=150)
    with pytest.raises(budgets.BudgetClosed):
        budgets.reserve(db, source.id, 51, now=NOW)
    r = budgets.reserve(db, source.id, 50, now=NOW)
    assert _budget(db, source).reserved_requests == 50
    budgets.settle(db, r, 7)
    b = _budget(db, source)
    assert (b.reserved_requests, b.used_requests) == (0, 157)
    budgets.reserve(db, source.id, 200, now=NOW + timedelta(days=1))
    assert _budget(db, source).used_requests == 0


@pytest.mark.parametrize(
    "kwargs",
    [{"enabled": False}, {"pause": "source_denial"}, {"pause": "x", "until": NOW + timedelta(hours=1)}],
)
def test_closed_budgets_refuse_any_run(db, kwargs):
    source = _source(db, **kwargs)
    with pytest.raises(budgets.BudgetClosed):
        budgets.reserve(db, source.id, 1, now=NOW)


def test_no_budget_row_means_no_run(db):
    source = Source(name="shop", base_url="https://shop.example.test")
    db.add(source)
    db.commit()
    with pytest.raises(budgets.BudgetClosed):
        budgets.reserve(db, source.id, 1, now=NOW)


# --- the run ------------------------------------------------------------------------------------


def _run(db, f, pages=PAGES, handled=None, version=VERSION):
    seen = handled if handled is not None else []
    return run_list_pages(
        db, source_name="shop", parser_version=version, robots_url=ROBOTS, pages=pages, fetcher=f,
        handle_page=lambda db, source, parsed, raw, report: seen.append((parsed.group_key, raw.id)),
        clock=lambda: NOW,
    )


def test_a_run_stores_raw_before_handing_rows_on(db):
    source = _source(db)
    f, _, _ = fetcher()
    handled = []
    report = _run(db, f, handled=handled)
    raws = db.query(RawSnapshot).order_by(RawSnapshot.id).all()
    assert [g for g, _ in handled] == ["1", "2"]
    assert [r.id for r in raws] == [raw_id for _, raw_id in handled]
    assert all(r.parser_version == VERSION and r.raw_content == PAGE for r in raws)
    assert (report.pages_fetched, report.requests, report.rows_parsed, report.stopped) == (2, 3, 2, None)
    b = _budget(db, source)
    assert (b.used_requests, b.reserved_requests) == (3, 0)
    assert '"event": "source_collector_run"' in report.to_log()


def test_a_denial_stores_its_page_pauses_the_source_and_ends_the_run(db):
    source = _source(db)
    f, transport, _ = fetcher({PAGES[0]: (403, b"forbidden")})
    report = _run(db, f)
    assert report.stopped == "http_403"
    assert [u for u, _ in transport.calls] == [ROBOTS, PAGES[0]]
    assert db.query(RawSnapshot).one().http_status == 403
    b = _budget(db, source)
    assert (b.pause_reason, b.paused_until, b.used_requests, b.reserved_requests) == ("source_denial", None, 2, 0)
    with pytest.raises(budgets.BudgetClosed):
        _run(db, fetcher()[0])


def test_robots_disallow_means_no_page_request(db):
    _source(db)
    f, transport, _ = fetcher({ROBOTS: (200, b"User-agent: *\nDisallow: /list\n")})
    report = _run(db, f)
    assert report.stopped.startswith("robots:")
    assert [u for u, _ in transport.calls] == [ROBOTS]
    assert db.query(RawSnapshot).count() == 0


def test_a_parser_rejection_keeps_the_raw_and_moves_on(db):
    _source(db)
    f, _, _ = fetcher({PAGES[0]: (200, b"<html>broken</html>")})
    handled = []
    report = _run(db, f, handled=handled)
    assert [g for g, _ in handled] == ["2"]
    assert report.parse_failures == 1 and db.query(RawSnapshot).count() == 2


def test_no_parser_means_no_request(db):
    _source(db)
    f, transport, _ = fetcher()
    with pytest.raises(ParserUnavailable):
        _run(db, f, version="unregistered-v1")
    assert transport.calls == []
