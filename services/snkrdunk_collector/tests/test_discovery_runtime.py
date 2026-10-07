from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Base,
    Source,
    SourceCardMapping,
    SnkrdunkCandidate,
    PriceObservation,
    RawSnapshot,
)
from app.services.freshness_queue import plan_discovery_scope
from opcg_source_identity import canonical_source_listing_identity
from snkrdunk_collector.discovery import ROBOTS, RetainedDocument, consume, intent
from snkrdunk_collector.published_discovery import INDEX

SHARD = "https://snkrdunk.com/en/sitemap/sitemap-en-product-trading-card-single-0.xml"
ANCHOR = "https://snkrdunk.com/en/trading-cards/40001"
NEIGHBOUR = "https://snkrdunk.com/en/trading-cards/900005"


@pytest.fixture
def setup():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    source = Source(name="snkrdunk", base_url="https://snkrdunk.com")
    session.add(source)
    session.flush()
    mapping = SourceCardMapping(
        source_id=source.id,
        card_id=1,
        card_print_id=1,
        source_card_id="40001",
        source_url=ANCHOR,
        is_active=True,
        manual_verified=True,
        review_status="approved",
        canonical_source_listing_identity=canonical_source_listing_identity(
            "snkrdunk", ANCHOR
        ),
    )
    session.add(mapping)
    session.flush()
    scope = "snkr-published:mock-neighbour-evidence-v1"
    work = plan_discovery_scope(
        session,
        source.id,
        scope,
        due_at=datetime.now(timezone.utc),
        estimated_request_cost=300,
    )
    work.attempt_count = 1
    work.state = "claimed"
    work.claim_token = "mock-token"
    work.claimed_by = "mock-owner"
    work.claimed_at = datetime.now(timezone.utc)
    work.claim_expires_at = work.claimed_at + timedelta(minutes=10)
    work.resume_cursor = {
        "version": 1,
        "scope_key": scope,
        "explicit_published_discovery": True,
        "anchor_mapping_ids": [mapping.id],
        "radius_start": 1,
        "radius_end": 1,
        "max_products": 20,
    }
    session.commit()
    claim = SimpleNamespace(
        work_id=work.id, scope_key=scope, resume_cursor=work.resume_cursor
    )
    yield session, claim, work, mapping
    session.close()
    engine.dispose()


def documents(*, deny_product=False, not_found=False):
    code = 403 if deny_product else 404 if not_found else 200
    return {
        ROBOTS: (200, b"User-agent: *\nDisallow: /en/v1/\n"),
        INDEX: (
            200,
            f"<sitemapindex><sitemap><loc>{SHARD}</loc></sitemap></sitemapindex>".encode(),
        ),
        SHARD: (
            200,
            f"<urlset><url><loc>{ANCHOR}</loc></url><url><loc>{NEIGHBOUR}</loc></url></urlset>".encode(),
        ),
        NEIGHBOUR: (
            code,
            b'<html><title>Nami R-P [OP01-016] (Booster Pack ROMANCE DAWN) | SNKRDUNK</title><meta property="og:image" content="https://cdn.snkrdunk.com/uploads/media/OPC-EN-TCG-OP01-016_p1-of.webp"></html>',
        ),
    }


def run(session, claim, responses):
    calls = []
    trace = []

    def fetch(url):
        calls.append(url)
        trace.append(("retained", url))
        status, body = responses[url]
        return RetainedDocument(url, body, len(calls), status)

    fresh = SimpleNamespace(
        begin_result=lambda: trace.append(("fenced", None)),
        clock=lambda: datetime.now(timezone.utc),
    )
    result = consume(session, claim, freshness=fresh, fetch=fetch)
    return result, calls, trace


def test_published_mock_pipeline_creates_only_unmatched_candidate(setup):
    session, claim, work, mapping = setup
    result, calls, trace = run(session, claim, documents())
    rows = session.scalars(select(SnkrdunkCandidate)).all()
    assert len(rows) == 1 and rows[0].match_status == "unmatched"
    assert rows[0].detected_card_code == "OP01-016"
    assert rows[0].detected_set_code == "OP-01" and rows[0].detected_variant == "p1"
    assert rows[0].price_jpy is None and rows[0].matched_card_id is None
    assert session.scalars(select(PriceObservation)).all() == []
    assert len(session.scalars(select(SourceCardMapping)).all()) == 1
    assert mapping.manual_verified and mapping.review_status == "approved"
    assert calls == [ROBOTS, INDEX, SHARD, NEIGHBOUR]
    assert trace[-1] == ("fenced", None)
    assert result.outcome == "completed" and result.observation_ids == {}
    assert (
        result.resume_cursor["mapping_writes"]
        == result.resume_cursor["price_writes"]
        == 0
    )
    assert result.next_due_at.year > 2100


def test_known_candidate_and_review_are_preserved_without_fetch(setup):
    session, claim, _, _ = setup
    old = SnkrdunkCandidate(
        source_url=NEIGHBOUR,
        title="Prior manual source evidence",
        price_jpy=9999,
        match_status="rejected",
    )
    session.add(old)
    session.commit()
    result, calls, _ = run(session, claim, documents())
    assert NEIGHBOUR not in calls and result.resume_cursor["new_candidate_ids"] == []
    assert (
        old.title == "Prior manual source evidence"
        and old.price_jpy == 9999
        and old.match_status == "rejected"
    )


