"""Next Yuyu identity-capture batch (ops-write `enqueue-capture-batch`, ops-readonly `capture-batch-preview`).

The NEW100 plan is finished (work ids 3678 to 3777, never replayed), so this runbook builds the
next plan live instead of reading a committed one:

1. Population (read-only): Yuyu-Tei listings whose current proposal group is ambiguous and
   pending. Each is excluded for one reason, first match wins: a reviewed decision, a blocked
   capture, an attempted capture, a queued capture (scope ``yuyu-identity:<id>[:...]``). The
   rest are uncaptured, oldest candidate first.
2. One run of the live resolver (F1 included) over every uncaptured listing. A listing it now
   resolves exactly is no longer an ambiguous family and drops out, so no capture is spent on a
   listing an F1 approval batch can map. Every remaining ambiguous family with 2..12 siblings and
   an authoritative release is planned; none is cut off by the batch size.
3. Every guard of the PR #116 enqueue tool per planned candidate (ops.replan). The shared-print
   guard runs in plan order: a candidate is eligible when its other guards pass and no earlier
   eligible candidate holds one of its prints, so eligible candidates never share a print and
   any prefix of them is a valid batch.
4. ``count`` means "up to": the batch is the first min(count, eligible) eligible candidates,
   pinned by SHA-256, with the storage fit and the tool's own checks. Nothing eligible is the one
   refusal of the plan; an apply refuses only when its re-planned list's SHA-256 differs from the
   dry run's. Dry run unless ``apply``.

Before 2026-10-19 the batch size also bounded step 3 (only the first 2 * count were judged), so
a smaller count judged fewer candidates and found fewer eligible (12 of 100, then 9 of 24).

``preview`` is the same plan over a read-only session with every candidate judged, for the
exclusion breakdown without an owner approval; its SHA-256 equals a dry run's on the same state.
It never approves, reviews or maps, never fetches a source and never triggers a job; the intents
are claimed by ordinary scheduled Yuyu turns under the source budget.
"""
from __future__ import annotations

import json
from collections import Counter

from ops import common

DEFAULT_COUNT = 50
MAX_COUNT = 100  # the enqueue tool's batch limit
MAX_SIBLINGS = 12  # services/yuyutei_collector/yuyutei_collector/identity_evidence.py
SHARED = "no_shared_print_with_other_planned"

_SCOPE = """from freshness_work w where w.source_id = g.source_id
    and (w.scope_key = 'yuyu-identity:' || g.source_candidate_id
         or w.scope_key like 'yuyu-identity:' || g.source_candidate_id || ':%')"""
POPULATION_SQL = f"""
select g.source_candidate_id, case
  when exists (select 1 from source_mapping_proposal_groups r where r.source_id = g.source_id
    and r.source_candidate_id = g.source_candidate_id and r.reviewed_at is not null) then 'reviewed_decision'
  when exists (select 1 {_SCOPE} and w.state = 'blocked') then 'capture_blocked'
  when exists (select 1 {_SCOPE} and w.attempt_count > 0) then 'already_captured'
  when exists (select 1 {_SCOPE}) then 'capture_queued'
  else 'uncaptured' end
from source_mapping_proposal_groups g join sources s on s.id = g.source_id
where s.name = 'yuyutei' and g.source_candidate_type = 'yuyutei_candidate' and g.superseded_at is null
  and g.review_status = 'pending' and g.resolution_status = 'ambiguous'
order by g.source_candidate_id
"""


def check_count(count):
    count = DEFAULT_COUNT if count is None else count
    if type(count) is not int or not 1 <= count <= MAX_COUNT:
        raise common.Refused(f"count must be 1..{MAX_COUNT} (the enqueue tool's batch limit)")
    return count


