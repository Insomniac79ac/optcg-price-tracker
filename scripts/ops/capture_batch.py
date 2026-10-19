"""Next Yuyu identity-capture batch (ops-write runbook `enqueue-capture-batch`).

The NEW100 plan is finished (work ids 3678 to 3777, never replayed), so this runbook builds the
next plan live instead of reading a committed one:

1. Candidates (read-only): Yuyu-Tei listings whose current proposal group is ambiguous, pending
   and unreviewed, with no capture scope of any kind (``yuyu-identity:<id>[:...]``), oldest
   candidate first.
2. One run of the live resolver (F1 included) over all of them. A listing it now resolves
   exactly is no longer an ambiguous family and drops out, so no capture is spent on a listing an
   F1 approval batch can map. The first ``2 * count`` ambiguous families with 2..12 siblings and
   an authoritative release form the plan.
3. From there it is enqueue-remaining-50: every guard of the PR #116 enqueue tool per candidate
   (ops.replan), the shared-print guard over the plan, the first ``count`` eligible pinned by
   SHA-256, the storage fit, and the tool's own checks. Dry run unless ``apply`` with the dry
   run's SHA-256.
It never approves, reviews or maps, never fetches a source and never triggers a job; the intents
are claimed by ordinary scheduled Yuyu turns under the source budget.
"""
from __future__ import annotations

import json

from ops import common

DEFAULT_COUNT = 50
MAX_SIBLINGS = 12  # services/yuyutei_collector/yuyutei_collector/identity_evidence.py

CANDIDATES_SQL = """
select g.source_candidate_id from source_mapping_proposal_groups g join sources s on s.id = g.source_id
where s.name = 'yuyutei' and g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  and g.review_status = 'pending' and g.resolution_status = 'ambiguous'
  and not exists (select 1 from freshness_work w where w.source_id = g.source_id
    and (w.scope_key = 'yuyu-identity:' || g.source_candidate_id
         or w.scope_key like 'yuyu-identity:' || g.source_candidate_id || ':%'))
  and not exists (select 1 from source_mapping_proposal_groups r where r.source_id = g.source_id
    and r.source_candidate_id = g.source_candidate_id and r.reviewed_at is not null)
order by g.source_candidate_id
"""


def check_count(count):
    count = DEFAULT_COUNT if count is None else count
    if type(count) is not int or not 1 <= count <= 100:
        raise common.Refused("count must be 1..100 (the enqueue tool's batch limit)")
    return count


def shortlist(candidate_ids, plans, limit):
    """Plan records for the first ``limit`` candidates whose live plan is a bounded ambiguous family."""
    records, dropped = [], {"not_ambiguous_now": 0, "unbounded_or_unreleased": 0}
    for cid in candidate_ids:
        plan = plans.get(cid)
        if plan is None or plan.resolution_status != "ambiguous":
            dropped["not_ambiguous_now"] += 1
            continue
        ids = sorted(a.card_print_id for a in plan.alternatives)
        if not 2 <= len(ids) <= MAX_SIBLINGS or plan.release_product_id is None:
            dropped["unbounded_or_unreleased"] += 1
            continue
        if len(records) < limit:
            records.append({"candidate_id": cid, "card_code": plan.card_code, "evidence_digest": plan.evidence_digest,
                            "considered_print_ids": ids})
    return records, dropped


def build_plan(session, count):
    """(plan, summary): the live plan, from one resolver run over every uncaptured ambiguous listing."""
    from sqlalchemy import text
    from app.services.source_mapping_proposals import ProposalFilters, analyse_source_mapping_proposals

    observed_at = session.execute(text("select now()")).scalar().isoformat()
    ids = [row[0] for row in session.execute(text(CANDIDATES_SQL))]
    if not ids:
        raise common.Refused("no uncaptured ambiguous Yuyu-Tei listing")
    analysis = analyse_source_mapping_proposals(
        session, ProposalFilters(source="yuyutei", candidate_ids=tuple(ids)),
        ignore_existing_mappings=True, build_report=False)
    plans = {o.candidate_id: o.proposal for o in analysis.outcomes if o.source_name == "yuyutei"}
    records, dropped = shortlist(ids, plans, 2 * count)
    session.rollback()
    summary = {"uncaptured_ambiguous_listings": len(ids), "dropped": dropped,
               "bounded_ambiguous_now": len(ids) - sum(dropped.values()), "planned": len(records)}
    return {"observed_at": observed_at, "records": records}, summary


def run(out_dir, *, apply=False, count=None, expected_sha256=""):
    from pathlib import Path
    from sqlalchemy.orm import Session
    from ops import db as ops_db, enqueue_remaining, replan

    count = check_count(count)
    out = Path(out_dir)
    with Session(ops_db.engine(statement_timeout_ms=300000)) as session:
        plan, candidates = build_plan(session, count)
        common.write_json(out / "plan.json", plan)
        replanned = replan.replan(session, plan)
    result = enqueue_remaining.enqueue_list(out, replanned, count, apply=apply, expected_sha256=expected_sha256,
                                            batch=f"capture-{count}")
    codes = {r["candidate_id"]: r.get("card_code") for r in plan["records"]}
    entries = json.loads((out / "approved-list.json").read_text())["entries"]
    # The exact batch for the owner's review: candidate, card code, official siblings to capture.
    batch = [[e["candidate_id"], codes.get(e["candidate_id"]), len(e["considered_print_ids"])] for e in entries]
    return {**result, "candidates": candidates, "batch": batch}
