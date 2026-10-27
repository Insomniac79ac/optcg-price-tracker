"""Return SNKRDUNK refresh work refused by the class-name parser bug to the queue (owner-gated).

SNKRDUNK renamed its CSS-module classes on 2026-10-26 (~08:29Z). Until the fix (#223, released
by #224; every collector on it by 2026-10-27 07:04Z) the parser found no main image, so every
refresh was settled as identity_refusal, and identity_refusal blocks its work: 284 items, all with
the reason main_image_not_found:expected_exactly_one_mainImage_img. Blocked work is never retried
on its own, so SNKRDUNK had nothing left to refresh.

Owner decision 2026-10-27 (perfectionist): one canary first, then the rest.

- canary (count 1): reopens the one refused item whose last clean capture is newest. Refused while
  any earlier requeue is still open or once a canary has already proven the fix.
- rest (no count, or a cap): needs proof that the fix works on a live page (a refused item has
  since captured a price on the new code) and refuses if anything was refused again on the new
  code. Reopens the remaining refused items.

Only work refused for exactly that reason between CHANGE_AT and RELEASE_AT is eligible: older
quarantine and any refusal on the new code are never touched. Reopening sets the work pending and
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
MARKER = "requeued after SNKRDUNK class-name fix (owner 2026-10-27): "
MAX_COUNT = 500
PLAN_KEYS = ("source_id", "mode", "work_ids")


def _source_id(db):
    source_id = db.scalar(select(Source.id).where(Source.name == SOURCE))
    if source_id is None:
        raise ValueError("no SNKRDUNK source")
    return source_id


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
            FreshnessWork.last_failure.like(REASON + "%"),
            FreshnessWork.last_failure_at >= CHANGE_AT,
            FreshnessWork.last_failure_at < RELEASE_AT,
        )
        .order_by(FreshnessWork.last_successfully_checked_at.desc().nulls_last(), FreshnessWork.id)
    )
    if lock:
        query = query.with_for_update()
    return list(db.scalars(query))


def _eligible(db, work):
    try:
        mapping = queue._eligible_mapping(db, work.source_card_mapping_id)
    except ValueError as exc:
        return str(exc)
    if (mapping.card_print_id != work.card_print_id
            or mapping.canonical_source_listing_identity != work.product_identity):
        return "planned mapping lineage changed"
    return None


def _facts(db, source_id):
    open_requeues = list(db.scalars(select(FreshnessWork.id).where(
        *_base(source_id), FreshnessWork.state != "blocked",
        FreshnessWork.last_outcome == "identity_refusal",
        FreshnessWork.last_failure.like(MARKER + "%"),
    ).order_by(FreshnessWork.id)))
    proven = list(db.scalars(select(FreshnessWork.id).where(
        *_base(source_id), FreshnessWork.last_outcome == "captured",
        FreshnessWork.last_successfully_checked_at >= RELEASE_AT, _refused_in_window(),
    ).order_by(FreshnessWork.id)))
    refused_again = [
        {"work_id": w.id, "at": w.last_failure_at.isoformat(), "reason": (w.last_failure or "")[:160]}
        for w in db.scalars(select(FreshnessWork).where(
            *_base(source_id), FreshnessWork.state == "blocked",
            FreshnessWork.last_outcome == "identity_refusal",
            FreshnessWork.last_failure_at >= RELEASE_AT,
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
    if mode == "rest":
        if not facts["proven_captures"]:
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
