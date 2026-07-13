import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CardTag,
    CollectionItem,
    CollectionItemGroup,
    CollectionItemTag,
    CollectorGroup,
    CollectorTag,
)

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def slugify(name: str) -> str:
    base = _SLUG_INVALID_CHARS.sub("-", name.strip().lower()).strip("-")
    return base or "item"


def validate_color(color: str | None) -> str | None:
    """Returns the cleaned color, or raises ValueError if it's non-blank and
    not a valid #RGB/#RRGGBB hex value. Blank/None means "no color"."""
    if color is None:
        return None
    cleaned = color.strip()
    if cleaned == "":
        return None
    if not _HEX_COLOR_RE.match(cleaned):
        raise ValueError("color must be a hex value like #RGB or #RRGGBB, or blank")
    return cleaned


def generate_unique_slug(
    db: Session, model: type, name: str, *, user_id: int, exclude_id: int | None = None
) -> str:
    base = slugify(name)
    slug = base
    counter = 2
    while True:
        query = select(model).where(model.slug == slug, model.user_id == user_id)
        if exclude_id is not None:
            query = query.where(model.id != exclude_id)
        if db.scalar(query) is None:
            return slug
        slug = f"{base}-{counter}"
        counter += 1


def get_or_create_tag(db: Session, name: str, *, user_id: int) -> tuple[CollectorTag, bool]:
    """Used by CSV import to resolve a tag by name (within the current
    user's own tags), creating it (with a fresh unique slug) if it doesn't
    already exist. Returns (tag, created)."""
    cleaned_name = name.strip()
    tag = db.scalar(
        select(CollectorTag).where(CollectorTag.name == cleaned_name, CollectorTag.user_id == user_id)
    )
    if tag is not None:
        return tag, False
    tag = CollectorTag(
        user_id=user_id,
        name=cleaned_name,
        slug=generate_unique_slug(db, CollectorTag, cleaned_name, user_id=user_id),
    )
    db.add(tag)
    db.flush()
    return tag, True


def get_or_create_group(db: Session, name: str, *, user_id: int) -> tuple[CollectorGroup, bool]:
    """Used by CSV import to resolve a group by name (within the current
    user's own groups), creating it (with a fresh unique slug) if it doesn't
    already exist. Returns (group, created)."""
    cleaned_name = name.strip()
    group = db.scalar(
        select(CollectorGroup).where(
            CollectorGroup.name == cleaned_name, CollectorGroup.user_id == user_id
        )
    )
    if group is not None:
        return group, False
    group = CollectorGroup(
        user_id=user_id,
        name=cleaned_name,
        slug=generate_unique_slug(db, CollectorGroup, cleaned_name, user_id=user_id),
    )
    db.add(group)
    db.flush()
    return group, True


def ensure_collection_item_tag(db: Session, collection_item_id: int, tag_id: int) -> None:
    existing = db.scalar(
        select(CollectionItemTag).where(
            CollectionItemTag.collection_item_id == collection_item_id,
            CollectionItemTag.tag_id == tag_id,
        )
    )
    if existing is None:
        db.add(CollectionItemTag(collection_item_id=collection_item_id, tag_id=tag_id))
        db.flush()


def ensure_collection_item_group(db: Session, collection_item_id: int, group_id: int) -> None:
    existing = db.scalar(
        select(CollectionItemGroup).where(
            CollectionItemGroup.collection_item_id == collection_item_id,
            CollectionItemGroup.group_id == group_id,
        )
    )
    if existing is None:
        db.add(CollectionItemGroup(collection_item_id=collection_item_id, group_id=group_id))
        db.flush()


def get_tags_for_cards(
    db: Session, card_ids: set[int], *, user_id: int | None = None
) -> dict[int, list[CollectorTag]]:
    """Batch-loads card-level tags for a set of card ids in one query, so
    list endpoints don't do a per-row lookup (N+1). Cards are a shared public
    catalog but tags are per-user, so callers that show this to a specific
    person (app/api/cards.py's public read endpoints) MUST pass that user's
    id to avoid mixing in other users' private tags - passing no user_id
    (the default) returns every user's tags unfiltered, which is only
    appropriate for the admin-only aggregate views (opportunity scoring)."""
    if not card_ids:
        return {}
    filters = [CardTag.card_id.in_(card_ids)]
    if user_id is not None:
        filters.append(CollectorTag.user_id == user_id)
    rows = db.execute(
        select(CardTag.card_id, CollectorTag)
        .join(CollectorTag, CardTag.tag_id == CollectorTag.id)
        .where(*filters)
        .order_by(CollectorTag.name)
    ).all()
    result: dict[int, list[CollectorTag]] = defaultdict(list)
    for card_id, tag in rows:
        result[card_id].append(tag)
    return result


def get_tags_for_collection_items(
    db: Session, item_ids: set[int]
) -> dict[int, list[CollectorTag]]:
    if not item_ids:
        return {}
    rows = db.execute(
        select(CollectionItemTag.collection_item_id, CollectorTag)
        .join(CollectorTag, CollectionItemTag.tag_id == CollectorTag.id)
        .where(CollectionItemTag.collection_item_id.in_(item_ids))
        .order_by(CollectorTag.name)
    ).all()
    result: dict[int, list[CollectorTag]] = defaultdict(list)
    for item_id, tag in rows:
        result[item_id].append(tag)
    return result


def get_groups_for_collection_items(
    db: Session, item_ids: set[int]
) -> dict[int, list[CollectorGroup]]:
    if not item_ids:
        return {}
    rows = db.execute(
        select(CollectionItemGroup.collection_item_id, CollectorGroup)
        .join(CollectorGroup, CollectionItemGroup.group_id == CollectorGroup.id)
        .where(CollectionItemGroup.collection_item_id.in_(item_ids))
        .order_by(CollectorGroup.sort_order, CollectorGroup.name)
    ).all()
    result: dict[int, list[CollectorGroup]] = defaultdict(list)
    for item_id, group in rows:
        result[item_id].append(group)
    return result


def get_groups_for_cards(db: Session, card_ids: set[int]) -> dict[int, list[CollectorGroup]]:
    """Unions groups across every collection item owning each card - groups
    are assigned per collection item, not per card, so a card with several
    owned copies (different conditions/sources) can surface several items'
    worth of groups here, deduplicated."""
    if not card_ids:
        return {}
    rows = db.execute(
        select(CollectionItem.card_id, CollectorGroup)
        .join(CollectionItemGroup, CollectionItemGroup.collection_item_id == CollectionItem.id)
        .join(CollectorGroup, CollectionItemGroup.group_id == CollectorGroup.id)
        .where(CollectionItem.card_id.in_(card_ids))
        .order_by(CollectorGroup.sort_order, CollectorGroup.name)
    ).all()
    result: dict[int, list[CollectorGroup]] = defaultdict(list)
    seen: dict[int, set[int]] = defaultdict(set)
    for card_id, group in rows:
        if group.id in seen[card_id]:
            continue
        seen[card_id].add(group.id)
        result[card_id].append(group)
    return result
