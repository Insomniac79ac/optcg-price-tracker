"""D9 F1 batch approval (ops-write runbook `approve-f1-batch`).

Approves current exact Yuyu-Tei proposals made by the F1 rule (reason
``unique_listing_kind_resolves_one_release_sibling``) or resolved by a retained physical
artwork review (reason ``retained_positive_unique_physical_artwork_review``, owner 2026-10-29)
in owner-approved batches, through the same `approve_exact_proposal` the admin review page
uses, so every guard is the admin guard. The summary counts the batch per rule.

1. Select the batch (read-only): current, pending, exact Yuyu-Tei groups carrying the F1 reason,
   oldest group first. Each is re-checked against a fresh resolver run (same evidence digest,
   resolver version and sole recommended print), the candidate state the proposal recorded, the
   listing's mapping (none, or the same print, never rejected) and the print (active, verified,
   no other current Yuyu-Tei mapping, not claimed twice in the batch). A proposal failing any
   check is left out and counted under its reason.
2. Pin the first ``count`` (default 500) as the approved list, by SHA-256, and write it in full
   with a 20-row random sample (seeded by the SHA, so the same list gives the same sample).
3. Dry run by default: nothing is written. ``apply`` rebuilds the list and refuses unless its
   SHA-256 equals ``expected_sha256`` from the dry run the owner reviewed, then approves each
   proposal in its own transaction (as the admin page does), stopping at the first refusal or
   at a quiet window. Approved proposals stay approved; the summary names them.
It never fetches a source, never enqueues work and never touches a collector service. New
mappings are collected on the collectors' own schedule (the 48 h storage check follows each
batch).
"""
from __future__ import annotations

from collections import Counter
from datetime import timezone
import hashlib
import json
from pathlib import Path
import random
import time

from ops import common

F1_REASON = "unique_listing_kind_resolves_one_release_sibling"
REVIEW_REASON = "retained_positive_unique_physical_artwork_review"
RULES = {F1_REASON: "f1", REVIEW_REASON: "physical_review"}
DEFAULT_COUNT = 500
MAX_COUNT = 600
SAMPLE_SIZE = 20
LIST_KEYS = ("proposal_group_id", "selected_alternative_id", "source_candidate_id", "card_print_id",
             "evidence_digest", "resolver_version", "updated_at")


def _iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def approvable_rule(reasons):
    """The approvable rule an exact proposal's reasons name (F1 or a physical review), or None."""
    names = [RULES[r] for r in (reasons or []) if r in RULES]
    return names[0] if len(names) == 1 else None


def check_count(count):
    count = DEFAULT_COUNT if count is None else count
    if not 1 <= count <= MAX_COUNT:
        raise common.Refused(f"count must be 1..{MAX_COUNT} (batches of about {DEFAULT_COUNT})")
    return count


def pinned_list(entries, count):
    """(bytes, sha256, doc) of the first ``count`` eligible entries, in the order given."""
    chosen = [{k: e[k] for k in LIST_KEYS} for e in entries[:count]]
    if not chosen:
        raise common.Refused("no eligible F1 proposal to approve")
    doc = {"runbook": "approve-f1-batch", "reasons": sorted(RULES), "expected_count": len(chosen), "entries": chosen}
    data = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    return data, hashlib.sha256(data).hexdigest(), doc


def sample(entries, sha, size=SAMPLE_SIZE):
    """A reproducible random sample: the same list always gives the same rows."""
    rng = random.Random(int(sha[:16], 16))
    picked = rng.sample(range(len(entries)), min(size, len(entries)))
    return [entries[i] for i in sorted(picked)]


def check_apply(apply, expected_sha256, sha):
    if not apply:
        return
    if not (isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)):
        raise common.Refused("apply needs expected_sha256: the approved-list SHA-256 from a dry run")
    if expected_sha256 != sha:
        raise common.Refused("the rebuilt list differs from the dry run's (expected_sha256); dry run again")


