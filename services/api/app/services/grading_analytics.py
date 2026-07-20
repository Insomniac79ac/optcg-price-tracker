"""Grading ROI analytics: whether grading submissions are creating value,
which cards are still pending, and which outcomes were worth the cost - see
GET /analytics/grading.

Builds on top of app.services.grading (parse_numeric_grade, WAITING_RETURN_
STATUSES) and app.services.collector (get_tags_for_collection_items,
get_groups_for_collection_items) rather than re-deriving grade parsing or
tag/group lookups. It never touches graded_adjusted valuation itself (see
app.services.portfolio_valuation) - ROI here is computed directly from
purchase_price_jpy/graded_value_jpy/fees per the feature's own rules, not
from the portfolio's graded-adjusted P&L (which additionally blends in raw
market fallback pricing and is scoped to "current value", not "was grading
worth it").
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import pagination_response
from app.models import Card, CollectionItem, GradingSubmission
from app.schemas import (
    GradingAnalyticsBreakdownItemOut,
    GradingAnalyticsBreakdownsOut,
    GradingAnalyticsFlagsOut,
    GradingAnalyticsOut,
    GradingAnalyticsPendingOut,
    GradingAnalyticsRoiOut,
    GradingAnalyticsSubmissionOut,
    GradingAnalyticsSummaryOut,
)
from app.services.collector import get_groups_for_collection_items, get_tags_for_collection_items
from app.services.grading import WAITING_RETURN_STATUSES, parse_numeric_grade

# Non-terminal statuses - a submission is still "in flight" (not yet back
# and valued, not abandoned) in any of these. Same status set as
# sell_decision_support.ACTIVE_GRADING_STATUSES, duplicated here (not
# imported - that constant is scoped to sell-decision-support's own
# "should I grade before selling" question, a different concept that just
# happens to share the same status list).
ACTIVE_STATUSES = ("planned", "preparing", "submitted", "grading", "shipped_back")

PENDING_WINDOW_DAYS = 30
LIST_LIMIT = 10


def _pct(numerator: int, denominator: int) -> float | None:
    """Same rounding/None-on-zero-denominator convention duplicated across
    every analytics service in this app - a generic percent-rounding
    utility, not a valuation formula."""
    if not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _total_grading_cost_jpy(submission: GradingSubmission) -> int:
    """grading_fee + shipping_fee + insurance_fee + other_fee, treating an
    unset fee as 0 - unlike app.services.grading.compute_total_cost_jpy
    (which returns None when *nothing* has been entered, since that helper
    feeds the persisted total_cost_jpy column and "unknown" is the right
    default there), this feature's own ROI rules call for a 0 fallback
    unconditionally so a not-yet-invoiced submission still nets a usable
    ROI figure instead of forcing every submission missing a fee value out
    of the calculation."""
    return (
        (submission.grading_fee_jpy or 0)
        + (submission.shipping_fee_jpy or 0)
        + (submission.insurance_fee_jpy or 0)
        + (submission.other_fee_jpy or 0)
    )


def _days_in_grading(submitted_at: date | None, received_at: date | None, today: date) -> int | None:
    if submitted_at is None:
        return None
    end = received_at if received_at is not None else today
    return (end - submitted_at).days


def _is_overdue(submission_status: str, expected_return_date: date | None, today: date) -> bool:
    return (
        expected_return_date is not None
        and submission_status not in ("received", "cancelled")
        and expected_return_date < today
    )


def _is_expected_next_30d(submission_status: str, expected_return_date: date | None, today: date) -> bool:
    return (
        expected_return_date is not None
        and submission_status not in ("received", "cancelled")
        and today <= expected_return_date <= today + timedelta(days=PENDING_WINDOW_DAYS)
    )


def _build_breakdown(
    entries: list[tuple[str, str, GradingAnalyticsSubmissionOut]],
) -> list[GradingAnalyticsBreakdownItemOut]:
    buckets: dict[str, dict] = {}
    for key, label, submission in entries:
        bucket = buckets.setdefault(
            key,
            {
                "label": label,
                "submission_count": 0,
                "received_count": 0,
                "active_count": 0,
                "total_cost_jpy": 0,
                "graded_value_jpy": 0,
                "raw_cost_basis_jpy": 0,
            },
        )
        bucket["submission_count"] += 1
        if submission.submission_status == "received":
            bucket["received_count"] += 1
        if submission.flags.active:
            bucket["active_count"] += 1
        bucket["total_cost_jpy"] += submission.total_cost_jpy
        if submission.graded_value_jpy is not None:
            bucket["graded_value_jpy"] += submission.graded_value_jpy
        if submission.raw_cost_basis_jpy is not None:
            bucket["raw_cost_basis_jpy"] += submission.raw_cost_basis_jpy

    results = []
    for key, bucket in buckets.items():
        roi_jpy = bucket["graded_value_jpy"] - bucket["raw_cost_basis_jpy"] - bucket["total_cost_jpy"]
        roi_pct = _pct(roi_jpy, bucket["raw_cost_basis_jpy"] + bucket["total_cost_jpy"])
        results.append(
            GradingAnalyticsBreakdownItemOut(
                key=key,
                label=bucket["label"],
                submission_count=bucket["submission_count"],
                received_count=bucket["received_count"],
                active_count=bucket["active_count"],
                total_cost_jpy=bucket["total_cost_jpy"],
                graded_value_jpy=bucket["graded_value_jpy"],
                roi_jpy=roi_jpy,
                roi_pct=roi_pct,
            )
        )
    results.sort(key=lambda r: (-r.submission_count, r.key))
    return results


def get_grading_analytics(
    db: Session,
    *,
    user_id: int,
    include_cancelled: bool = False,
    grading_company: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> GradingAnalyticsOut:
    today = date.today()

    query = select(GradingSubmission).join(
        CollectionItem, GradingSubmission.collection_item_id == CollectionItem.id
    ).where(CollectionItem.user_id == user_id)
    all_submissions = db.scalars(query.order_by(GradingSubmission.id)).all()

    submissions = [s for s in all_submissions if include_cancelled or s.submission_status != "cancelled"]

    item_ids = {s.collection_item_id for s in submissions}
    items_by_id = {
        item.id: item for item in db.scalars(select(CollectionItem).where(CollectionItem.id.in_(item_ids))).all()
    }
    card_ids = {item.card_id for item in items_by_id.values()}
    cards_by_id = {c.id: c for c in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()}
    tags_by_item = get_tags_for_collection_items(db, item_ids)
    groups_by_item = get_groups_for_collection_items(db, item_ids)

    out_submissions: list[GradingAnalyticsSubmissionOut] = []

    for submission in submissions:
        item = items_by_id[submission.collection_item_id]
        card = cards_by_id[item.card_id]

        total_cost_jpy = _total_grading_cost_jpy(submission)
        raw_cost_basis_jpy = (
            item.purchase_price_jpy * item.quantity if item.purchase_price_jpy is not None else None
        )

        if submission.graded_value_jpy is not None and raw_cost_basis_jpy is not None:
            roi_jpy = submission.graded_value_jpy - raw_cost_basis_jpy - total_cost_jpy
            roi_pct = _pct(roi_jpy, raw_cost_basis_jpy + total_cost_jpy)
        else:
            roi_jpy = roi_pct = None

        days_in_grading = _days_in_grading(submission.submitted_at, submission.received_at, today)
        overdue = _is_overdue(submission.submission_status, submission.expected_return_date, today)
        active = submission.submission_status in ACTIVE_STATUSES

        out_submissions.append(
            GradingAnalyticsSubmissionOut(
                grading_submission_id=submission.id,
                collection_item_id=item.id,
                card_id=card.id,
                card_code=card.card_code,
                name_en=card.name_en,
                name_jp=card.name_jp,
                set_code=card.set_code,
                rarity=card.rarity,
                variant=card.variant,
                quantity=item.quantity,
                grading_company=submission.grading_company,
                submission_name=submission.submission_name,
                submission_status=submission.submission_status,
                declared_value_jpy=submission.declared_value_jpy,
                grading_fee_jpy=submission.grading_fee_jpy,
                shipping_fee_jpy=submission.shipping_fee_jpy,
                insurance_fee_jpy=submission.insurance_fee_jpy,
                other_fee_jpy=submission.other_fee_jpy,
                total_cost_jpy=total_cost_jpy,
                purchase_price_jpy=item.purchase_price_jpy,
                raw_cost_basis_jpy=raw_cost_basis_jpy,
                graded_value_jpy=submission.graded_value_jpy,
                roi_jpy=roi_jpy,
                roi_pct=roi_pct,
                submitted_at=submission.submitted_at,
                expected_return_date=submission.expected_return_date,
                received_at=submission.received_at,
                days_in_grading=days_in_grading,
                final_grade=submission.final_grade,
                cert_number=submission.cert_number,
                tracking_number=submission.tracking_number,
                notes=submission.notes,
                tags=[tag.name for tag in tags_by_item.get(item.id, [])],
                groups=[group.name for group in groups_by_item.get(item.id, [])],
                flags=GradingAnalyticsFlagsOut(
                    profitable=roi_jpy is not None and roi_jpy > 0,
                    missing_cost_basis=raw_cost_basis_jpy is None,
                    missing_graded_value=submission.graded_value_jpy is None,
                    overdue=overdue,
                    active=active,
                ),
            )
        )

    if grading_company is not None:
        out_submissions = [s for s in out_submissions if s.grading_company == grading_company]
    if status is not None:
        out_submissions = [s for s in out_submissions if s.submission_status == status]

    out_submissions.sort(key=lambda s: s.grading_submission_id)

    total_submissions = len(out_submissions)
    active_submissions = sum(1 for s in out_submissions if s.flags.active)
    received_submissions = sum(1 for s in out_submissions if s.submission_status == "received")
    cancelled_submissions = sum(1 for s in out_submissions if s.submission_status == "cancelled")
    total_declared_value_jpy = sum(s.declared_value_jpy or 0 for s in out_submissions)
    total_grading_cost_jpy = sum(s.total_cost_jpy for s in out_submissions)
    total_graded_value_jpy = sum(s.graded_value_jpy or 0 for s in out_submissions)
    total_raw_cost_basis_jpy = sum(s.raw_cost_basis_jpy or 0 for s in out_submissions)
    total_roi_jpy = total_graded_value_jpy - total_raw_cost_basis_jpy - total_grading_cost_jpy
    total_roi_pct = _pct(total_roi_jpy, total_raw_cost_basis_jpy + total_grading_cost_jpy)

    numeric_grades = [
        g for g in (parse_numeric_grade(s.final_grade) for s in out_submissions) if g is not None
    ]
    average_grade = round(sum(numeric_grades) / len(numeric_grades), 2) if numeric_grades else None
    median_grade = round(statistics.median(numeric_grades), 2) if numeric_grades else None

    profitable_count = sum(1 for s in out_submissions if s.flags.profitable)
    unprofitable_count = sum(1 for s in out_submissions if s.roi_jpy is not None and s.roi_jpy <= 0)
    missing_graded_value_count = sum(1 for s in out_submissions if s.flags.missing_graded_value)
    missing_cost_basis_count = sum(1 for s in out_submissions if s.flags.missing_cost_basis)
    items_waiting_return = sum(
        1 for s in out_submissions if s.submission_status in WAITING_RETURN_STATUSES
    )

    summary = GradingAnalyticsSummaryOut(
        total_submissions=total_submissions,
        active_submissions=active_submissions,
        received_submissions=received_submissions,
        cancelled_submissions=cancelled_submissions,
        total_declared_value_jpy=total_declared_value_jpy,
        total_grading_cost_jpy=total_grading_cost_jpy,
        total_graded_value_jpy=total_graded_value_jpy,
        total_raw_cost_basis_jpy=total_raw_cost_basis_jpy,
        total_roi_jpy=total_roi_jpy,
        total_roi_pct=total_roi_pct,
        average_grade=average_grade,
        median_grade=median_grade,
        profitable_count=profitable_count,
        unprofitable_count=unprofitable_count,
        missing_graded_value_count=missing_graded_value_count,
        missing_cost_basis_count=missing_cost_basis_count,
        items_waiting_return=items_waiting_return,
    )

    by_status = _build_breakdown(
        [(s.submission_status, s.submission_status.replace("_", " ").capitalize(), s) for s in out_submissions]
    )
    by_company = _build_breakdown([(s.grading_company, s.grading_company, s) for s in out_submissions])
    by_grade = _build_breakdown(
        [(s.final_grade, s.final_grade, s) for s in out_submissions if s.final_grade is not None]
    )
    by_set = _build_breakdown([(s.set_code, s.set_code, s) for s in out_submissions])
    by_rarity = _build_breakdown([(s.rarity, s.rarity, s) for s in out_submissions])

    breakdowns = GradingAnalyticsBreakdownsOut(
        by_status=by_status, by_company=by_company, by_grade=by_grade, by_set=by_set, by_rarity=by_rarity,
    )

    best_roi_submissions = sorted(
        (s for s in out_submissions if s.roi_jpy is not None),
        key=lambda s: (-s.roi_jpy, s.grading_submission_id),
    )[:LIST_LIMIT]
    worst_roi_submissions = sorted(
        (s for s in out_submissions if s.roi_jpy is not None),
        key=lambda s: (s.roi_jpy, s.grading_submission_id),
    )[:LIST_LIMIT]
    highest_graded_value = sorted(
        (s for s in out_submissions if s.graded_value_jpy is not None),
        key=lambda s: (-s.graded_value_jpy, s.grading_submission_id),
    )[:LIST_LIMIT]
    highest_grading_cost = sorted(
        out_submissions, key=lambda s: (-s.total_cost_jpy, s.grading_submission_id)
    )[:LIST_LIMIT]
    missing_value_or_cost = [
        s for s in out_submissions if s.flags.missing_graded_value or s.flags.missing_cost_basis
    ][:LIST_LIMIT]

    roi = GradingAnalyticsRoiOut(
        best_roi_submissions=best_roi_submissions,
        worst_roi_submissions=worst_roi_submissions,
        highest_graded_value=highest_graded_value,
        highest_grading_cost=highest_grading_cost,
        missing_value_or_cost=missing_value_or_cost,
    )

    waiting_return = [s for s in out_submissions if s.submission_status in WAITING_RETURN_STATUSES]
    overdue_list = [s for s in out_submissions if s.flags.overdue]
    expected_next_30d = [
        s
        for s in out_submissions
        if _is_expected_next_30d(s.submission_status, s.expected_return_date, today)
    ]

    pending = GradingAnalyticsPendingOut(
        waiting_return=waiting_return, overdue=overdue_list, expected_next_30d=expected_next_30d,
    )

    page = out_submissions[offset : offset + limit]

    return GradingAnalyticsOut(
        summary=summary,
        breakdowns=breakdowns,
        roi=roi,
        pending=pending,
        submissions=page,
        limit=limit,
        offset=offset,
        pagination=pagination_response(page, total_submissions, limit, offset),
    )
