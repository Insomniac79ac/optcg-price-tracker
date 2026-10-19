"""Read-only Yuyu identity-capture re-plan on live digests, and the approved list built from it
(session 13 tools new100_replan.py and make_approved_list.py).

For each planned candidate, rerun the canonical resolver (`resolve_current_candidate_proposal`,
the call the collector's `load_intent` makes at claim time) and evaluate every guard the PR #116
enqueue tool enforces: ambiguous family with a bounded sibling set (2..12); authoritative release
and one canonical card for every considered print (never a card-code prefix); no active Yuyu
mapping on any print or the listing; no prior capture scope and no reviewed decision; listing
identity matches the stored set/product; no print shared with another planned candidate.
No writes (read-only session, rolled back), no source requests.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json

from ops import common

MAX_SIBLINGS = 12  # services/yuyutei_collector/yuyutei_collector/identity_evidence.py
# Last full re-plan of the NEW100 plan (session 13, 2026-10-15 04:03Z): 100 candidates, the 50
# not yet captured are eligible. Its records carry the plan's candidates and digests.
DEFAULT_PLAN = "docs/agent/handoff/2026-10-15/capacity75-session13/evidence/new100-replan.json"


def evaluate_candidate(s, r):
    """One plan record -> re-plan row with guards (shared-print guard added by replan())."""
    from sqlalchemy import text
    from opcg_source_identity import yuyutei_listing_identity
    from app.models import YuyuteiCandidate
    from app.services.identity_evidence_scope import identity_evidence_scope
    from app.services.source_mapping_proposals import resolve_current_candidate_proposal

    cid = r["candidate_id"]
    row = {"candidate_id": cid, "card_code": r.get("card_code"), "old_digest": r.get("evidence_digest"),
           "old_considered_print_ids": r.get("considered_print_ids"), "guards": {}}
    g = row["guards"]
    cand = s.get(YuyuteiCandidate, cid)
    plan = resolve_current_candidate_proposal(s, source_name="yuyutei", candidate_id=cid)
    g["candidate_listing_identity"] = cand is not None and yuyutei_listing_identity(cand.source_url) == (cand.set_slug, cand.product_id)
    if plan is None:
        g["current_plan"] = False
        return row
    ids = sorted(a.card_print_id for a in plan.alternatives)
    row.update({"resolution_status": plan.resolution_status, "evidence_digest": plan.evidence_digest,
                "resolver_version": plan.resolver_version, "release_product_id": plan.release_product_id,
                "canonical_card_id": plan.canonical_card_id, "considered_print_ids": ids, "source_url": plan.source_url})
    g["current_plan"] = True
    g["ambiguous_family"] = plan.resolution_status == "ambiguous"
    g["bounded_sibling_set"] = 2 <= len(ids) <= MAX_SIBLINGS
    row["siblings_changed"] = ids != sorted(r.get("considered_print_ids") or [])
    prints = s.execute(text("select id, release_product_id, canonical_card_id from card_prints where id = any(:ids)"),
                       {"ids": ids}).mappings().all()
    g["prints_exist"] = len(prints) == len(ids)
    g["authoritative_release"] = (plan.release_product_id is not None and bool(prints)
                                  and all(p["release_product_id"] == plan.release_product_id for p in prints))
    g["same_canonical_card"] = bool(prints) and all(p["canonical_card_id"] == plan.canonical_card_id for p in prints)
    active = s.execute(text("""select id, card_print_id from source_card_mappings where source_id = :sid
        and is_active and superseded_at is null and (card_print_id = any(:ids) or source_url = :url)"""),
        {"sid": plan.source_id, "ids": ids, "url": plan.source_url}).mappings().all()
    row["active_yuyu_mappings"] = [dict(a) for a in active]
    g["no_active_yuyu_mapping"] = not active
    prior = s.execute(text("""select id, scope_key, state from freshness_work where source_id = :sid
        and (scope_key = :legacy or scope_key like :pattern)"""),
        {"sid": plan.source_id, "legacy": f"yuyu-identity:{cid}", "pattern": f"yuyu-identity:{cid}:%"}).mappings().all()
    row["prior_capture_scopes"] = [dict(p) for p in prior]
    g["no_prior_capture_scope"] = not prior
    reviewed = s.execute(text("""select count(*) from source_mapping_proposal_groups where source_id = :sid
        and source_candidate_id = :cid and reviewed_at is not null"""), {"sid": plan.source_id, "cid": cid}).scalar()
    g["no_reviewed_decision"] = reviewed == 0
    row["scope_key"] = identity_evidence_scope(cid, plan.evidence_digest, 2)
    return row


def finish(records, plan_meta, observed_at, resolver_version, evaluated):
    """Shared-print guard, eligibility and summary over evaluated rows (pure)."""
    shared = Counter(i for row in evaluated for i in row.get("considered_print_ids", []))
    for row in evaluated:
        row["guards"]["no_shared_print_with_other_planned"] = all(shared[i] == 1 for i in row.get("considered_print_ids", []))
        row["eligible"] = all(row["guards"].values())
    eligible = [r for r in evaluated if r["eligible"]]
    return {"read_only": True, "source_requests": 0, "database_writes": 0, "resolver_version": resolver_version,
            "plan": plan_meta, "observed_at": observed_at, "records": evaluated,
            "summary": {"planned": len(records), "eligible": len(eligible),
                        "guard_failures": dict(Counter(k for r in evaluated for k, v in r["guards"].items() if not v)),
                        "digest_changed": sum(r.get("evidence_digest") != r["old_digest"] for r in evaluated),
                        "siblings_changed": sum(bool(r.get("siblings_changed")) for r in evaluated),
                        "official_sibling_images": sum(len(r.get("considered_print_ids", [])) for r in eligible),
                        "yuyu_images": len(eligible)}}


def replan(session, plan):
    from sqlalchemy import text
    from app.services.source_mapping_proposals import RESOLVER_VERSION

    records = plan["records"]
    observed_at = session.execute(text("select now()")).scalar().isoformat()
    evaluated = [evaluate_candidate(session, r) for r in records]
    session.rollback()
    meta = {"observed_at": plan.get("observed_at"), "records": len(records)}
    return finish(records, meta, observed_at, RESOLVER_VERSION, evaluated)


def approved_list(replanned, count, batch=None):
    """(bytes, sha256, doc): the first ``count`` eligible candidates in plan order. Refuses short."""
    eligible = [r for r in replanned["records"] if r["eligible"]]
    if type(count) is not int or not 1 <= count <= 100:
        raise common.Refused("count must be 1..100")
    if len(eligible) < count:
        raise common.Refused(f"only {len(eligible)} eligible candidates; refusing a batch of {count}")
    # Content only: no re-plan timestamp, so an apply re-plan of an unchanged list hashes to the
    # dry run's SHA-256 (replan.json keeps observed_at). A moved digest still changes the SHA.
    doc = {"batch": batch or f"NEW{count}", "expected_count": count, "resolver_version": replanned["resolver_version"],
           "entries": [{"candidate_id": r["candidate_id"], "evidence_digest": r["evidence_digest"],
                        "release_product_id": r["release_product_id"], "considered_print_ids": r["considered_print_ids"]}
                       for r in eligible[:count]]}
    data = (json.dumps(doc, indent=1) + "\n").encode()
    return data, hashlib.sha256(data).hexdigest(), doc


def load_plan(path=None):
    path = (common.ROOT / (path or DEFAULT_PLAN)).resolve()
    if not path.is_relative_to(common.ROOT / "docs/agent") or not path.is_file():
        raise common.Refused("plan must be a committed file under docs/agent/")
    plan = json.loads(path.read_text())
    if not isinstance(plan.get("records"), list) or not plan["records"]:
        raise common.Refused("plan has no records")
    return plan
