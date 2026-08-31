"""Approve REVIEWED, EXACT SNKRDUNK candidates in a batch. Plans by default.

WHY THIS EXISTS. 418 of staging's 676 candidates resolve to exactly one
printing under the live exact-print gate. Approving them one HTTP call at a
time is not the problem; approving them without a written-down, re-checkable
statement of what is about to happen IS. So this job's real output is the
plan: one line per candidate naming the listing, the card code, the product,
the printing, the variant, the resolver's verdict and the evidence that
narrowed it. `--apply` writes that plan and nothing else.

WHY IT LIVES IN THE API SERVICE AND NOT THE WORKER. The approval primitives -
`resolve_exact_print`, `canonical_listing_url`, and the write in
`app.services.snkrdunk_candidate_approval` - are api-side modules, and the
worker is a separate deployable that cannot import them (it mirrors
`snkrdunk_urls` for exactly this reason). A worker-side batch job would
therefore have to re-implement the gate, and a second implementation of the
gate is the one thing this tranche must not produce. It sits alongside the
other `app/*.py` operational commands instead.

NOTHING HERE DECIDES ANYTHING ABOUT A PRINT. The verdict comes from
`resolve_exact_print`, run once per sibling printing exactly as the approval
screen runs it, and the write comes from `approve_candidate_onto_print`, which
is the same function the human approve-match endpoint calls. This module
contributes the eligibility filter, the plan, and the transaction.

THE SAFETY CONTRACT, in the order it is enforced:

  1. Planning is the default. `--apply` is required to write anything.
  2. Scope is explicit. `--candidate-ids` or `--from-file`; there is no
     "approve every exact candidate" switch, by design. The operator names
     the rows they read.
  3. Every candidate is re-resolved against the live catalogue at plan time.
     Stored derived fields are read as SOURCE EVIDENCE (title, card code,
     product, variant - what SNKRDUNK said) and never as a stored verdict.
  4. Apply demands the confirmation phrase, typed exactly.
  5. Apply RE-PLANS first and aborts the WHOLE batch if any candidate's
     verdict, print or eligibility has moved since the plan was printed.
  6. One transaction for the whole batch. A failure rolls all of it back.
  7. Approval creates no PriceObservation and fetches nothing. It makes a
     listing collectable; it does not collect it.
  8. Re-running an applied batch writes nothing new: the candidates are then
     `matched`, which the eligibility filter refuses.

WHAT `manual_verified = true` IS ASSERTING, and why this job may set it. The
collector's eligibility filter reads that column, so setting it under weaker
conditions than a human's click would silently widen what gets priced. It is
set here because `approve_candidate_onto_print` sets it - this job does not
write the field itself - and because the operator's action is the same one the
endpoint requires: they read a specific candidate/print pair on a printed
plan, and they type a confirmation phrase naming that batch. What the job may
never do is reach the write without a human having seen those pairs, which is
why an unscoped run is refused rather than defaulted.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ReleaseProduct, Source
from app.models.snkrdunk_candidate import SnkrdunkCandidate
from app.services.exact_print_approval import (
    ExactPrintApprovalError,
    SourceEvidence,
    printing_label,
    resolve_exact_print,
    sibling_prints_for_card_code,
    special_print_label,
)
from app.services.non_target_tcg import identify_non_target_tcg
from app.services.snkrdunk_candidate_approval import (
    SnkrdunkSourceMissing,
    approve_candidate_onto_print,
    assert_mapping_may_be_approved,
    find_mapping_for_listing,
    get_snkrdunk_source,
)
from app.services.snkrdunk_urls import (
    canonical_listing_url,
    equivalent_listing_urls,
    listing_id,
)

CONFIRM_PHRASE = "approve exact candidates"

# The only candidate state this job will act on. A `matched` row has already
# been approved, a `rejected` one has been refused by a person, and
# `suggested`/`ambiguous` mean the scorer had something to say that nobody has
# resolved yet. Only `unmatched` is a row no human decision has landed on, and
# a batch approval must be the FIRST decision on a row, never an override of
# an existing one.
ELIGIBLE_MATCH_STATUS = "unmatched"

# Refusal codes this module raises itself, alongside the exact-print gate's
# own. Machine-readable for the same reason the gate's are: the plan is read
# by a person and grepped by the next run.
REFUSAL_NOT_UNMATCHED = "candidate_not_unmatched"
REFUSAL_NOT_ONE_PIECE = "listing_is_another_game"
REFUSAL_NOT_EXACT = "resolver_verdict_not_exact"
REFUSAL_NO_SIBLINGS = "card_code_not_in_catalogue"
REFUSAL_MAPPING_CONFLICT = "existing_mapping_names_another_print"
REFUSAL_MAPPING_NO_PRINT = "existing_mapping_has_no_card_print"
# The duplicate-listing and rejected-mapping refusals are NOT defined here.
# They come from app.services.exact_print_approval via the shared guards in
# snkrdunk_candidate_approval, so the plan reports exactly the code the write
# path would raise - see REFUSAL_MULTIPLE_MAPPINGS_FOR_LISTING and
# REFUSAL_MAPPING_WAS_REJECTED.


class BatchApprovalError(RuntimeError):
    """Refusal or abort. Raised before any write, or to abandon the batch."""


@dataclass
class CandidatePlan:
    """What would happen to one candidate, decided without writing.

    Every field the operator needs to check the row by hand is here, because
    a plan that omits the product or the variant cannot be checked - it can
    only be trusted, and the point of the plan is not to have to.
    """

    candidate_id: int
    source_url: str
    match_status: str
    canonical_url: str | None = None
    listing_identity: str | None = None
    card_code: str | None = None
    product_label: str | None = None
    release_product: str | None = None
    release_product_id: int | None = None
    card_print_id: int | None = None
    variant: str | None = None
    printing: str | None = None
    special_print: str | None = None
    language: str | None = None
    verdict: str = "refused"
    evidence_used: list[str] = field(default_factory=list)
    considered_print_ids: list[int] = field(default_factory=list)
    approvable_print_ids: list[int] = field(default_factory=list)
    sibling_refusals: dict[int, str] = field(default_factory=dict)
    existing_mapping_id: int | None = None
    existing_mapping_print_id: int | None = None
    existing_mapping_status: str | None = None
    action: str = "refuse"
    refusal_code: str | None = None
    refusal_reason: str | None = None

    @property
    def approvable(self) -> bool:
        return self.refusal_code is None

    def identity(self) -> tuple:
        """The facts that must not have moved between plan and apply.

        Compared as a whole rather than field by field so a change anywhere -
        a print deactivated, a product alias added, a mapping created by
        someone else - aborts the batch instead of being applied against a
        plan the operator never read.
        """
        return (
            self.candidate_id,
            self.match_status,
            self.card_print_id,
            self.canonical_url,
            tuple(self.considered_print_ids),
            tuple(self.approvable_print_ids),
            tuple(self.evidence_used),
            self.existing_mapping_id,
            self.existing_mapping_print_id,
            self.action,
            self.refusal_code,
        )

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "source_url": self.source_url,
            "canonical_listing_url": self.canonical_url,
            "listing_identity": self.listing_identity,
            "match_status": self.match_status,
            "card_code": self.card_code,
            "source_product_label": self.product_label,
            "release_product": self.release_product,
            "release_product_id": self.release_product_id,
            "card_print_id": self.card_print_id,
            "variant": self.variant,
            "printing": self.printing,
            "special_print": self.special_print,
            "language": self.language,
            "resolver_verdict": self.verdict,
            "evidence_used": self.evidence_used,
            "considered_print_ids": self.considered_print_ids,
            "approvable_print_ids": self.approvable_print_ids,
            "sibling_refusals": {str(k): v for k, v in self.sibling_refusals.items()},
            "existing_mapping_id": self.existing_mapping_id,
            "existing_mapping_card_print_id": self.existing_mapping_print_id,
            "existing_mapping_review_status": self.existing_mapping_status,
            "proposed_action": self.action,
            "refusal_code": self.refusal_code,
            "refusal_reason": self.refusal_reason,
        }


@dataclass
class ApprovalOutcome:
    """What one approval actually wrote. Read back off the row, not assumed."""

    candidate_id: int
    mapping_id: int
    mapping_created: bool
    card_print_id: int | None
    card_id: int | None
    review_status: str
    manual_verified: bool
    source_url: str
    candidate_status: str
    evidence_used: list[str]

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "mapping_id": self.mapping_id,
            "mapping_created": self.mapping_created,
            "card_print_id": self.card_print_id,
            "card_id": self.card_id,
            "review_status": self.review_status,
            "manual_verified": self.manual_verified,
            "source_url": self.source_url,
            "candidate_status": self.candidate_status,
            "evidence_used": self.evidence_used,
        }


@dataclass
class BatchReport:
    plans: list[CandidatePlan] = field(default_factory=list)
    outcomes: list[ApprovalOutcome] = field(default_factory=list)
    applied: bool = False

    @property
    def approvable(self) -> list[CandidatePlan]:
        return [p for p in self.plans if p.approvable]

    @property
    def refused(self) -> list[CandidatePlan]:
        return [p for p in self.plans if not p.approvable]

    @property
    def mappings_created(self) -> int:
        return sum(1 for o in self.outcomes if o.mapping_created)

    @property
    def mappings_reused(self) -> int:
        return sum(1 for o in self.outcomes if not o.mapping_created)

    def as_dict(self) -> dict:
        return {
            "applied": self.applied,
            "scoped": len(self.plans),
            "approvable": len(self.approvable),
            "refused": len(self.refused),
            "approved": len(self.outcomes),
            "mappings_created": self.mappings_created,
            "mappings_reused": self.mappings_reused,
            # Stated rather than counted: approval writes no price. If this
            # is ever anything but zero, something has grown a side effect.
            "price_observations_written": 0,
            "candidates": [p.as_dict() for p in self.plans],
            "outcomes": [o.as_dict() for o in self.outcomes],
        }


def select_candidates(db: Session, candidate_ids: list[int]) -> list[SnkrdunkCandidate]:
    """The scoped rows, in id order.

    Refuses an empty scope. "Approve every exact candidate" is not a switch
    this job has: the operator names the ids they read on a plan, and a
    missing id aborts rather than being silently skipped - a typo that
    quietly approves a different set is precisely the failure mode.
    """
    if not candidate_ids:
        raise BatchApprovalError(
            "Refusing an unscoped batch approval: pass --candidate-ids or "
            "--from-file. There is no 'approve all exact candidates' mode."
        )
    unique = sorted(set(candidate_ids))
    rows = list(
        db.scalars(
            select(SnkrdunkCandidate)
            .where(SnkrdunkCandidate.id.in_(unique))
            .order_by(SnkrdunkCandidate.id)
        )
    )
    missing = sorted(set(unique) - {r.id for r in rows})
    if missing:
        raise BatchApprovalError(
            f"Refusing: candidate id(s) {missing} do not exist. Nothing was read or written."
        )
    return rows


def plan_candidate(db: Session, source: Source, candidate: SnkrdunkCandidate) -> CandidatePlan:
    """Decide one candidate against the LIVE catalogue. Writes nothing.

    The order of the checks is the order in which their answers are useful.
    The cheap facts about the row come first, so an already-approved candidate
    is not reported as an artwork problem; the resolver runs next, so the plan
    can name the printing; the mapping and URL checks come last, because they
    are only meaningful once a printing is known.
    """
    evidence = SourceEvidence.from_snkrdunk_candidate(candidate)
    plan = CandidatePlan(
        candidate_id=candidate.id,
        source_url=candidate.source_url,
        match_status=candidate.match_status,
        listing_identity=listing_id(candidate.source_url),
        card_code=candidate.detected_card_code,
        product_label=evidence.product_label,
        variant=candidate.detected_variant,
    )

    def refuse(code: str, reason: str) -> CandidatePlan:
        plan.refusal_code = code
        plan.refusal_reason = reason
        plan.action = "refuse"
        return plan

    if candidate.match_status != ELIGIBLE_MATCH_STATUS:
        return refuse(
            REFUSAL_NOT_UNMATCHED,
            f"match_status is {candidate.match_status!r}, not {ELIGIBLE_MATCH_STATUS!r}: a "
            "decision has already landed on this row and a batch approval must never "
            "override one.",
        )

    # The source naming another game outright, in its own asset filename.
    # Checked before the resolver so the plan says "Shadowverse" rather than
    # "card code not in the catalogue", which is the same row described in a
    # way that hides why.
    foreign = identify_non_target_tcg(candidate.image_url)
    if foreign is not None:
        return refuse(
            REFUSAL_NOT_ONE_PIECE,
            f"The listing's own asset filename identifies this as {foreign}, not One Piece.",
        )

    # THE RESOLVER, run exactly as the approval screen runs it: once per
    # sibling printing, with the surviving set being the answer. Nothing is
    # read from a stored verdict column.
    siblings = sibling_prints_for_card_code(db, evidence.card_code) if evidence.card_code else []
    plan.considered_print_ids = sorted(p.id for p, _ in siblings)
    if not siblings:
        plan.verdict = REFUSAL_NO_SIBLINGS
        return refuse(
            REFUSAL_NO_SIBLINGS,
            f"No active verified print shares card code {candidate.detected_card_code!r}."
            if candidate.detected_card_code
            else "The listing has no detected card code, so no printing can be proposed.",
        )

    approvable: list[int] = []
    decisions = {}
    for print_row, _canonical in sorted(siblings, key=lambda r: r[0].id):
        try:
            decision = resolve_exact_print(db, card_print_id=print_row.id, evidence=evidence)
        except ExactPrintApprovalError as exc:
            plan.sibling_refusals[print_row.id] = exc.code
        else:
            approvable.append(print_row.id)
            decisions[print_row.id] = decision
    plan.approvable_print_ids = approvable

    if len(approvable) != 1:
        # The refusal codes the gate produced ARE the verdict - they say
        # whether the product was unreadable, the evidence contradicted every
        # printing, or nothing distinguished them. Reported verbatim.
        codes = sorted(set(plan.sibling_refusals.values()))
        plan.verdict = "/".join(codes) if codes else "no_verdict"
        return refuse(
            REFUSAL_NOT_EXACT,
            f"{len(approvable)} of {len(siblings)} printings can be justified from the stored "
            f"evidence (need exactly 1). Gate refusals: {codes}.",
        )

    decision = decisions[approvable[0]]
    print_row = decision.card_print
    canonical = decision.canonical
    product = (
        db.get(ReleaseProduct, print_row.release_product_id)
        if print_row.release_product_id
        else None
    )
    plan.verdict = "exact"
    plan.card_print_id = print_row.id
    plan.evidence_used = list(decision.evidence_used)
    plan.language = print_row.language
    plan.variant = print_row.official_asset_variant
    plan.printing = printing_label(print_row)
    plan.special_print = special_print_label(print_row, canonical)
    plan.release_product_id = print_row.release_product_id
    plan.release_product = (
        print_row.release_product_code
        or (f"uncoded #{product.id} {product.display_name}" if product else None)
    )
    plan.card_code = canonical.card_code

    # Redundant with the gate - `assert_print_is_priceable` has already run
    # inside `resolve_exact_print` - and kept anyway, because the eligibility
    # rule is stated as "print active + verified" and a rule that is only
    # enforced somewhere else is a rule that can be silently dropped.
    if not print_row.is_active or print_row.verification_status != "verified":
        return refuse(
            "print_not_priceable",
            f"card_print {print_row.id} is active={print_row.is_active} "
            f"verification_status={print_row.verification_status!r}.",
        )

    # THE URL THE COLLECTOR WILL FETCH. Refused, never guessed at.
    try:
        plan.canonical_url = canonical_listing_url(
            candidate.source_url, card_print_language=print_row.language
        )
    except ExactPrintApprovalError as exc:
        return refuse(exc.code, exc.detail)

    # The SAME listing-identity lookup the human approval paths use - see
    # app.services.snkrdunk_candidate_approval.find_mapping_for_listing. It
    # raises when one listing has more than one mapping, which a batch must
    # never choose between.
    try:
        mapping = find_mapping_for_listing(db, source=source, url=candidate.source_url)
    except ExactPrintApprovalError as exc:
        return refuse(exc.code, exc.detail)
    if mapping is not None:
        plan.existing_mapping_id = mapping.id
        plan.existing_mapping_print_id = mapping.card_print_id
        plan.existing_mapping_status = mapping.review_status
        # The SAME rejected-mapping guard the write path enforces, called here
        # so the plan REPORTS the refusal instead of only discovering it at
        # apply time. One definition, two moments.
        try:
            assert_mapping_may_be_approved(mapping)
        except ExactPrintApprovalError as exc:
            return refuse(exc.code, exc.detail)
        if mapping.card_print_id is None:
            return refuse(
                REFUSAL_MAPPING_NO_PRINT,
                f"Mapping {mapping.id} predates exact prints and names no printing. "
                "Approve it individually so the change of claim is visible.",
            )
        if mapping.card_print_id != print_row.id:
            return refuse(
                REFUSAL_MAPPING_CONFLICT,
                f"Mapping {mapping.id} already prices card_print {mapping.card_print_id}, "
                f"and the resolver says {print_row.id}. A batch must not re-point an "
                "existing mapping.",
            )
        if mapping.source_url not in equivalent_listing_urls(candidate.source_url):
            return refuse(
                REFUSAL_MAPPING_CONFLICT,
                f"Mapping {mapping.id} holds this listing under a non-canonical URL "
                f"({mapping.source_url!r}). The approval write reuses a mapping by URL "
                "equality, so applying here would create a SECOND mapping for one listing. "
                "Canonicalise that row first.",
            )
        plan.action = "update existing mapping (already names this print)"
    else:
        plan.action = "create mapping"
    return plan


def plan_batch(db: Session, candidate_ids: list[int]) -> BatchReport:
    """Decide the whole batch without writing anything."""
    try:
        source = get_snkrdunk_source(db)
    except SnkrdunkSourceMissing as exc:
        raise BatchApprovalError(str(exc)) from exc
    report = BatchReport()
    for candidate in select_candidates(db, candidate_ids):
        report.plans.append(plan_candidate(db, source, candidate))
    return report


def apply_batch(
    db: Session,
    candidate_ids: list[int],
    confirm: str | None = None,
    expected_plan: list[CandidatePlan] | None = None,
    commit: bool = True,
) -> BatchReport:
    """Re-plan, verify nothing moved, then write the whole batch at once.

    The re-plan is not a formality. Between the plan the operator read and
    this call, a print can be deactivated, a product alias can be added, or
    someone can approve one of these listings by hand - and any of those makes
    the printed plan a description of a decision that no longer exists. So the
    batch is abandoned in full rather than partially applied: an approval the
    operator did not read is exactly what this job exists to prevent.
    """
    if confirm != CONFIRM_PHRASE:
        raise BatchApprovalError(
            f'Refusing to apply without the confirmation phrase. Pass --confirm "{CONFIRM_PHRASE}".'
        )

    report = plan_batch(db, candidate_ids)

    if expected_plan is not None:
        before = {p.candidate_id: p.identity() for p in expected_plan}
        now = {p.candidate_id: p.identity() for p in report.plans}
        moved = sorted(k for k in set(before) | set(now) if before.get(k) != now.get(k))
        if moved:
            raise BatchApprovalError(
                f"Refusing: candidate(s) {moved} resolve differently now than when the plan "
                "was made. The WHOLE batch was abandoned; nothing was written. Re-plan and "
                "read it again."
            )

    refused = report.refused
    if refused:
        raise BatchApprovalError(
            "Refusing: "
            f"{len(refused)} of {len(report.plans)} scoped candidate(s) are not "
            f"approval-eligible ({sorted(p.candidate_id for p in refused)}). A batch approves "
            "the set it was given or none of it - narrow --candidate-ids to the eligible rows."
        )

    source = get_snkrdunk_source(db)
    try:
        for plan in report.plans:
            candidate = db.get(SnkrdunkCandidate, plan.candidate_id)
            result = approve_candidate_onto_print(
                db,
                candidate=candidate,
                card_print_id=plan.card_print_id,
                # No legacy Card row is created or named. card_print_id is the
                # authoritative lineage and card_id stays NULL - see
                # app.services.snkrdunk_candidate_approval.
                card=None,
                source=source,
            )
            mapping = result.mapping
            report.outcomes.append(
                ApprovalOutcome(
                    candidate_id=candidate.id,
                    mapping_id=mapping.id,
                    mapping_created=result.mapping_created,
                    card_print_id=mapping.card_print_id,
                    card_id=mapping.card_id,
                    review_status=mapping.review_status,
                    manual_verified=mapping.manual_verified,
                    source_url=mapping.source_url,
                    candidate_status=candidate.match_status,
                    evidence_used=list(result.decision.evidence_used),
                )
            )
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        raise

    report.applied = True
    return report


def format_report(report: BatchReport) -> str:
    lines = []
    mode = "APPLIED" if report.applied else "PLAN (dry run - nothing written)"
    lines.append(f"== SNKRDUNK exact batch approval: {mode} ==")
    for plan in report.plans:
        lines.append("")
        lines.append(f"candidate {plan.candidate_id}  [{plan.match_status}]  {plan.source_url}")
        lines.append(f"  canonical listing : {plan.canonical_url or '-'}  (id {plan.listing_identity or '-'})")
        lines.append(f"  card code         : {plan.card_code or '-'}")
        lines.append(f"  source product    : {plan.product_label or '(none named)'}")
        lines.append(f"  release product   : {plan.release_product or '-'}")
        lines.append(
            f"  card_print_id     : {plan.card_print_id or '-'}"
            f"  variant={plan.variant or '-'}"
            f"  printing={plan.printing or 'base'}"
            f"  special={plan.special_print or '-'}"
            f"  lang={plan.language or '-'}"
        )
        lines.append(f"  resolver verdict  : {plan.verdict}")
        lines.append(f"  evidence used     : {'; '.join(plan.evidence_used) or '-'}")
        lines.append(
            f"  considered prints : {plan.considered_print_ids} approvable={plan.approvable_print_ids}"
        )
        if plan.existing_mapping_id is not None:
            lines.append(
                f"  existing mapping  : #{plan.existing_mapping_id} "
                f"card_print_id={plan.existing_mapping_print_id} "
                f"status={plan.existing_mapping_status}"
            )
        else:
            lines.append("  existing mapping  : none")
        lines.append(f"  proposed action   : {plan.action}")
        if plan.refusal_code:
            lines.append(f"  REFUSED [{plan.refusal_code}]: {plan.refusal_reason}")
    if report.outcomes:
        lines.append("")
        lines.append("-- written --")
        for out in report.outcomes:
            lines.append(
                f"candidate {out.candidate_id} -> mapping {out.mapping_id} "
                f"({'created' if out.mapping_created else 'reused'}) "
                f"card_print_id={out.card_print_id} card_id={out.card_id} "
                f"review_status={out.review_status} manual_verified={out.manual_verified} "
                f"candidate={out.candidate_status} url={out.source_url}"
            )
    lines.append("")
    lines.append(
        f"scoped={len(report.plans)} approvable={len(report.approvable)} "
        f"refused={len(report.refused)} approved={len(report.outcomes)} "
        f"mappings_created={report.mappings_created} mappings_reused={report.mappings_reused} "
        f"price_observations_written=0"
    )
    return "\n".join(lines)


def _parse_ids(raw: str | None, path: str | None) -> list[int]:
    ids: list[int] = []
    if raw:
        ids += [int(x) for x in raw.replace("\n", ",").split(",") if x.strip()]
    if path:
        with open(path) as fh:
            text = fh.read()
        ids += [int(x) for x in text.replace("\n", ",").split(",") if x.strip()]
    return ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Approve reviewed, exactly-resolved SNKRDUNK candidates onto their printings. "
            "Plans by default; fetches nothing; writes no price observations."
        )
    )
    parser.add_argument("--candidate-ids", default=None, help="Comma-separated candidate ids.")
    parser.add_argument(
        "--from-file", default=None, help="File of candidate ids (comma or newline separated)."
    )
    parser.add_argument("--apply", action="store_true", help="Write the plan. Requires --confirm.")
    parser.add_argument("--confirm", default=None, help=f'Exactly: "{CONFIRM_PHRASE}"')
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    args = parser.parse_args(argv)

    ids = _parse_ids(args.candidate_ids, args.from_file)

    db = SessionLocal()
    try:
        if args.apply:
            # The plan the operator's confirmation refers to, re-made here and
            # compared inside apply_batch. Same session, so it sees exactly
            # what the write will see.
            expected = plan_batch(db, ids).plans
            report = apply_batch(db, ids, confirm=args.confirm, expected_plan=expected)
        else:
            report = plan_batch(db, ids)
    except BatchApprovalError as exc:
        print(f"REFUSED: {exc}")
        return 2
    finally:
        db.close()

    print(json.dumps(report.as_dict(), indent=2) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
