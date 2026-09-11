"""Fail-closed SQL ownership rules for personal search and ranking."""
from sqlalchemy import and_, or_, select

from app.models import CollectionItem, GradingSubmission, MarketSignalEvent, WishlistItem


def require_user_id(user_id: int) -> int:
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("A trusted current user ID is required")
    return user_id


def owned_collection_ids(user_id: int):
    return select(CollectionItem.id).where(CollectionItem.user_id == require_user_id(user_id))


def owned_grading_ids(user_id: int):
    return select(GradingSubmission.id).where(
        GradingSubmission.collection_item_id.in_(owned_collection_ids(user_id))
    )


def owned_signal_ids(user_id: int):
    return select(MarketSignalEvent.id).where(signal_owned_by(user_id))


def signal_owned_by(user_id: int):
    # A public card ID is not evidence of ownership.
    return MarketSignalEvent.collection_item_id.in_(owned_collection_ids(user_id))


def linked_owned_by(model, user_id: int):
    """Require at least one owned parent and reject every conflicting parent.

    A row linked to A's collection and B's wishlist is visible to neither.
    Ownerless reports/workflows cannot establish safe personal ownership.
    """
    parents = [
        (model.collection_item_id, owned_collection_ids(user_id)),
        (model.wishlist_item_id, select(WishlistItem.id).where(WishlistItem.user_id == user_id)),
        (model.grading_submission_id, owned_grading_ids(user_id)),
        (model.market_signal_event_id, owned_signal_ids(user_id)),
    ]
    restrictions = [or_(column.is_(None), column.in_(ids)) for column, ids in parents]
    restrictions.append(or_(*(column.is_not(None) for column, _ in parents)))
    restrictions.append(model.market_report_id.is_(None))
    if hasattr(model, "market_workflow_run_id"):
        restrictions.append(model.market_workflow_run_id.is_(None))
    return and_(*restrictions)
