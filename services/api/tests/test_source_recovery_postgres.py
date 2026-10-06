"""Disposable PostgreSQL and mocked source only; no production/source sockets."""

from datetime import timedelta
from sqlalchemy import select, func
import pytest
from app.models import (
    FreshnessAttempt,
    FreshnessWork,
    SourceDispatchBudget,
    PriceObservation,
)
from app.services.freshness_queue import pause_source, complete_claim, claim_due
from app.services.source_recovery import claim_source_recovery, resume_after_recovery
from app.services.source_recovery import plan_source_recovery
from app.services.freshness_policy import utc_now
from test_freshness_queue_postgres import db, claim, admit, T0
from test_freshness_adapters_postgres import (
    seed,
    Transport,
    forbid_unmocked_browser,
    HTML,
)
from snkrdunk_collector.recovery import run_recovery


def denied_episode(factory, source, mapping_id):
    seed(factory, mapping_id, bound=30)
    picked = claim(factory, source)[0]
    admit(factory, picked.claim_token)
    with factory.begin() as session:
        pause_source(session, picked.claim_token, clock=lambda: T0)
        complete_claim(
            session,
            picked.claim_token,
            outcome="source_denial",
            actual_request_cost=1,
            clock=lambda: T0,
        )
        return session.scalar(select(FreshnessAttempt.id))


def test_probe_keeps_ordinary_dispatch_paused_and_never_replays(db):
    factory, source, mapping_id, _ = db
    denial_id = denied_episode(factory, source, mapping_id)
    with factory.begin() as session:
        probe = claim_source_recovery(
            session,
            source,
            mapping_id,
            denial_id,
            "fixture",
            request_bound=30,
            clock=lambda: T0 + timedelta(minutes=1),
        )
        assert probe is not None
        assert (
            session.scalar(select(SourceDispatchBudget.pause_reason)) == "source_denial"
        )
        assert (
            claim_due(
                session,
                source,
                "ordinary",
                limit=1,
                lease=timedelta(minutes=1),
                clock=lambda: T0 + timedelta(minutes=1),
            )
            == []
        )
    assert admit(factory, probe.claim_token, at=T0 + timedelta(minutes=1))
    assert not admit(factory, probe.claim_token, at=T0 + timedelta(minutes=1))
    with factory.begin() as session:
        assert (
            claim_source_recovery(
                session,
                source,
                mapping_id,
                denial_id,
                "second",
                request_bound=30,
                clock=lambda: T0 + timedelta(minutes=1),
            )
            is None
        )
        with pytest.raises(ValueError, match="settled"):
            resume_after_recovery(
                session, probe.claim_token, clock=lambda: T0 + timedelta(minutes=1)
            )


def test_fresh_required_denial_revokes_probe_and_prevents_another_probe(db):
    factory, source, mapping_id, _ = db
    denial_id = denied_episode(factory, source, mapping_id)
    at = T0 + timedelta(minutes=1)
    with factory.begin() as session:
        probe = claim_source_recovery(
            session,
            source,
            mapping_id,
            denial_id,
            "fixture",
            request_bound=30,
            clock=lambda: at,
        )
    admit(factory, probe.claim_token, at=at)
    with factory.begin() as session:
        pause_source(session, probe.claim_token, clock=lambda: at)
    with pytest.raises(ValueError, match="paused"):
        admit(factory, probe.claim_token, at=at, ordinal=2)
    with factory.begin() as session:
        complete_claim(
            session,
            probe.claim_token,
            outcome="source_denial",
            actual_request_cost=1,
            clock=lambda: at,
        )
        latest = session.scalar(
            select(FreshnessAttempt.id).order_by(FreshnessAttempt.id.desc())
        )
        with pytest.raises(ValueError, match="another probe"):
            claim_source_recovery(
                session,
                source,
                mapping_id,
                latest,
                "retry",
                request_bound=30,
                clock=lambda: at,
            )
        assert (
            session.scalar(select(SourceDispatchBudget.pause_reason)) == "source_denial"
        )
        assert session.scalar(select(SourceDispatchBudget.reserved_requests)) == 0


def test_disabled_source_and_unbounded_recovery_are_closed(db):
    factory, source, mapping_id, _ = db
    denial_id = denied_episode(factory, source, mapping_id)
    with factory.begin() as session:
        with pytest.raises(ValueError, match="bounded"):
            claim_source_recovery(
                session, source, mapping_id, denial_id, "fixture", request_bound=601
            )
        session.scalar(select(SourceDispatchBudget)).enabled = False
        session.flush()
        with pytest.raises(ValueError, match="current retained"):
            claim_source_recovery(
                session, source, mapping_id, denial_id, "fixture", request_bound=30
            )


def test_real_exact_writer_proves_recovery_without_persisting_a_price(db, monkeypatch):
    factory, source, mapping_id, _ = db
    denial_id = denied_episode(factory, source, mapping_id)
    transport = Transport(monkeypatch)
    result = run_recovery(
        source, mapping_id, denial_id, request_bound=30, session_factory=factory
    )
    assert result["status"] == "completed" and result["resumed"]
    assert len(transport.sent) == result["request_cost"]
    with factory() as session:
        assert session.scalar(select(SourceDispatchBudget.pause_reason)) is None
        assert session.scalar(select(SourceDispatchBudget.reserved_requests)) == 0
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0
        probe = session.get(FreshnessWork, result["work_id"])
        assert probe.resume_cursor["identity_verified"]
        assert probe.resume_cursor["raw_outcome"] == "listed"
        normal = session.scalar(
            select(FreshnessWork).where(FreshnessWork.kind == "refresh")
        )
        assert normal.last_successfully_checked_at is None
    with pytest.raises(ValueError, match="current retained"):
        run_recovery(source, mapping_id, denial_id, session_factory=factory)


