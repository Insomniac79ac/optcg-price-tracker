"""The router-layer half of the exact-print approval contract.

Two things live here, and both exist so that "approved" means one thing no
matter which endpoint wrote it:

  * `approval_http_error` - the single refusal-code -> status-code mapping,
    shared by the candidate approval endpoints and the admin mapping ones.
  * `guard_transition_to_approved` - the check every path that moves a row
    INTO `approved` must run first.

Why a router-layer module rather than the service: `app.services.*` does not
import FastAPI in this codebase (one unrelated exception aside), and the
service is deliberately transport-agnostic - it raises
`ExactPrintApprovalError` and lets the edge decide what an HTTP client sees.

WHY THE GUARD EXISTS AT ALL. 4F-1 closed the paths that CREATE a mapping, but
a mapping can also become approved by having its review state flipped - and
those endpoints never looked at `card_print_id`. A legacy row whose
`card_print_id` is NULL could therefore be walked into `approved` without ever
passing the exact-print contract, which is the same unsupported claim the
contract exists to prevent: a price attached to a card code rather than to the
printing that was actually sold.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import SourceCardMapping
from app.services.exact_print_approval import (
    REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT,
    REFUSAL_PRINT_NOT_FOUND,
    REFUSAL_PRINT_REQUIRED,
    ExactPrintApprovalError,
    assert_print_is_priceable,
)

APPROVED = "approved"


def approval_http_error(exc: ExactPrintApprovalError) -> HTTPException:
    """One mapping from a refusal to a status code, shared by every approval
    endpoint so they cannot drift.

    409 is the interesting one: "the evidence does not prove this print", or
    "this row names no print at all", is not a malformed request and not a
    missing resource - it is a conflict between what was asked for and what
    can be substantiated. Clients branch on `code`, never on the prose.
    """
    if exc.code == REFUSAL_PRINT_REQUIRED:
        status = 400
    elif exc.code == REFUSAL_PRINT_NOT_FOUND:
        status = 404
    elif exc.needs_review:
        status = 409
    else:
        status = 400
    return HTTPException(
        status_code=status,
        detail={
            "code": exc.code,
            "message": exc.detail,
            "alternatives": exc.alternatives,
            "needs_review": exc.needs_review,
        },
    )


def guard_transition_to_approved(db: Session, mapping: SourceCardMapping) -> None:
    """Refuse to let a row ENTER `approved` unless it names a priceable print.

    Raises ExactPrintApprovalError; callers turn that into a response with
    `approval_http_error`. It must be called BEFORE any field is written, so a
    refused request leaves the row exactly as it was.

    ALREADY-APPROVED ROWS ARE NOT A TRANSITION, and are left alone on purpose.
    Six approved Yuyu-Tei mappings on staging predate exact prints and carry a
    NULL `card_print_id`; they stay readable and keep working. Demoting them
    here would be a data migration wearing an endpoint's clothes, and this
    guard's job is to stop the set growing, not to rewrite history. Their gap
    is real and stays visible in `card_print_id`.

    Nothing is inferred. A NULL print is never filled in from the card code -
    that is the inference the whole contract forbids.
    """
    if mapping.review_status == APPROVED:
        return

    if mapping.card_print_id is None:
        raise ExactPrintApprovalError(
            REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT,
            f"Source mapping {mapping.id} has no card_print_id, so approving it would "
            "assert a price against a card code rather than against the printing that "
            "was sold. Re-approve it through a candidate approval path that resolves "
            "the exact print; it will not be guessed from the card code.",
        )

    # A print that has since been deactivated or un-verified cannot be priced
    # against either, so the same three facts are checked here as at creation.
    assert_print_is_priceable(db, mapping.card_print_id)
