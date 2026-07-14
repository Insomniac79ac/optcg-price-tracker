"""Unified search across cards, collection, wishlist, grading, notes,
activity, market signals, opportunities, and market reports.

Follows the same "load the relevant rows, score/filter in Python" pattern
already used by app/services/opportunity_scoring.py and
app/services/activity_timeline.py, rather than building one giant
cross-table SQL query - this app's tables are personal-collector-scale, and
scoring (tiered field matches + bonuses) is much simpler to express and test
in Python than in SQL. Opportunities specifically delegates to
opportunity_scoring.get_opportunities() so its ranking formula is never
duplicated here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Card,
    CollectionItem,
    CollectorActivityEvent,
    CollectorNote,
    GradingSubmission,
    MarketIntelligenceReport,
    MarketSignalEvent,
    SearchHistory,
    WishlistItem,
)
from app.schemas import SearchResultOut, SearchSuggestionOut
from app.services.collector import (
    get_groups_for_collection_items,
    get_tags_for_collection_items,
)
from app.services.opportunity_scoring import get_opportunities

SEARCH_TYPES: tuple[str, ...] = (
    "cards",
    "collection",
    "wishlist",
    "grading",
    "notes",
    "activity",
    "signals",
    "opportunities",
    "reports",
)

MIN_QUERY_LENGTH = 2
RECENT_WINDOW = timedelta(days=7)

# --- scoring tiers (see feature spec) -------------------------------------

SCORE_CODE_EXACT = 100
SCORE_CODE_PARTIAL = 90
SCORE_NAME_EXACT = 85
SCORE_NAME_PARTIAL = 75
SCORE_TEXT_MATCH = 50
SCORE_METADATA_MATCH = 35

BONUS_RECENT = 5
BONUS_OWNED = 5
BONUS_WISHLIST_PRIORITY = 5

HIGH_WISHLIST_PRIORITIES = ("grail", "high")


def _naive(dt: datetime) -> datetime:
    """sqlite (used in tests) round-trips DateTime(timezone=True) columns as
    naive datetimes, so any Python-side comparison against a tz-aware
    `datetime.now(timezone.utc)` value needs both sides stripped to naive -
    same approach as app/services/market_signals.py's _naive()."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _is_recent(dt: datetime | None, now: datetime) -> bool:
    if dt is None:
        return False
    return _naive(now) - _naive(dt) <= RECENT_WINDOW


def _match_field(value: str | None, q_lower: str, kind: str) -> int | None:
    """Returns the score tier if `value` contains/equals `q_lower`, else
    None. `kind` selects which tier ladder applies: "code" (card_code-style
    identifiers), "name" (display names), "text" (free-form prose - notes,
    messages, summary lines), or "meta" (everything else: statuses, enums,
    labels)."""
    if not value:
        return None
    value_lower = value.lower()
    if kind == "code":
        if value_lower == q_lower:
            return SCORE_CODE_EXACT
        if q_lower in value_lower:
            return SCORE_CODE_PARTIAL
        return None
    if kind == "name":
        if value_lower == q_lower:
            return SCORE_NAME_EXACT
        if q_lower in value_lower:
            return SCORE_NAME_PARTIAL
        return None
    if kind == "text":
        return SCORE_TEXT_MATCH if q_lower in value_lower else None
    if kind == "meta":
        return SCORE_METADATA_MATCH if q_lower in value_lower else None
    raise ValueError(f"unknown field kind: {kind!r}")


def _score_fields(
    fields: list[tuple[str, str | None, str]], q_lower: str
) -> tuple[int, list[str]] | None:
    matched_fields: list[str] = []
    best_score = 0
    for name, value, kind in fields:
        tier = _match_field(value, q_lower, kind)
        if tier is not None:
            matched_fields.append(name)
            best_score = max(best_score, tier)
    if not matched_fields:
        return None
    return best_score, matched_fields


def _clamp_score(score: int) -> int:
    return max(0, min(100, score))


def _owned_card_ids(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(CollectionItem.card_id, CollectionItem.quantity)
    ).all()
    totals: dict[int, int] = {}
    for card_id, quantity in rows:
        totals[card_id] = totals.get(card_id, 0) + (quantity or 0)
    return totals


