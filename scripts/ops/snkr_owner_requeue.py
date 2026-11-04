"""snkr-owner-requeue: reopen SNKRDUNK refresh work the owner confirmed by photo (owner-gated).

Owner 2026-11-04 (plan B). The collector honours an owner photo confirmation
(snkrdunk_collector/owner_artwork.py, committed owner_artwork_confirmations.json) at capture time,
but quarantined work stays blocked until something reopens it. This reopens exactly the blocked
SNKRDUNK refresh items that

- were refused by the artwork check (last_failure starts artwork_not_confirmed_match),
- have a committed confirmation for the same mapping, the print the mapping is on now and the
  listing it names now, and
- still pass the queue's own eligibility and lineage checks (an approved, verified, active mapping
  whose print and listing are the ones the work was planned for).

Nothing else is touched: other refusals (release, code, rarity, an unreadable photo) and items
without a confirmation stay blocked. The collector re-checks every reopened item in full; the
confirmation only stands in for the matcher on the exact photo confirmed. Dry run by default; apply
re-plans under row locks and refuses unless the plan SHA equals the dry run's. No source request.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ops import common

COLLECTOR = Path(__file__).resolve().parents[2] / "services" / "snkrdunk_collector"
MARKER = "requeued after owner photo confirmation (owner 2026-11-04): "
PLAN_KEYS = ("work_ids",)


def plan_sha(p):
    return hashlib.sha256(json.dumps({k: p[k] for k in PLAN_KEYS}, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def committed_confirmations():
    import sys

    if str(COLLECTOR) not in sys.path:
        sys.path.insert(0, str(COLLECTOR))
    from snkrdunk_collector.owner_artwork import confirmations

    return confirmations()


def build_plan(session, confirmations=None, *, lock=False):
    """(plan, facts): blocked artwork refusals with a committed confirmation, still eligible."""
    from sqlalchemy import select

    from app.models import FreshnessWork, Source, SourceCardMapping
    from app.services import freshness_queue as queue

    confirmations = committed_confirmations() if confirmations is None else confirmations
    source_id = session.scalar(select(Source.id).where(Source.name == "snkrdunk"))
    if source_id is None:
        raise common.Refused("no snkrdunk source")
    query = select(FreshnessWork).where(
        FreshnessWork.source_id == source_id, FreshnessWork.kind == "refresh",
        FreshnessWork.state == "blocked", FreshnessWork.claim_token.is_(None),
        FreshnessWork.last_failure.like("artwork_not_confirmed_match%"),
    ).order_by(FreshnessWork.id)
    if lock:
        query = query.with_for_update()
    work_ids, skipped, seen = [], [], set()
    confirmed_mappings = {key[0] for key in confirmations}
    for work in session.scalars(query):
        if work.source_card_mapping_id not in confirmed_mappings:
            continue
        seen.add(work.source_card_mapping_id)
        mapping = session.get(SourceCardMapping, work.source_card_mapping_id)
        key = (mapping.id, mapping.card_print_id, mapping.canonical_source_listing_identity)
        if key not in confirmations:
            skipped.append({"work_id": work.id, "mapping_id": mapping.id,
                            "why": "confirmation names another print or listing"})
            continue
        try:
            queue._eligible_mapping(session, work.source_card_mapping_id)
        except ValueError as exc:
            skipped.append({"work_id": work.id, "mapping_id": mapping.id, "why": str(exc)[:120]})
            continue
        if mapping.card_print_id != work.card_print_id or mapping.canonical_source_listing_identity != work.product_identity:
            skipped.append({"work_id": work.id, "mapping_id": mapping.id, "why": "planned mapping lineage changed"})
            continue
        work_ids.append(work.id)
    plan = {"work_ids": work_ids}
    facts = {"confirmations": len(confirmations), "skipped": skipped,
             "confirmed_but_not_blocked": sorted(confirmed_mappings - seen)}
    return plan, facts


def default_preview():
    from sqlalchemy.orm import Session

    from ops import db as ops_db

    with Session(ops_db.engine(statement_timeout_ms=120000)) as session:
        try:
            return build_plan(session)
        finally:
            session.rollback()


def apply_plan(session, approved, confirmations=None, clock=None):
    """Re-plan under row locks; reopen exactly the approved work."""
    from datetime import datetime, timezone

    from app.models import FreshnessWork

    current, _ = build_plan(session, confirmations, lock=True)
    if plan_sha(current) != plan_sha(approved):
        raise ValueError("the requeue plan differs from the approved dry run")
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    for work_id in approved["work_ids"]:
        work = session.get(FreshnessWork, work_id)
        work.state = "pending"
        work.next_due_at = now
        work.retry_not_before_at = None
        work.last_failure = (MARKER + (work.last_failure or ""))[:500]
        work.last_failure_at = now
        work.updated_at = now
    session.flush()
    return {"reopened": list(approved["work_ids"])}


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
                raise common.Refused(f"snkr-owner-requeue refused: {exc}") from None
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
    summary = {"apply": bool(apply), "reopen": len(p["work_ids"]), "work_ids": p["work_ids"],
               "plan_sha256": sha, **facts, "source_requests": 0}
    common.write_json(Path(out_dir) / "snkr-owner-requeue.json", {**summary, "plan": p})
    if not p["work_ids"]:
        summary["ok"] = False
        summary["problems"] = ["no blocked artwork refusal has a committed owner confirmation"]
        if apply:
            raise common.Refused("nothing to reopen")
        return summary
    summary["ok"] = True
    if not apply:
        return summary
    check_apply(expected_sha256, sha)
    summary.update(written=(write or _write)(p),
                   next_step="next SNKRDUNK turns re-check the reopened items; db-diagnostic snkrdunk-quarantine")
    return summary
