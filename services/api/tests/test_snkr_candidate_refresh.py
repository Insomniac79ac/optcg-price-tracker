"""snkr-candidate-refresh (scripts/ops/snkr_candidate_refresh.py): SNKRDUNK listings with no set
code or no proposal get both, through the collector's own evidence reading and discovery's own
proposal persistence; nothing else is touched (owner 2026-11-03, perfectionist)."""

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import SnkrdunkCandidate, SourceCardMapping, SourceMappingProposalGroup

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from ops import snkr_candidate_refresh as scr  # noqa: E402


def _candidate(db, product_id, title, *, set_code=None, rarity=None):
    row = SnkrdunkCandidate(source_url=f"https://snkrdunk.com/apparels/{product_id}", title=title,
                            detected_card_code="OP08-002", detected_set_code=set_code,
                            detected_rarity=rarity, match_status="unmatched")
    db.add(row)
    db.flush()
    return row


def scenario(db):
    from tests.test_source_mapping_proposals import _base, _snk_family

    _, snk = _base(db)
    _, family, prints = _snk_family(db, code="OP08-002")
    new = _candidate(db, 900001, 'Marco L-P [OP08-002](Booster Pack "Two Legends")', rarity="L-P")
    unknown = _candidate(db, 900002, "Marco L [OP08-002] (Booster Pack 500 Yeas in the Future)", rarity="L")
    mapped = _candidate(db, 900003, 'Marco L [OP08-002](Booster Pack "Two Legends")', set_code="OP-08", rarity="L")
    db.add(SourceCardMapping(source_id=snk.id, card_print_id=prints["base"].id, source_card_id="900003",
                             source_url="https://snkrdunk.com/apparels/900003",
                             canonical_source_listing_identity="900003", is_active=True,
                             manual_verified=True, review_status="approved"))
    db.commit()
    return new, unknown, mapped, prints


def groups(db, cid):
    return db.scalars(select(SourceMappingProposalGroup).where(
        SourceMappingProposalGroup.source_candidate_type == "snkrdunk_candidate",
        SourceMappingProposalGroup.source_candidate_id == cid,
        SourceMappingProposalGroup.superseded_at.is_(None))).all()


def test_plan_sets_codes_only_where_empty_and_targets_listings_without_proposal_or_mapping(db_session):
    new, unknown, mapped, _ = scenario(db_session)
    plan, facts = scr.build_plan(db_session)
    assert plan == {"set_codes": [[new.id, "OP-08"]], "targets": [new.id, unknown.id]}
    assert facts["set_codes_by_release"] == {"OP-08": 1}
    assert facts["targets_without_set_code"] == [("Booster Pack 500 Yeas in the Future", 1)]


def test_apply_writes_the_code_and_persists_proposals(db_session):
    new, unknown, mapped, prints = scenario(db_session)
    plan, _ = scr.build_plan(db_session)
    result = scr.apply_plan(db_session, plan)
    db_session.commit()
    assert db_session.get(SnkrdunkCandidate, new.id).detected_set_code == "OP-08"
    assert db_session.get(SnkrdunkCandidate, unknown.id).detected_set_code is None
    assert result["created"] == 2
    group = groups(db_session, new.id)[0]
    assert group.resolution_status == "exact"  # "L-P" names the one parallel print of OP-08
    assert groups(db_session, unknown.id)[0].resolution_status != "exact"
    assert groups(db_session, mapped.id) == []
    # Nothing left to do: a second plan is empty.
    assert scr.build_plan(db_session)[0] == {"set_codes": [], "targets": []}


def test_a_stored_code_is_never_overwritten(db_session):
    from tests.test_source_mapping_proposals import _base

    _base(db_session)
    wrong = _candidate(db_session, 900004, 'Marco L [OP08-002](Booster Pack "Two Legends")', set_code="OP-05")
    db_session.commit()
    plan, facts = scr.build_plan(db_session)
    assert plan["set_codes"] == [] and facts["stored_code_disagreements"] == [[wrong.id, "OP-05", "OP-08"]]


def test_apply_refuses_a_plan_that_no_longer_matches(db_session):
    new, *_ = scenario(db_session)
    plan, _ = scr.build_plan(db_session)
    stale = {**plan, "targets": plan["targets"][:1]}
    with pytest.raises(ValueError, match="differs"):
        scr.apply_plan(db_session, stale)
    assert db_session.get(SnkrdunkCandidate, new.id).detected_set_code is None


def test_run_is_a_dry_run_by_default_and_apply_needs_the_sha(tmp_path):
    from ops import common

    plan = {"set_codes": [[7, "OP-08"]], "targets": [7]}
    facts = {"candidates": 1, "set_codes_by_release": {"OP-08": 1}, "stored_code_disagreements": [],
             "disagreement_count": 0, "targets_without_set_code": []}
    written = []
    out = scr.run(tmp_path, preview=lambda: (plan, facts), write=written.append)
    assert out["ok"] and out["targets"] == 1 and written == []
    with pytest.raises(common.Refused):
        scr.run(tmp_path, apply=True, expected_sha256="0" * 64, preview=lambda: (plan, facts), write=written.append)
    scr.run(tmp_path, apply=True, expected_sha256=out["plan_sha256"], preview=lambda: (plan, facts),
            write=lambda p: written.append(p) or {"created": 1})
    assert written == [plan]