def _cards_by_id(db: Session, card_ids: set[int]) -> dict[int, Card]:
    if not card_ids:
        return {}
    return {c.id: c for c in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()}


def _card_title(card: Card) -> str:
    return f"{card.card_code} {card.name_en or card.name_jp or ''}".strip()


def _card_subtitle(card: Card) -> str:
    return " • ".join(filter(None, [card.set_code, card.rarity, card.variant, card.language]))


@dataclass
class _ScoredResult:
    type: str
    id: int
    score: int
    title: str
    subtitle: str
    matched_fields: list[str]
    card_id: int | None
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    url: str
    metadata: dict = field(default_factory=dict)
    sort_time: datetime | None = None


def _finalize(results: list[_ScoredResult]) -> list[SearchResultOut]:
    results.sort(
        key=lambda r: (r.score, _naive(r.sort_time) if r.sort_time else datetime.min),
        reverse=True,
    )
    return [
        SearchResultOut(
            type=r.type,
            id=r.id,
            score=r.score,
            title=r.title,
            subtitle=r.subtitle,
            matched_fields=r.matched_fields,
            card_id=r.card_id,
            card_code=r.card_code,
            name_en=r.name_en,
            name_jp=r.name_jp,
            url=r.url,
            metadata=r.metadata,
        )
        for r in results
    ]


# --- cards -----------------------------------------------------------------


def _search_cards(db: Session, q_lower: str, owned_by_card: dict[int, int]) -> list[_ScoredResult]:
    cards = db.scalars(select(Card)).all()
    out: list[_ScoredResult] = []
    for card in cards:
        scored = _score_fields(
            [
                ("card_code", card.card_code, "code"),
                ("name_en", card.name_en, "name"),
                ("name_jp", card.name_jp, "name"),
                ("set_code", card.set_code, "meta"),
                ("rarity", card.rarity, "meta"),
                ("variant", card.variant, "meta"),
                ("language", card.language, "meta"),
            ],
            q_lower,
        )
        if scored is None:
            continue
        base_score, matched_fields = scored
        bonus = BONUS_OWNED if owned_by_card.get(card.id, 0) > 0 else 0
        out.append(
            _ScoredResult(
                type="cards",
                id=card.id,
                score=_clamp_score(base_score + bonus),
                title=_card_title(card),
                subtitle=_card_subtitle(card),
                matched_fields=matched_fields,
                card_id=card.id,
                card_code=card.card_code,
                name_en=card.name_en,
                name_jp=card.name_jp,
                url=f"/cards/{card.id}",
                metadata={"owned_quantity": owned_by_card.get(card.id, 0)},
                sort_time=card.updated_at,
            )
        )
    return out


# --- collection --------------------------------------------------------------


def _search_collection(
    db: Session, q_lower: str, owned_by_card: dict[int, int]
) -> list[_ScoredResult]:
    items = db.scalars(select(CollectionItem)).all()
    if not items:
        return []
    card_ids = {i.card_id for i in items}
    cards_by_id = _cards_by_id(db, card_ids)
    item_ids = {i.id for i in items}
    tags_by_item = get_tags_for_collection_items(db, item_ids)
    groups_by_item = get_groups_for_collection_items(db, item_ids)

    out: list[_ScoredResult] = []
    for item in items:
        card = cards_by_id.get(item.card_id)
        tag_names = " ".join(t.name for t in tags_by_item.get(item.id, []))
        group_names = " ".join(g.name for g in groups_by_item.get(item.id, []))
        scored = _score_fields(
            [
                ("card_code", card.card_code if card else None, "code"),
                ("name_en", card.name_en if card else None, "name"),
                ("name_jp", card.name_jp if card else None, "name"),
                ("condition_label", item.condition_label, "meta"),
                ("purchase_source", item.purchase_source, "meta"),
                ("status", item.status, "meta"),
                ("notes", item.notes, "text"),
                ("tags", tag_names or None, "meta"),
                ("groups", group_names or None, "meta"),
            ],
            q_lower,
        )
        if scored is None:
            continue
        base_score, matched_fields = scored
        bonus = BONUS_OWNED if owned_by_card.get(item.card_id, 0) > 0 else 0
        title = _card_title(card) if card else f"Collection item #{item.id}"
        subtitle = f"{item.status} • qty {item.quantity}" + (
            f" • {item.condition_label}" if item.condition_label else ""
        )
        out.append(
            _ScoredResult(
                type="collection",
                id=item.id,
                score=_clamp_score(base_score + bonus),
                title=title,
                subtitle=subtitle,
                matched_fields=matched_fields,
                card_id=item.card_id,
                card_code=card.card_code if card else None,
                name_en=card.name_en if card else None,
                name_jp=card.name_jp if card else None,
                url="/collection",
                metadata={
                    "quantity": item.quantity,
                    "status": item.status,
                    "purchase_source": item.purchase_source,
                },
                sort_time=item.updated_at,
            )
        )
    return out


