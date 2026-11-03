"""snkr-candidate-refresh: set codes and proposals for SNKRDUNK listings that have none.

Owner 2026-11-03 (perfectionist, fix 3). The 37 listings the seeds reached on 2026-11-02 and 03
were stored with no set code (the label tables knew only OP-01 to OP-04 and EB-01) and no proposal
(SNKRDUNK discovery never created proposals; the existing ones came from a one-off run). The label
tables now carry the Bandai-proven titles (docs/agent/evidence/bandai-label-evidence-20261103.json)
and discovery now creates proposals for new listings; this runbook catches up the backlog:

1. Plan (read-only): every stored SNKRDUNK candidate is re-read with the collector's own
   evidence_from_listing (the stored title and image URL, the only inputs discovery ever reads; no
   page fetch). A candidate whose stored set code is empty and now resolves gets that code; a
   stored code is never overwritten (a disagreement is counted, not changed). Targets for proposals:
   every candidate with a new set code, and every candidate with no current proposal group whose
   listing has no active mapping. The plan pins both lists with a SHA-256.
2. Dry run by default. apply re-plans in the write transaction, refuses unless the SHA equals the
   dry run's, writes the set codes, then calls refresh_discovery_proposals (discovery's own
   persistence: reviewed groups are preserved) for exactly the targets. One transaction; no source
   request, no mapping (approve-snkr-batch does that next, owner-gated).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ops import common

COLLECTOR = Path(__file__).resolve().parents[2] / "services" / "snkrdunk_collector"
LISTING = re.compile(r"^https://snkrdunk\.com/(?:apparels|en/trading-cards)/([0-9]+)")
PLAN_KEYS = ("set_codes", "targets")


def plan_sha(p):
    return hashlib.sha256(json.dumps({k: p[k] for k in PLAN_KEYS}, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _evidence():
    import sys

    if str(COLLECTOR) not in sys.path:
        sys.path.insert(0, str(COLLECTOR))
    from snkrdunk_collector.discovery_evidence.snkrdunk_listing_evidence import evidence_from_listing

    return evidence_from_listing


def build_plan(session, evidence_from_listing=None):
    """(plan, facts). plan: set_codes [[candidate id, code]] and targets [candidate ids], sorted."""
    from sqlalchemy import select

    from app.models import SnkrdunkCandidate, Source, SourceCardMapping, SourceMappingProposalGroup

    evidence_from_listing = evidence_from_listing or _evidence()
    source = session.scalar(select(Source).where(Source.name == "snkrdunk"))
    if source is None:
        raise common.Refused("no snkrdunk source")
    candidates = session.scalars(select(SnkrdunkCandidate).order_by(SnkrdunkCandidate.id)).all()
    grouped = set(session.scalars(select(SourceMappingProposalGroup.source_candidate_id).where(
        SourceMappingProposalGroup.source_candidate_type == "snkrdunk_candidate",
        SourceMappingProposalGroup.superseded_at.is_(None))))
    mapped = {m for m in session.scalars(select(SourceCardMapping.canonical_source_listing_identity).where(
        SourceCardMapping.source_id == source.id, SourceCardMapping.is_active.is_(True),
        SourceCardMapping.superseded_at.is_(None))) if m}
    set_codes, targets, disagree, unresolved_labels = [], set(), [], {}
    for c in candidates:
        ev = evidence_from_listing(c.source_url, c.title, c.image_url)
        code = ev.resolved_product_code
        if c.detected_set_code is None and code is not None:
            set_codes.append([c.id, code])
            targets.add(c.id)
        elif c.detected_set_code is not None and code is not None and code != c.detected_set_code:
            disagree.append([c.id, c.detected_set_code, code])
        m = LISTING.match(c.source_url or "")
        if c.id not in grouped and not (m and m.group(1) in mapped):
            targets.add(c.id)
            if code is None and ev.product_label:
                unresolved_labels[ev.product_label] = unresolved_labels.get(ev.product_label, 0) + 1
    plan = {"set_codes": set_codes, "targets": sorted(targets)}
    by_code = {}
    for _, code in set_codes:
        by_code[code] = by_code.get(code, 0) + 1
    facts = {"candidates": len(candidates), "set_codes_by_release": dict(sorted(by_code.items())),
             "stored_code_disagreements": disagree[:20], "disagreement_count": len(disagree),
             "targets_without_set_code": sorted(unresolved_labels.items(), key=lambda kv: -kv[1])[:20]}
    return plan, facts


def default_preview():
    from sqlalchemy.orm import Session

    from ops import db as ops_db

    with Session(ops_db.engine(statement_timeout_ms=300000)) as session:
        try:
            return build_plan(session)
        finally:
            session.rollback()


def apply_plan(session, approved, evidence_from_listing=None):
    """Re-plan in this transaction, write the approved set codes, refresh the approved targets."""
    from app.models import SnkrdunkCandidate
    from app.services.discovery_proposal_refresh import refresh_discovery_proposals

    current, _ = build_plan(session, evidence_from_listing)
    if plan_sha(current) != plan_sha(approved):
        raise ValueError("the plan differs from the approved dry run")
    for cid, code in approved["set_codes"]:
        candidate = session.get(SnkrdunkCandidate, cid)
        if candidate.detected_set_code is not None:
            raise ValueError(f"candidate {cid} gained a set code since the plan")
        candidate.detected_set_code = code
    session.flush()
    return refresh_discovery_proposals(session, "snkrdunk", approved["targets"])


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
                raise common.Refused(f"snkr-candidate-refresh refused: {exc}") from None
    finally:
        engine.dispose()
    return result


def check_apply(expected_sha256, sha):
    if not (isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)):
        raise common.Refused("apply needs expected_sha256: the plan SHA-256 from a dry run")
    if expected_sha256 != sha:
        raise common.Refused("the plan differs from the dry run's (expected_sha256); dry run again")


def run(out_dir, *, apply=False, expected_sha256="", preview=None, write=None):
    p, facts = (preview or default_preview)()
    sha = plan_sha(p)
    summary = {"apply": bool(apply), "set_codes": len(p["set_codes"]), "targets": len(p["targets"]),
               "plan_sha256": sha, **facts, "source_requests": 0}
    common.write_json(Path(out_dir) / "snkr-candidate-refresh.json", {**summary, "plan": p})
    if not p["targets"]:
        summary["ok"] = False
        summary["problems"] = ["no SNKRDUNK candidate needs a set code or a proposal"]
        if apply:
            raise common.Refused("nothing to refresh")
        return summary
    summary["ok"] = True
    if not apply:
        return summary
    check_apply(expected_sha256, sha)
    result = (write or _write)(p)
    summary.update(written=result, next_step="approve-snkr-batch dry run: exact title-kind groups are approvable")
    return summary
