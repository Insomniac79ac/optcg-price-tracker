"""Request and response shapes for /me. Money is integer JPY plus ``currency``.

Percentages are decimal text with two places (never floats). A value that
cannot be measured is ``null`` with a reason, never 0.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.accounts.models import NOTE_MAX_LENGTH

MAX_QUANTITY = 9999
MAX_JPY = 100_000_000

Currency = Literal["JPY"]

# Security audit 2026-10-16, F11: Postgres rejects NUL in text (a 500), and no
# other C0 control belongs in a note. Tab and line breaks stay allowed.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
EARLIEST_ACQUIRED_ON = date(1900, 1, 1)


def _note_text(value: str | None) -> str | None:
    if value is not None and _CONTROL_CHARACTERS.search(value):
        raise ValueError("note must not contain control characters")
    return value


def _acquired_on(value: date | None) -> date | None:
    # The website refuses dates after the collector's local today; one day of
    # slack covers time zones ahead of UTC.
    latest = datetime.now(timezone.utc).date() + timedelta(days=1)
    if value is not None and not EARLIEST_ACQUIRED_ON <= value <= latest:
        raise ValueError(f"acquired_on must be between {EARLIEST_ACQUIRED_ON.isoformat()} and today")
    return value


NoteText = Annotated[str | None, Field(max_length=NOTE_MAX_LENGTH), AfterValidator(_note_text)]
AcquiredOn = Annotated[date | None, AfterValidator(_acquired_on)]


class PrintSummaryOut(BaseModel):
    card_print_id: int
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    treatment: str | None
    official_asset_variant: str | None
    release_product_id: int | None
    release_code: str | None
    release_name: str | None


class CollectionEntryCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_print_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=MAX_QUANTITY)
    paid_jpy_per_card: int | None = Field(default=None, ge=0, le=MAX_JPY)
    acquired_on: AcquiredOn = None
    note: NoteText = None


class CollectionEntryUpdateIn(BaseModel):
    """Only the fields sent are changed; send ``null`` to clear an optional one."""

    model_config = ConfigDict(extra="forbid")

    quantity: int | None = Field(default=None, ge=1, le=MAX_QUANTITY)
    paid_jpy_per_card: int | None = Field(default=None, ge=0, le=MAX_JPY)
    acquired_on: AcquiredOn = None
    note: NoteText = None


class CollectionEntryOut(BaseModel):
    id: int
    card_print_id: int | None
    resolution: Literal["exact", "unresolved"]
    quantity: int
    paid_jpy_per_card: int | None
    acquired_on: date | None
    note: str | None
    legacy_card_id: int | None
    created_at: datetime
    updated_at: datetime
    print: PrintSummaryOut | None
    value_status: Literal["priced", "no_price", "unresolved"]
    value_per_card_jpy: int | None
    value_jpy: int | None


class CoverageOut(BaseModel):
    value_jpy: int | None
    priced_cards: int
    total_cards: int
    priced_entries: int
    total_entries: int
    unresolved_entries: int
    coverage_pct: str | None


class CollectionOut(BaseModel):
    currency: Currency = "JPY"
    as_of: date | None
    summary: CoverageOut
    entries: list[CollectionEntryOut]


class MoverOut(BaseModel):
    card_print_id: int
    units: int
    prior_value_per_card_jpy: int
    current_value_per_card_jpy: int
    delta_jpy: int
    change_pct: str | None
    contribution_pct_points: str | None


class StepOut(BaseModel):
    available: bool
    reason: str | None
    from_date: date | None
    to_date: date | None
    missing_dates: list[date]
    comparable_cards: int
    prior_comparable_jpy: int | None
    current_comparable_jpy: int | None
    change_jpy: int | None
    change_pct: str | None
    exclusions: dict[str, int]


class MoversOut(StepOut):
    up: list[MoverOut]
    down: list[MoverOut]


class ReleaseShareOut(BaseModel):
    release_product_id: int | None
    release_code: str | None
    release_name: str | None
    value_jpy: int | None
    priced_cards: int
    total_cards: int
    share_pct: str | None
    change: StepOut


class PaidOut(BaseModel):
    cards_with_paid: int
    cards_compared: int
    total_cards: int
    paid_jpy: int | None
    priced_today_jpy: int | None
    change_pct: str | None


class RecordedChangeOut(BaseModel):
    window: str
    available: bool
    reason: str | None
    from_date: date | None
    to_date: date | None
    change_pct: str | None
    missing_dates: list[date]
    failed_step_date: date | None


class HistoryPointOut(BaseModel):
    date: date
    value_jpy: int | None
    priced_cards: int
    total_cards: int
    step_publishable: bool | None
    step_reason: str | None
    segment_number: int


class HistoryOut(BaseModel):
    """The collection's own recorded daily values (S4 daily stage)."""

    kind: Literal["recorded"] = "recorded"
    methodology_version: int
    change: RecordedChangeOut
    points: list[HistoryPointOut]


