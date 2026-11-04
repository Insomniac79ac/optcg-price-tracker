"""snkr-owner-requeue (owner 2026-11-04, plan B): reopens exactly the blocked artwork refusals the
owner confirmed for the same mapping, print and listing; disposable PostgreSQL, no source sockets."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import FreshnessWork, SourceCardMapping
from app.services.freshness_queue import complete_claim

from test_freshness_queue_postgres import admit, claim, db, mapping, plan, snapshot  # noqa: F401 - fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from ops import snkr_owner_requeue as orq  # noqa: E402

AT = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)
ARTWORK = "artwork_not_confirmed_match:no_match"


def refuse(factory, source, mapping_id, reason=ARTWORK, at=AT):
    work_id = plan(factory, mapping_id, at=at - timedelta(minutes=5))
    picked = [c for c in claim(factory, source, at=at - timedelta(minutes=1)) if c.work_id == work_id][0]
    admit(factory, picked.claim_token, at=at - timedelta(seconds=50))
    snap = snapshot(factory, source, at - timedelta(seconds=40))
    with factory.begin() as session:
        complete_claim(session, picked.claim_token, outcome="identity_refusal", actual_request_cost=1,
                       raw_snapshot_id=snap, failure=reason, clock=lambda: at)
    return work_id


def key(factory, mapping_id):
    with factory() as session:
        m = session.get(SourceCardMapping, mapping_id)
        return (m.id, m.card_print_id, m.canonical_source_listing_identity)


def confirmed(*keys):
    return {k: {"photo_url": "https://cdn.snkrdunk.com/x.webp", "confirmed_on": "2026-11-03"} for k in keys}


def build(factory, confirmations):
    with factory() as session:
        return orq.build_plan(session, confirmations)


def test_only_confirmed_artwork_refusals_are_planned(db):
    factory, source, mapping_id, print_id = db
    ok = refuse(factory, source, mapping_id)
    other = mapping(factory, source, print_id, 2001)
    unconfirmed = refuse(factory, source, other, at=AT + timedelta(minutes=10))
    release = mapping(factory, source, print_id, 2002)
    refuse(factory, source, release, reason="release_name_mismatch:displayed=x", at=AT + timedelta(minutes=20))
    plan_, facts = build(factory, confirmed(key(factory, mapping_id), key(factory, release)))
    assert plan_ == {"work_ids": [ok]}
    assert facts["confirmed_but_not_blocked"] == [release]  # a release refusal is never reopened here
    assert unconfirmed not in plan_["work_ids"]


def test_a_confirmation_for_another_print_or_listing_is_skipped(db):
    factory, source, mapping_id, print_id = db
    refuse(factory, source, mapping_id)
    m, p, listing = key(factory, mapping_id)
    plan_, facts = build(factory, confirmed((m, p, "999999")))
    assert plan_ == {"work_ids": []}
    plan_, facts = build(factory, {(m, p + 1, listing): {}})
    assert plan_ == {"work_ids": []} and facts["skipped"][0]["why"].startswith("confirmation names another")


def test_an_ineligible_mapping_is_skipped_not_reopened(db):
    factory, source, mapping_id, print_id = db
    refuse(factory, source, mapping_id)
    with factory.begin() as session:
        session.get(SourceCardMapping, mapping_id).is_active = False
    plan_, facts = build(factory, confirmed(key(factory, mapping_id)))
    assert plan_ == {"work_ids": []} and facts["skipped"][0]["mapping_id"] == mapping_id


def test_apply_reopens_exactly_the_plan_and_keeps_the_reason(db):
    factory, source, mapping_id, print_id = db
    work_id = refuse(factory, source, mapping_id)
    conf = confirmed(key(factory, mapping_id))
    plan_, _ = build(factory, conf)
    with factory.begin() as session:
        assert orq.apply_plan(session, plan_, conf, clock=lambda: NOW) == {"reopened": [work_id]}
    with factory() as session:
        w = session.get(FreshnessWork, work_id)
        assert (w.state, w.next_due_at) == ("pending", NOW)
        assert w.last_failure.startswith(orq.MARKER) and ARTWORK in w.last_failure
    # Reopened work is no longer a candidate.
    assert build(factory, conf)[0] == {"work_ids": []}


def test_apply_refuses_a_stale_plan(db):
    factory, source, mapping_id, print_id = db
    refuse(factory, source, mapping_id)
    conf = confirmed(key(factory, mapping_id))
    with factory.begin() as session, pytest.raises(ValueError, match="differs"):
        orq.apply_plan(session, {"work_ids": []}, conf, clock=lambda: NOW)


def test_run_is_a_dry_run_by_default_and_apply_needs_the_sha(tmp_path):
    from ops import common

    plan_ = {"work_ids": [7]}
    facts = {"confirmations": 1, "skipped": [], "confirmed_but_not_blocked": []}
    written = []
    out = orq.run(tmp_path, preview=lambda: (plan_, facts), write=written.append)
    assert out["ok"] and out["reopen"] == 1 and written == []
    with pytest.raises(common.Refused):
        orq.run(tmp_path, apply=True, expected_sha256="0" * 64, preview=lambda: (plan_, facts), write=written.append)
    orq.run(tmp_path, apply=True, expected_sha256=out["plan_sha256"], preview=lambda: (plan_, facts),
            write=lambda p: written.append(p) or {"reopened": [7]})
    assert written == [plan_]