# --- wishlist ----------------------------------------------------------------


def _search_wishlist(
    db: Session, q_lower: str, owned_by_card: dict[int, int]
) -> list[_ScoredResult]:
    items = db.scalars(select(WishlistItem)).all()
    if not items:
        return []
    cards_by_id = _cards_by_id(db, {i.card_id for i in items})

    out: list[_ScoredResult] = []
    for item in items:
        card = cards_by_id.get(item.card_id)
        scored = _score_fields(
            [
                ("card_code", card.card_code if card else None, "code"),
                ("name_en", card.name_en if card else None, "name"),
                ("name_jp", card.name_jp if card else None, "name"),
                ("priority", item.priority, "meta"),
                ("status", item.status, "meta"),
                ("preferred_condition", item.preferred_condition, "meta"),
                ("preferred_source", item.preferred_source, "meta"),
                ("notes", item.notes, "text"),
            ],
            q_lower,
        )
        if scored is None:
            continue
        base_score, matched_fields = scored
        bonus = 0
        if owned_by_card.get(item.card_id, 0) > 0:
            bonus += BONUS_OWNED
        if item.priority in HIGH_WISHLIST_PRIORITIES:
            bonus += BONUS_WISHLIST_PRIORITY
        title = _card_title(card) if card else f"Wishlist item #{item.id}"
        subtitle = f"{item.priority} • {item.status}"
        out.append(
            _ScoredResult(
                type="wishlist",
                id=item.id,
                score=_clamp_score(base_score + bonus),
                title=title,
                subtitle=subtitle,
                matched_fields=matched_fields,
                card_id=item.card_id,
                card_code=card.card_code if card else None,
                name_en=card.name_en if card else None,
                name_jp=card.name_jp if card else None,
                url="/wishlist",
                metadata={"priority": item.priority, "status": item.status},
                sort_time=item.updated_at,
            )
        )
    return out


# --- grading -------------------------------------------------------------


def _search_grading(
    db: Session, q_lower: str, owned_by_card: dict[int, int]
) -> list[_ScoredResult]:
    submissions = db.scalars(select(GradingSubmission)).all()
    if not submissions:
        return []
    item_ids = {s.collection_item_id for s in submissions}
    items_by_id = {
        i.id: i for i in db.scalars(select(CollectionItem).where(CollectionItem.id.in_(item_ids))).all()
    }
    cards_by_id = _cards_by_id(db, {i.card_id for i in items_by_id.values()})

    out: list[_ScoredResult] = []
    for sub in submissions:
        item = items_by_id.get(sub.collection_item_id)
        card = cards_by_id.get(item.card_id) if item else None
        scored = _score_fields(
            [
                ("card_code", card.card_code if card else None, "code"),
                ("name_en", card.name_en if card else None, "name"),
                ("name_jp", card.name_jp if card else None, "name"),
                ("grading_company", sub.grading_company, "meta"),
                ("submission_name", sub.submission_name, "meta"),
                ("submission_status", sub.submission_status, "meta"),
                ("tracking_number", sub.tracking_number, "meta"),
                ("final_grade", sub.final_grade, "meta"),
                ("cert_number", sub.cert_number, "meta"),
                ("notes", sub.notes, "text"),
            ],
            q_lower,
        )
        if scored is None:
            continue
        base_score, matched_fields = scored
        bonus = BONUS_OWNED if item and owned_by_card.get(item.card_id, 0) > 0 else 0
        title = (
            f"{card.card_code if card else 'Unknown card'} - {sub.grading_company} "
            f"({sub.submission_status})"
        )
        subtitle = sub.submission_name or f"Submission #{sub.id}"
        out.append(
            _ScoredResult(
                type="grading",
                id=sub.id,
                score=_clamp_score(base_score + bonus),
                title=title,
                subtitle=subtitle,
                matched_fields=matched_fields,
                card_id=item.card_id if item else None,
                card_code=card.card_code if card else None,
                name_en=card.name_en if card else None,
                name_jp=card.name_jp if card else None,
                url="/grading",
                metadata={
                    "grading_company": sub.grading_company,
                    "submission_status": sub.submission_status,
                    "final_grade": sub.final_grade,
                },
                sort_time=sub.updated_at,
            )
        )
    return out


