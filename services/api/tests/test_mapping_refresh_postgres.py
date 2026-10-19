"""Approval plans the mapping's raw refresh work, exactly once. Disposable local PostgreSQL.

The planner's upsert is PostgreSQL-only (ON CONFLICT on the work key), so these run on the real
schema: a Yuyu-Tei candidate approved through the service every Yuyu approval path uses gets one
pending `refresh` row with one raw `sell` category; approving it again, or calling the shared
function again, adds nothing and resets nothing; a not-yet-eligible SNKRDUNK row gets none.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from tests.pg_url import postgres_unavailable, postgres_url, server_label
from tests.test_yuyutei_candidate_approval import make_candidate, make_print, make_run

from app.db import Base
from app.models import FreshnessPriceState, FreshnessWork, ReleaseProduct, Source, SourceCardMapping
from app.services.mapping_refresh import DEFAULT_REQUEST_BOUND, ensure_refresh_work
from app.services.yuyutei_candidate_approval import approve_candidate

URL = postgres_url()


@pytest.fixture()
def factory():
    parsed = make_url(URL)
    if parsed.host not in {"localhost", "127.0.0.1"} or parsed.database != "opcg_test":
        postgres_unavailable(f"mapping refresh tests require local disposable opcg_test, not {server_label()}")
    engine = create_engine(URL)
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        postgres_unavailable(f"disposable local PostgreSQL is unavailable at {server_label()}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    with factory.begin() as session:
        session.add_all([
            Source(name="yuyutei", base_url="https://yuyu-tei.jp"),
            Source(name="snkrdunk", base_url="https://snkrdunk.com"),
            ReleaseProduct(source_catalogue="jp", official_code="OP01", display_name="OP-01",
                           first_seen_name="OP-01", source_series_id="OP01",
                           source_url="https://example.test/OP-01", verification_status="verified"),
        ])
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def approved_candidate(session):
    print_row = make_print(session, "OP01-001")
    candidate = make_candidate(session, make_run(session), card_print=print_row)
    return approve_candidate(session, candidate=candidate)


def refresh_rows(session):
    return session.scalars(select(FreshnessWork).where(FreshnessWork.kind == "refresh")).all()


def test_approval_creates_refresh_work_exactly_once(factory):
    with factory.begin() as session:
        result = approved_candidate(session)
    with factory.begin() as session:
        rows = refresh_rows(session)
        assert len(rows) == 1
        work = rows[0]
        assert work.source_card_mapping_id == result.mapping.id
        assert work.card_print_id == result.mapping.card_print_id
        assert work.state == "pending"
        assert work.estimated_request_cost == DEFAULT_REQUEST_BOUND
        states = session.scalars(select(FreshnessPriceState).where(FreshnessPriceState.work_id == work.id)).all()
        # Raw only: one Yuyu-Tei sell category, never PSA10.
        assert [(s.price_category, s.price_type, s.condition_label) for s in states] == [("raw", "sell", None)]


def test_reapproval_does_not_duplicate_or_reset_work(factory):
    with factory.begin() as session:
        approved_candidate(session)
    later = datetime.now(timezone.utc) + timedelta(hours=20)
    with factory.begin() as session:
        work = refresh_rows(session)[0]
        work.next_due_at = later
        work.attempt_count = 3
    with factory.begin() as session:
        from app.models.yuyutei_candidate import YuyuteiCandidate

        candidate = session.scalars(select(YuyuteiCandidate)).one()
        again = approve_candidate(session, candidate=candidate)
        assert again.mapping_created is False
        assert ensure_refresh_work(session, again.mapping) is not None
    with factory.begin() as session:
        rows = refresh_rows(session)
        assert len(rows) == 1
        assert rows[0].attempt_count == 3
        assert rows[0].next_due_at == later
        assert session.scalar(select(func.count()).select_from(FreshnessPriceState)) == 1


def test_new_work_uses_the_sources_existing_request_bound(factory):
    with factory.begin() as session:
        approved_candidate(session)
        refresh_rows(session)[0].estimated_request_cost = 41
    with factory.begin() as session:
        source = session.scalars(select(Source).where(Source.name == "yuyutei")).one()
        other = make_print(session, "OP01-002")
        mapping = SourceCardMapping(source_id=source.id, card_print_id=other.id, source_card_id="OP01-002",
                                    source_url="https://yuyu-tei.jp/sell/opc/card/op01/10002",
                                    is_active=True, manual_verified=True, review_status="approved")
        session.add(mapping)
        session.flush()
        assert ensure_refresh_work(session, mapping).estimated_request_cost == 41


def test_an_ineligible_mapping_gets_no_work_and_the_session_survives(factory):
    with factory.begin() as session:
        source = session.scalars(select(Source).where(Source.name == "snkrdunk")).one()
        print_row = make_print(session, "OP01-003")
        # SNKRDUNK is collected only once manually verified; approval without it plans nothing.
        mapping = SourceCardMapping(source_id=source.id, card_print_id=print_row.id, source_card_id="OP01-003",
                                    source_url="https://snkrdunk.com/apparels/123", is_active=True,
                                    manual_verified=False, review_status="approved")
        session.add(mapping)
        session.flush()
        assert ensure_refresh_work(session, mapping) is None
        assert refresh_rows(session) == []
        mapping.manual_verified = True
        session.flush()
        work = ensure_refresh_work(session, mapping)
        assert work is not None
        states = session.scalars(select(FreshnessPriceState).where(FreshnessPriceState.work_id == work.id)).all()
        assert [(s.price_category, s.price_type) for s in states] == [("raw", "floor")]
