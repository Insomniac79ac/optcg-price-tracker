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
from freshness_offline import offline_only

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


def test_explicit_artwork_capture_settles_without_price_or_mapping_decision(
    db, monkeypatch
):
    import io
    from PIL import Image
    from app.models import YuyuteiCandidate, YuyuteiDiscoveryRun
    from app.services.source_mapping_proposals import resolve_current_candidate_proposal
    from app.services.freshness_queue import claim_due
    from yuyutei_collector.identity_evidence import load_intent, capture_pages

    factory, _, _, pid = db
    with factory.begin() as session:
        base = session.get(CardPrint, pid)
        release = session.get(ReleaseProduct, base.release_product_id)
        release.source_catalogue, release.official_code, release.verification_status = (
            "bandai_jp",
            "OP-01",
            "verified",
        )
        base.image_url = (
            "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001.png"
        )
        sibling = CardPrint(
            canonical_card_id=base.canonical_card_id,
            release_product_id=release.id,
            language="jp",
            is_active=True,
            verification_status="verified",
            official_asset_variant="p2",
            artwork_key="fixture-parallel",
            image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png",
        )
        source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
        run = YuyuteiDiscoveryRun(
            status="completed",
            requested_set_slugs=["op01"],
            per_slug_metrics_json={"op01": {"enumeration_complete": True}},
        )
        session.add_all([sibling, source, run])
        session.flush()
        candidate = YuyuteiCandidate(
            discovery_run_id=run.id,
            set_slug="op01",
            product_id="10002",
            source_url="https://yuyu-tei.jp/sell/opc/card/op01/10002",
            detected_card_code="OP01-001",
            name_jp="ロロノア・ゾロ(パラレル)",
            match_status="family_matched",
        )
        session.add(candidate)
        session.flush()
        session.add(
            SourceDispatchBudget(
                source_id=source.id,
                enabled=True,
                request_limit=100,
                window_seconds=1800,
                window_started_at=T0,
            )
        )
        current = resolve_current_candidate_proposal(
            session, source_name="yuyutei", candidate_id=candidate.id
        )
        assert current.resolution_status == "ambiguous"
        work = plan_discovery_scope(
            session,
            source.id,
            f"yuyu-identity:{candidate.id}",
            due_at=T0,
            estimated_request_cost=100,
        )
        work.resume_cursor = {
            "version": 1,
            "candidate_id": candidate.id,
            "explicit_identity_capture": True,
            "evidence_digest": current.evidence_digest,
            "release_product_id": release.id,
            "considered_print_ids": sorted([base.id, sibling.id]),
        }
        source_id = source.id
    img = io.BytesIO()
    Image.new("RGB", (40, 56), "red").save(img, format="PNG")
    page = SimpleNamespace(
        context=SimpleNamespace(
            request=SimpleNamespace(
                get=lambda *args, **kw: SimpleNamespace(
                    status=200, ok=True, body=lambda: img.getvalue()
                )
            )
        )
    )
    product_html = (
        ROOT / "services/yuyutei_collector/tests/fixtures/product_op01_001_reduced.html"
    ).read_text()
    with factory() as session:
        granted = claim_due(
            session,
            source_id,
            "fixture-artwork",
            limit=1,
            lease=timedelta(minutes=4),
            clock=lambda: T0,
            supported_kinds={"discovery"},
        )[0]
        session.commit()
        attempt = Attempt(session, granted, clock=lambda: T0)
        candidate, current, prints, urls = load_intent(session, granted)

        def navigation(page, url):
            attempt.admit()
            return {"html": product_html, "http_status": 200, "final_url": url}

        monkeypatch.setattr(
            "yuyutei_collector.identity_evidence.goto_and_capture_raw", navigation
        )
        monkeypatch.setattr(
            "yuyutei_collector.identity_evidence.classify_capture",
            lambda *args: {"classification": "normal_product", "http_status": 200},
        )
        monkeypatch.setattr(
            "yuyutei_collector.identity_evidence.time.sleep", lambda _: None
        )
        capture_pages(session, granted, attempt, page, candidate, current, prints, urls)
        assert attempt.finish(attempt.result)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceCardMapping)
                .where(SourceCardMapping.source_id == source_id)
            )
            == 0
        )
        retained = session.scalar(
            select(FreshnessWork).where(FreshnessWork.source_id == source_id)
        )
        assert retained.resume_cursor["identity_status"].startswith("unresolved")
        assert (
            retained.last_successfully_checked_at == T0
        )  # discovery scope only, never RAW state
        budget = session.scalar(
            select(SourceDispatchBudget).where(
                SourceDispatchBudget.source_id == source_id
            )
        )
        assert budget.used_requests == 5 and budget.reserved_requests == 0
        assert (
            session.scalar(select(func.count()).select_from(FreshnessPriceState)) == 0
        )
        assert session.scalar(select(func.count()).select_from(RawSnapshot)) == 5
        assert (
            claim_due(
                session,
                source_id,
                "fixture-replay",
                limit=1,
                lease=timedelta(minutes=4),
                clock=lambda: T0,
                supported_kinds={"discovery"},
            )
            == []
        )