# --- notes -----------------------------------------------------------------


def _search_notes(db: Session, q_lower: str, owned_by_card: dict[int, int]) -> list[_ScoredResult]:
    notes = db.scalars(select(CollectorNote)).all()
    if not notes:
        return []
    cards_by_id = _cards_by_id(db, {n.card_id for n in notes if n.card_id is not None})

    out: list[_ScoredResult] = []
    for note in notes:
        card = cards_by_id.get(note.card_id) if note.card_id is not None else None
        scored = _score_fields(
            [
                ("title", note.title, "meta"),
                ("body", note.body, "text"),
                ("note_type", note.note_type, "meta"),
                ("card_code", card.card_code if card else None, "code"),
                ("name_en", card.name_en if card else None, "name"),
                ("name_jp", card.name_jp if card else None, "name"),
            ],
            q_lower,
        )
        if scored is None:
            continue
        base_score, matched_fields = scored
        bonus = BONUS_OWNED if card and owned_by_card.get(card.id, 0) > 0 else 0
        out.append(
            _ScoredResult(
                type="notes",
                id=note.id,
                score=_clamp_score(base_score + bonus),
                title=note.title or note.body[:80],
                subtitle=f"{note.note_type} note",
                matched_fields=matched_fields,
                card_id=note.card_id,
                card_code=card.card_code if card else None,
                name_en=card.name_en if card else None,
                name_jp=card.name_jp if card else None,
                url=f"/cards/{card.id}" if card else "/dashboard",
                metadata={"note_type": note.note_type, "pinned": note.pinned},
                sort_time=note.updated_at,
            )
        )
    return out


# --- activity ----------------------------------------------------------------


def _search_activity(
    db: Session, q_lower: str, owned_by_card: dict[int, int], now: datetime
) -> list[_ScoredResult]:
    events = db.scalars(select(CollectorActivityEvent)).all()
    if not events:
        return []
    cards_by_id = _cards_by_id(db, {e.card_id for e in events if e.card_id is not None})

    out: list[_ScoredResult] = []
    for event in events:
        card = cards_by_id.get(event.card_id) if event.card_id is not None else None
        scored = _score_fields(
            [
                ("event_type", event.event_type, "meta"),
                ("event_source", event.event_source, "meta"),
                ("title", event.title, "meta"),
                ("message", event.message, "text"),
                ("card_code", card.card_code if card else None, "code"),
                ("name_en", card.name_en if card else None, "name"),
                ("name_jp", card.name_jp if card else None, "name"),
            ],
            q_lower,
        )
        if scored is None:
            continue
        base_score, matched_fields = scored
        bonus = 0
        if card and owned_by_card.get(card.id, 0) > 0:
            bonus += BONUS_OWNED
        if _is_recent(event.created_at, now):
            bonus += BONUS_RECENT
        out.append(
            _ScoredResult(
                type="activity",
                id=event.id,
                score=_clamp_score(base_score + bonus),
                title=event.title,
                subtitle=f"{event.event_source} • {event.event_type}",
                matched_fields=matched_fields,
                card_id=event.card_id,
                card_code=card.card_code if card else None,
                name_en=card.name_en if card else None,
                name_jp=card.name_jp if card else None,
                url=f"/cards/{card.id}" if card else "/dashboard",
                metadata={"event_source": event.event_source, "event_type": event.event_type},
                sort_time=event.created_at,
            )
        )
    return out


