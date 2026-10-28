"""scripts/yuyu_identity_capture_enqueue.py on a disposable localhost PostgreSQL only.

Dry run writes nothing; apply writes exactly the approved intents in the shape the
collector's load_intent accepts; reruns are no-ops; any changed or unsafe entry refuses
the whole batch; proposals and mappings are never written.
"""

from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys

import pytest
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "services/yuyutei_collector")]

from test_freshness_queue_postgres import db, T0  # noqa: F401  (fixture)

from app.models import (
    CardPrint,
    FreshnessWork,
    ReleaseProduct,
    Source,
    SourceCardMapping,
    SourceDispatchBudget,
    SourceMappingProposalGroup,
    YuyuteiCandidate,
    YuyuteiDiscoveryRun,
)
from app.services.source_mapping_proposals import resolve_current_candidate_proposal
import yuyu_identity_capture_enqueue as tool


def family(session, base_print_id, product_id="10002", code="OP01-001", variant="p2"):
    """One ambiguous Yuyu family: the fixture print plus a verified parallel sibling."""
    base = session.get(CardPrint, base_print_id)
    release = session.get(ReleaseProduct, base.release_product_id)
    release.source_catalogue, release.official_code, release.verification_status = ("bandai_jp", "OP-01", "verified")
    base.image_url = f"https://www.onepiece-cardgame.com/images/cardlist/card/{code}.png"
    sibling = CardPrint(
        canonical_card_id=base.canonical_card_id, release_product_id=release.id, language="jp",
        is_active=True, verification_status="verified", official_asset_variant=variant,
        artwork_key=f"fixture-{variant}",
        image_url=f"https://www.onepiece-cardgame.com/images/cardlist/card/{code}_{variant}.png",
    )
    source = session.scalars(select(Source).where(Source.name == "yuyutei")).one_or_none()
    if source is None:
        source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
        session.add(source)
        session.flush()
        session.add(SourceDispatchBudget(source_id=source.id, enabled=True, request_limit=100,
                                         window_seconds=1800, window_started_at=T0))
    run = YuyuteiDiscoveryRun(status="completed", requested_set_slugs=["op01"],
                              per_slug_metrics_json={"op01": {"enumeration_complete": True}})
    session.add_all([sibling, run])
    session.flush()
    candidate = YuyuteiCandidate(
        discovery_run_id=run.id, set_slug="op01", product_id=product_id,
        source_url=f"https://yuyu-tei.jp/sell/opc/card/op01/{product_id}",
        detected_card_code=code, name_jp="ロロノア・ゾロ(パラレル)", match_status="family_matched",
    )
    session.add(candidate)
    session.flush()
    plan = resolve_current_candidate_proposal(session, source_name="yuyutei", candidate_id=candidate.id)
    assert plan.resolution_status == "ambiguous"
    return {
        "candidate_id": candidate.id,
        "evidence_digest": plan.evidence_digest,
        "release_product_id": plan.release_product_id,
        "considered_print_ids": sorted(a.card_print_id for a in plan.alternatives),
    }


def approved(entries):
    return {"batch": "NEW-test", "expected_count": len(entries), "entries": entries}


def counts(session):
    return (
        session.scalar(select(func.count()).select_from(FreshnessWork)),
        session.scalar(select(func.count()).select_from(SourceMappingProposalGroup)),
        session.scalar(select(func.count()).select_from(SourceCardMapping)),
    )


@pytest.fixture()
def one(db):  # noqa: F811
    factory, _, _, pid = db
    with factory.begin() as session:
        entry = family(session, pid)
    return factory, entry


def test_dry_run_checks_everything_and_writes_nothing(one):
    factory, entry = one
    with factory() as session:
        before = counts(session)
        report = tool.enqueue(session, approved([entry]), apply=False)
        session.rollback()
        assert report["checked"] == 1 and len(report["to_enqueue"]) == 1 and report["written"] == []
        assert counts(session) == before


def test_apply_writes_the_intent_the_collector_accepts_and_never_a_decision(one):
    from app.services.freshness_queue import claim_due
    from yuyutei_collector.identity_evidence import load_intent

    factory, entry = one
    with factory() as session:
        _, groups, mappings = counts(session)
        report = tool.enqueue(session, approved([entry]), apply=True, now=T0)
        session.commit()
        assert len(report["written"]) == 1
        work = session.get(FreshnessWork, report["written"][0]["work_id"])
        assert (work.kind, work.state, work.attempt_count, work.lane) == ("discovery", "pending", 0, "discovery")
        assert work.scope_key == f"yuyu-identity:{entry['candidate_id']}:sha256:{entry['evidence_digest']}"
        summary = work.resume_cursor.pop("evidence_summary")
        assert work.resume_cursor == {**entry, "version": 2, "explicit_identity_capture": True}
        from app.services.source_mapping_proposals import evidence_digest
        assert evidence_digest(summary) == entry["evidence_digest"]  # the planned evidence travels with it
        assert counts(session)[1:] == (groups, mappings)  # no proposal or mapping write
        source_id = work.source_id
    with factory() as session:
        granted = claim_due(session, source_id, "fixture-shard", limit=1, lease=timedelta(minutes=4),
                            clock=lambda: T0 + timedelta(seconds=1), supported_kinds={"discovery"})[0]
        session.commit()
        candidate, plan, prints, urls = load_intent(session, granted)
        assert candidate.id == entry["candidate_id"] and sorted(urls) == entry["considered_print_ids"]


