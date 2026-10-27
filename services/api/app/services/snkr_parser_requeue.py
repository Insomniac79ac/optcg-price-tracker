"""Return SNKRDUNK refresh work refused by the class-name parser bug to the queue (owner-gated).

SNKRDUNK renamed its CSS-module classes on 2026-10-26 (~08:29Z). Until the fix (#223, released
by #224; every collector on it by 2026-10-27 07:04Z) the parser found no main image, so every
refresh was settled as identity_refusal, and identity_refusal blocks its work: 284 items, all with
the reason main_image_not_found:expected_exactly_one_mainImage_img. Blocked work is never retried
on its own, so SNKRDUNK had nothing left to refresh.

Owner decision 2026-10-27 (perfectionist): one canary first, then the rest.

- canary (count 1): reopens the one refused item whose last clean capture is newest. Refused while
  an earlier requeue has not settled, once the fix is proven, or after any refusal on the new code.
- rest (no count): needs proof that the fix works on a live page (an attempt on a refused item
  captured a price on the new code) and refuses if anything was refused on the new code. Reopens
  the remaining refused items.

Only work refused between CHANGE_AT and RELEASE_AT whose reason holds REASON and nothing beyond
the parser bug's own companions is eligible: older quarantine, genuine mismatches and any refusal
on the new code are never touched. A refusal on the new code stops both modes for good (it needs
investigating; this runbook does not get past it). Reopening sets the work pending and
due now; nothing else changes and no request is made. The work's last_failure records the requeue
(the original reason stays in it) so an open requeue is visible. preview() is read-only; apply()
re-runs it under row locks and writes only the approved plan.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import exists, select

from app.models import FreshnessAttempt, FreshnessWork, Source
from app.services import freshness_queue as queue
from app.services.freshness_policy import require_utc, utc_now

SOURCE = "snkrdunk"
CHANGE_AT = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
RELEASE_AT = datetime(2026, 10, 27, 7, 4, tzinfo=timezone.utc)
REASON = "main_image_not_found:expected_exactly_one_mainImage_img"
# Every reason the broken parser produced alongside REASON (measured on staging 2026-10-27: all 284
# rows read REASON;artwork_not_confirmed_match:missing_image_url;no_raw_condition_price_available).
# A row whose reason carries anything else (a genuine title or card-code mismatch) is not reopened.
PARSER_BUG_REASONS = frozenset({
    REASON, "artwork_not_confirmed_match:missing_image_url", "no_raw_condition_price_available",
})
MARKER = "requeued after SNKRDUNK class-name fix (owner 2026-10-27): "
MAX_COUNT = 500
PLAN_KEYS = ("source_id", "mode", "work_ids")


def _source_id(db):
    source_id = db.scalar(select(Source.id).where(Source.name == SOURCE))
    if source_id is None:
        raise ValueError("no SNKRDUNK source")
    return source_id


def _attempted_on_new_code(outcomes):
    """A refresh work row with an attempt claimed on the new code that ended in one of `outcomes`."""
    return exists().where(
        FreshnessAttempt.work_id == FreshnessWork.id,
        FreshnessAttempt.outcome.in_(outcomes),
        FreshnessAttempt.claimed_at >= RELEASE_AT,
    )


def _parser_bug_reason(failure):
    parts = (failure or "").split(";")
    return parts[0] == REASON and set(parts) <= PARSER_BUG_REASONS


def _refused_in_window():
    """A refresh work row with an identity_refusal attempt finished in [CHANGE_AT, RELEASE_AT)."""
    return exists().where(
        FreshnessAttempt.work_id == FreshnessWork.id,
        FreshnessAttempt.outcome == "identity_refusal",
        FreshnessAttempt.finished_at >= CHANGE_AT,
        FreshnessAttempt.finished_at < RELEASE_AT,
    )


def _base(source_id):
    return (FreshnessWork.source_id == source_id, FreshnessWork.kind == "refresh")


def _candidates(db, source_id, *, lock=False):
    query = (
        select(FreshnessWork)
        .where(
            *_base(source_id),
            FreshnessWork.state == "blocked",
            FreshnessWork.claim_token.is_(None),
            FreshnessWork.last_outcome == "identity_refusal",
            FreshnessWork.last_failure.startswith(REASON, autoescape=True),
            FreshnessWork.last_failure_at >= CHANGE_AT,
            FreshnessWork.last_failure_at < RELEASE_AT,
        )
        .order_by(FreshnessWork.last_successfully_checked_at.desc().nulls_last(), FreshnessWork.id)
    )
    if lock:
        query = query.with_for_update()
    return [w for w in db.scalars(query) if _parser_bug_reason(w.last_failure)]


def _eligible(db, work):
    from app.services.freshness_policy import FreshnessPolicy

    if work.policy_version != FreshnessPolicy.version:
        return "unsupported work freshness policy version"
    try:
        mapping = queue._eligible_mapping(db, work.source_card_mapping_id)
    except ValueError as exc:
        return str(exc)
    if (mapping.card_print_id != work.card_print_id
            or mapping.canonical_source_listing_identity != work.product_identity):
        return "planned mapping lineage changed"
    return None


def _facts(db, source_id):
    # From attempt history, not the row's latest outcome: a reopened item stays open until one of
    # its new-code attempts settles as captured or no_listing (a transient failure keeps it open),
    # and the proof is a captured attempt on the new code, whatever the row did after.
    open_requeues = list(db.scalars(select(FreshnessWork.id).where(
        *_base(source_id), FreshnessWork.state != "blocked", _refused_in_window(),
        ~_attempted_on_new_code(("captured", "no_listing")),
    ).order_by(FreshnessWork.id)))
    proven = list(db.scalars(select(FreshnessWork.id).where(
        *_base(source_id), _refused_in_window(), _attempted_on_new_code(("captured",)),
    ).order_by(FreshnessWork.id)))
    # Refusals by the new code only (an identity_refusal attempt claimed after RELEASE_AT), not
    # rows the queue blocked for mapping drift.
    refused_again = [
        {"work_id": w.id, "at": w.last_failure_at.isoformat() if w.last_failure_at else None,
         "reason": (w.last_failure or "")[:160]}
        for w in db.scalars(select(FreshnessWork).where(
            *_base(source_id), FreshnessWork.state == "blocked",
            _attempted_on_new_code(("identity_refusal",)),
        ).order_by(FreshnessWork.id))
    ]
    return {"open_requeues": open_requeues, "proven_captures": proven, "refused_on_new_code": refused_again}


def preview(db, *, mode, count=None, clock=utc_now):
    """(plan or None, problems, facts). Read only: no lock, no write. mode "canary" reopens one
    item; "rest" reopens every remaining one (at most count)."""
    require_utc(clock())
    if mode not in {"canary", "rest"}:
        return None, ["mode must be canary or rest"], {}
    if count is not None and (type(count) is not int or not 1 <= count <= MAX_COUNT):
        return None, [f"count must be 1..{MAX_COUNT} or empty"], {}
    source_id = _source_id(db)
    facts = _facts(db, source_id)
    problems = []
    if facts["open_requeues"]:
        problems.append(f"an earlier requeue has not settled yet (work {facts['open_requeues'][:5]})")
    if mode == "canary" and facts["proven_captures"]:
        problems.append("the fix is already proven by a captured price; run the rest (no count)")
    if mode == "rest" and not facts["proven_captures"]:
        problems.append("no refused item has captured a price on the new code yet; run the canary "
                        "(count 1) and wait for its capture")
    if facts["refused_on_new_code"]:
        problems.append(f"{len(facts['refused_on_new_code'])} item(s) were refused again on the new "
                        "code; investigate before reopening more")
    eligible, skipped = [], []
    for work in _candidates(db, source_id):
        why = _eligible(db, work)
        (skipped if why else eligible).append({"work_id": work.id, "why": why} if why else work.id)
    facts.update(candidates=len(eligible) + len(skipped), ineligible=skipped)
    if not eligible:
        problems.append("no refused item is eligible to reopen")
    if problems:
        return None, problems, facts
    chosen = eligible[:1] if mode == "canary" else eligible[: count or len(eligible)]
    return {"source_id": source_id, "mode": mode, "work_ids": chosen}, [], facts


def apply(db, approved, *, clock=utc_now):
    """Reopen exactly the approved work, after re-running the preview under row locks."""
    if not isinstance(approved, dict) or set(approved) != set(PLAN_KEYS):
        raise ValueError("an approved plan with exactly the plan keys is required")
    now = require_utc(clock())
    _candidates(db, approved["source_id"], lock=True)  # lock every candidate row first
    plan, problems, _ = preview(db, mode=approved["mode"],
                                count=None if approved["mode"] == "canary" else len(approved["work_ids"]),
                                clock=clock)
    if problems:
        raise ValueError("; ".join(problems))
    if plan != approved:
        raise ValueError("the requeue plan differs from the approved dry run")
    reopened = []
    for work_id in plan["work_ids"]:
        work = db.get(FreshnessWork, work_id)
        work.state = "pending"
        work.next_due_at = now
        work.retry_not_before_at = None
        work.last_failure = (MARKER + (work.last_failure or ""))[:500]
        work.last_failure_at = now
        work.updated_at = now
        reopened.append(work_id)
    db.flush()
    return reopened
