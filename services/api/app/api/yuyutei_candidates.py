"""Admin-only review and approval of Yuyu-Tei discovery candidates.

ADMIN ONLY, AT THE ROUTER. `require_admin_token` is a router-level dependency
exactly as on /admin/snkrdunk-candidates, so every path added here inherits it
and no future endpoint can be added without it by forgetting a decorator.
Nothing on this router is reachable publicly, and none of it is mounted under
a public prefix.

WHY APPROVAL TAKES NO PRINT ID. The SNKRDUNK screen asks the operator to pick
a printing from the siblings and then checks the pick. Here the pick has
already been made by the catalogue: discovery writes `matched_card_print_id`
only when the card code resolved to exactly one active print, on both sides of
a 1:1, and `ck_yuyutei_candidates_print_requires_print_matched` makes any other
value unrepresentable. Accepting a print id in the request body would create a
route to approve a printing the classification never established - the exact
hole the discovery design closes. So the operator's decision is *whether*, and
the endpoint takes only review notes.

WHAT APPROVAL DOES NOT DO, from this layer's point of view: it commits one
mapping row and nothing else. No price observation is written, the collector
is not invoked, and no Market Index code is reachable from here - none of it
is imported.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api._mapping_approval import approval_http_error
from app.auth import require_admin_token
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, pagination_response
from app.db import get_db
from app.models import CanonicalCard, CardPrint, SourceCardMapping
from app.models.yuyutei_candidate import MATCH_STATUSES, YuyuteiCandidate
from app.schemas import (
    YuyuteiApprovalOut,
    YuyuteiApproveIn,
    YuyuteiCandidateListOut,
    YuyuteiCandidateOut,
    YuyuteiMatchedPrintOut,
)
from app.services.exact_print_approval import ExactPrintApprovalError
from app.services.yuyutei_candidate_approval import (
    YuyuteiSourceMissing,
    approve_candidate,
    get_yuyutei_source,
)
from app.services.yuyutei_urls import listing_identity
from app.services.app_logging import record_app_log

router = APIRouter(
    prefix="/admin/yuyutei-candidates",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)

# The queue opens on the only status that can be approved. A reviewer landing
# on 412 rows of which 218 are unapprovable spends their attention deciding
# what to ignore; landing on the 194 that are actionable spends it on the
# decision. Every other status stays one query parameter away, never hidden.
DEFAULT_MATCH_STATUS = "print_matched"


def _get_candidate_or_404(db: Session, candidate_id: int) -> YuyuteiCandidate:
    candidate = db.get(YuyuteiCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


def _mapping_ids_by_identity(
    db: Session, candidates: list[YuyuteiCandidate]
) -> dict[tuple[str, str], int]:
    """Listing identity -> mapping id, for the whole page in one query.

    Batched deliberately: the approval state of N candidates is N lookups done
    naively, and this endpoint's whole job is to show a page of them.

    Matched on the PARSED identity, never on URL equality - the same rule the
    approval path follows (see
    yuyutei_candidate_approval.find_mapping_for_listing). A stored URL with a
    query string is the same listing; the legacy card-code rows parse to None
    and so match nothing, which is correct - they are not listings.
    """
    source = get_yuyutei_source(db)
    wanted = {
        identity
        for identity in (listing_identity(c.source_url) for c in candidates)
        if identity is not None
    }
    if not wanted:
        return {}
    rows = db.scalars(
        select(SourceCardMapping).where(SourceCardMapping.source_id == source.id)
    ).all()
    found: dict[tuple[str, str], int] = {}
    for mapping in rows:
        identity = listing_identity(mapping.source_url)
        if identity is not None and identity in wanted:
            # Lowest id wins only for display. A listing held by two mappings
            # is a real conflict, and the approval path refuses it loudly
            # rather than picking - this dict never feeds that decision.
            previous = found.get(identity)
            found[identity] = mapping.id if previous is None else min(previous, mapping.id)
    return found


def _matched_prints(
    db: Session, candidates: list[YuyuteiCandidate]
) -> dict[int, YuyuteiMatchedPrintOut]:
    """card_print_id -> the printing summary, for the whole page in one query."""
    print_ids = {c.matched_card_print_id for c in candidates if c.matched_card_print_id}
    if not print_ids:
        return {}
    rows = db.execute(
        select(CardPrint, CanonicalCard)
        .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .where(CardPrint.id.in_(print_ids))
    ).all()
    return {
        print_row.id: YuyuteiMatchedPrintOut(
            card_print_id=print_row.id,
            card_code=canonical.card_code,
            treatment=print_row.treatment,
            language=print_row.language,
            release_product_code=print_row.release_product_code,
            official_asset_variant=print_row.official_asset_variant,
            verification_status=print_row.verification_status,
            is_active=print_row.is_active,
            image_url=print_row.image_url,
        )
        for print_row, canonical in rows
    }


def _serialize(
    candidate: YuyuteiCandidate,
    mapping_ids: dict[tuple[str, str], int],
    prints: dict[int, YuyuteiMatchedPrintOut],
) -> YuyuteiCandidateOut:
    identity = listing_identity(candidate.source_url)
    mapping_id = mapping_ids.get(identity) if identity is not None else None
    out = YuyuteiCandidateOut.model_validate(candidate)
    out.mapping_id = mapping_id
    out.approved = mapping_id is not None
    if candidate.matched_card_print_id is not None:
        out.matched_print = prints.get(candidate.matched_card_print_id)
    return out


@router.get("", response_model=YuyuteiCandidateListOut)
def list_candidates(
    set_slug: str | None = Query(default=None),
    match_status: str | None = Query(default=DEFAULT_MATCH_STATUS),
    approved: bool | None = Query(
        default=None,
        description="Filter on whether a Yuyu-Tei mapping already holds the listing. "
        "Derived from the mappings table, not from a column on the candidate.",
    ),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """The review queue. Defaults to `print_matched`; pass
    `match_status=` (empty) to see every status.

    The `approved` filter is applied in Python rather than in SQL, and that is
    a deliberate trade rather than an oversight: approval state is a parsed
    listing identity, not a column, and expressing "the mapping whose URL
    parses to this candidate's (slug, product_id)" as a join would mean
    matching on URL equality - the exact shortcut that let one SNKRDUNK
    listing acquire two mappings. The candidate table is small (412 rows on
    staging today) and the filter runs after the status/slug narrowing.
    """
    if match_status is not None and match_status != "" and match_status not in MATCH_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid match_status. Must be one of {list(MATCH_STATUSES)}",
        )

    filters = []
    if set_slug:
        filters.append(YuyuteiCandidate.set_slug == set_slug)
    if match_status:
        filters.append(YuyuteiCandidate.match_status == match_status)

    if approved is None:
        total = db.scalar(
            select(func.count()).select_from(YuyuteiCandidate).where(*filters)
        )
        rows = list(
            db.scalars(
                select(YuyuteiCandidate)
                .where(*filters)
                .order_by(YuyuteiCandidate.set_slug.asc(), YuyuteiCandidate.id.asc())
                .limit(limit)
                .offset(offset)
            ).all()
        )
        mapping_ids = _mapping_ids_by_identity(db, rows)
    else:
        matching = list(
            db.scalars(
                select(YuyuteiCandidate)
                .where(*filters)
                .order_by(YuyuteiCandidate.set_slug.asc(), YuyuteiCandidate.id.asc())
            ).all()
        )
        mapping_ids = _mapping_ids_by_identity(db, matching)

        def _is_approved(candidate: YuyuteiCandidate) -> bool:
            identity = listing_identity(candidate.source_url)
            return identity is not None and identity in mapping_ids

        matching = [c for c in matching if _is_approved(c) is approved]
        total = len(matching)
        rows = matching[offset : offset + limit]

    prints = _matched_prints(db, rows)
    items = [_serialize(candidate, mapping_ids, prints) for candidate in rows]
    return YuyuteiCandidateListOut(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        pagination=pagination_response(items, total, limit, offset),
    )


@router.get("/{candidate_id}", response_model=YuyuteiCandidateOut)
def get_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = _get_candidate_or_404(db, candidate_id)
    mapping_ids = _mapping_ids_by_identity(db, [candidate])
    prints = _matched_prints(db, [candidate])
    return _serialize(candidate, mapping_ids, prints)


@router.post("/{candidate_id}/approve", response_model=YuyuteiApprovalOut)
def approve(
    candidate_id: int,
    payload: YuyuteiApproveIn,
    db: Session = Depends(get_db),
):
    """Approve one candidate onto the printing it already names.

    Explicit and human-triggered: one POST, one candidate, one operator. There
    is no batch endpoint, no `approve-all`, and nothing schedules this - the
    only way a Yuyu-Tei mapping is created from a candidate is a person
    sending this request.
    """
    candidate = _get_candidate_or_404(db, candidate_id)

    try:
        result = approve_candidate(
            db, candidate=candidate, review_notes=payload.review_notes
        )
    except ExactPrintApprovalError as exc:
        # One shared refusal -> status mapping, so this endpoint cannot drift
        # from the SNKRDUNK one. Clients branch on detail.code.
        raise approval_http_error(exc) from exc
    except YuyuteiSourceMissing as exc:
        # A deployment fault, not something the operator can resolve by
        # looking at the listing.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    db.commit()
    db.refresh(candidate)
    db.refresh(result.mapping)

    record_app_log(
        "info",
        "api",
        "yuyutei_candidates",
        f"Candidate {candidate.id} approved -> card_print_id={result.mapping.card_print_id}",
        context={
            "candidate_id": candidate.id,
            "set_slug": candidate.set_slug,
            "product_id": candidate.product_id,
            "card_print_id": result.mapping.card_print_id,
            "mapping_id": result.mapping.id,
            "mapping_created": result.mapping_created,
            "evidence_used": result.decision.evidence_used,
        },
        related_entity_type="yuyutei_candidate",
        related_entity_id=candidate.id,
    )

    mapping_ids = _mapping_ids_by_identity(db, [candidate])
    prints = _matched_prints(db, [candidate])
    return YuyuteiApprovalOut(
        candidate=_serialize(candidate, mapping_ids, prints),
        mapping_id=result.mapping.id,
        card_print_id=result.mapping.card_print_id,
        source_card_id=result.mapping.source_card_id,
        source_url=result.mapping.source_url,
        mapping_created=result.mapping_created,
        review_notes=result.mapping.review_notes,
        evidence_used=result.decision.evidence_used,
    )