@pytest.mark.parametrize("change, captures", [
    ({"price_jpy": 1980, "availability": "out_of_stock", "raw_listing_text": "1,980円 売切"}, True),
    ({"name_jp": "別の商品"}, False),
])
def test_a_price_change_before_the_claim_keeps_the_capture(one, change, captures):
    """Owner 2026-10-29: no proposal group holds the planned evidence here, so only the summary
    the intent carries can prove the listing is the same one; a price change must not void it."""
    from app.services.freshness_queue import claim_due
    from yuyutei_collector.identity_evidence import load_intent

    factory, entry = one
    with factory() as session:
        report = tool.enqueue(session, approved([entry]), apply=True, now=T0)
        for key, value in change.items():
            setattr(session.get(YuyuteiCandidate, entry["candidate_id"]), key, value)
        session.commit()
        source_id = session.get(FreshnessWork, report["written"][0]["work_id"]).source_id
    with factory() as session:
        granted = claim_due(session, source_id, "fixture-shard", limit=1, lease=timedelta(minutes=4),
                            clock=lambda: T0 + timedelta(seconds=1), supported_kinds={"discovery"})[0]
        session.commit()
        if captures:
            assert load_intent(session, granted)[0].id == entry["candidate_id"]
        else:
            with pytest.raises(ValueError, match="current ambiguous"):
                load_intent(session, granted)


def test_rerun_is_a_no_op(one):
    factory, entry = one
    with factory() as session:
        tool.enqueue(session, approved([entry]), apply=True, now=T0)
        session.commit()
        before = counts(session)
        report = tool.enqueue(session, approved([entry]), apply=True, now=T0)
        session.commit()
        assert report["written"] == [] and len(report["already_enqueued"]) == 1
        assert counts(session) == before


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda e: {**e, "evidence_digest": "0" * 64}, "digest changed"),
        (lambda e: {**e, "release_product_id": e["release_product_id"] + 999}, "release_product_id"),
        (lambda e: {**e, "considered_print_ids": e["considered_print_ids"][:1]}, "sibling set"),
        (lambda e: {**e, "candidate_id": e["candidate_id"] + 999}, "listing identity"),
    ],
)
def test_changed_entry_refuses_the_whole_batch(db, mutate, reason):  # noqa: F811
    factory, _, _, pid = db
    with factory.begin() as session:
        good = family(session, pid)
    with factory() as session:
        before = counts(session)
        with pytest.raises(tool.Refused, match=reason):
            # the good entry first: nothing may be written once a later entry fails
            tool.enqueue(session, approved([mutate(good)]), apply=True, now=T0)
        session.rollback()
        assert counts(session) == before


def test_active_mapping_on_a_sibling_refuses(one):
    factory, entry = one
    with factory.begin() as session:
        source = session.scalars(select(Source).where(Source.name == "yuyutei")).one()
        session.add(SourceCardMapping(source_id=source.id, card_print_id=entry["considered_print_ids"][1],
                                      source_card_id="op01:99999", source_url="https://yuyu-tei.jp/sell/opc/card/op01/99999", is_active=True))
    with factory() as session:
        with pytest.raises(tool.Refused, match="active Yuyu mapping"):
            tool.enqueue(session, approved([entry]), apply=True, now=T0)


def test_any_other_capture_scope_refuses(one):
    from app.services.freshness_queue import plan_discovery_scope

    factory, entry = one
    with factory.begin() as session:
        source = session.scalars(select(Source).where(Source.name == "yuyutei")).one()
        plan_discovery_scope(session, source.id, f"yuyu-identity:{entry['candidate_id']}", due_at=T0)
    with factory() as session:
        with pytest.raises(tool.Refused, match="another capture scope"):
            tool.enqueue(session, approved([entry]), apply=True, now=T0)


def test_shared_print_between_entries_refuses(one):
    factory, entry = one
    twin = {**entry, "candidate_id": entry["candidate_id"] + 1}
    with factory() as session:
        with pytest.raises(tool.Refused, match="shared"):
            tool.enqueue(session, approved([entry, twin]), apply=False)


def test_list_is_pinned_and_strict(tmp_path):
    entry = {"candidate_id": 1, "evidence_digest": "a" * 64, "release_product_id": 2, "considered_print_ids": [3, 4]}
    path = tmp_path / "approved.json"
    path.write_text(json.dumps(approved([entry])))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert tool.load_list(path, digest)[1] == digest
    with pytest.raises(tool.Refused, match="SHA-256"):
        tool.load_list(path, "0" * 64)
    for bad in (
        {**approved([entry]), "expected_count": 2},
        approved([{**entry, "review_status": "approved"}]),
        approved([entry, entry]),
        approved([{**entry, "considered_print_ids": [4, 3]}]),
    ):
        path.write_text(json.dumps(bad))
        with pytest.raises(tool.Refused):
            tool.load_list(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_tool_is_outside_every_collector_runtime_and_writes_no_decisions():
    import collector_runtime_inputs as graph

    source = (ROOT / "scripts/yuyu_identity_capture_enqueue.py").read_text()
    for forbidden in ("review_status =", "approve_", "SourceCardMapping(", "resulting_source_card_mapping_id"):
        assert forbidden not in source
    for collector in graph.COLLECTORS:
        prefixes = graph.full_paths(collector)
        assert not any("scripts/yuyu_identity_capture_enqueue.py".startswith(p) for p in prefixes)
    for package in ("services/yuyutei_collector", "services/snkrdunk_collector", "services/api/app"):
        for module in (ROOT / package).rglob("*.py"):
            assert "yuyu_identity_capture_enqueue" not in module.read_text(), module