def select_batch(session):
    """(eligible entries with detail, Counter of exclusion reasons). Read-only: no locks, no writes."""
    from sqlalchemy import select
    from app.models import (CanonicalCard, CardPrint, SourceCardMapping, SourceMappingProposalAlternative,
                            SourceMappingProposalGroup, YuyuteiCandidate)
    from app.services.exact_print_approval import ExactPrintApprovalError, assert_print_is_priceable
    from app.services.source_mapping_proposal_decision import (ProposalDecisionError, _assert_candidate_state,
                                                               _assert_plan_matches)
    from app.services.source_mapping_proposals import (ProposalFilters, analyse_source_mapping_proposals,
                                                       print_listing_kind, yuyu_listing_kind)
    from app.services.yuyutei_candidate_approval import (assert_mapping_may_be_approved, find_mapping_for_listing,
                                                         get_yuyutei_source)

    source = get_yuyutei_source(session)
    groups = [g for g in session.scalars(
        select(SourceMappingProposalGroup).where(
            SourceMappingProposalGroup.source_id == source.id,
            SourceMappingProposalGroup.source_candidate_type == "yuyutei_candidate",
            SourceMappingProposalGroup.superseded_at.is_(None),
            SourceMappingProposalGroup.review_status == "pending",
            SourceMappingProposalGroup.resolution_status == "exact",
        ).order_by(SourceMappingProposalGroup.id)) if approvable_rule(g.resolution_reasons_json)]
    excluded = Counter()
    if not groups:
        return [], excluded

    # One resolver run for every candidate: the same outcomes resolve_current_candidate_proposal
    # gives one at a time (the listing-kind index always spans every candidate).
    analysis = analyse_source_mapping_proposals(
        session, ProposalFilters(source="yuyutei", candidate_ids=tuple(sorted({g.source_candidate_id for g in groups}))),
        ignore_existing_mappings=True, build_report=False)
    plans = {o.candidate_id: o.proposal for o in analysis.outcomes if o.source_name == "yuyutei"}

    rows = []
    for group in groups:
        alternatives = session.scalars(select(SourceMappingProposalAlternative).where(
            SourceMappingProposalAlternative.proposal_group_id == group.id)).all()
        if len(alternatives) != 1 or not alternatives[0].recommended or alternatives[0].review_disposition != "pending":
            excluded["no_single_pending_recommended_alternative"] += 1
            continue
        alternative = alternatives[0]
        candidate = session.get(YuyuteiCandidate, group.source_candidate_id)
        if candidate is None:
            excluded["candidate_missing"] += 1
            continue
        try:
            _assert_candidate_state(group, candidate)
            _assert_plan_matches(group, alternative, source, plans.get(candidate.id))
            print_row = assert_print_is_priceable(session, alternative.card_print_id)
            mapping = find_mapping_for_listing(session, source=source, url=candidate.source_url)
            assert_mapping_may_be_approved(mapping, alternative.card_print_id)
        except ProposalDecisionError as error:
            excluded[error.code] += 1
            continue
        except ExactPrintApprovalError as error:
            excluded[getattr(error, "code", None) or type(error).__name__] += 1
            continue
        other = select(SourceCardMapping.id).where(
            SourceCardMapping.source_id == source.id, SourceCardMapping.card_print_id == print_row.id,
            SourceCardMapping.is_active.is_(True), SourceCardMapping.superseded_at.is_(None))
        if mapping is not None:
            other = other.where(SourceCardMapping.id != mapping.id)
        if session.scalar(other.limit(1)) is not None:
            excluded["print_source_already_mapped"] += 1
            continue
        canonical = session.get(CanonicalCard, print_row.canonical_card_id)
        rows.append({
            "proposal_group_id": group.id, "selected_alternative_id": alternative.id,
            "source_candidate_id": candidate.id, "card_print_id": print_row.id,
            "evidence_digest": group.evidence_digest, "resolver_version": group.resolver_version,
            "updated_at": _iso(group.updated_at),
            "detail": {"rule": approvable_rule(group.resolution_reasons_json),
                       "card_code": canonical.card_code if canonical else None,
                       "print_name": print_row.official_name, "print_rarity": print_row.official_rarity,
                       "print_variant": print_row.official_asset_variant, "print_treatment": print_row.treatment,
                       "print_kind": print_listing_kind(print_row), "release_product_id": print_row.release_product_id,
                       "listing": group.canonical_source_listing_identity, "listing_url": candidate.source_url,
                       "listing_title": candidate.name_jp, "listing_rarity": candidate.detected_rarity,
                       "listing_kind": yuyu_listing_kind(candidate.name_jp, candidate.detected_rarity),
                       "listing_price_jpy": candidate.price_jpy, "existing_mapping_id": mapping.id if mapping else None}})
    # One listing prices one print: a print two proposals claim goes to neither.
    claims = Counter(r["card_print_id"] for r in rows)
    eligible = [r for r in rows if claims[r["card_print_id"]] == 1]
    if len(eligible) != len(rows):
        excluded["print_claimed_by_two_proposals"] += len(rows) - len(eligible)
    return eligible, excluded


def _timed_resolve(session, candidate_id):
    from app.services.source_mapping_proposals import resolve_current_candidate_proposal
    start = time.monotonic()
    resolve_current_candidate_proposal(session, source_name="yuyutei", candidate_id=candidate_id)
    return time.monotonic() - start


