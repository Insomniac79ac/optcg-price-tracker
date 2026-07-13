from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.db import get_db
from app.models import Card, CollectionItem, GradingSubmission, User
from app.models.grading_submission import GRADING_SUBMISSION_STATUSES
from app.schemas import (
    GradingSubmissionCreateIn,
    GradingSubmissionListOut,
    GradingSubmissionOut,
    GradingSubmissionUpdateIn,
    GradingSummaryOut,
)
from app.services.grading import (
    build_grading_submission_out,
    build_grading_summary,
    compute_total_cost_jpy,
)

router = APIRouter(prefix="/grading", tags=["grading"])


def _get_item_or_404(db: Session, item_id: int, user: User) -> CollectionItem:
    item = db.get(CollectionItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Collection item not found")
    return item


def _get_submission_or_404(db: Session, submission_id: int, user: User) -> GradingSubmission:
    """A submission's ownership is transitive through its collection item -
    grading_submissions has no user_id column of its own (mirrors how it
    already cascade-deletes off collection_items)."""
    submission = db.scalar(
        select(GradingSubmission)
        .join(CollectionItem, GradingSubmission.collection_item_id == CollectionItem.id)
        .where(GradingSubmission.id == submission_id, CollectionItem.user_id == user.id)
    )
    if submission is None:
        raise HTTPException(status_code=404, detail="Grading submission not found")
    return submission


def _recompute_total_cost(submission: GradingSubmission) -> None:
    submission.total_cost_jpy = compute_total_cost_jpy(
        submission.grading_fee_jpy,
        submission.shipping_fee_jpy,
        submission.insurance_fee_jpy,
        submission.other_fee_jpy,
    )


@router.get("/submissions", response_model=GradingSubmissionListOut)
def list_grading_submissions(
    status: str | None = Query(default=None),
    grading_company: str | None = Query(default=None),
    card_code: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    if status is not None and status not in GRADING_SUBMISSION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(GRADING_SUBMISSION_STATUSES)}",
        )

    filters = [CollectionItem.user_id == user.id]
    if status is not None:
        filters.append(GradingSubmission.submission_status == status)
    if grading_company is not None:
        filters.append(GradingSubmission.grading_company == grading_company)

    base = (
        select(GradingSubmission)
        .join(CollectionItem, GradingSubmission.collection_item_id == CollectionItem.id)
        .join(Card, CollectionItem.card_id == Card.id)
        .where(*filters)
    )
    if card_code is not None:
        base = base.where(Card.card_code == card_code)

    count_stmt = (
        select(func.count())
        .select_from(GradingSubmission)
        .join(CollectionItem, GradingSubmission.collection_item_id == CollectionItem.id)
        .join(Card, CollectionItem.card_id == Card.id)
        .where(*filters)
    )
    if card_code is not None:
        count_stmt = count_stmt.where(Card.card_code == card_code)
    total = db.scalar(count_stmt) or 0

    submissions = db.scalars(
        base.order_by(GradingSubmission.id.desc()).limit(limit).offset(offset)
    ).all()

    item_ids = {s.collection_item_id for s in submissions}
    items_by_id: dict[int, CollectionItem] = {}
    cards_by_item_id: dict[int, Card] = {}
    if item_ids:
        items_by_id = {
            i.id: i for i in db.scalars(select(CollectionItem).where(CollectionItem.id.in_(item_ids))).all()
        }
        card_ids = {i.card_id for i in items_by_id.values()}
        cards_by_id = {
            c.id: c for c in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()
        }
        cards_by_item_id = {
            item_id: cards_by_id[item.card_id] for item_id, item in items_by_id.items()
        }

    out_items = [
        build_grading_submission_out(
            s, items_by_id[s.collection_item_id], cards_by_item_id[s.collection_item_id]
        )
        for s in submissions
    ]
    return GradingSubmissionListOut(items=out_items, total=total, limit=limit, offset=offset)


@router.get("/summary", response_model=GradingSummaryOut)
def get_grading_summary(
    db: Session = Depends(get_db), user: User = Depends(require_current_user)
):
    summary = build_grading_summary(db, user_id=user.id)
    return GradingSummaryOut(
        total_submissions=summary.total_submissions,
        by_status=summary.by_status,
        total_declared_value_jpy=summary.total_declared_value_jpy,
        total_grading_cost_jpy=summary.total_grading_cost_jpy,
        total_graded_value_jpy=summary.total_graded_value_jpy,
        total_unrealized_gain_after_grading_jpy=summary.total_unrealized_gain_after_grading_jpy,
        average_grade=summary.average_grade,
        items_waiting_return=summary.items_waiting_return,
    )


@router.post("/submissions", response_model=GradingSubmissionOut, status_code=201)
def create_grading_submission(
    body: GradingSubmissionCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    item = _get_item_or_404(db, body.collection_item_id, user)

    submission = GradingSubmission(**body.model_dump())
    _recompute_total_cost(submission)
    db.add(submission)
    db.commit()
    db.refresh(submission)

    card = db.get(Card, item.card_id)
    return build_grading_submission_out(submission, item, card)


@router.get("/submissions/{submission_id}", response_model=GradingSubmissionOut)
def get_grading_submission(
    submission_id: int, db: Session = Depends(get_db), user: User = Depends(require_current_user)
):
    submission = _get_submission_or_404(db, submission_id, user)
    item = db.get(CollectionItem, submission.collection_item_id)
    card = db.get(Card, item.card_id)
    return build_grading_submission_out(submission, item, card)


@router.patch("/submissions/{submission_id}", response_model=GradingSubmissionOut)
def update_grading_submission(
    submission_id: int,
    body: GradingSubmissionUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_current_user),
):
    submission = _get_submission_or_404(db, submission_id, user)

    updates = body.model_dump(exclude_unset=True)
    if "collection_item_id" in updates:
        _get_item_or_404(db, updates["collection_item_id"], user)

    for field, value in updates.items():
        setattr(submission, field, value)

    _recompute_total_cost(submission)

    db.commit()
    db.refresh(submission)

    item = db.get(CollectionItem, submission.collection_item_id)
    card = db.get(Card, item.card_id)
    return build_grading_submission_out(submission, item, card)


@router.delete("/submissions/{submission_id}", status_code=204)
def delete_grading_submission(
    submission_id: int, db: Session = Depends(get_db), user: User = Depends(require_current_user)
):
    submission = _get_submission_or_404(db, submission_id, user)
    db.delete(submission)
    db.commit()
    return None
