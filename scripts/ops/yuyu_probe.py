"""yuyu-source-probe: authorize ONE Yuyu-Tei probe after a source denial pause (owner-gated).

Owner decision 2026-10-26 (perfectionist). One challenge page from Yuyu-Tei (2026-10-25 16:27Z)
paused every Yuyu-Tei shard (source_dispatch_budgets.pause_reason = source_denial, no timer).
Clearing the pause blindly could send up to nine shards into the same challenge. Instead:

1. Dry run (read-only): the Yuyu-Tei budget (must be paused for source_denial), the latest
   denial attempt (must come from ordinary refresh work, not an earlier probe), any probe already
   recorded for it, and the probe mapping: the approved, active Yuyu-Tei mapping whose refresh
   last succeeded most recently (a page known to capture cleanly). plan_sha256 covers source,
   denial, mapping, print and product identity.
2. apply=true with that SHA: re-reads the same facts, refuses unless the plan is identical, then
   calls app.services.source_recovery.plan_yuyu_probe in one transaction. It records one
   authorized, unattempted validation scope; it makes no request and reserves nothing.
3. The next scheduled Yuyu shard turn serves it (yuyutei_collector.recovery): one metered product
   capture from the collectors' own network, identity validated, no price written. Only a
   completed, identity-verified HTTP 200 capture clears the pause; a challenge keeps it paused
   and this authority can never be reused (a new denial needs a new dry run and approval).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ops import common

FACTS_SQL = """
select s.id source_id, b.enabled, b.pause_reason, b.paused_until, b.reserved_requests,
  b.used_requests, b.request_limit
from sources s join source_dispatch_budgets b on b.source_id = s.id where s.name = 'yuyutei'"""
DENIAL_SQL = """
select a.id attempt_id, a.finished_at, w.kind work_kind, w.id work_id, left(w.last_failure, 160) failure
from freshness_attempts a join freshness_work w on w.id = a.work_id
where w.source_id = %(source_id)s and a.outcome = 'source_denial' order by a.id desc limit 1"""
PROBE_SQL = """
select id, state, attempt_count, last_outcome, left(last_failure, 160) failure from freshness_work
where source_id = %(source_id)s and scope_key = %(scope)s"""
MAPPING_SQL = """
select m.id mapping_id, m.card_print_id, m.canonical_source_listing_identity product_identity,
  m.source_url, w.last_successfully_checked_at last_success
from freshness_work w
join source_card_mappings m on m.id = w.source_card_mapping_id
join card_prints p on p.id = m.card_print_id
where w.source_id = %(source_id)s and w.kind = 'refresh' and w.last_successfully_checked_at is not null
  and m.is_active and m.superseded_at is null and m.review_status = 'approved'
  and p.is_active and p.verification_status = 'verified'
  and m.canonical_source_listing_identity is not null