# --- signals -----------------------------------------------------------------


def _search_signals(
    db: Session, q_lower: str, owned_by_card: dict[int, int], now: datetime
) -> list[_ScoredResult]:
    events = db.scalars(select(MarketSignalEvent)).all()
    if not events:
        return []
    cards_by_id = _cards_by_id(db, {e.card_id for e in events if e.card_id is not None})

    out: list[_ScoredResult] = []
    for event in events:
        card = cards_by_id.get(event.card_id) if event.card_id is not None else None
        scored = _score_fields(
            [
                ("signal_type", event.signal_type, "meta"),
                ("suggested_action", event.suggested_action, "meta"),
                ("status", event.status, "meta"),
                ("message", event.message, "text"),
                ("card_code", card.card_code if card else None, "code"),
                ("name_en", card.name_en if card else None, "name"),
                ("name_jp", card.name_jp if card else None, "name"),
            ],
            q_lower,
        )
        if scored is None:
            continue
        base_score, matched_fields = scored
        bonus = 0
        if card and owned_by_card.get(card.id, 0) > 0:
            bonus += BONUS_OWNED
        if _is_recent(event.last_seen_at, now):
            bonus += BONUS_RECENT
        title = f"{event.signal_type}" + (f" - {card.card_code}" if card else "")
        out.append(
            _ScoredResult(
                type="signals",
                id=event.id,
                score=_clamp_score(base_score + bonus),
                title=title,
                subtitle=f"{event.status} • {event.suggested_action or 'no action'}",
                matched_fields=matched_fields,
                card_id=event.card_id,
                card_code=card.card_code if card else None,
                name_en=card.name_en if card else None,
                name_jp=card.name_jp if card else None,
                url="/market/signal-events",
                metadata={"status": event.status, "suggested_action": event.suggested_action},
                sort_time=event.last_seen_at,
            )
        )
    return out


# --- opportunities -------------------------------------------------------


def _search_opportunities(
    db: Session, q: str, q_lower: str
) -> list[_ScoredResult]:
    """Reuses opportunity_scoring.get_opportunities() for the ranked set and
    only filters the results by the query text here - the score/ranking
    formula for opportunities themselves is never recomputed or duplicated
    in this module."""
    response = get_opportunities(db, limit=10_000)

    out: list[_ScoredResult] = []
    for opp in response.opportunities:
        scored = _score_fields(
            [
                ("card_code", opp.card_code, "code"),
                ("name_en", opp.name_en, "name"),
                ("name_jp", opp.name_jp, "name"),
                ("signal_type", opp.signal_type, "meta"),
                ("suggested_action", opp.suggested_action, "meta"),
                ("message", opp.message, "text"),
            ],
            q_lower,
        )
        if scored is None:
            continue
        base_score, matched_fields = scored
        bonus = 0
        if opp.owned_quantity > 0:
            bonus += BONUS_OWNED
        if opp.wishlist_priority in HIGH_WISHLIST_PRIORITIES:
            bonus += BONUS_WISHLIST_PRIORITY
        title = f"{opp.card_code or 'Unlisted'} - {opp.category} opportunity (score {opp.score})"
        out.append(
            _ScoredResult(
                type="opportunities",
                id=opp.event_id,
                score=_clamp_score(base_score + bonus),
                title=title,
                subtitle=opp.message or opp.signal_type,
                matched_fields=matched_fields,
                card_id=opp.card_id,
                card_code=opp.card_code,
                name_en=opp.name_en,
                name_jp=opp.name_jp,
                url="/market/opportunities",
                metadata={"category": opp.category, "opportunity_score": opp.score},
                sort_time=opp.last_seen_at,
            )
        )
    return out