def browser_request(
    url="https://snkrdunk.com/apparels/123", *, main=True, iframe=False
):
    frame = SimpleNamespace()
    frame.page = SimpleNamespace(main_frame=frame if main else object())
    return SimpleNamespace(
        url=url,
        method="GET",
        headers={},
        frame=frame,
        resource_type="document" if main or iframe else "script",
        is_navigation_request=lambda: main or iframe,
    )


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
        route.request = browser_request(url)
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
            clock=kwargs.pop("clock", lambda: T0),
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
        assert row.retry_not_before_at == T0 + timedelta(hours=23)
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
    from datetime import datetime
    from app.services import print_market_index
    from app.services.print_market_index import get_market_index_for_print
    from app.snapshot_market_index import select_snapshottable_print_ids

    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = T0 + timedelta(minutes=1)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    # Collection uses T0. Keep valuation in that same fixture window so this
    # RAW-versus-PSA10 test does not expire as the wall clock advances.
    monkeypatch.setattr(print_market_index, "datetime", FixtureClock)
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
        raw_id = attempt.snapshot(
            source,
            "https://snkrdunk.com/apparels/123",
            {"html": "fixture", "http_status": 200},
            "fixture",
        )
        attempt.begin_result()
        attempt.finish(
            CaptureResult(
                "transient_failure",
                raw_snapshot_id=raw_id,
                category_outcomes={"raw": "absent", "psa10": "parsing_failure"},
            )
        )
        archive = export_backup(
            session, include_prices=True, include_raw_snapshots=True
        )
    assert archive["metadata"]["backup_version"] == 19
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
        first.request = browser_request(main=False)
        first.fetch.return_value.status = 200
        handler(first)  # helper page or image subresource
        first.fulfill.assert_called_once()
        redirect = MagicMock()
        redirect.request = browser_request()
        redirect.fetch.return_value.status = 302
        handler(redirect)
        redirect.abort.assert_called_once()
        redirect.fulfill.assert_not_called()  # browser cannot follow unmetered
        later = MagicMock()
        later.request = browser_request()
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


@pytest.mark.parametrize("missing", ["raw", "psa10"])
@pytest.mark.parametrize("malformed", [False, True])
def test_real_adapter_retries_over_48_simulated_hours(
    db, monkeypatch, missing, malformed
):
    from bs4 import BeautifulSoup

    factory, source, mid, _ = db
    work = seed(factory, mid)
    soup = BeautifulSoup(HTML, "html.parser")
    labels = {"PSA10"} if missing == "psa10" else {"A", "B", "C", "D"}
    for label in labels:
        chip = next(
            p for p in soup.find_all("p") if p.get_text(strip=True) == label
        ).parent
        if malformed:
            for p in list(chip.find_all("p"))[1:]:
                p.decompose()
            chip.append(BeautifulSoup('<p class="c__price">要確認</p>', "html.parser"))
        else:
            chip.decompose()
    transport = Transport(monkeypatch, str(soup))
    times = []
    for tick in range(193):
        at = T0 + timedelta(minutes=15 * tick)
        results = run(factory, source, clock=lambda: at)
        assert len(results) <= 1
        if results:
            times.append(tick / 4)
    assert times == (
        [0, 0.25, 0.75, 1.75, 3.75, 7.75, 15.75, 31.75] if malformed else [0, 23, 46]
    )
    # Exactly one product navigation per capture; home/artwork/history remain
    # separately admitted by the existing mock transport integration.
    products = [
        url
        for url in transport.sent
        if url.rstrip("/") == "https://snkrdunk.com/apparels/123"
    ]
    assert len(products) == len(times)
    with factory() as session:
        facts = {
            r["category"]: r
            for r in price_facts(session, work, clock=lambda: T0 + timedelta(hours=48))
        }
        assert facts[missing]["captured_at"] is None
        assert facts[missing]["checked_at"] is None
        assert facts[missing]["next_due_at"] == T0
        assert facts[missing]["availability"] == "unknown"
        assert facts[missing]["category_outcome"] == (
            "parsing_failure" if malformed else "absent"
        )
        assert facts[missing]["consecutive_failures"] == (8 if malformed else 0)


