"""proposal-refresh (scripts/ops/proposal_refresh.py): stored ambiguous Yuyu-Tei groups that a
physical artwork review now resolves are refreshed through discovery's own path; nothing else is.

Owner 2026-10-31 (perfectionist): the 13 reviews of #242 validate but their stored groups stayed
ambiguous, and approve-f1-batch reads stored exact groups only."""

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import SourceMappingProposalGroup
from app.services import physical_artwork_proof as proof_module
from app.services.source_mapping_proposals import analyse_source_mapping_proposals, persist_proposals

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from ops import proposal_refresh as pr  # noqa: E402


def scenario(db_session, monkeypatch):
    from tests.test_source_mapping_proposals import _base, _family, _print, _release, _run, _yuyu

    _base(db_session)
    release = _release(db_session, "OP-01")
    reviewed, other = _family(db_session, "OP01-120"), _family(db_session, "OP01-121")
    _print(db_session, reviewed, release)
    selected = _print(db_session, reviewed, release, "p1")
    _print(db_session, other, release)
    _print(db_session, other, release, "p1")
    run = _run(db_session, "op01")
    cand = _yuyu(db_session, run, "op01", 10151, reviewed.card_code)
    untouched = _yuyu(db_session, run, "op01", 10152, other.card_code)
    db_session.commit()
    # Discovery stored both as ambiguous before any review existed.
    persist_proposals(db_session, analyse_source_mapping_proposals(db_session, build_report=False).plans)
    db_session.commit()

    def resolve(session, plan, siblings):
        return (selected.id, "review-digest", "claude:test-review") if plan.source_candidate_id == cand.id else None

    monkeypatch.setattr(proof_module, "resolve", resolve)
    return cand, untouched, selected


def current(db_session, cid):
    return db_session.scalars(select(SourceMappingProposalGroup).where(
        SourceMappingProposalGroup.source_candidate_id == cid,
        SourceMappingProposalGroup.superseded_at.is_(None))).one()


def test_only_the_reviewed_group_is_planned_and_refreshed_to_exact(db_session, monkeypatch):
    cand, untouched, selected = scenario(db_session, monkeypatch)
    plan, facts = pr.build_plan(db_session)
    assert [c["candidate_id"] for c in plan["candidates"]] == [cand.id]
    assert plan["candidates"][0]["selected_card_print_id"] == selected.id
    assert facts["ambiguous_pending_groups"] == 2 and facts["left_as_is"] == {"ambiguous": 1}
    before_untouched = current(db_session, untouched.id).id

    result = pr.apply_plan(db_session, plan)
    db_session.commit()

    assert result["resolutions"] == {"exact": 1}
    group = current(db_session, cand.id)
    assert group.resolution_status == "exact" and group.review_status == "pending"
    assert pr.REVIEW_REASON in group.resolution_reasons_json
    assert current(db_session, untouched.id).id == before_untouched  # not refreshed


def test_apply_refuses_a_plan_that_no_longer_matches(db_session, monkeypatch):
    cand, _, _ = scenario(db_session, monkeypatch)
    plan, _ = pr.build_plan(db_session)
    stale = {**plan, "candidates": [{**plan["candidates"][0], "new_digest": "0" * 64}]}
    with pytest.raises(ValueError, match="differs"):
        pr.apply_plan(db_session, stale)
    assert current(db_session, cand.id).resolution_status == "ambiguous"


def test_run_is_a_dry_run_by_default_and_apply_needs_the_sha(tmp_path):
    plan = {"source_id": 1, "candidates": [{"candidate_id": 7, "new_digest": "a" * 64, "selected_card_print_id": 9}]}
    facts = {"ambiguous_pending_groups": 3, "left_as_is": {"ambiguous": 2}, "resolved_by_review_now": []}
    written = []
    out = pr.run(tmp_path, preview=lambda: (plan, facts), write=written.append)
    assert out["ok"] and out["refresh"] == 1 and written == []
    from ops import common
    with pytest.raises(common.Refused):
        pr.run(tmp_path, apply=True, expected_sha256="0" * 64, preview=lambda: (plan, facts), write=written.append)
    pr.run(tmp_path, apply=True, expected_sha256=out["plan_sha256"], preview=lambda: (plan, facts),
           write=lambda p: written.append(p) or {"resolutions": {"exact": 1}})
    assert written == [plan]
    empty = pr.run(tmp_path, preview=lambda: ({"source_id": 1, "candidates": []}, facts))
    assert empty["ok"] is False