def shortlist(candidate_ids, plans):
    """(records, dropped): plan records for every candidate whose live plan is a bounded ambiguous family."""
    records, dropped = [], Counter()
    for cid in candidate_ids:
        plan = plans.get(cid)
        if plan is None:
            dropped["no_current_plan"] += 1
            continue
        if plan.resolution_status == "exact":
            # The first reason names the rule (F1's listing-kind and special-rarity rules among them).
            dropped["exact_now:" + (plan.resolution_reasons[0] if plan.resolution_reasons else "-")] += 1
            continue
        if plan.resolution_status != "ambiguous":
            dropped["resolved_since:" + str(plan.resolution_status)] += 1
            continue
        ids = sorted(a.card_print_id for a in plan.alternatives)
        if not 2 <= len(ids) <= MAX_SIBLINGS:
            dropped["unbounded_siblings"] += 1
            continue
        if plan.release_product_id is None:
            dropped["no_release"] += 1
            continue
        records.append({"candidate_id": cid, "card_code": plan.card_code, "evidence_digest": plan.evidence_digest,
                        "considered_print_ids": ids})
    return records, dict(dropped)


def choose(rows, held=None):
    """Shared-print guard in plan order, then eligibility (pure; sets both on each row).

    ``held`` is the prints of eligible rows so far, carried across calls."""
    held = set() if held is None else held
    for row in rows:
        ids = set(row.get("considered_print_ids") or [])
        row["guards"][SHARED] = not ids & held
        row["eligible"] = all(row["guards"].values())
        if row["eligible"]:
            held |= ids
    return rows


def first_failed_guards(rows):
    """One line per reason: each ineligible row counted once, under its first failed guard."""
    return dict(Counter(next(k for k, v in r["guards"].items() if not v) for r in rows if not r["eligible"]))


def build_plan(session):
    """(plan, breakdown): the live plan, from one resolver run over every uncaptured ambiguous listing."""
    from app.services.source_mapping_proposals import (
        ProposalFilters,
        analyse_source_mapping_proposals,
    )
    from sqlalchemy import text

    observed_at = session.execute(text("select now()")).scalar().isoformat()
    population = session.execute(text(POPULATION_SQL)).all()
    ids = [cid for cid, reason in population if reason == "uncaptured"]
    excluded = Counter(reason for _, reason in population if reason != "uncaptured")
    plans = {}
    if ids:
        analysis = analyse_source_mapping_proposals(
            session, ProposalFilters(source="yuyutei", candidate_ids=tuple(ids)),
            ignore_existing_mappings=True, build_report=False)
        plans = {o.candidate_id: o.proposal for o in analysis.outcomes if o.source_name == "yuyutei"}
    records, dropped = shortlist(ids, plans)
    session.rollback()
    breakdown = {"ambiguous_pending_listings": len(population), "excluded_before_resolver": dict(excluded),
                 "uncaptured": len(ids), "not_a_bounded_ambiguous_family_now": dropped,
                 "bounded_ambiguous_now": len(records)}
    return {"observed_at": observed_at, "records": records}, breakdown


def replan_all(session, plan, limit=None, resolver_version=None):
    """Guards over the plan in order. With ``limit``, stops once that many are eligible: eligibility
    depends only on earlier rows, so the first ``limit`` eligible are the same as a full pass."""
    from sqlalchemy import text

    from ops import replan

    if resolver_version is None:
        from app.services.source_mapping_proposals import (
            RESOLVER_VERSION as resolver_version,
        )

    records = plan["records"]
    observed_at = session.execute(text("select now()")).scalar().isoformat()
    evaluated, held, eligible = [], set(), 0
    for record in records:
        if limit is not None and eligible >= limit:
            break
        row = replan.evaluate_candidate(session, record)
        choose([row], held)
        evaluated.append(row)
        eligible += row["eligible"]
    session.rollback()
    meta = {"observed_at": plan.get("observed_at"), "records": len(records), "judged": len(evaluated)}
    return replan.summarize(records, meta, observed_at, resolver_version, evaluated)