# --- reports -----------------------------------------------------------------


def _search_reports(db: Session, q: str, q_lower: str) -> list[_ScoredResult]:
    reports = db.scalars(select(MarketIntelligenceReport)).all()
    if not reports:
        return []

    out: list[_ScoredResult] = []
    for report in reports:
        payload = report.report_payload_json or {}
        summary_lines = " ".join(payload.get("deterministic_summary_lines") or [])
        payload_text = json.dumps(payload, default=str)
        scored = _score_fields(
            [
                ("report_date", report.report_date.isoformat(), "meta"),
                ("deterministic_summary_lines", summary_lines or None, "text"),
                ("payload", payload_text, "meta"),
            ],
            q_lower,
        )
        if scored is None:
            continue
        base_score, matched_fields = scored
        out.append(
            _ScoredResult(
                type="reports",
                id=report.id,
                score=_clamp_score(base_score),
                title=f"Market report - {report.report_date.isoformat()}",
                subtitle=f"{report.total_opportunities} opportunities, avg score {report.average_score or 0}",
                matched_fields=matched_fields,
                card_id=None,
                card_code=None,
                name_en=None,
                name_jp=None,
                url="/market/report",
                metadata={"report_date": report.report_date.isoformat()},
                sort_time=report.created_at,
            )
        )
    return out


_SEARCH_FUNCS = {
    "cards": lambda db, q, q_lower, owned, now: _search_cards(db, q_lower, owned),
    "collection": lambda db, q, q_lower, owned, now: _search_collection(db, q_lower, owned),
    "wishlist": lambda db, q, q_lower, owned, now: _search_wishlist(db, q_lower, owned),
    "grading": lambda db, q, q_lower, owned, now: _search_grading(db, q_lower, owned),
    "notes": lambda db, q, q_lower, owned, now: _search_notes(db, q_lower, owned),
    "activity": lambda db, q, q_lower, owned, now: _search_activity(db, q_lower, owned, now),
    "signals": lambda db, q, q_lower, owned, now: _search_signals(db, q_lower, owned, now),
    "opportunities": lambda db, q, q_lower, owned, now: _search_opportunities(db, q, q_lower),
    "reports": lambda db, q, q_lower, owned, now: _search_reports(db, q, q_lower),
}


@dataclass
class SearchOutcome:
    query: str
    total_results: int
    by_type: dict[str, int]
    results: list[SearchResultOut]


def is_exact_card_code(db: Session, q: str) -> bool:
    """Whether `q` exactly matches (case-insensitively) an existing card's
    card_code - the one way a query shorter than MIN_QUERY_LENGTH is still
    allowed through, since a real card_code is real data to check against
    rather than a guessed shape/pattern."""
    return (
        db.scalar(select(Card.id).where(Card.card_code.ilike(q)).limit(1)) is not None
    )