def test_missing_picker_is_parsing_failure_for_both_categories(db, monkeypatch):
    from bs4 import BeautifulSoup

    factory, source, mid, _ = db
    work = seed(factory, mid)
    soup = BeautifulSoup(HTML, "html.parser")
    next(
        p for p in soup.find_all("p") if p.get_text(strip=True) == "PSA10"
    ).parent.parent.decompose()
    Transport(monkeypatch, str(soup))
    assert len(run(factory, source)) == 1
    with factory() as session:
        facts = price_facts(session, work, clock=lambda: T0)
        assert {r["category_outcome"] for r in facts} == {"parsing_failure"}
        assert {r["availability"] for r in facts} == {"unknown"}
        assert {r["captured_at"] for r in facts} == {None}
        assert {r["consecutive_failures"] for r in facts} == {1}


@pytest.mark.parametrize("status", [200, 429])
def test_asset_redirect_hops_are_metered_and_cross_origin_secrets_removed(db, status):
    factory, source, mid, _ = db
    seed(factory, mid, bound=5)
    picked = claim(factory, source)[0]
    with factory() as session:
        attempt = Attempt(session, picked, clock=lambda: T0)
        context = MagicMock()
        attempt.install_browser(context)
        handler = context.route.call_args.args[1]
        route = MagicMock()
        route.request = SimpleNamespace(
            url="https://snkrdunk.com/asset",
            method="GET",
            headers={
                "cookie": "source-only",
                "authorization": "source-only",
                "accept": "image/*",
            },
            is_navigation_request=lambda: False,
            resource_type="script",
        )
        route.fetch.side_effect = [
            SimpleNamespace(
                status=302, headers={"location": "https://cdn.example.test/asset"}
            ),
            SimpleNamespace(status=status),
        ]
        handler(route)
        assert attempt.charged_cost == 2
        assert route.fetch.call_args.kwargs["url"] == "https://cdn.example.test/asset"
        assert route.fetch.call_args.kwargs["headers"] == {"accept": "image/*"}
        assert route.fetch.call_args.kwargs["max_redirects"] == 0
        assert not attempt.denied
        assert session.scalar(select(SourceDispatchBudget.pause_reason)) is None
        assert attempt.health["optional_resource"] == int(status == 429)


def test_optional_asset_transport_failure_does_not_poison_product(db):
    factory, source, mid, _ = db
    seed(factory, mid, bound=5)
    picked = claim(factory, source)[0]
    with factory() as session:
        attempt = Attempt(session, picked, clock=lambda: T0)
        context = MagicMock()
        attempt.install_browser(context)
        handler = context.route.call_args.args[1]
        asset = MagicMock()
        asset.request = browser_request(main=False)
        asset.fetch.side_effect = RuntimeError("connection reset")
        handler(asset)
        assert attempt.stopped is None
        product = MagicMock()
        product.request = browser_request()
        product.fetch.return_value.status = 200
        handler(product)
        product.fulfill.assert_called_once()
        assert attempt.charged_cost == 2