def plan_batch(session, count, judge_all):
    """(plan, replanned, breakdown) for a batch of up to ``count``."""
    plan, breakdown = build_plan(session)
    replanned = replan_all(session, plan, limit=None if judge_all else count)
    breakdown.update(judged=len(replanned["records"]), first_failed_guard=first_failed_guards(replanned["records"]),
                     eligible=replanned["summary"]["eligible"])
    return plan, replanned, breakdown


def batch_rows(plan, entries):
    """The exact batch for the owner's review: candidate, card code, official siblings to capture."""
    codes = {r["candidate_id"]: r.get("card_code") for r in plan["records"]}
    return [[e["candidate_id"], codes.get(e["candidate_id"]), len(e["considered_print_ids"])] for e in entries]


def run(out_dir, *, apply=False, count=None, expected_sha256=""):
    from pathlib import Path

    from sqlalchemy.orm import Session

    from ops import db as ops_db

    count = check_count(count)
    with Session(ops_db.engine(statement_timeout_ms=300000)) as session:
        plan, replanned, breakdown = plan_batch(session, count, judge_all=False)
    return deliver(Path(out_dir), plan, replanned, breakdown, count, apply=apply, expected_sha256=expected_sha256)


def deliver(out, plan, replanned, breakdown, count, *, apply, expected_sha256):
    """Batch of min(count, eligible), then the enqueue tool; refuses only when nothing is eligible."""
    from ops import enqueue_remaining

    common.write_json(out / "plan.json", plan)
    eligible = replanned["summary"]["eligible"]
    if not eligible:
        common.write_json(out / "replan.json", replanned)
        return {"mode": "apply" if apply else "dry-run", "status": "REFUSED", "requested": count, "batch_size": 0,
                "reason": "no eligible candidate", "breakdown": breakdown}
    size = min(count, eligible)
    result = enqueue_remaining.enqueue_list(out, replanned, size, apply=apply, expected_sha256=expected_sha256,
                                            batch=f"capture-{size}")
    entries = json.loads((out / "approved-list.json").read_text())["entries"]
    return {**result, "requested": count, "batch_size": size, "breakdown": breakdown, "batch": batch_rows(plan, entries)}


def preview(out_dir, *, count=None):
    """The dry run's plan and list over a read-only session, every candidate judged; writes nothing."""
    from pathlib import Path

    from sqlalchemy.orm import Session

    from ops import db as ops_db
    from ops import enqueue_remaining, replan, storage_rates

    count = check_count(count)
    out = Path(out_dir)
    with Session(ops_db.engine(statement_timeout_ms=300000)) as session:
        plan, replanned, breakdown = plan_batch(session, count, judge_all=True)
    common.write_json(out / "plan.json", plan)
    common.write_json(out / "replan.json", replanned)
    result = {"read_only": True, "source_requests": 0, "database_writes": 0, "requested": count,
              "breakdown": breakdown, "guard_failures": replanned["summary"]["guard_failures"]}
    eligible = replanned["summary"]["eligible"]
    if not eligible:
        return {**result, "status": "NOTHING_ELIGIBLE", "batch_size": 0}
    size = min(count, eligible)
    data, sha, doc = replan.approved_list(replanned, size, batch=f"capture-{size}")
    (out / "approved-list.json").write_bytes(data)
    events = storage_rates.load_events()
    fit = enqueue_remaining.storage_fit(doc, storage_rates.compute(storage_rates.fetch_series(events["window_start"]), events))
    common.write_json(out / "storage-fit.json", fit)
    return {**result, "status": "PREVIEW_OK", "batch_size": size, "approved_list_sha256": sha,
            "storage_fit": {k: fit[k] for k in ("one_off_mb_s9", "room_to_reserve_mb_s9", "fits_planning_and_stress_A",
                                                "fits_planning_and_stress_B")},
            "batch": batch_rows(plan, doc["entries"])}
