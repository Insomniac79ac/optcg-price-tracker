"""approve-snkr-batch (scripts/ops/f1_approve.py, source snkrdunk; owner 2026-11-01): SNKRDUNK
proposals the title-kind rule made exact are selected with every approve-f1-batch guard and become
mappings through the admin approval path."""

import sys
from pathlib import Path

from sqlalchemy import select

from app.models import SourceCardMapping
from app.services.source_mapping_proposals import analyse_source_mapping_proposals, persist_proposals

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from ops import f1_approve  # noqa: E402


def _stored_exact(db_session):
    from tests.test_source_mapping_proposals import _base, _snk, _snk_family

    _base(db_session)
    _, family, prints = _snk_family(db_session)
    plain = _snk(db_session, 1, family.card_code, f"Nami R [{family.card_code}] (Booster Pack)", "R")
    parallel = _snk(db_session, 2, family.card_code, f"Nami R-P [{family.card_code}] (Booster Pack)", "R-P")
    db_session.commit()
    persist_proposals(db_session, analyse_source_mapping_proposals(db_session, build_report=False).plans)
    db_session.commit()
    return prints, plain, parallel


def test_selects_only_snkrdunk_title_kind_groups_and_approves_them(db_session):
    prints, plain, parallel = _stored_exact(db_session)
    eligible, excluded = f1_approve.select_batch(db_session, "snkrdunk")
    assert excluded == {}
    by_candidate = {e["source_candidate_id"]: e for e in eligible}
    assert by_candidate[plain.id]["card_print_id"] == prints["base"].id
    assert by_candidate[parallel.id]["card_print_id"] == prints["p1"].id
    assert {e["detail"]["rule"] for e in eligible} == {"snkr_title_kind"}
    assert {e["detail"]["listing_kind"] for e in eligible} == {"plain", "parallel"}
    # The Yuyu-Tei batch never picks a SNKRDUNK group.
    assert f1_approve.select_batch(db_session, "yuyutei") == ([], {})

    _, sha, doc = f1_approve.pinned_list(eligible, 10, "snkrdunk")
    assert doc["runbook"] == "approve-snkr-batch" and len(sha) == 64
    approved, stopped = f1_approve.approve(db_session, doc["entries"], run_label="test:approve-snkr-batch",
                                           now=lambda: __import__("datetime").datetime(2026, 11, 1, 12, 0,
                                                                                      tzinfo=__import__("datetime").timezone.utc))
    assert stopped is None and len(approved) == 2
    mapped = {m.card_print_id for m in db_session.scalars(select(SourceCardMapping)).all()}
    assert mapped == {prints["base"].id, prints["p1"].id}


def test_the_approval_gate_narrows_by_title_kind_and_never_widens(db_session):
    import pytest
    from app.services.exact_print_approval import ExactPrintApprovalError, SourceEvidence, resolve_exact_print
    from tests.test_source_mapping_proposals import _base, _snk, _snk_family

    _base(db_session)
    _, family, prints = _snk_family(db_session)
    parallel = _snk(db_session, 7, family.card_code, f"Nami R-P [{family.card_code}] (Booster Pack)", "R-P")
    comic = _snk(db_session, 8, family.card_code, f"Nami R-SP (Comic Parallel) [{family.card_code}] (Booster Pack)", "R-SP")
    db_session.commit()
    evidence = SourceEvidence.from_snkrdunk_candidate(parallel)
    assert evidence.listing_kind == "parallel"
    assert resolve_exact_print(db_session, card_print_id=prints["p1"].id, evidence=evidence).card_print.id == prints["p1"].id
    with pytest.raises(ExactPrintApprovalError):  # the title says parallel; the base contradicts it
        resolve_exact_print(db_session, card_print_id=prints["base"].id, evidence=evidence)
    with pytest.raises(ExactPrintApprovalError):  # no title kind: still indistinguishable
        resolve_exact_print(db_session, card_print_id=prints["p1"].id,
                            evidence=SourceEvidence.from_snkrdunk_candidate(comic))