def test_confident_no_listing_proves_access_without_freshening_price(db, monkeypatch):
    from bs4 import BeautifulSoup

    factory, source, mapping_id, _ = db
    denial_id = denied_episode(factory, source, mapping_id)
    soup = BeautifulSoup(HTML, "html.parser")
    for label in ("A", "B"):
        chip = next(
            p for p in soup.find_all("p") if p.get_text(strip=True) == label
        ).parent
        chip.find("p", class_="css3__price").replace_with(
            BeautifulSoup('<p class="css3__awaiting">出品待ち</p>', "html.parser")
        )
    Transport(monkeypatch, str(soup))
    result = run_recovery(
        source, mapping_id, denial_id, request_bound=30, session_factory=factory
    )
    assert result["status"] == "completed" and result["resumed"]
    with factory() as session:
        assert (
            session.get(FreshnessWork, result["work_id"]).resume_cursor["raw_outcome"]
            == "no_listing"
        )
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0


def test_required_product_denial_keeps_source_paused(db, monkeypatch):
    from types import SimpleNamespace

    factory, source, mapping_id, _ = db
    denial_id = denied_episode(factory, source, mapping_id)
    transport = Transport(monkeypatch)
    original = transport.response
    transport.response = lambda url: (
        SimpleNamespace(status=403, ok=False, body=lambda: b"Forbidden")
        if "/apparels/" in url
        else original(url)
    )
    result = run_recovery(
        source, mapping_id, denial_id, request_bound=30, session_factory=factory
    )
    assert result["status"] == "source_denial" and not result["resumed"]
    assert len(transport.sent) == 2  # homepage, product; no artwork/retry.
    with factory() as session:
        assert (
            session.scalar(select(SourceDispatchBudget.pause_reason)) == "source_denial"
        )
        assert session.scalar(select(SourceDispatchBudget.reserved_requests)) == 0
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0


def test_identity_refusal_cannot_unpause(db, monkeypatch):
    factory, source, mapping_id, _ = db
    denial_id = denied_episode(factory, source, mapping_id)
    Transport(monkeypatch)
    from snkrdunk_collector import collect

    monkeypatch.setattr(collect, "compare_artwork", lambda *a: {"match": False})
    result = run_recovery(
        source, mapping_id, denial_id, request_bound=30, session_factory=factory
    )
    assert result["status"] == "identity_refusal" and not result["resumed"]
    with factory() as session:
        assert (
            session.scalar(select(SourceDispatchBudget.pause_reason)) == "source_denial"
        )
        assert session.scalar(select(SourceDispatchBudget.reserved_requests)) == 0


def test_scheduled_consumer_serves_only_explicit_intent_once(db, monkeypatch):
    from snkrdunk_collector.due import run_due

    factory, source, mapping_id, _ = db
    denial_id = denied_episode(factory, source, mapping_id)
    Transport(monkeypatch)
    assert (
        run_due(session_factory=factory) == []
    )  # pause alone never authorizes a probe
    with factory.begin() as session:
        sequence = session.scalar(select(SourceDispatchBudget.claim_sequence))
        work = plan_source_recovery(
            session, source, mapping_id, denial_id, request_bound=30
        )
        wid = work.id
        assert work.attempt_count == 0 and work.state == "pending"
        assert session.scalar(select(SourceDispatchBudget.claim_sequence)) == sequence
        assert session.scalar(select(SourceDispatchBudget.reserved_requests)) == 0
        assert session.scalar(select(func.count()).select_from(FreshnessAttempt)) == 1
    result = run_due(session_factory=factory)
    assert len(result) == 1 and result[0]["resumed"] and result[0]["work_id"] == wid
    with factory() as session:
        work = session.get(FreshnessWork, wid)
        assert work.attempt_count == 1 and work.last_outcome == "completed"
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 0
        assert session.scalar(select(SourceDispatchBudget.reserved_requests)) == 0
    # A normal later invocation consumes ordinary work; it cannot repeat validation.
    run_due(session_factory=factory)
    with factory() as session:
        assert session.get(FreshnessWork, wid).attempt_count == 1


def test_planned_recovery_lineage_cannot_change_before_scheduled_consumption(db):
    from app.models import SourceCardMapping

    factory, source, mapping_id, _ = db
    denial_id = denied_episode(factory, source, mapping_id)
    with factory.begin() as session:
        plan_source_recovery(session, source, mapping_id, denial_id, request_bound=30)
    with factory.begin() as session:
        mapping = session.get(SourceCardMapping, mapping_id)
        mapping.source_url = "https://snkrdunk.com/apparels/999"
        mapping.canonical_source_listing_identity = "999"
    with factory.begin() as session:
        with pytest.raises(ValueError):
            claim_source_recovery(
                session, source, mapping_id, denial_id, "changed", request_bound=30
            )
        assert session.scalar(select(SourceDispatchBudget.reserved_requests)) == 0