order by w.last_successfully_checked_at desc, m.id limit 1"""
PLAN_KEYS = ("source_id", "denial_attempt_id", "mapping_id", "card_print_id", "product_identity")


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def read_facts(conn):
    """The facts a probe plan rests on (read-only connection, dict rows)."""
    budget = conn.execute(FACTS_SQL).fetchone()
    if budget is None:
        raise common.Refused("no Yuyu-Tei source dispatch budget found")
    source_id = budget["source_id"]
    denial = conn.execute(DENIAL_SQL, {"source_id": source_id}).fetchone()
    mapping = conn.execute(MAPPING_SQL, {"source_id": source_id}).fetchone()
    existing = None
    if denial is not None:
        existing = conn.execute(PROBE_SQL, {"source_id": source_id,
                                            "scope": f"source-recovery:yuyutei:{denial['attempt_id']}"}).fetchone()
    return {"budget": dict(budget), "denial": dict(denial) if denial else None,
            "mapping": dict(mapping) if mapping else None, "existing_probe": dict(existing) if existing else None}


def plan(facts):
    """(plan dict, problems). A plan exists only when every precondition holds."""
    b, d, m = facts["budget"], facts["denial"], facts["mapping"]
    problems = []
    if not b["enabled"]:
        problems.append("Yuyu-Tei dispatch is disabled")
    if b["pause_reason"] != "source_denial" or b["paused_until"] is not None:
        problems.append(f"Yuyu-Tei is not paused for a source denial (pause_reason={b['pause_reason']!r})")
    if d is None:
        problems.append("no source_denial attempt recorded")
    elif d["work_kind"] != "refresh":
        problems.append("the latest denial came from a probe; a probe's own denial cannot authorize another")
    if facts["existing_probe"] is not None:
        problems.append("a probe for this denial already exists (never replayed)")
    if m is None:
        problems.append("no approved Yuyu-Tei mapping with a past successful refresh")
    if b["reserved_requests"]:
        problems.append("Yuyu-Tei has reserved requests outstanding")
    if problems:
        return None, problems
    return {"source_id": b["source_id"], "denial_attempt_id": d["attempt_id"], "mapping_id": m["mapping_id"],
            "card_print_id": m["card_print_id"], "product_identity": m["product_identity"]}, []


def plan_sha(p):
    return hashlib.sha256(json.dumps({k: p[k] for k in PLAN_KEYS}, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def check_apply(expected_sha256, sha):
    if not (isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)):
        raise common.Refused("apply needs expected_sha256: the plan SHA-256 from a dry run")
    if expected_sha256 != sha:
        raise common.Refused("the plan differs from the dry run's (expected_sha256); dry run again")


def _summary(facts, p, problems, sha):
    d, m = facts["denial"] or {}, facts["mapping"] or {}
    return {"paused_for": facts["budget"]["pause_reason"],
            "denial": {"attempt_id": d.get("attempt_id"), "at": _iso(d.get("finished_at")),
                       "work_kind": d.get("work_kind"), "failure": d.get("failure")},
            "probe_mapping": {"mapping_id": m.get("mapping_id"), "card_print_id": m.get("card_print_id"),
                              "source_url": m.get("source_url"), "last_success": _iso(m.get("last_success"))},
            "existing_probe": facts["existing_probe"], "problems": problems, "plan_sha256": sha,
            "source_requests": 0}


def run(out_dir, *, apply=False, expected_sha256="", read=None, write=None):
    from ops import db as ops_db

    def default_read():
        with ops_db.connection() as conn:
            facts = read_facts(conn)
            conn.rollback()
        return facts

    facts = (read or default_read)()
    p, problems = plan(facts)
    sha = plan_sha(p) if p else None
    summary = _summary(facts, p, problems, sha)
    summary["apply"] = bool(apply)
    common.write_json(Path(out_dir) / "yuyu-source-probe.json", {**summary, "facts": facts})
    if problems:
        summary["ok"] = False
        if apply:
            raise common.Refused("no probe can be planned: " + "; ".join(problems))
        return summary
    if not apply:
        summary["ok"] = True
        return summary
    check_apply(expected_sha256, sha)
    work_id = (write or _write_plan)(p)
    summary.update(ok=True, probe_work_id=work_id, written=1,
                   next_step="the next scheduled Yuyu-Tei shard turn serves the probe (at most 30 minutes)")
    return summary


def _write_plan(p):
    """plan_yuyu_probe in one transaction on the verified staging database."""
    from sqlalchemy.orm import Session
    from ops import apply_migration, db as ops_db
    from app.services.source_recovery import plan_yuyu_probe

    with ops_db.connection() as conn:  # fingerprint and revision-equals-head check first
        facts = read_facts(conn)
        conn.rollback()
    again, problems = plan(facts)
    if problems or plan_sha(again) != plan_sha(p):
        raise common.Refused("the facts changed between the plan and the write; dry run again")
    engine, _guard = apply_migration.staging_engine(writable=True)
    try:
        with Session(engine) as session:
            try:
                work = plan_yuyu_probe(session, p["source_id"], p["mapping_id"], p["denial_attempt_id"])
                work_id = work.id
                session.commit()
            except ValueError as exc:
                session.rollback()
                raise common.Refused(f"plan_yuyu_probe refused: {exc}") from None
    finally:
        engine.dispose()
    return work_id