@pytest.mark.parametrize("evidence_kind", ["mapped", "retained"])
def test_known_evidence_alias_without_candidate_is_not_refetched(setup, evidence_kind):
    session, claim, _, anchor = setup
    alias = "https://snkrdunk.com/apparels/900005"
    if evidence_kind == "mapped":
        prior = SourceCardMapping(
            source_id=anchor.source_id,
            card_id=2,
            card_print_id=2,
            source_card_id="900005",
            source_url=alias,
            is_active=False,
            manual_verified=True,
            review_status="approved",
        )
    else:
        prior = RawSnapshot(
            source_id=anchor.source_id,
            source_url=alias,
            http_status=404,
            content_hash="a" * 64,
            raw_content="immutable prior source evidence",
        )
    session.add(prior)
    session.commit()
    result, calls, _ = run(session, claim, documents())
    assert calls == [ROBOTS, INDEX, SHARD]
    assert result.resume_cursor["new_candidate_ids"] == []
    assert session.scalars(select(SnkrdunkCandidate)).all() == []
    assert prior.source_url == alias
    if evidence_kind == "mapped":
        assert prior.manual_verified and prior.review_status == "approved"
        assert not prior.is_active
    else:
        assert prior.raw_content == "immutable prior source evidence"
        assert prior.http_status == 404


def test_missing_published_anchor_creates_no_probe_urls(setup):
    session, claim, _, _ = setup
    responses = documents()
    responses[SHARD] = (200, b"<urlset/>")
    result, calls, _ = run(session, claim, responses)
    assert (
        calls == [ROBOTS, INDEX, SHARD]
        and result.resume_cursor["new_candidate_ids"] == []
    )


def test_absent_advertised_product_gets_no_raw_price_credit(setup):
    session, claim, _, _ = setup
    result, _, _ = run(session, claim, documents(not_found=True))
    assert result.no_listing_categories == set() and result.observation_ids == {}
    assert result.resume_cursor["new_candidate_ids"] == []


def test_robots_disallow_refuses_before_index_fetch(setup):
    session, claim, _, _ = setup
    responses = documents()
    responses[ROBOTS] = (200, b"User-agent: *\nDisallow: /en/\n")
    calls = []

    def fetch(url):
        calls.append(url)
        status, body = responses[url]
        return RetainedDocument(url, body, 1, status)

    with pytest.raises(ValueError, match="robots"):
        consume(session, claim, freshness=SimpleNamespace(), fetch=fetch)
    assert calls == [ROBOTS]


@pytest.mark.parametrize(
    "change",
    [
        "completed_attempt",
        "wrong_kind",
        "wrong_scope",
        "not_explicit",
        "unverified_anchor",
    ],
)
def test_intent_guards_reject_before_source_io(setup, change):
    session, claim, work, mapping = setup
    if change == "completed_attempt":
        work.attempt_count = 2
    elif change == "wrong_kind":
        work.kind = "validation"
    elif change == "wrong_scope":
        claim.scope_key = "unknown"
    elif change == "not_explicit":
        claim.resume_cursor = {
            **claim.resume_cursor,
            "explicit_published_discovery": False,
        }
    elif change == "unverified_anchor":
        mapping.manual_verified = False
    with pytest.raises(ValueError):
        intent(session, claim)


@pytest.mark.parametrize(
    "status,body,denied",
    [
        (200, b"<!doctype html><html><title>Normal document</title></html>", False),
        (403, b"Forbidden", True),
        (429, b"Too many requests", True),
        (200, b"<!doctype html><html><title>Just a moment...</title></html>", True),
    ],
)
def test_transport_admits_and_retains_exact_bytes_before_classification(
    monkeypatch, status, body, denied
):
    import base64
    import hashlib
    import json
    from snkrdunk_collector import discovery

    trace = []

    class Response:
        def body(self):
            trace.append("body")
            return body

        def dispose(self):
            trace.append("dispose")

    response = Response()
    response.status = status

    def get(url, **kwargs):
        assert url == INDEX
        assert kwargs == {"max_redirects": 0, "max_retries": 0, "timeout": 20000}
        trace.append("get")
        return response

    def snapshot(source_id, url, payload, parser):
        trace.append("snapshot")
        assert source_id == 1 and url == INDEX and payload["http_status"] == status
        envelope = json.loads(payload["html"])
        assert base64.b64decode(envelope["body"]) == body
        assert envelope["body_sha256"] == hashlib.sha256(body).hexdigest()
        return 42

    def deny():
        trace.append("deny")

    freshness = SimpleNamespace(
        admit=lambda: trace.append("admit"),
        snapshot=snapshot,
        record_http=lambda code: trace.append(("status", code)),
        deny=deny,
        check=lambda: trace.append("check"),
        claim=SimpleNamespace(work_id=1),
    )
    page = SimpleNamespace(context=SimpleNamespace(request=SimpleNamespace(get=get)))
    monkeypatch.setattr(discovery.time, "sleep", lambda seconds: None)
    result = discovery.retained_fetch(page, freshness, 1, INDEX)
    assert trace[:5] == ["admit", "get", "body", "snapshot", "dispose"]
    assert ("deny" in trace) is denied
    assert result.body == body and result.raw_snapshot_id == 42


def test_transport_lost_admission_never_starts_http():
    from app.services.freshness_integration import AdmissionStopped
    from snkrdunk_collector.discovery import retained_fetch

    def stop():
        raise AdmissionStopped("budget refused")

    freshness = SimpleNamespace(admit=stop)
    with pytest.raises(AdmissionStopped):
        retained_fetch(None, freshness, 1, INDEX)