def search(
    db: Session,
    q: str,
    *,
    types: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SearchOutcome:
    active_types = list(types) if types else list(SEARCH_TYPES)
    q_lower = q.lower()
    now = datetime.now(timezone.utc)
    owned_by_card = _owned_card_ids(db)

    all_results: list[_ScoredResult] = []
    for t in active_types:
        func_ = _SEARCH_FUNCS[t]
        all_results.extend(func_(db, q, q_lower, owned_by_card, now))

    by_type: dict[str, int] = {t: 0 for t in SEARCH_TYPES}
    for r in all_results:
        by_type[r.type] = by_type.get(r.type, 0) + 1

    finalized = _finalize(all_results)
    page = finalized[offset : offset + limit]

    return SearchOutcome(
        query=q,
        total_results=len(finalized),
        by_type=by_type,
        results=page,
    )


def record_search_history(db: Session, q: str, result_count: int) -> None:
    """Best-effort: a failure here must never break the search response
    itself, since this is just a log of past queries, not load-bearing
    data."""
    try:
        db.add(SearchHistory(query=q, result_count=result_count))
        db.commit()
    except Exception:
        db.rollback()


# --- suggestions -------------------------------------------------------


SUGGESTIONS_PER_SOURCE = 10


def _recent_searched_card_codes(db: Session, limit: int) -> list[SearchSuggestionOut]:
    rows = db.scalars(
        select(SearchHistory.query)
        .order_by(SearchHistory.created_at.desc())
        .limit(limit * 3)
    ).all()
    seen: set[str] = set()
    suggestions: list[SearchSuggestionOut] = []
    for query in rows:
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        card = db.scalar(select(Card).where(Card.card_code.ilike(query)).limit(1))
        if card is not None:
            suggestions.append(
                SearchSuggestionOut(
                    label=_card_title(card), type="card", url=f"/cards/{card.id}"
                )
            )
        else:
            suggestions.append(
                SearchSuggestionOut(label=query, type="recent_search", url=f"/search?q={query}")
            )
        if len(suggestions) >= limit:
            break
    return suggestions


def _top_owned_cards(db: Session, limit: int) -> list[SearchSuggestionOut]:
    totals = _owned_card_ids(db)
    owned_ids = sorted(
        (cid for cid, qty in totals.items() if qty > 0),
        key=lambda cid: totals[cid],
        reverse=True,
    )[:limit]
    cards_by_id = _cards_by_id(db, set(owned_ids))
    return [
        SearchSuggestionOut(label=_card_title(cards_by_id[cid]), type="card", url=f"/cards/{cid}")
        for cid in owned_ids
        if cid in cards_by_id
    ]


def _wishlist_grails(db: Session, limit: int) -> list[SearchSuggestionOut]:
    items = db.scalars(
        select(WishlistItem)
        .where(WishlistItem.priority.in_(HIGH_WISHLIST_PRIORITIES), WishlistItem.status != "removed")
        .order_by(WishlistItem.created_at.desc())
        .limit(limit)
    ).all()
    cards_by_id = _cards_by_id(db, {i.card_id for i in items})
    suggestions = []
    for item in items:
        card = cards_by_id.get(item.card_id)
        label = f"{_card_title(card)} ({item.priority})" if card else f"Wishlist item #{item.id}"
        suggestions.append(SearchSuggestionOut(label=label, type="wishlist", url="/wishlist"))
    return suggestions


def _recent_opportunities(db: Session, limit: int) -> list[SearchSuggestionOut]:
    response = get_opportunities(db, limit=limit)
    return [
        SearchSuggestionOut(
            label=f"{opp.card_code or 'Unlisted'} - {opp.category} (score {opp.score})",
            type="opportunity",
            url="/market/opportunities",
        )
        for opp in response.opportunities
    ]


def _recent_notes(db: Session, limit: int) -> list[SearchSuggestionOut]:
    notes = db.scalars(
        select(CollectorNote).order_by(CollectorNote.created_at.desc()).limit(limit)
    ).all()
    cards_by_id = _cards_by_id(db, {n.card_id for n in notes if n.card_id is not None})
    suggestions = []
    for note in notes:
        card = cards_by_id.get(note.card_id) if note.card_id is not None else None
        label = note.title or note.body[:60]
        url = f"/cards/{card.id}" if card else "/dashboard"
        suggestions.append(SearchSuggestionOut(label=label, type="note", url=url))
    return suggestions


def get_suggestions(db: Session, q: str | None, limit: int) -> list[SearchSuggestionOut]:
    per_source = min(limit, SUGGESTIONS_PER_SOURCE)
    combined: list[SearchSuggestionOut] = []
    combined.extend(_recent_searched_card_codes(db, per_source))
    combined.extend(_top_owned_cards(db, per_source))
    combined.extend(_wishlist_grails(db, per_source))
    combined.extend(_recent_opportunities(db, per_source))
    combined.extend(_recent_notes(db, per_source))

    if q:
        q_lower = q.lower()
        combined = [s for s in combined if q_lower in s.label.lower()]

    # Dedupe by (label, url) while preserving source-priority order.
    seen: set[tuple[str, str]] = set()
    deduped: list[SearchSuggestionOut] = []
    for s in combined:
        key = (s.label, s.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)

    return deduped[:limit]
