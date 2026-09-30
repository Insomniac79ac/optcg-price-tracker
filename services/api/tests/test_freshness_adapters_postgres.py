"""Mock source transports plus disposable localhost PostgreSQL only."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select, text

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(ROOT / "services/snkrdunk_collector"),
    str(ROOT / "services/yuyutei_collector"),
    str(ROOT / "services/worker"),
]

from test_freshness_queue_postgres import (
    db,
    T0,
    mapping,
    plan,
    claim,
    admit,
    snapshot,
    observation,
)
from app.models import (
    CanonicalCard,
    CardPrint,
    FreshnessAttempt,
    FreshnessPriceState,
    FreshnessWork,
    PriceObservation,
    RawSnapshot,
    ReleaseProduct,
    Source,
    SourceCardMapping,
    SourceDispatchBudget,
)
from app.services.freshness_integration import (
    Attempt,
    CaptureResult,
    CATEGORIES,
    drain,
    price_facts,
)
from app.services.freshness_queue import (
    plan_refresh,
    plan_discovery_scope,
    complete_claim,
)
from snkrdunk_collector import collect
from snkrdunk_collector.run_lock import (
    collection_lock,
    pinned_session,
    assert_lock_owned,
    LockLost,
    COLLECTION_LOCK_KEY,
)

HTML = (
    (ROOT / "services/snkrdunk_collector/tests/fixtures/product_page_reduced.html")
    .read_text()
    .replace("ブースターパックロマンスドーン", "ブースターパック ROMANCE DAWN")
)
HISTORY = (
    ROOT / "services/snkrdunk_collector/tests/fixtures/sales_history_page_reduced.html"
).read_text()


@pytest.fixture(autouse=True)
def forbid_unmocked_browser(monkeypatch):
    def refused(*args, **kwargs):
        pytest.fail("unmocked browser forbidden: these tests are offline")

    monkeypatch.setattr(collect, "sync_playwright", refused)


def seed(factory, mid, *, high=False, bound=30):
    with factory.begin() as session:
        row = session.get(SourceCardMapping, mid)
        row.source_card_id = "OP01-001"
        card_print = session.get(CardPrint, row.card_print_id)
        card_print.treatment = "parallel"
        card_print.image_url = (
            "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png"
        )
        canonical = session.get(CanonicalCard, card_print.canonical_card_id)
        canonical.name_jp, canonical.rarity = "ロロノア・ゾロ", "L"
        release = session.get(ReleaseProduct, card_print.release_product_id)
        release.source_catalogue, release.official_code = "bandai_jp", "OP-01"
        release.display_name = release.first_seen_name = "ROMANCE DAWN"
        release.verification_status = "verified"
        session.flush()
        return plan_refresh(
            session,
            mid,
            CATEGORIES["snkrdunk"],
            high_interest=high,
            estimated_request_cost=bound,
            clock=lambda: T0,
        ).id


class Transport:
    """Runs real collector capture/classification/extraction/writer, no sockets."""

    def __init__(self, monkeypatch, html=HTML):
        self.sent = []
        self.html = html
        self.before_request = lambda: None
        self.context = MagicMock()
        self.context.route.side_effect = lambda pattern, handler: setattr(
            self, "handler", handler
        )
        self.context.request.get.side_effect = self.get
        page = self.page = MagicMock()
        page.context = self.context
        self.context.new_page.return_value = page
        page.goto.side_effect = self.goto
        page.content.side_effect = lambda: self.body
        page.title.side_effect = lambda: "Fixture"
        browser = MagicMock()
        browser.new_context.return_value = self.context
        playwright = MagicMock()
        playwright.__enter__.return_value.chromium.launch.return_value = browser
        monkeypatch.setattr(collect, "sync_playwright", lambda: playwright)
        monkeypatch.setattr(collect, "compare_artwork", lambda *args: {"match": True})

    def response(self, url):
        return SimpleNamespace(status=200, ok=True, body=lambda: b"mock artwork")

    def get(self, url, **kwargs):
        assert kwargs["max_redirects"] == kwargs["max_retries"] == 0
        self.sent.append(url)
        return self.response(url)

    def goto(self, url, **kwargs):
        self.before_request()
        self.page.url = url
        self.body = (
            HISTORY
            if "sales-histories" in url
            else self.html if "/apparels/" in url else "<html>Home</html>"
        )
        route = MagicMock()
        route.fetch.side_effect = lambda **kwargs: self.get(url, **kwargs)
        self.handler(route)
        if route.abort.called:
            raise RuntimeError("transport aborted before dispatch")
        return self.response(url)


def run(factory, source, **kwargs):
    with factory() as session:
        return drain(
            session,
            source,
            "fixture",
            collect.run_one_mapping_detailed,
            runtime_seconds=1200,
            mapping_seconds=180,
            chunk_size=2,
            delay_seconds=0,
            clock=lambda: T0,
            sleep=lambda _: None,
            **kwargs,
        )


def test_multiple_chunks_real_collector_one_capture_per_product(db, monkeypatch):
    factory, source, mid, pid = db
    ids = [mid] + [
        mapping(factory, source, pid, product) for product in range(200, 204)
    ]
    for item in ids:
        seed(factory, item)
    transport = Transport(monkeypatch)
    results = run(factory, source)
    assert len(results) == 5  # chunks of two drain all five without a calendar wait
    product_requests = [
        url
        for url in transport.sent
        if "/apparels/" in url and "sales-histories" not in url
    ]
    assert len(product_requests) == len(set(product_requests)) == 5
    with factory() as session:
        rows = session.scalars(select(PriceObservation)).all()
        assert len(rows) == 10, list(
            session.scalars(select(FreshnessWork.last_failure))
        )
        assert {r.price_type for r in rows} == {"floor", "psa10_asking"}
        for item in ids:
            pair = [r for r in rows if r.source_card_mapping_id == item]
            assert len({r.raw_snapshot_id for r in pair}) == 1
            assert {r.observed_at for r in pair} == {T0}
        assert session.scalar(select(func.count()).select_from(FreshnessAttempt)) == 5
        assert all(
            fact["expires_at"] == T0 + timedelta(hours=24)
            for result in results
            for fact in result
        )
        assert all(
            fact["next_due_at"] == T0 + timedelta(hours=23)
            for result in results
            for fact in result
        )
    assert run(factory, source) == []


@pytest.mark.parametrize("missing", ["raw", "psa10"])
def test_independent_categories_and_high_interest(db, monkeypatch, missing):
    from bs4 import BeautifulSoup

    factory, source, mid, _ = db
    work = seed(factory, mid, high=True)
    soup = BeautifulSoup(HTML, "html.parser")
    labels = {"A", "B"} if missing == "raw" else {"PSA10"}
    for label in labels:
        chip = next(
            p for p in soup.find_all("p") if p.get_text(strip=True) == label
        ).parent
        chip.find("p", class_="css3__price").replace_with(
            BeautifulSoup('<p class="css3__awaiting">出品待ち</p>', "html.parser")
        )
    Transport(monkeypatch, str(soup))
    results = run(factory, source)
    assert len(results) == 1
    with factory() as session:
        facts = {r["category"]: r for r in price_facts(session, work, clock=lambda: T0)}
        assert facts[missing]["captured_at"] is None
        assert facts[missing]["category_outcome"] == "no_listing"
        other = "psa10" if missing == "raw" else "raw"
        assert facts[other]["captured_at"] == T0
        assert facts[other]["expires_at"] == T0 + timedelta(hours=4)
        assert {r["next_due_at"] for r in facts.values()} == {T0 + timedelta(hours=3)}


def test_partial_absence_keeps_deadline_and_does_not_recapture_in_same_run(
    db, monkeypatch
):
    from bs4 import BeautifulSoup

    factory, source, mid, _ = db
    work = seed(factory, mid)
    soup = BeautifulSoup(HTML, "html.parser")
    next(
        p for p in soup.find_all("p") if p.get_text(strip=True) == "PSA10"
    ).parent.decompose()
    Transport(monkeypatch, str(soup))
    assert len(run(factory, source)) == 1
    with factory() as session:
        row = session.get(FreshnessWork, work)
        assert row.next_due_at == T0
        assert row.retry_not_before_at == T0 + timedelta(minutes=15)
        assert (
            session.scalar(select(FreshnessAttempt.category_outcomes))["psa10"]
            == "absent"
        )


def test_request_pause_after_claim_blocks_helper_and_rolls_back_prices(db, monkeypatch):
    factory, source, mid, _ = db
    seed(factory, mid)
    transport = Transport(monkeypatch)

    def pause_after_home():
        if transport.sent:
            with factory.begin() as session:
                session.scalar(select(SourceDispatchBudget)).pause_reason = (
                    "operator_pause"
                )

    transport.before_request = pause_after_home
    assert len(run(factory, source)) == 1
    assert transport.sent == [collect.HOMEPAGE_URL]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0
        assert (
            session.scalar(select(FreshnessPriceState.last_valid_price_observed_at))
            is None
        )
        assert session.scalar(select(FreshnessAttempt.outcome)) == "transient_failure"


def test_budget_exhaustion_during_helper_traffic_never_bypasses_admission(
    db, monkeypatch
):
    factory, source, mid, _ = db
    seed(factory, mid, bound=2)
    transport = Transport(monkeypatch)
    run(factory, source)
    assert len(transport.sent) == 2
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0
        assert session.scalar(select(FreshnessAttempt.actual_request_cost)) == 2


def test_result_lease_expiry_rolls_back_domain_write(db):
    factory, source, mid, _ = db
    seed(factory, mid)
    picked = claim(factory, source)[0]
    with factory() as session:
        attempt = Attempt(session, picked, clock=lambda: T0)
        attempt.admit()
        raw = attempt.snapshot(
            source,
            "https://snkrdunk.com/apparels/123",
            {"html": "fixture", "http_status": 200},
            "test",
        )
        attempt.begin_result()
        row = session.get(SourceCardMapping, mid)
        obs = PriceObservation(
            source_id=source,
            source_card_mapping_id=mid,
            card_print_id=row.card_print_id,
            raw_snapshot_id=raw,
            price_type="floor",
            condition_label="A",
            price_jpy=10000,
            observed_at=T0,
        )
        session.add(obs)
        session.flush()
        attempt.clock = lambda: picked.expires_at
        with pytest.raises(ValueError, match="ownership"):
            attempt.finish(
                CaptureResult(
                    "captured", raw_snapshot_id=raw, observation_ids={"raw": obs.id}
                )
            )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0
        assert session.get(RawSnapshot, raw) is not None  # durable evidence survives


def test_singleton_contention_and_loss(db):
    from snkrdunk_collector.due import run_due

    factory, source, mid, _ = db
    seed(factory, mid)
    with collection_lock(factory.kw["bind"]) as lock:
        assert lock.acquired
        assert run_due(session_factory=factory) == []
        with pinned_session(lock, factory) as session:
            session.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": COLLECTION_LOCK_KEY}
            )
            session.commit()
            with pytest.raises(LockLost):
                drain(
                    session,
                    source,
                    "lost",
                    lambda *a, **k: pytest.fail("must not collect"),
                    runtime_seconds=1200,
                    mapping_seconds=180,
                    ownership_check=assert_lock_owned,
                )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(FreshnessAttempt)) == 0


def test_discovery_lane_yields_without_changing_checkpoint(db):
    factory, source, mid, _ = db
    with factory.begin() as session:
        work = plan_discovery_scope(session, source, "existing-checkpoint", due_at=T0)
        work.resume_cursor = {"version": 1, "discovery_run_id": 456}
        session.scalar(select(SourceDispatchBudget)).claim_sequence = (
            3  # discovery's turn
        )
    seed(factory, mid)
    assert run(factory, source) == []
    with factory() as session:
        assert session.scalar(
            select(FreshnessWork.resume_cursor).where(FreshnessWork.kind == "discovery")
        ) == {"version": 1, "discovery_run_id": 456}
        assert session.scalar(select(SourceDispatchBudget.claim_sequence)) == 3


def test_raw_valuation_input_and_snapshot_selection_exclude_psa10(db, monkeypatch):
    from app.services.print_market_index import get_market_index_for_print
    from app.snapshot_market_index import select_snapshottable_print_ids

    factory, source, mid, pid = db
    seed(factory, mid)
    Transport(monkeypatch)
    run(factory, source)
    with factory.begin() as session:
        before = get_market_index_for_print(session, pid).model_dump(
            exclude={"calculated_at"}
        )
        assert before["index_value_jpy"] == 24500
        psa = session.scalar(
            select(PriceObservation).where(
                PriceObservation.price_type == "psa10_asking"
            )
        )
        psa.price_jpy = 99999999
        session.flush()
        assert (
            get_market_index_for_print(session, pid).model_dump(
                exclude={"calculated_at"}
            )
            == before
        )
        raw = session.scalar(
            select(PriceObservation).where(PriceObservation.price_type == "floor")
        )
        session.delete(raw)
        session.flush()
        assert get_market_index_for_print(session, pid).index_value_jpy is None
        assert pid not in select_snapshottable_print_ids(session)
        # Market Value and CPI replay read these raw MarketIndexSnapshot inputs,
        # not arbitrary current-price observations. No eligible input is added.


def test_request_costs_shared_with_discovery_and_validation_transports(db):
    import httpx
    from app.services.freshness_queue import plan_validation
    from worker.adapters.snkrdunk_discovery import SnkrdunkDiscoveryAdapter

    factory, source, _, _ = db
    with factory.begin() as session:
        plan_validation(session, source, "check", due_at=T0, estimated_request_cost=2)
    picked = claim(factory, source)[0]
    sent = []

    def transport(request):
        sent.append(str(request.url))
        return httpx.Response(429, text="denied")

    with factory() as session, httpx.Client(
        transport=httpx.MockTransport(transport)
    ) as client:
        attempt = Attempt(session, picked, clock=lambda: T0)
        adapter = SnkrdunkDiscoveryAdapter(
            client=client, request_delay_ms=0, admission=attempt
        )
        response = adapter.fetch_page("https://snkrdunk.com/search")
        assert response.http_status == 429
        with pytest.raises(Exception, match="source_denial"):
            adapter.fetch_page("https://snkrdunk.com/search?page=2")
    assert len(sent) == 1
    with factory() as session:
        assert (
            session.scalar(select(SourceDispatchBudget.pause_reason)) == "source_denial"
        )


def test_category_outcomes_backup_roundtrip_and_v16_compatibility(db):
    from app.services.backup import export_backup, validate_backup
    from app.services.freshness_backup import prepare_restore

    factory, source, mid, _ = db
    seed(factory, mid)
    picked = claim(factory, source)[0]
    with factory() as session:
        attempt = Attempt(session, picked, clock=lambda: T0)
        attempt.admit()
        attempt.begin_result()
        attempt.finish(
            CaptureResult(
                "transient_failure",
                category_outcomes={"raw": "absent", "psa10": "parsing_failure"},
            )
        )
        archive = export_backup(
            session, include_prices=True, include_raw_snapshots=True
        )
    assert archive["metadata"]["backup_version"] == 17
    assert validate_backup(archive).valid
    outcomes = archive["tables"]["freshness_attempts"][0]["category_outcomes"]
    assert outcomes == {"raw": "absent", "psa10": "parsing_failure"}
    restored, _ = prepare_restore(archive["tables"], T0)
    assert restored["freshness_attempts"][0]["category_outcomes"] == outcomes
    archive["metadata"]["backup_version"] = 16
    del archive["tables"]["freshness_attempts"][0]["category_outcomes"]
    assert validate_backup(archive).valid


@pytest.mark.parametrize("high,hours", [(False, 24), (True, 4)])
def test_yuyu_nine_shards_use_identical_category_policy(db, high, hours):
    from yuyutei_collector.due import write_capture
    from yuyutei_collector.models import SourceCardMapping as YuyuMapping

    factory, source, mid, pid = db
    ids = [mid] + [
        mapping(factory, source, pid, product) for product in range(200, 209)
    ]
    with factory.begin() as session:
        session.get(Source, source).name = "yuyutei"
        for item in ids:
            row = session.get(SourceCardMapping, item)
            row.source_url = f"https://yuyu-tei.jp/sell/opc/card/op01/{10000 + item}"
            row.source_card_id = "OP01-001"
        session.flush()
        for item in ids:
            plan_refresh(
                session,
                item,
                CATEGORIES["yuyutei"],
                high_interest=high,
                clock=lambda: T0,
            )
    seen = []

    def runner(session, mapping_id, *, freshness):
        assert mapping_id % 9 == shard
        seen.append(mapping_id)
        freshness.admit()
        row = session.get(YuyuMapping, mapping_id)
        raw = freshness.snapshot(
            source, row.source_url, {"html": "fixture", "http_status": 200}, "test"
        )
        freshness.begin_result()
        freshness.result = write_capture(
            session,
            row,
            {
                "classification": "normal_product",
                "raw_snapshot_id": raw,
                "extraction": {
                    "extraction_status": "extracted",
                    "extracted": {"card_code": "OP01-001", "sell_price_jpy": 10000},
                },
            },
        )
        return SimpleNamespace(source_denied=False, stage="captured", reasons=[])

    for shard in range(9):
        with factory() as session:
            drain(
                session,
                source,
                f"shard-{shard}",
                runner,
                runtime_seconds=100,
                mapping_seconds=1,
                shard_index=shard,
                chunk_size=1,
                delay_seconds=0,
                clock=lambda: T0,
                sleep=lambda _: None,
            )
    assert sorted(seen) == ids
    with factory() as session:
        for state in session.scalars(select(FreshnessPriceState)):
            facts = price_facts(session, state.work_id, clock=lambda: T0)[0]
            assert facts["expires_at"] == T0 + timedelta(hours=hours)
            assert facts["next_due_at"] == T0 + timedelta(hours=hours - 1)


def test_result_replay_cannot_publish_a_second_price(db):
    factory, source, mid, _ = db
    seed(factory, mid)
    picked = claim(factory, source)[0]
    with factory() as session:
        attempt = Attempt(session, picked, clock=lambda: T0)
        attempt.admit()
        raw = attempt.snapshot(
            source,
            "https://snkrdunk.com/apparels/123",
            {"html": "fixture", "http_status": 200},
            "test",
        )
        attempt.begin_result()
        result = CaptureResult(
            "no_listing", raw_snapshot_id=raw, no_listing_categories={"raw", "psa10"}
        )
        assert attempt.finish(result)
        with pytest.raises(Exception, match="already completed"):
            attempt.begin_result()
        assert not attempt.finish(result)
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0


def test_browser_subresources_redirects_and_denials_are_admitted(db):
    factory, source, mid, _ = db
    seed(factory, mid, bound=3)
    picked = claim(factory, source)[0]
    with factory() as session:
        attempt = Attempt(session, picked, clock=lambda: T0)
        context = MagicMock()
        attempt.install_browser(context)
        handler = context.route.call_args.args[1]
        first = MagicMock()
        first.fetch.return_value.status = 200
        handler(first)  # helper page or image subresource
        first.fulfill.assert_called_once()
        redirect = MagicMock()
        redirect.fetch.return_value.status = 302
        handler(redirect)
        redirect.abort.assert_called_once()
        redirect.fulfill.assert_not_called()  # browser cannot follow unmetered
        later = MagicMock()
        handler(later)
        later.fetch.assert_not_called()
        assert attempt.charged_cost == 2


def test_capacity_shortage_leaves_overdue_tail_visible(db, monkeypatch):
    factory, source, mid, pid = db
    seed(factory, mid, bound=5)
    tail = mapping(factory, source, pid, 200)
    tail_work = seed(factory, tail, bound=5)
    with factory.begin() as session:
        session.scalar(select(SourceDispatchBudget)).request_limit = 5
    Transport(monkeypatch)
    assert len(run(factory, source)) == 1
    with factory() as session:
        work = session.get(FreshnessWork, tail_work)
        assert work.state == "pending" and work.next_due_at == T0
        assert work.attempt_count == 0  # no invented freshness or dropped tail


def test_bounded_runtime_resumes_tail_on_next_invocation(db, monkeypatch):
    factory, source, mid, pid = db
    ids = [mid] + [mapping(factory, source, pid, p) for p in (200, 201)]
    for item in ids:
        seed(factory, item)
    transport = Transport(monkeypatch)
    elapsed = [0]

    def runner(*args, **kwargs):
        result = collect.run_one_mapping_detailed(*args, **kwargs)
        elapsed[0] += 300
        return result

    with factory() as session:
        result = drain(
            session,
            source,
            "bounded",
            runner,
            runtime_seconds=500,
            mapping_seconds=180,
            chunk_size=1,
            delay_seconds=0,
            clock=lambda: T0,
            monotonic=lambda: elapsed[0],
            sleep=lambda _: None,
        )
    assert len(result) == 2
    assert len(run(factory, source)) == 1
    product_urls = [
        u for u in transport.sent if "/apparels/" in u and "sales-histories" not in u
    ]
    assert len(product_urls) == len(set(product_urls)) == 3


def test_shared_planner_coalesces_categories_and_rejects_wrong_source(db):
    from app.services.freshness_integration import plan_product

    factory, source, mid, _ = db
    with factory.begin() as session:
        first = plan_product(
            session, mid, "snkrdunk", high_interest=False, request_bound=30
        )
        second = plan_product(
            session, mid, "snkrdunk", high_interest=True, request_bound=30
        )
        assert first.id == second.id
        assert session.scalar(select(func.count()).select_from(FreshnessWork)) == 1
        assert (
            session.scalar(select(func.count()).select_from(FreshnessPriceState)) == 2
        )
        with pytest.raises(ValueError, match="requested source"):
            plan_product(session, mid, "yuyutei", high_interest=False, request_bound=30)