def approve(session, entries, *, run_label, now=common.now_utc):
    """Approve each entry in its own transaction; stop at the first refusal or quiet window."""
    from app.admin_actor import AdminActor
    from app.services.exact_print_approval import ExactPrintApprovalError
    from app.services.source_mapping_proposal_decision import ProposalDecisionError, approve_exact_proposal
    from app.source_mapping_proposal_schemas import ApproveExactProposalIn
    from datetime import datetime

    actor = AdminActor(id=run_label, email=run_label)
    approved, stopped = [], None
    for entry in entries:
        reason = common.quiet_window_refusal(now(), collector_affecting=True, write=True)
        if reason:
            stopped = {"proposal_group_id": entry["proposal_group_id"], "code": "quiet_window", "message": reason}
            break
        request = ApproveExactProposalIn(
            selected_alternative_id=entry["selected_alternative_id"],
            expected_evidence_digest=entry["evidence_digest"],
            expected_resolver_version=entry["resolver_version"],
            expected_updated_at=datetime.fromisoformat(entry["updated_at"]))
        try:
            result = approve_exact_proposal(session, entry["proposal_group_id"], request, actor)
            session.commit()
        except (ProposalDecisionError, ExactPrintApprovalError) as error:
            session.rollback()
            stopped = {"proposal_group_id": entry["proposal_group_id"],
                       "code": getattr(error, "code", type(error).__name__),
                       "message": str(getattr(error, "message", "") or error)[:300]}
            break
        except Exception:
            session.rollback()
            raise
        approved.append({"proposal_group_id": result.proposal_group_id,
                         "source_card_mapping_id": result.resulting_source_card_mapping_id,
                         "card_print_id": result.card_print_id, "mapping_created": result.mapping_created})
    return approved, stopped


def run(out_dir, *, apply=False, count=None, expected_sha256="", run_label=None):
    import os
    from sqlalchemy.orm import Session
    from ops import db as ops_db, storage_rates
    import yuyu_identity_capture_enqueue as tool

    count = check_count(count)
    out = Path(out_dir)
    with Session(ops_db.engine(statement_timeout_ms=300000)) as session:
        eligible, excluded = select_batch(session)
        data, sha, doc = pinned_list(eligible, count)
        seconds_per_resolve = round(_timed_resolve(session, doc["entries"][0]["source_candidate_id"]), 2)
        session.rollback()
    (out / "approved-list.json").write_bytes(data)
    chosen = eligible[:len(doc["entries"])]
    common.write_json(out / "batch-detail.json", chosen)
    picked = sample(chosen, sha)
    common.write_json(out / "sample.json", picked)
    check_apply(apply, expected_sha256, sha)

    events = storage_rates.load_events()
    rates = storage_rates.compute(storage_rates.fetch_series(events["window_start"]), events)
    planning = rates["variants"]["ex_steps"]["planning_mb_day_s9"]
    room = rates["room_to_reserve_mb_s9"]
    storage = {"room_to_reserve_mb_s9": room, "planning_mb_day_s9": planning,
               "days_to_reserve_planning": round(room / planning, 1) if planning else None,
               "last_24h_mb_s9": rates.get("last_24h_mb_s9")}

    summary = {"mode": "apply" if apply else "dry-run", "status": "DRY_RUN_OK", "reason_rules": sorted(RULES),
               "rules": dict(Counter(r["detail"]["rule"] for r in chosen)),
               "approved_list_sha256": sha, "batch_size": len(chosen), "eligible_total": len(eligible),
               "excluded": dict(excluded), "kinds": dict(Counter(f"{r['detail']['listing_kind']}->{r['detail']['print_kind']}"
                                                            for r in chosen)),
               "proposal_group_ids": [r["proposal_group_id"] for r in chosen],
               "sample": [dict(proposal_group_id=r["proposal_group_id"], card_print_id=r["card_print_id"], **r["detail"])
                          for r in picked],
               "apply_minutes_estimate": round(len(chosen) * 2 * seconds_per_resolve / 60, 1),
               "seconds_per_resolve_measured": seconds_per_resolve, "storage_now": storage,
               "source_requests": 0, "written": 0}
    if not apply:
        return summary

    run_label = run_label or f"ops-write:approve-f1-batch:{os.environ.get('GITHUB_RUN_ID', 'local')}"
    # Mask the database password in the log before the tool opens its own session.
    ops_db.resolve()[1].clear()
    with tool.staging_session(writable=True) as session:
        live, _ = select_batch(session)
        session.rollback()
        live_sha = pinned_list(live, count)[1] if live else ""
        check_apply(True, expected_sha256, live_sha)
        approved, stopped = approve(session, pinned_list(live, count)[2]["entries"], run_label=run_label)
    common.write_json(out / "approve-receipt.json", {"approved": approved, "stopped": stopped, "run_label": run_label})
    summary.update(status="APPLIED" if stopped is None else "STOPPED", written=len(approved), stopped=stopped,
                   reviewed_by=run_label, approved_group_ids=[a["proposal_group_id"] for a in approved],
                   mappings_created=sum(a["mapping_created"] for a in approved))
    if stopped is not None:
        summary["ok"] = False
    return summary
