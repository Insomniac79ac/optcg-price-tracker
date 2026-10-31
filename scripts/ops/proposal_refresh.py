"""proposal-refresh: refresh stored Yuyu-Tei proposals a physical artwork review now resolves.

Owner 2026-10-31 (perfectionist). A merged review resolves a listing only in a fresh resolver run;
the stored proposal group stays "ambiguous" until Yuyu-Tei discovery revisits that listing and
refreshes it, and approve-f1-batch reads stored "exact" groups only. The 13 Claude reviews of #242
validate (identity-proof-check, 2026-10-31: zero refusals) but still sit as ambiguous groups.

1. Plan (read-only): current, pending, ambiguous Yuyu-Tei groups whose fresh resolver run (the
   discovery path, refresh_discovery_proposals' own filters) is exact by reason
   retained_positive_unique_physical_artwork_review. Nothing else is touched: another ambiguous
   group stays as discovery left it. The plan pins each candidate with its new evidence digest and
   selected print, and its SHA-256.
2. Dry run by default. apply re-plans in the write transaction, refuses unless the SHA equals the
   dry run's, and calls refresh_discovery_proposals (discovery's own persistence) for exactly those
   candidates, then checks every refreshed group is exact. One transaction; no source request, no
   mapping (approve-f1-batch does that next, as the identity review pipeline says).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ops import common

REVIEW_REASON = "retained_positive_unique_physical_artwork_review"
PLAN_KEYS = ("source_id", "candidates")


def plan_sha(p):
    return hashlib.sha256(json.dumps({k: p[k] for k in PLAN_KEYS}, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def build_plan(session):
    """(plan, facts): ambiguous pending groups a review now resolves, from one fresh resolver run."""
    from sqlalchemy import select

    from app.models import SourceMappingProposalGroup
    from app.services.source_mapping_proposals import ProposalFilters, analyse_source_mapping_proposals
    from app.services.yuyutei_candidate_approval import get_yuyutei_source

    source = get_yuyutei_source(session)
    groups = session.scalars(select(SourceMappingProposalGroup).where(
        SourceMappingProposalGroup.source_id == source.id,
        SourceMappingProposalGroup.source_candidate_type == "yuyutei_candidate",
        SourceMappingProposalGroup.superseded_at.is_(None),
        SourceMappingProposalGroup.review_status == "pending",
        SourceMappingProposalGroup.resolution_status == "ambiguous",
    ).order_by(SourceMappingProposalGroup.source_candidate_id)).all()
    by_candidate = {g.source_candidate_id: g for g in groups}
    plans = {}
    if by_candidate:
        # The same call refresh_discovery_proposals makes (existing mappings respected).
        analysis = analyse_source_mapping_proposals(
            session, ProposalFilters(source="yuyutei", candidate_ids=tuple(sorted(by_candidate))),
            build_report=False)
        plans = {p.source_candidate_id: p for p in analysis.plans}
    candidates, still = [], {}
    for cid, group in by_candidate.items():
        p = plans.get(cid)
        if p is None:
            still["no_plan_now"] = still.get("no_plan_now", 0) + 1
        elif p.resolution_status != "exact" or REVIEW_REASON not in p.resolution_reasons:
            key = f"{p.resolution_status}"
            still[key] = still.get(key, 0) + 1
        else:
            selected = [a.card_print_id for a in p.alternatives if a.recommended]
            candidates.append({"candidate_id": cid, "card_code": p.card_code,
                               "listing": p.canonical_source_listing_identity,
                               "stored_group_id": group.id, "stored_digest": group.evidence_digest[:12],
                               "new_digest": p.evidence_digest, "selected_card_print_id": selected[0] if len(selected) == 1 else None})
    plan = {"source_id": source.id, "candidates": [
        {"candidate_id": c["candidate_id"], "new_digest": c["new_digest"],
         "selected_card_print_id": c["selected_card_print_id"]} for c in candidates]}
    facts = {"ambiguous_pending_groups": len(groups), "resolved_by_review_now": candidates,
             "left_as_is": still}
    return plan, facts


def default_preview():
    from sqlalchemy.orm import Session

    from ops import db as ops_db

    with Session(ops_db.engine(statement_timeout_ms=300000)) as session:
        try:
            return build_plan(session)
        finally:
            session.rollback()


def check_apply(expected_sha256, sha):
    if not (isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)):
        raise common.Refused("apply needs expected_sha256: the plan SHA-256 from a dry run")
    if expected_sha256 != sha:
        raise common.Refused("the plan differs from the dry run's (expected_sha256); dry run again")


def apply_plan(session, approved):
    """Re-plan in this transaction, refresh exactly the approved candidates, check they are exact."""
    from app.services.discovery_proposal_refresh import refresh_discovery_proposals

    current, _ = build_plan(session)
    if plan_sha(current) != plan_sha(approved):
        raise ValueError("the refresh plan differs from the approved dry run")
    ids = [c["candidate_id"] for c in approved["candidates"]]
    result = refresh_discovery_proposals(session, "yuyutei", ids)
    if result["resolutions"] != ({"exact": len(ids)} if ids else {}):
        raise ValueError(f"refresh did not make every approved group exact: {result['resolutions']}")
    return result


def _write(p):
    from sqlalchemy.orm import Session

    from ops import apply_migration, db as ops_db

    engine, guard = apply_migration.staging_engine(writable=True)
    try:
        raw = engine.raw_connection()
        try:
            raw.driver_connection.read_only = True
            ops_db.verify(raw.driver_connection, guard)
        finally:
            raw.close()
        with Session(engine) as session:
            try:
                result = apply_plan(session, p)
                session.commit()
            except ValueError as exc:
                session.rollback()
                raise common.Refused(f"proposal-refresh refused: {exc}") from None
    finally:
        engine.dispose()
    return result


def run(out_dir, *, apply=False, expected_sha256="", preview=None, write=None):
    p, facts = (preview or default_preview)()
    sha = plan_sha(p)
    summary = {"apply": bool(apply), "refresh": len(p["candidates"]), "plan_sha256": sha,
               "ambiguous_pending_groups": facts["ambiguous_pending_groups"],
               "left_as_is": facts["left_as_is"], "candidates": facts["resolved_by_review_now"],
               "source_requests": 0}
    common.write_json(Path(out_dir) / "proposal-refresh.json", {**summary, "plan": p})
    if not p["candidates"]:
        summary["ok"] = False
        summary["problems"] = ["no stored ambiguous group is resolved by a review now"]
        if apply:
            raise common.Refused("nothing to refresh")
        return summary
    summary["ok"] = True
    if not apply:
        return summary
    check_apply(expected_sha256, sha)
    result = (write or _write)(p)
    summary.update(written=result, next_step="approve-f1-batch dry run: the refreshed groups are exact by review")
    return summary