@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://snkrdunk.com/v1/accounts/me", "fetch"),
        ("https://bbc.bibian.co.jp/js/bbc_v1.js", "script"),
        ("https://cdn.snkrdunk.com/large-presentation-image.png", "image"),
        ("https://yuyu-tei.jp/presentation.woff2", "font"),
        ("https://yuyu-tei.jp/presentation.mp4", "media"),
    ],
)
def test_non_evidence_browser_requests_are_not_dispatched_or_charged(db, url, kind):
    factory, source, mid, _ = db
    seed(factory, mid, bound=5)
    picked = claim(factory, source)[0]
    with factory() as session:
        attempt = Attempt(session, picked, clock=lambda: T0)
        context = MagicMock()
        attempt.install_browser(context)
        route = MagicMock()
        route.request = browser_request(url, main=False)
        route.request.resource_type = kind
        context.route.call_args.args[1](route)
        route.abort.assert_called_once()
        route.fetch.assert_not_called()
        assert attempt.charged_cost == 0
        assert attempt.stopped is None
        assert not attempt.denied
        assert session.scalar(select(SourceDispatchBudget.pause_reason)) is None


@pytest.mark.parametrize(
    "url,kind,main",
    [
        ("https://snkrdunk.com/apparels/123", "document", True),
        ("https://snkrdunk.com/v1/products/123", "fetch", False),
        ("https://snkrdunk.com/v1/accounts/me", "document", True),
        ("https://yuyu-tei.jp/sell/opc/card/op01/10001", "document", True),
    ],
)
def test_required_source_denials_still_pause(db, url, kind, main):
    factory, source, mid, _ = db
    seed(factory, mid, bound=5)
    picked = claim(factory, source)[0]
    with factory() as session:
        attempt = Attempt(session, picked, clock=lambda: T0)
        context = MagicMock()
        attempt.install_browser(context)
        route = MagicMock()
        route.request = browser_request(url, main=main)
        route.request.resource_type = kind
        route.fetch.return_value.status = 403
        context.route.call_args.args[1](route)
        assert attempt.charged_cost == 1
        assert attempt.denied
        assert (
            session.scalar(select(SourceDispatchBudget.pause_reason)) == "source_denial"
        )


def test_isolated_admission_failure_continues_with_other_products(db):
    from app.services.freshness_integration import AdmissionStopped

    factory, source, mid, pid = db
    seed(factory, mid)
    second = mapping(factory, source, pid, 200)
    seed(factory, second)

    def runner(session, mapping_id, *, freshness):
        freshness.admit()
        if mapping_id == mid:
            freshness.stopped = "unsupported browser redirect"
            raise AdmissionStopped(freshness.stopped)
        rid = freshness.snapshot(
            source,
            "https://snkrdunk.com/apparels/200",
            {"http_status": 200, "html": "mock verified no listing"},
            "fixture",
        )
        freshness.result = CaptureResult(
            "no_listing", raw_snapshot_id=rid, no_listing_categories={"raw", "psa10"}
        )
        return SimpleNamespace(
            source_denied=False, stage="floor_unavailable", reasons=[]
        )

    with factory() as session:
        assert (
            len(
                drain(
                    session,
                    source,
                    "fixture",
                    runner,
                    runtime_seconds=60,
                    mapping_seconds=10,
                    max_work=2,
                    clock=lambda: T0,
                    sleep=lambda _: None,
                )
            )
            == 2
        )
        assert session.scalars(
            select(FreshnessAttempt.outcome).order_by(FreshnessAttempt.id)
        ).all() == ["transient_failure", "no_listing"]


