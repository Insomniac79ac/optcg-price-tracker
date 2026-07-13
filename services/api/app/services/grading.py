import re
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card, CollectionItem, GradingSubmission
from app.models.grading_submission import GRADING_SUBMISSION_STATUSES
from app.schemas import GradingInfoOut, GradingSubmissionOut

# Submitted-but-not-yet-back-in-hand statuses - used for the "items waiting
# return" summary metric. "planned"/"preparing" haven't left the owner yet;
# "received"/"cancelled" are terminal states.
WAITING_RETURN_STATUSES = ("submitted", "grading", "shipped_back")

_NUMERIC_GRADE_RE = re.compile(r"(\d+(?:\.\d+)?)")


def compute_total_cost_jpy(
    grading_fee_jpy: int | None,
    shipping_fee_jpy: int | None,
    insurance_fee_jpy: int | None,
    other_fee_jpy: int | None,
) -> int | None:
    """Sums the four fee components, treating an unset one as a 0
    contribution - but only once at least one fee has actually been entered.
    If nothing has been entered yet, the total cost is unknown, not 0."""
    fees = (grading_fee_jpy, shipping_fee_jpy, insurance_fee_jpy, other_fee_jpy)
    if all(f is None for f in fees):
        return None
    return sum(f or 0 for f in fees)


def parse_numeric_grade(final_grade: str | None) -> float | None:
    """Extracts a numeric grade from a free-text final_grade value (e.g.
    "10", "9.5", "PSA 10", "BGS 9.5") so it can feed an average - returns
    None when no number is present (e.g. "Authentic", "N/A")."""
    if not final_grade:
        return None
    match = _NUMERIC_GRADE_RE.search(final_grade)
    if not match:
        return None
    return float(match.group(1))


def get_submissions_for_items(
    db: Session, item_ids: set[int]
) -> dict[int, list[GradingSubmission]]:
    """Batch-loads all grading submissions for a set of collection item ids,
    each item's list ordered newest-first (by id)."""
    if not item_ids:
        return {}
    rows = db.scalars(
        select(GradingSubmission)
        .where(GradingSubmission.collection_item_id.in_(item_ids))
        .order_by(GradingSubmission.id.desc())
    ).all()
    result: dict[int, list[GradingSubmission]] = defaultdict(list)
    for row in rows:
        result[row.collection_item_id].append(row)
    return result


def get_submissions_for_cards(
    db: Session, card_ids: set[int]
) -> dict[int, list[GradingSubmission]]:
    """Unions grading submissions across every collection item owning each
    card, newest-first - a card can have several owned copies, each with its
    own grading history."""
    if not card_ids:
        return {}
    rows = db.execute(
        select(CollectionItem.card_id, GradingSubmission)
        .join(GradingSubmission, GradingSubmission.collection_item_id == CollectionItem.id)
        .where(CollectionItem.card_id.in_(card_ids))
        .order_by(GradingSubmission.id.desc())
    ).all()
    result: dict[int, list[GradingSubmission]] = defaultdict(list)
    for card_id, submission in rows:
        result[card_id].append(submission)
    return result


def latest_submission(
    submissions_by_key: dict[int, list[GradingSubmission]], key: int
) -> GradingSubmission | None:
    items = submissions_by_key.get(key)
    return items[0] if items else None


def latest_updated_submission(submissions: list[GradingSubmission]) -> GradingSubmission | None:
    """Most-recently-*updated* submission in a list - distinct from
    latest_submission's newest-by-id ordering. Graded-adjusted valuation
    keys off this one, since a re-submission or status correction on an
    older row should take precedence over a merely newer-id row."""
    if not submissions:
        return None
    return max(submissions, key=lambda s: s.updated_at)


def received_grading_cost_jpy(submissions: list[GradingSubmission]) -> int:
    """Sums grading cost across only 'received' submissions for an item,
    treating an unset fee component as 0. Costs tied to
    planned/preparing/submitted/grading/shipped_back/cancelled submissions
    never became a realized cost against the graded value, so they're
    excluded from graded-adjusted P/L entirely."""
    total = 0
    for s in submissions:
        if s.submission_status != "received":
            continue
        total += (
            (s.grading_fee_jpy or 0)
            + (s.shipping_fee_jpy or 0)
            + (s.insurance_fee_jpy or 0)
            + (s.other_fee_jpy or 0)
        )
    return total


