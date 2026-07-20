from pathlib import Path

import httpx
import pytest

from worker.adapters.snkrdunk_discovery import (
    BLOCKED_STATUS_CODES,
    SnkrdunkDiscoveryAdapter,
    SnkrdunkDiscoveryError,
    is_blocked_response,
)
from worker.jobs.discover_snkrdunk import discover_snkrdunk
from worker.models import (
    Card,
    RawSnapshot,
    SnkrdunkCandidate,
    SnkrdunkDiscoveryRun,
    Source,
    SourceCardMapping,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SEARCH_PAGE_HTML = (FIXTURES / "snkrdunk_search_sample.html").read_text(encoding="utf-8")
CANDIDATE_PAGE_HTML = (FIXTURES / "snkrdunk_candidate_sample.html").read_text(encoding="utf-8")

SEARCH_URL = "https://snkrdunk.com/trading-cards/search?category=one-piece-card-game"
NEXT_PAGE_URL = "https://snkrdunk.com/trading-cards/search?category=one-piece-card-game&page=2"

EMPTY_LAST_PAGE_HTML = """
<html><body><div class="search-results"></div></body></html>
"""


def make_adapter(handler, **kwargs) -> SnkrdunkDiscoveryAdapter:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return SnkrdunkDiscoveryAdapter(client=client, **kwargs)


def single_page_handler(html: str, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=html)

    return handler


def two_page_handler(request: httpx.Request) -> httpx.Response:
    if "page=2" in str(request.url):
        return httpx.Response(200, text=EMPTY_LAST_PAGE_HTML)
    return httpx.Response(200, text=SEARCH_PAGE_HTML)


# --- adapter-level tests -------------------------------------------------


def test_fetch_page_raises_for_off_domain_url():
    adapter = make_adapter(single_page_handler(SEARCH_PAGE_HTML))
    with pytest.raises(SnkrdunkDiscoveryError):
        adapter.fetch_page("https://example.com/not-snkrdunk")


def test_parse_search_page_extracts_candidates_and_skips_off_domain_links():
    adapter = make_adapter(single_page_handler(SEARCH_PAGE_HTML))
    snapshot = adapter.fetch_page(SEARCH_URL)

    result = adapter.parse_search_page(snapshot)

    urls = [c.source_url for c in result.candidates]
    assert len(result.candidates) == 3
    assert all(url.startswith("https://snkrdunk.com/") for url in urls)
    assert "https://external-shop.example.com/should-be-ignored" not in urls

    luffy = next(c for c in result.candidates if "luffy-l" in c.source_url)
    assert luffy.title == "ONE PIECEカードゲーム OP01-001 モンキー・D・ルフィ L"
    assert luffy.price_jpy == 1200
    assert luffy.listing_count == 12
    assert luffy.condition_label == "中古"
    assert luffy.image_url == "https://img.snkrdunk.com/op01-001.jpg"


def test_parse_search_page_follows_pagination_when_present():
    adapter = make_adapter(single_page_handler(SEARCH_PAGE_HTML))
    snapshot = adapter.fetch_page(SEARCH_URL)

    result = adapter.parse_search_page(snapshot)

    assert result.next_page_url == NEXT_PAGE_URL


def test_parse_search_page_no_pagination_link_returns_none():
    adapter = make_adapter(single_page_handler(CANDIDATE_PAGE_HTML))
    snapshot = adapter.fetch_page(SEARCH_URL)

    result = adapter.parse_search_page(snapshot)

    assert result.next_page_url is None
    assert len(result.candidates) == 1


def test_parse_search_page_returns_empty_for_non_200_status():
    adapter = make_adapter(single_page_handler(SEARCH_PAGE_HTML, status_code=500))
    snapshot = adapter.fetch_page(SEARCH_URL)

    result = adapter.parse_search_page(snapshot)

    assert result.candidates == []
    assert result.next_page_url is None


def test_parse_search_page_returns_empty_for_403_response():
    adapter = make_adapter(single_page_handler(SEARCH_PAGE_HTML, status_code=403))
    snapshot = adapter.fetch_page(SEARCH_URL)

    assert snapshot.http_status == 403
    result = adapter.parse_search_page(snapshot)

    assert result.candidates == []
    assert result.next_page_url is None


def test_is_blocked_response_covers_401_403_429_only():
    assert BLOCKED_STATUS_CODES == frozenset({401, 403, 429})
    assert is_blocked_response(401)
    assert is_blocked_response(403)
    assert is_blocked_response(429)
    assert not is_blocked_response(200)
    assert not is_blocked_response(404)
    assert not is_blocked_response(500)


def test_fetch_page_rate_limits_between_consecutive_requests():
    sleep_calls = []
    clock = iter([1000.0, 1000.01, 1000.02])
    adapter = make_adapter(
        single_page_handler(SEARCH_PAGE_HTML),
        request_delay_ms=100,
        sleep_fn=sleep_calls.append,
        monotonic_fn=lambda: next(clock),
    )

    adapter.fetch_page(SEARCH_URL)
    adapter.fetch_page(SEARCH_URL)

    assert sleep_calls == [pytest.approx(0.09)]


# --- job-level tests (discover_snkrdunk) ---------------------------------


def seed_source_and_cards(db_session):
    db_session.add(Source(name="snkrdunk", base_url="https://snkrdunk.com"))
    db_session.add(
        Card(
            card_code="OP01-001", name_en="Monkey D. Luffy", name_jp="モンキー・D・ルフィ",
            set_code="OP01", rarity="L", variant=None, language="jp",
        )
    )
    db_session.add(
        Card(
            card_code="OP02-025", name_en="Nico Robin", name_jp="ニコ・ロビン",
            set_code="OP02", rarity="R", variant=None, language="jp",
        )
    )
    db_session.flush()


def write_seed_file(tmp_path: Path) -> Path:
    seed_file = tmp_path / "snkrdunk_one_piece_urls.txt"
    seed_file.write_text(f"# comment\n\n{SEARCH_URL}\n")
    return seed_file


def test_discover_snkrdunk_stores_snapshots_candidates_and_matches(db_session, tmp_path):
    seed_source_and_cards(db_session)
    adapter = make_adapter(two_page_handler)

    summary = discover_snkrdunk(
        db_session,
        max_pages=5,
        seed_file=write_seed_file(tmp_path),
        adapter=adapter,
    )

    assert summary.status == "completed"
    assert summary.pages_fetched == 2
    assert summary.candidates_found == 3

    assert db_session.query(RawSnapshot).count() == 2
    assert db_session.query(SnkrdunkDiscoveryRun).count() == 1
    assert db_session.query(SnkrdunkCandidate).count() == 3

    luffy = (
        db_session.query(SnkrdunkCandidate)
        .filter(SnkrdunkCandidate.source_url.like("%luffy-l"))
        .one()
    )
    assert luffy.match_status == "matched"
    assert luffy.detected_card_code == "OP01-001"

    robin = (
        db_session.query(SnkrdunkCandidate)
        .filter(SnkrdunkCandidate.source_url.like("%robin-r"))
        .one()
    )
    assert robin.match_status == "matched"

    graded = (
        db_session.query(SnkrdunkCandidate)
        .filter(SnkrdunkCandidate.source_url.like("%luffy-graded"))
        .one()
    )
    assert graded.match_status == "suggested"
    assert graded.condition_label == "PSA10"

    assert summary.candidates_matched == 2
    assert summary.candidates_needing_review == 1

    mappings = db_session.query(SourceCardMapping).all()
    assert len(mappings) == 2
    assert all(m.manual_verified is False for m in mappings)


def test_discover_snkrdunk_dedups_by_source_url_on_rerun(db_session, tmp_path):
    seed_source_and_cards(db_session)
    seed_file = write_seed_file(tmp_path)

    discover_snkrdunk(db_session, max_pages=5, seed_file=seed_file, adapter=make_adapter(two_page_handler))
    first_count = db_session.query(SnkrdunkCandidate).count()

    second_summary = discover_snkrdunk(
        db_session, max_pages=5, seed_file=seed_file, adapter=make_adapter(two_page_handler)
    )

    assert db_session.query(SnkrdunkCandidate).count() == first_count
    # Already-matched candidates aren't re-matched on rerun.
    assert second_summary.candidates_matched == 0


def test_discover_snkrdunk_does_not_override_manual_mapping(db_session, tmp_path):
    seed_source_and_cards(db_session)
    source = db_session.query(Source).filter_by(name="snkrdunk").one()
    luffy_card = db_session.query(Card).filter_by(card_code="OP01-001").one()

    manual_mapping = SourceCardMapping(
        card_id=luffy_card.id,
        source_id=source.id,
        source_card_id="manual-OP01-001",
        source_url="https://snkrdunk.com/trading-cards/manually-verified-listing",
        manual_verified=True,
    )
    db_session.add(manual_mapping)
    db_session.flush()

    discover_snkrdunk(
        db_session, max_pages=5, seed_file=write_seed_file(tmp_path), adapter=make_adapter(two_page_handler)
    )

    db_session.refresh(manual_mapping)
    assert manual_mapping.manual_verified is True
    assert manual_mapping.source_url == "https://snkrdunk.com/trading-cards/manually-verified-listing"

    # No second mapping was created for the same card/source pair.
    count = (
        db_session.query(SourceCardMapping)
        .filter_by(card_id=luffy_card.id, source_id=source.id)
        .count()
    )
    assert count == 1


def test_discover_snkrdunk_dry_run_persists_nothing(db_session, tmp_path):
    seed_source_and_cards(db_session)

    summary = discover_snkrdunk(
        db_session,
        max_pages=5,
        seed_file=write_seed_file(tmp_path),
        adapter=make_adapter(two_page_handler),
        dry_run=True,
    )

    assert summary.status == "completed"
    assert db_session.query(SnkrdunkDiscoveryRun).count() == 0
    assert db_session.query(SnkrdunkCandidate).count() == 0
    assert db_session.query(RawSnapshot).count() == 0
    assert db_session.query(SourceCardMapping).count() == 0


def test_discover_snkrdunk_respects_max_pages(db_session, tmp_path):
    seed_source_and_cards(db_session)

    summary = discover_snkrdunk(
        db_session,
        max_pages=1,
        seed_file=write_seed_file(tmp_path),
        adapter=make_adapter(two_page_handler),
    )

    assert summary.pages_fetched == 1


def test_discover_snkrdunk_respects_limit_candidates(db_session, tmp_path):
    seed_source_and_cards(db_session)

    summary = discover_snkrdunk(
        db_session,
        max_pages=5,
        limit_candidates=2,
        seed_file=write_seed_file(tmp_path),
        adapter=make_adapter(two_page_handler),
    )

    assert summary.candidates_found == 2


# --- blocked/rate-limited response handling ------------------------------


def write_seed_file_multi(tmp_path: Path, urls: list[str]) -> Path:
    seed_file = tmp_path / "snkrdunk_one_piece_urls.txt"
    seed_file.write_text("\n".join(urls) + "\n")
    return seed_file


def test_discover_snkrdunk_403_creates_raw_snapshot(db_session, tmp_path):
    seed_source_and_cards(db_session)

    discover_snkrdunk(
        db_session,
        max_pages=5,
        seed_file=write_seed_file(tmp_path),
        adapter=make_adapter(single_page_handler(SEARCH_PAGE_HTML, status_code=403)),
    )

    snapshots = db_session.query(RawSnapshot).all()
    assert len(snapshots) == 1
    assert snapshots[0].http_status == 403
    assert snapshots[0].raw_content == SEARCH_PAGE_HTML


def test_discover_snkrdunk_403_does_not_create_candidates(db_session, tmp_path):
    seed_source_and_cards(db_session)

    discover_snkrdunk(
        db_session,
        max_pages=5,
        seed_file=write_seed_file(tmp_path),
        adapter=make_adapter(single_page_handler(SEARCH_PAGE_HTML, status_code=403)),
    )

    assert db_session.query(SnkrdunkCandidate).count() == 0


def test_discover_snkrdunk_run_status_blocked_when_all_pages_403(db_session, tmp_path):
    seed_source_and_cards(db_session)

    summary = discover_snkrdunk(
        db_session,
        max_pages=5,
        seed_file=write_seed_file(tmp_path),
        adapter=make_adapter(single_page_handler(SEARCH_PAGE_HTML, status_code=403)),
    )

    assert summary.status == "blocked"
    assert summary.pages_fetched == 1
    assert summary.candidates_found == 0

    run = db_session.query(SnkrdunkDiscoveryRun).one()
    assert run.status == "blocked"


@pytest.mark.parametrize("status_code", [401, 403, 429])
def test_discover_snkrdunk_run_status_blocked_for_each_blocked_status_code(
    db_session, tmp_path, status_code
):
    seed_source_and_cards(db_session)

    summary = discover_snkrdunk(
        db_session,
        max_pages=5,
        seed_file=write_seed_file(tmp_path),
        adapter=make_adapter(single_page_handler(SEARCH_PAGE_HTML, status_code=status_code)),
    )

    assert summary.status == "blocked"


def test_discover_snkrdunk_logs_clear_blocked_message(db_session, tmp_path, caplog):
    seed_source_and_cards(db_session)

    with caplog.at_level("WARNING"):
        discover_snkrdunk(
            db_session,
            max_pages=5,
            seed_file=write_seed_file(tmp_path),
            adapter=make_adapter(single_page_handler(SEARCH_PAGE_HTML, status_code=403)),
        )

    expected = (
        f"SNKRDUNK blocked or refused automated access for {SEARCH_URL} "
        "with status 403. Stored raw snapshot and skipped parsing."
    )
    assert expected in caplog.text


def test_discover_snkrdunk_completed_with_warnings_when_some_pages_blocked(db_session, tmp_path):
    seed_source_and_cards(db_session)

    ok_url = "https://snkrdunk.com/trading-cards/search?category=one-piece-card-game&seed=ok"
    blocked_url = "https://snkrdunk.com/trading-cards/search?category=one-piece-card-game&seed=blocked"

    def handler(request: httpx.Request) -> httpx.Response:
        if "seed=blocked" in str(request.url):
            return httpx.Response(403, text="blocked")
        return httpx.Response(200, text=CANDIDATE_PAGE_HTML)

    summary = discover_snkrdunk(
        db_session,
        max_pages=5,
        seed_file=write_seed_file_multi(tmp_path, [ok_url, blocked_url]),
        adapter=make_adapter(handler),
    )

    assert summary.status == "completed_with_warnings"
    assert summary.pages_fetched == 2
    assert summary.candidates_found == 1
