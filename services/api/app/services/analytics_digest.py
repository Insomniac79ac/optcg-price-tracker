"""Combined analytics digest: one deterministic summary of collection
analytics, wishlist analytics, buy/sell decision support, grading ROI, and
portfolio risk - see GET /analytics/digest.

Builds entirely on top of the existing analytics services
(collection_analytics, wishlist_analytics, buy_decision_support,
sell_decision_support, grading_analytics, portfolio_risk) - this module only
extracts, re-shapes, filters, and orders what those services already
compute. It never recomputes a valuation, a score, or a risk figure itself,
and every deterministic_summary_lines entry is a fixed template over
already-computed numbers - no AI/LLM involvement.

Two distinct scopes:
- build_analytics_digest(db, user_id=..., valuation_mode=...) is pure (no
  persistence) and scoped to one signed-in user - backs the interactive
  GET /analytics/digest.
- generate_analytics_digest(db, valuation_mode=...) persists a row to
  analytics_digest_reports for the CLI/admin-action/market-workflow-triggered
  path, which has no request-scoped user. Like
  app.services.portfolio_valuation.get_portfolio_valuation's own admin-only
  aggregate callers, this resolves the single collector account (lowest user
  id) rather than aggregating across users, since none of the six services
  above support an "every user" mode - this app is not yet multi-tenant in
  practice (see that module's "explicit scope boundary" note).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalyticsDigestReport, User
from app.schemas import (
    AnalyticsDigestBuyDecisionsSectionOut,
    AnalyticsDigestCollectionSectionOut,
    AnalyticsDigestGradingSectionOut,
    AnalyticsDigestOut,
    AnalyticsDigestPortfolioRiskSectionOut,
    AnalyticsDigestPriorityItemOut,
    AnalyticsDigestPriorityItemsOut,
    AnalyticsDigestSectionsOut,
    AnalyticsDigestSellDecisionsSectionOut,
    AnalyticsDigestSummaryOut,
    AnalyticsDigestWishlistSectionOut,
    BuyDecisionCandidateOut,
    GradingAnalyticsSubmissionOut,
    PortfolioRiskDataQualityCardOut,
    PortfolioRiskFlagOut,
    SellDecisionCandidateOut,
    ValuationMode,
    WishlistAnalyticsTargetItemOut,
)
from app.services.buy_decision_support import get_buy_decision_support
from app.services.cache import delete_cache_prefix
from app.services.collection_analytics import get_collection_analytics
from app.services.grading_analytics import get_grading_analytics
from app.services.job_locks import with_job_lock
from app.services.portfolio_risk import get_portfolio_risk
from app.services.sell_decision_support import get_sell_decision_support
from app.services.wishlist_analytics import get_wishlist_analytics

# "Fetch effectively everything" limit for the underlying paginated
# services, matching the convention already used elsewhere in this app for a
# call that needs a whole candidate/item list to filter/rank client-side
# (e.g. app.services.sell_decision_support's own call into
# app.services.wishlist.get_wishlist_items).
ALL_LIMIT = 1_000_000

# How many entries each ranked priority_items/section list carries - not
# spec'd beyond "top 5 review_buy/review_sell candidates by score"; reused
# for every other priority_items list for consistency and a bounded
# response size.
TOP_N = 5
GRADING_TOP_N = 3

_SEVERITY_RANK = {"critical": 2, "warning": 1, "info": 0}

_SECTION_LINKS = {
    "collection": "/analytics/collection",
    "wishlist": "/analytics/wishlist",
    "buy_decisions": "/analytics/buy-decisions",
    "sell_decisions": "/analytics/sell-decisions",
    "grading": "/analytics/grading",
    "portfolio_risk": "/analytics/portfolio-risk",
}


class NoUsersError(RuntimeError):
    """Raised by generate_analytics_digest when the `users` table is empty
    (e.g. a fresh deployment before the first Google sign-in) - there is no
    account to scope the persisted digest to."""


def _resolve_default_user_id(db: Session) -> int:
    user_id = db.scalar(select(User.id).order_by(User.id).limit(1))
    if user_id is None:
        raise NoUsersError("No user accounts exist yet - sign in once before generating a digest.")
    return user_id


def _buy_priority_item(c: BuyDecisionCandidateOut) -> AnalyticsDigestPriorityItemOut:
    message = "; ".join(c.score_reasons) if c.score_reasons else c.recommended_action.replace("_", " ")
    return AnalyticsDigestPriorityItemOut(
        card_id=c.card_id,
        card_code=c.card_code,
        name_en=c.name_en,
        score=c.score,
        risk_level=None,
        severity=None,
        message=message,
        link=_SECTION_LINKS["buy_decisions"],
    )


def _sell_priority_item(c: SellDecisionCandidateOut) -> AnalyticsDigestPriorityItemOut:
    message = "; ".join(c.score_reasons) if c.score_reasons else c.recommended_action.replace("_", " ")
    return AnalyticsDigestPriorityItemOut(
        card_id=c.card_id,
        card_code=c.card_code,
        name_en=c.name_en,
        score=c.score,
        risk_level=None,
        severity=None,
        message=message,
        link=_SECTION_LINKS["sell_decisions"],
    )


def _risk_flag_priority_item(f: PortfolioRiskFlagOut) -> AnalyticsDigestPriorityItemOut:
    return AnalyticsDigestPriorityItemOut(
        card_id=None,
        card_code=f.related_cards[0] if f.related_cards else None,
        name_en=None,
        score=None,
        risk_level=None,
        severity=f.severity,
        message=f.message,
        link=_SECTION_LINKS["portfolio_risk"],
    )


def _wishlist_target_hit_priority_item(
    item: WishlistAnalyticsTargetItemOut,
) -> AnalyticsDigestPriorityItemOut:
    gap_text = (
        f"{item.gap_to_target_pct}% below target" if item.gap_to_target_pct is not None else "at target"
    )
    return AnalyticsDigestPriorityItemOut(
        card_id=item.card_id,
        card_code=item.card_code,
        name_en=item.name_en,
        score=None,
        risk_level=None,
        severity=None,
        message=f"Target hit ({item.priority}): {gap_text}.",
        link=_SECTION_LINKS["wishlist"],
    )


def _grading_overdue_priority_item(
    sub: GradingAnalyticsSubmissionOut,
) -> AnalyticsDigestPriorityItemOut:
    message = (
        f"Grading overdue since {sub.expected_return_date}."
        if sub.expected_return_date is not None
        else "Grading overdue."
    )
    return AnalyticsDigestPriorityItemOut(
        card_id=sub.card_id,
        card_code=sub.card_code,
        name_en=sub.name_en,
        score=None,
        risk_level=None,
        severity="warning",
        message=message,
        link=_SECTION_LINKS["grading"],
    )


def _missing_data_priority_item(card: PortfolioRiskDataQualityCardOut) -> AnalyticsDigestPriorityItemOut:
    return AnalyticsDigestPriorityItemOut(
        card_id=card.card_id,
        card_code=card.card_code,
        name_en=card.name_en,
        score=None,
        risk_level=None,
        severity="warning",
        message=card.issue,
        link=_SECTION_LINKS["portfolio_risk"],
    )


def _deterministic_summary_lines(
    summary: AnalyticsDigestSummaryOut, sections: AnalyticsDigestSectionsOut
) -> list[str]:
    lines = [f"Portfolio risk level: {summary.portfolio_risk_level}."]

    if summary.wishlist_target_hits > 0:
        noun = "target" if summary.wishlist_target_hits == 1 else "targets"
        lines.append(f"{summary.wishlist_target_hits} wishlist {noun} are at or below target price.")

    if summary.sell_review_count > 0:
        noun = "card" if summary.sell_review_count == 1 else "cards"
        lines.append(f"{summary.sell_review_count} owned {noun} are marked review sell.")

    if summary.buy_review_count > 0:
        noun = "item" if summary.buy_review_count == 1 else "items"
        lines.append(f"{summary.buy_review_count} wishlist {noun} are marked review buy.")

    if summary.grading_active_count > 0:
        noun = "submission" if summary.grading_active_count == 1 else "submissions"
        lines.append(f"{summary.grading_active_count} grading {noun} are active.")

    if sections.grading.overdue_count > 0:
        noun = "submission" if sections.grading.overdue_count == 1 else "submissions"
        lines.append(f"{sections.grading.overdue_count} grading {noun} are overdue for return.")

    if summary.missing_cost_basis_count > 0:
        noun = "item" if summary.missing_cost_basis_count == 1 else "items"
        lines.append(f"{summary.missing_cost_basis_count} owned {noun} are missing cost basis.")

    if summary.missing_price_count > 0:
        noun = "item" if summary.missing_price_count == 1 else "items"
        lines.append(f"{summary.missing_price_count} owned {noun} are missing current price data.")

    if len(lines) == 1:
        lines.append("No urgent buy, sell, grading, or data quality items to review.")

    return lines


def build_analytics_digest(
    db: Session, *, user_id: int, valuation_mode: ValuationMode = "raw_market"
) -> AnalyticsDigestOut:
    """Pure, deterministic composition - no persistence. Safe to call
    repeatedly (e.g. for GET /analytics/digest to be re-derivable) and safe
    on an empty collection/wishlist."""
    collection = get_collection_analytics(db, user_id=user_id, valuation_mode=valuation_mode)
    wishlist = get_wishlist_analytics(db, user_id=user_id)
    buy = get_buy_decision_support(db, user_id=user_id, limit=ALL_LIMIT, offset=0)
    sell = get_sell_decision_support(
        db, user_id=user_id, valuation_mode=valuation_mode, limit=ALL_LIMIT, offset=0
    )
    grading = get_grading_analytics(db, user_id=user_id, limit=ALL_LIMIT, offset=0)
    risk = get_portfolio_risk(db, user_id=user_id, valuation_mode=valuation_mode)

    collection_section = AnalyticsDigestCollectionSectionOut(
        total_items=collection.summary.total_items,
        total_quantity=collection.summary.total_quantity,
        total_cost_basis_jpy=collection.summary.total_cost_basis_jpy,
        raw_market_value_jpy=collection.summary.raw_market_floor_value_jpy,
        graded_adjusted_value_jpy=collection.summary.graded_adjusted_value_jpy,
        largest_set_exposure=collection.concentration.largest_set_exposure,
        largest_rarity_exposure=collection.concentration.largest_rarity_exposure,
    )

    wishlist_section = AnalyticsDigestWishlistSectionOut(
        total_items=wishlist.summary.total_items,
        grail_count=wishlist.summary.grail_count,
        high_priority_count=wishlist.summary.high_priority_count,
        target_hit_count=wishlist.summary.target_hit_count,
        total_target_budget_jpy=wishlist.summary.total_target_budget_jpy,
        price_coverage_pct=wishlist.price_coverage.coverage_pct,
    )

    top_review_buy = [c for c in buy.candidates if c.recommended_action == "review_buy"][:TOP_N]
    buy_section = AnalyticsDigestBuyDecisionsSectionOut(
        review_buy_count=buy.summary.review_buy_count,
        wait_count=buy.summary.wait_count,
        missing_data_count=buy.summary.missing_data_count,
        top_review_buy=top_review_buy,
    )

    top_review_sell = [c for c in sell.candidates if c.recommended_action == "review_sell"][:TOP_N]
    sell_section = AnalyticsDigestSellDecisionsSectionOut(
        review_sell_count=sell.summary.review_sell_count,
        grade_first_count=sell.summary.grade_first_count,
        missing_data_count=sell.summary.missing_data_count,
        top_review_sell=top_review_sell,
    )

    grading_section = AnalyticsDigestGradingSectionOut(
        active_submissions=grading.summary.active_submissions,
        received_submissions=grading.summary.received_submissions,
        total_grading_cost_jpy=grading.summary.total_grading_cost_jpy,
        total_graded_value_jpy=grading.summary.total_graded_value_jpy,
        total_roi_jpy=grading.summary.total_roi_jpy,
        overdue_count=len(grading.pending.overdue),
        best_roi=grading.roi.best_roi_submissions[:GRADING_TOP_N],
        worst_roi=grading.roi.worst_roi_submissions[:GRADING_TOP_N],
    )

    risk_section = AnalyticsDigestPortfolioRiskSectionOut(
        risk_score=risk.summary.risk_score,
        risk_level=risk.summary.risk_level,
        concentration_score=risk.risk_breakdown.concentration.score,
        data_quality_score=risk.risk_breakdown.data_quality.score,
        liquidity_proxy_score=risk.risk_breakdown.liquidity_proxy.score,
        grading_exposure_score=risk.risk_breakdown.grading_exposure.score,
        wishlist_overlap_score=risk.risk_breakdown.wishlist_overlap.score,
        top_recommendation_flags=risk.recommendation_flags[:TOP_N],
    )

    sections = AnalyticsDigestSectionsOut(
        collection=collection_section,
        wishlist=wishlist_section,
        buy_decisions=buy_section,
        sell_decisions=sell_section,
        grading=grading_section,
        portfolio_risk=risk_section,
    )

    top_risk_flags = sorted(
        risk.recommendation_flags, key=lambda f: -_SEVERITY_RANK.get(f.severity, 0)
    )[:TOP_N]

    missing_data_items = [
        _missing_data_priority_item(c) for c in risk.risk_breakdown.data_quality.missing_prices[:TOP_N]
    ] + [
        _missing_data_priority_item(c)
        for c in risk.risk_breakdown.data_quality.missing_cost_basis[:TOP_N]
    ]

    priority_items = AnalyticsDigestPriorityItemsOut(
        top_buy_decisions=[_buy_priority_item(c) for c in top_review_buy],
        top_sell_decisions=[_sell_priority_item(c) for c in top_review_sell],
        top_risk_flags=[_risk_flag_priority_item(f) for f in top_risk_flags],
        wishlist_target_hits=[
            _wishlist_target_hit_priority_item(i) for i in wishlist.target_hits[:TOP_N]
        ],
        grading_overdue=[_grading_overdue_priority_item(s) for s in grading.pending.overdue[:TOP_N]],
        missing_data=missing_data_items[:TOP_N],
    )

    summary = AnalyticsDigestSummaryOut(
        valuation_mode=valuation_mode,
        generated_at=datetime.now(timezone.utc),
        collection_value_jpy=collection.summary.raw_market_floor_value_jpy,
        graded_adjusted_value_jpy=collection.summary.graded_adjusted_value_jpy,
        portfolio_risk_score=risk.summary.risk_score,
        portfolio_risk_level=risk.summary.risk_level,
        wishlist_target_hits=wishlist.summary.target_hit_count,
        buy_review_count=buy.summary.review_buy_count,
        sell_review_count=sell.summary.review_sell_count,
        grading_roi_jpy=grading.summary.total_roi_jpy,
        grading_active_count=grading.summary.active_submissions,
        missing_cost_basis_count=risk.summary.missing_cost_basis_count,
        missing_price_count=risk.summary.missing_price_count,
    )

    deterministic_summary_lines = _deterministic_summary_lines(summary, sections)

    return AnalyticsDigestOut(
        summary=summary,
        sections=sections,
        priority_items=priority_items,
        deterministic_summary_lines=deterministic_summary_lines,
    )


def generate_analytics_digest(
    db: Session, *, valuation_mode: ValuationMode = "raw_market", skip_lock: bool = False
) -> AnalyticsDigestReport:
    """Builds and persists one analytics_digest_reports row - shared by
    app/generate_analytics_digest.py's CLI, POST
    /admin/actions/generate-analytics-digest, and the best-effort digest
    step after a successful non-dry-run market workflow/report generation
    (see app.api.admin_actions). Acquires the 'analytics_digest_generation'
    concurrency lock for the call (see 'Worker job concurrency locking' in
    docs/operations.md). skip_lock is test/dev-CLI only, never exposed to
    the admin UI/API.

    Raises NoUsersError if no user account exists yet.
    """
    with with_job_lock("analytics_digest_generation", skip_lock=skip_lock):
        return _generate_analytics_digest_locked(db, valuation_mode)


def _generate_analytics_digest_locked(
    db: Session, valuation_mode: ValuationMode
) -> AnalyticsDigestReport:
    user_id = _resolve_default_user_id(db)
    digest = build_analytics_digest(db, user_id=user_id, valuation_mode=valuation_mode)

    report = AnalyticsDigestReport(
        valuation_mode=valuation_mode,
        collection_value_jpy=digest.summary.collection_value_jpy,
        graded_adjusted_value_jpy=digest.summary.graded_adjusted_value_jpy,
        portfolio_risk_score=digest.summary.portfolio_risk_score,
        portfolio_risk_level=digest.summary.portfolio_risk_level,
        wishlist_target_hits=digest.summary.wishlist_target_hits,
        buy_review_count=digest.summary.buy_review_count,
        sell_review_count=digest.summary.sell_review_count,
        grading_roi_jpy=digest.summary.grading_roi_jpy,
        digest_payload_json=digest.model_dump(mode="json"),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    # See 'Cache invalidation' in docs/operations.md - a newly generated
    # digest changes GET /analytics/digest/latest and GET
    # /analytics/digest/reports.
    delete_cache_prefix("analytics_digest")
    return report