def build_grading_submission_out(
    submission: GradingSubmission, item: CollectionItem, card: Card
) -> GradingSubmissionOut:
    return GradingSubmissionOut(
        id=submission.id,
        collection_item_id=submission.collection_item_id,
        card_code=card.card_code,
        name_en=card.name_en,
        name_jp=card.name_jp,
        quantity=item.quantity,
        grading_company=submission.grading_company,
        submission_name=submission.submission_name,
        submission_status=submission.submission_status,
        declared_value_jpy=submission.declared_value_jpy,
        grading_fee_jpy=submission.grading_fee_jpy,
        shipping_fee_jpy=submission.shipping_fee_jpy,
        insurance_fee_jpy=submission.insurance_fee_jpy,
        other_fee_jpy=submission.other_fee_jpy,
        total_cost_jpy=submission.total_cost_jpy,
        submitted_at=submission.submitted_at,
        received_at=submission.received_at,
        expected_return_date=submission.expected_return_date,
        tracking_number=submission.tracking_number,
        final_grade=submission.final_grade,
        cert_number=submission.cert_number,
        graded_value_jpy=submission.graded_value_jpy,
        notes=submission.notes,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
    )


def build_grading_info(latest: GradingSubmission | None) -> GradingInfoOut:
    if latest is None:
        return GradingInfoOut(
            has_grading_submission=False,
            latest_status=None,
            grading_company=None,
            final_grade=None,
            total_grading_cost_jpy=None,
            graded_value_jpy=None,
        )
    return GradingInfoOut(
        has_grading_submission=True,
        latest_status=latest.submission_status,
        grading_company=latest.grading_company,
        final_grade=latest.final_grade,
        total_grading_cost_jpy=latest.total_cost_jpy,
        graded_value_jpy=latest.graded_value_jpy,
    )


@dataclass
class GradingSummary:
    total_submissions: int = 0
    by_status: dict[str, int] = field(
        default_factory=lambda: {s: 0 for s in GRADING_SUBMISSION_STATUSES}
    )
    total_declared_value_jpy: int = 0
    total_grading_cost_jpy: int = 0
    total_graded_value_jpy: int = 0
    total_unrealized_gain_after_grading_jpy: int = 0
    average_grade: float | None = None
    items_waiting_return: int = 0


def build_grading_summary(db: Session, user_id: int) -> GradingSummary:
    submissions = db.scalars(
        select(GradingSubmission)
        .join(CollectionItem, GradingSubmission.collection_item_id == CollectionItem.id)
        .where(CollectionItem.user_id == user_id)
    ).all()

    summary = GradingSummary(total_submissions=len(submissions))
    if not submissions:
        return summary

    item_ids = {s.collection_item_id for s in submissions}
    items_by_id = {
        item.id: item for item in db.scalars(
            select(CollectionItem).where(CollectionItem.id.in_(item_ids))
        ).all()
    }

    numeric_grades: list[float] = []

    for s in submissions:
        summary.by_status[s.submission_status] = summary.by_status.get(s.submission_status, 0) + 1

        if s.declared_value_jpy is not None:
            summary.total_declared_value_jpy += s.declared_value_jpy
        if s.total_cost_jpy is not None:
            summary.total_grading_cost_jpy += s.total_cost_jpy
        if s.graded_value_jpy is not None:
            summary.total_graded_value_jpy += s.graded_value_jpy

        if s.graded_value_jpy is not None:
            item = items_by_id.get(s.collection_item_id)
            cost_basis = (
                item.purchase_price_jpy * item.quantity
                if item is not None and item.purchase_price_jpy is not None
                else None
            )
            if cost_basis is not None:
                gain = s.graded_value_jpy - cost_basis - (s.total_cost_jpy or 0)
                summary.total_unrealized_gain_after_grading_jpy += gain

        grade_value = parse_numeric_grade(s.final_grade)
        if grade_value is not None:
            numeric_grades.append(grade_value)

        if s.submission_status in WAITING_RETURN_STATUSES:
            summary.items_waiting_return += 1

    if numeric_grades:
        summary.average_grade = round(sum(numeric_grades) / len(numeric_grades), 2)

    return summary