def test_yuyu_small_turns_leave_budget_for_all_nine_shards(db, monkeypatch):
    from opcg_source_identity import canonical_source_listing_identity
    from app.services.freshness_queue import PriceCategory
    from yuyutei_collector.due import run_due
    from yuyutei_collector.config import settings as yuyu_settings

    factory, source, mid, print_id = db
    mids = [mid] + [mapping(factory, source, print_id, n) for n in range(124, 150)]
    with factory.begin() as session:
        session.get(Source, source).name = "yuyutei"
        budget = session.scalar(select(SourceDispatchBudget))
        budget.request_limit = 2300
        for mapping_id in mids:
            row = session.get(SourceCardMapping, mapping_id)
            row.source_url = f"https://yuyu-tei.jp/sell/opc/card/op01/{10000 + mapping_id}"
            row.canonical_source_listing_identity = canonical_source_listing_identity("yuyutei", row.source_url)
            session.flush()
            plan_refresh(session, mapping_id, {"raw": PriceCategory("sell")},
                         high_interest=False, estimated_request_cost=300, clock=lambda: T0)
    monkeypatch.setattr(yuyu_settings, "DUE_MAX_PRODUCTS_PER_RUN", 2)
    monkeypatch.setattr(yuyu_settings, "YUYUTEI_REQUEST_DELAY_MS", 0)
    visited = []

    def runner(session, mapping_id, *, freshness):
        freshness.admit(cost=110)  # Mock transport charge, no source network.
        visited.append(mapping_id)
        freshness.result = CaptureResult("identity_refusal", failure="fixture refusal")
        return SimpleNamespace(source_denied=False, stage="validation_failed", reasons=[])

    for shard in range(9):
        previous = len(visited)
        result = run_due(shard_index=shard, chunk_size=1, session_factory=factory, runner=runner)
        assert len(result) == 2
        assert all(mapping_id % 9 == shard for mapping_id in visited[previous:])
    assert len(visited) == len(set(visited)) == 18
    with factory() as session:
        budget = session.scalar(select(SourceDispatchBudget))
        assert budget.used_requests == 1980
        assert budget.reserved_requests == 0
        pending = list(session.scalars(select(FreshnessWork).where(FreshnessWork.state == "pending")))
        assert len(pending) == 9
        assert all(w.attempt_count == 0 and w.claim_token is None for w in pending)


def test_recurring_yuyu_discovery_consumes_shared_lane_atomically(db):
    from yuyutei_collector.due_discovery import persist_enumeration
    from yuyutei_collector.discovery import SlugEnumeration
    from app.models import YuyuteiDiscoveryRun

    factory, source, _, _ = db
    with factory.begin() as session:
        session.get(Source, source).name = "yuyutei"
        work = plan_discovery_scope(
            session, source, "yuyu-category:op01", due_at=T0, estimated_request_cost=10
        )
        wid = work.id
        session.scalar(select(SourceDispatchBudget)).claim_sequence = 3

    def discovery(session, claim, *, freshness):
        freshness.admit()
        rid = freshness.snapshot(
            source,
            "https://yuyu-tei.jp/sell/opc/s/op01",
            {"http_status": 200, "html": "<html>mock listing</html>"},
            "fixture",
        )
        enumeration = SlugEnumeration(slug="op01")
        enumeration.advertised_scopes = {
            "promo-100": "https://yuyu-tei.jp/sell/opc/s/search?vers%5B%5D=promo-100"
        }
        return persist_enumeration(session, claim, freshness, enumeration, rid)

    with factory() as session:
        result = drain(
            session,
            source,
            "yuyu-test-8",
            lambda *a, **k: pytest.fail("refresh called"),
            discovery_runner=discovery,
            shard_index=8,
            runtime_seconds=60,
            mapping_seconds=10,
            max_work=1,
            clock=lambda: T0,
            sleep=lambda _: None,
        )
        assert len(result) == 1
    with factory() as session:
        work = session.get(FreshnessWork, wid)
        assert work.next_due_at == T0 + timedelta(hours=24)
        assert work.state == "pending"
        assert work.resume_cursor["discovery_run_id"] == session.scalar(
            select(YuyuteiDiscoveryRun.id)
        )
        assert session.scalar(select(FreshnessAttempt.outcome)) == "completed"
        assert (
            session.scalar(select(func.count()).select_from(FreshnessPriceState)) == 0
        )
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0
        promo = session.scalar(select(FreshnessWork).where(
            FreshnessWork.scope_key == "yuyu-category:promo-100"))
        assert promo.state == "pending" and promo.attempt_count == 0
        assert promo.resume_cursor["advertised_snapshot_id"] == session.scalar(select(RawSnapshot.id))
        assert promo.resume_cursor["discovery_url"].endswith("=promo-100")


