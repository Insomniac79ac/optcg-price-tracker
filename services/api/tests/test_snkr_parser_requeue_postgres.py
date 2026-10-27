"""snkr-parser-requeue (owner 2026-10-27): disposable PostgreSQL, no source sockets."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import FreshnessWork, SourceCardMapping
from app.services import snkr_parser_requeue as rq
from app.services.freshness_queue import complete_claim

from test_freshness_queue_postgres import admit, claim, db, mapping, plan, snapshot  # noqa: F401 - fixture

IN_WINDOW = rq.CHANGE_AT + timedelta(hours=2)
NOW = rq.RELEASE_AT + timedelta(hours=1)


def refuse(factory, source, mapping_id, *, at=IN_WINDOW, reason=rq.REASON + ";artwork_not_confirmed_match:missing_image_url"):
    """One refresh of this mapping settled as identity_refusal at `at` (as the broken parser did)."""
    work_id = plan(factory, mapping_id, at=at - timedelta(minutes=5))
    picked = claim(factory, source, at=at - timedelta(minutes=1))[0]
    assert picked.work_id == work_id
    admit(factory, picked.claim_token, at=at - timedelta(seconds=50))
    snap = snapshot(factory, source, at - timedelta(seconds=40))
    with factory.begin() as session:
        complete_claim(session, picked.claim_token, outcome="identity_refusal", actual_request_cost=1,
                       raw_snapshot_id=snap, failure=reason, clock=lambda: at)
    return work_id


def seed(factory, source, first_mapping, print_id, n=3):
    ids = [refuse(factory, source, first_mapping)]
    for k in range(1, n):
        ids.append(refuse(factory, source, mapping(factory, source, print_id, 1000 + k)))
    return ids


def preview(factory, mode, count=None):
    with factory() as session:
        return rq.preview(session, mode=mode, count=count, clock=lambda: NOW)


def apply(factory, plan_):
    with factory.begin() as session:
        return rq.apply(session, plan_, clock=lambda: NOW)


def capture(factory, work_id, at=NOW + timedelta(minutes=30)):
    """The reopened item captured on the new code (only the fields the proof reads)."""
    with factory.begin() as session:
        work = session.get(FreshnessWork, work_id)
        work.last_outcome, work.last_successfully_checked_at = "captured", at


def test_canary_reopens_one_item_and_nothing_else(db):
    factory, source, mapping_id, print_id = db
    ids = seed(factory, source, mapping_id, print_id)
    plan_, problems, facts = preview(factory, "canary")
    assert problems == [] and plan_["mode"] == "canary" and len(plan_["work_ids"]) == 1
    assert facts["candidates"] == 3
    assert apply(factory, plan_) == plan_["work_ids"]
    with factory() as session:
        rows = {w.id: w for w in session.scalars(select(FreshnessWork).where(FreshnessWork.id.in_(ids)))}
    canary = rows[plan_["work_ids"][0]]
    assert (canary.state, canary.next_due_at, canary.last_failure.startswith(rq.MARKER)) == ("pending", NOW, True)
    assert rq.REASON in canary.last_failure  # the original reason is kept
    assert all(w.state == "blocked" for i, w in rows.items() if i != canary.id)


def test_preview_is_read_only(db):
    factory, source, mapping_id, print_id = db
    seed(factory, source, mapping_id, print_id, n=1)
    with factory() as session:
        session.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
        assert rq.preview(session, mode="canary", clock=lambda: NOW)[1] == []


def test_a_second_canary_waits_for_the_first_to_settle(db):
    factory, source, mapping_id, print_id = db
    seed(factory, source, mapping_id, print_id)
    apply(factory, preview(factory, "canary")[0])
    assert any("not settled" in p for p in preview(factory, "canary")[1])


def test_the_rest_needs_a_proven_capture_then_reopens_every_remaining_item(db):
    factory, source, mapping_id, print_id = db
    ids = seed(factory, source, mapping_id, print_id)
    canary = preview(factory, "canary")[0]
    apply(factory, canary)
    assert any("no refused item has captured" in p for p in preview(factory, "rest")[1])
    capture(factory, canary["work_ids"][0])
    assert any("already proven" in p for p in preview(factory, "canary")[1])
    rest, problems, facts = preview(factory, "rest")
    assert problems == [] and facts["proven_captures"] == canary["work_ids"]
    assert sorted(rest["work_ids"]) == sorted(set(ids) - set(canary["work_ids"]))
    apply(factory, rest)
    with factory() as session:
        assert {session.get(FreshnessWork, i).state for i in rest["work_ids"]} == {"pending"}
    assert any("no refused item is eligible" in p for p in preview(factory, "rest")[1])


def test_a_refusal_on_the_new_code_stops_the_rest(db):
    factory, source, mapping_id, print_id = db
    ids = seed(factory, source, mapping_id, print_id)
    canary = preview(factory, "canary")[0]
    apply(factory, canary)
    capture(factory, canary["work_ids"][0])
    refuse(factory, source, mapping(factory, source, print_id, 2000), at=NOW, reason="no_raw_condition_price_available")
    plan_, problems, facts = preview(factory, "rest")
    assert plan_ is None and any("refused again on the new code" in p for p in problems)
    assert len(facts["refused_on_new_code"]) == 1 and len(ids) == 3


def test_only_the_parser_bug_window_and_reason_are_eligible(db):
    factory, source, mapping_id, print_id = db
    refuse(factory, source, mapping_id, at=rq.CHANGE_AT - timedelta(days=3))  # older quarantine
    refuse(factory, source, mapping(factory, source, print_id, 3001), reason="artwork_not_confirmed_match:no_match")
    in_window = refuse(factory, source, mapping(factory, source, print_id, 3002))
    plan_, problems, facts = preview(factory, "canary")
    assert problems == [] and plan_["work_ids"] == [in_window] and facts["candidates"] == 1


def test_an_ineligible_mapping_is_reported_not_reopened(db):
    factory, source, mapping_id, print_id = db
    ids = seed(factory, source, mapping_id, print_id, n=2)
    with factory.begin() as session:
        session.get(SourceCardMapping, mapping_id).review_status = "needs_review"
    plan_, problems, facts = preview(factory, "canary")
    assert problems == [] and plan_["work_ids"] == [ids[1]]
    assert [s["work_id"] for s in facts["ineligible"]] == [ids[0]]


def test_apply_writes_only_the_approved_plan(db):
    factory, source, mapping_id, print_id = db
    ids = seed(factory, source, mapping_id, print_id)
    plan_ = preview(factory, "canary")[0]
    other = next(i for i in ids if i not in plan_["work_ids"])
    with pytest.raises(ValueError, match="differs"):
        apply(factory, {**plan_, "work_ids": [other]})
    with pytest.raises(ValueError, match="plan keys"):
        apply(factory, {**plan_, "extra": 1})
    with factory() as session:
        assert {session.get(FreshnessWork, i).state for i in ids} == {"blocked"}


def test_bad_inputs_are_refused(db):
    factory, source, mapping_id, print_id = db
    assert preview(factory, "everything")[1] == ["mode must be canary or rest"]
    assert preview(factory, "rest", count=0)[1][0].startswith("count must be")