PREVIEW_LABEL = (
    "Preview: how the cards you hold now moved over the last 30 days. "
    "This is not your collection's recorded history."
)


class PreviewPointOut(BaseModel):
    date: date
    value_jpy: int | None
    priced_cards: int
    step_publishable: bool | None
    step_reason: str | None


class PreviewOut(BaseModel):
    """Derived on read from today's cards and archived values; never stored."""

    kind: Literal["preview"] = "preview"
    label: str = PREVIEW_LABEL
    from_date: date | None
    to_date: date | None
    total_cards: int
    change: RecordedChangeOut
    points: list[PreviewPointOut]


class CollectionValueOut(BaseModel):
    currency: Currency = "JPY"
    as_of: date | None
    window: Literal["7d", "30d", "all"]
    summary: CoverageOut
    movers: MoversOut
    # Every comparable version's change over the window (the full list the
    # top-five movers are cut from), for the per-card change on /collection.
    # Empty when the window is unavailable; a version missing from it was not
    # comparable at both ends (new, sold, or its price inputs changed).
    cards: list[MoverOut] = []
    by_release: list[ReleaseShareOut]
    paid: PaidOut
    history: HistoryOut
    preview: PreviewOut


class WatchlistEntryCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_print_id: int = Field(gt=0)
    target_jpy: int | None = Field(default=None, gt=0, le=MAX_JPY)
    note: NoteText = None


class WatchlistEntryUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_jpy: int | None = Field(default=None, gt=0, le=MAX_JPY)
    note: NoteText = None


class WatchlistEntryOut(BaseModel):
    id: int
    card_print_id: int | None
    resolution: Literal["exact", "unresolved"]
    target_jpy: int | None
    note: str | None
    legacy_card_id: int | None
    created_at: datetime
    updated_at: datetime
    print: PrintSummaryOut | None
    value_status: Literal["priced", "no_price", "unresolved"]
    value_jpy: int | None
    target_gap_jpy: int | None
    # When the freshest source behind ``value_jpy`` was last read, from the
    # archived row the value comes from. Null when unknown or unpriced.
    checked_at: datetime | None = None
    # This version's change over the 7 days ending ``as_of``, by the same
    # comparability rules as the collection's movers. Null with a reason
    # (``change_7d_reason``) when the two ends are not comparable; never 0%.
    change_7d_pct: str | None = None
    change_7d_reason: str | None = None


class WatchlistOut(BaseModel):
    currency: Currency = "JPY"
    as_of: date | None
    entries: list[WatchlistEntryOut]
    # The 7-day window every entry's change is read over. ``change_7d_from``
    # is null when there is no priced day yet; ``change_7d_missing_dates``
    # names the days without verified prices when that is why it is
    # unavailable.
    change_7d_from: date | None = None
    change_7d_missing_dates: list[date] = []


class ProfileOut(BaseModel):
    """What /account shows. Name and email come from Google at sign-in."""

    email: str
    name: str | None
    member_since: datetime


class PreferencesOut(BaseModel):
    currency: Currency
    collection_visibility: Literal["private"]


class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Currency = "JPY"
    collection_visibility: Literal["private"] = "private"