def test_measured_yuyu_turns_fit_all_nine_shards_without_changing_budget(db, monkeypatch):
    from opcg_source_identity import canonical_source_listing_identity
    from app.services.freshness_queue import PriceCategory
    from yuyutei_collector.due import run_due
    from yuyutei_collector.config import settings as yuyu_settings
    factory, source, mid, print_id = db
    mids = [mid] + [mapping(factory, source, print_id, n) for n in range(124, 303)]
    with factory.begin() as session:
        session.get(Source, source).name = "yuyutei"
        session.scalar(select(SourceDispatchBudget)).request_limit = 9000
        for mapping_id in mids:
            row = session.get(SourceCardMapping, mapping_id)
            row.source_url = f"https://yuyu-tei.jp/sell/opc/card/op01/{10000+mapping_id}"
            row.canonical_source_listing_identity = canonical_source_listing_identity("yuyutei", row.source_url)
            session.flush()
            plan_refresh(session, mapping_id, {"raw": PriceCategory("sell")},
                high_interest=False, estimated_request_cost=300, clock=lambda: T0)
    monkeypatch.setattr(yuyu_settings, "YUYUTEI_REQUEST_DELAY_MS", 0)
    monkeypatch.setattr(yuyu_settings, "DUE_MAX_PRODUCTS_PER_RUN", 16)
    visited = []
    def runner(session, mapping_id, *, freshness):
        freshness.admit(cost=60)  # conservative bound above natural <=56 measurement
        visited.append(mapping_id)
        freshness.result = CaptureResult("transient_failure", failure="fixture parsing failure")
        return SimpleNamespace(source_denied=False, stage="operational_error", reasons=[])
    for shard in range(9):
        before = len(visited)
        assert len(run_due(shard_index=shard, session_factory=factory, runner=runner)) == 16
        assert all(mapping_id % 9 == shard for mapping_id in visited[before:])
    assert len(visited) == len(set(visited)) == 144
    with factory() as session:
        budget = session.scalar(select(SourceDispatchBudget))
        assert budget.used_requests == 8640 and budget.reserved_requests == 0
        assert budget.request_limit == 9000 and budget.pause_reason is None
        assert session.scalar(select(func.count()).select_from(FreshnessWork).where(FreshnessWork.state == "claimed")) == 0


def test_listing_snapshot_precedes_parse_and_denial(monkeypatch):
    from yuyutei_collector.discovery_probe import _scrape_listing, SourceDenied

    events = []
    page = MagicMock()
    page.goto.return_value.status = 200
    page.content.return_value = "<html>source evidence</html>"
    page.eval_on_selector_all.side_effect = lambda *args: events.append("parse") or []
    sink = lambda url, step: events.append(
        ("snapshot", step["http_status"], step["html"])
    )
    _scrape_listing(page, "https://yuyu-tei.jp/sell/opc/s/op01", 10, evidence_sink=sink)
    assert events[0] == ("snapshot", 200, "<html>source evidence</html>")
    assert events[1] == "parse"
    events.clear()
    page.goto.return_value.status = 403
    with pytest.raises(SourceDenied):
        _scrape_listing(
            page, "https://yuyu-tei.jp/sell/opc/s/op01", 10, evidence_sink=sink
        )
    assert events == [("snapshot", 403, "<html>source evidence</html>")]


def test_disappeared_discovery_category_is_bounded_failure(monkeypatch):
    from yuyutei_collector import due_discovery as discovery

    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        scope_key="yuyu-category:st16", source_id=1, resume_cursor=None
    )
    browser = MagicMock()
    monkeypatch.setattr(discovery, "sync_playwright", MagicMock(return_value=browser))
    monkeypatch.setattr(
        discovery,
        "goto_and_capture_raw",
        lambda *a: {"http_status": 200, "html": "warmup"},
    )
    monkeypatch.setattr(discovery, "homepage_session_ok", lambda step: True)
    monkeypatch.setattr(discovery.time, "sleep", lambda _: None)
    parsed = []

    def gone(page, slug, **kwargs):
        kwargs["evidence_sink"](
            "https://yuyu-tei.jp/sell/opc/s/st16", {"http_status": 404, "html": "gone"}
        )
        parsed.append(True)

    monkeypatch.setattr(discovery, "enumerate_slug", gone)
    attempt = MagicMock()
    attempt.snapshot.side_effect = [101, 102]
    discovery.run_discovery(session, SimpleNamespace(work_id=1), freshness=attempt)
    assert parsed == []
    assert attempt.result.outcome == "transient_failure"
    assert attempt.result.raw_snapshot_id == 102
    assert "404" in attempt.result.failure
    session.add.assert_not_called()
