from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.pagination import PaginationMeta


class CollectorTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    color: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class CollectorTagCreateIn(BaseModel):
    name: str = Field(min_length=1)
    color: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class CollectorTagUpdateIn(BaseModel):
    name: str | None = None
    color: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class CollectorGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


class CollectorGroupCreateIn(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class CollectorGroupUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


# --- collector notes -----------------------------------------------------


class CollectorNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    note_type: str
    card_id: int | None
    collection_item_id: int | None
    wishlist_item_id: int | None
    grading_submission_id: int | None
    market_signal_event_id: int | None
    market_report_id: int | None
    title: str | None
    body: str
    pinned: bool
    created_at: datetime
    updated_at: datetime


class CollectorNoteListOut(BaseModel):
    items: list[CollectorNoteOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class CollectorNoteCreateIn(BaseModel):
    note_type: str = "general"
    card_id: int | None = None
    collection_item_id: int | None = None
    wishlist_item_id: int | None = None
    grading_submission_id: int | None = None
    market_signal_event_id: int | None = None
    market_report_id: int | None = None
    title: str | None = None
    body: str = Field(min_length=1)
    pinned: bool = False

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("body must not be blank")
        return cleaned


class CollectorNoteUpdateIn(BaseModel):
    note_type: str | None = None
    card_id: int | None = None
    collection_item_id: int | None = None
    wishlist_item_id: int | None = None
    grading_submission_id: int | None = None
    market_signal_event_id: int | None = None
    market_report_id: int | None = None
    title: str | None = None
    body: str | None = None
    pinned: bool | None = None

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("body must not be blank")
        return cleaned


# --- collector activity timeline -----------------------------------------


class CollectorActivityEventOut(BaseModel):
    id: int
    event_type: str
    event_source: str
    card_id: int | None
    card_code: str | None = None
    name_en: str | None = None
    name_jp: str | None = None
    collection_item_id: int | None
    wishlist_item_id: int | None
    grading_submission_id: int | None
    market_signal_event_id: int | None
    market_report_id: int | None
    market_workflow_run_id: int | None
    title: str
    message: str | None
    created_at: datetime
    payload: dict[str, Any] | None = None


class CollectorActivityListSummaryOut(BaseModel):
    total_events: int
    by_source: dict[str, int]
    by_type: dict[str, int]


class CollectorActivityListOut(BaseModel):
    summary: CollectorActivityListSummaryOut
    events: list[CollectorActivityEventOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class CollectorActivitySummaryOut(BaseModel):
    today_count: int
    last_7d_count: int
    last_30d_count: int
    by_source: dict[str, int]
    recent_events: list[CollectorActivityEventOut]


class RecentActivityWidgetOut(BaseModel):
    events: list[CollectorActivityEventOut]


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    image_url: str | None
    tags: list[CollectorTagOut] = []
    # Catalog-enrichment fields (see app.services.card_catalog_import) - all
    # nullable, since most existing rows predate this metadata being
    # collected. Exposed here (previously only used internally by CSV import
    # preview) so the card detail page can render a metadata grid/effect
    # text without a new endpoint.
    release_date: date | None = None
    artist: str | None = None
    character: str | None = None
    color: str | None = None
    card_type: str | None = None
    cost: int | None = None
    power: int | None = None
    counter: int | None = None
    attribute: str | None = None
    effect_text: str | None = None
    trigger_text: str | None = None
    created_at: datetime
    updated_at: datetime


class PriceObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    card_id: int
    source_id: int
    source: str
    observed_at: datetime
    price_type: str
    price_jpy: int
    condition_label: str | None
    stock_status: str | None
    listing_count: int | None
    raw_snapshot_id: int | None


class MarketIndexSourceValueOut(BaseModel):
    """One normalized source reference (see app.services.market_index) -
    either a candidate for the Market Index itself (source_values) or an
    auxiliary value never eligible for it, e.g. Yuyu-Tei buy
    (auxiliary_values). Never a fixed 'yuyutei_price'/'snkrdunk_price' pair -
    this shape is what lets a future Cardrush/Mercado resolver slot in
    without a frontend contract change."""

    source: str
    reference_type: str
    evidence_type: Literal["listing", "transaction"]
    value_jpy: int | None
    observed_at: datetime | None
    sample_size: int | None
    stale: bool
    eligible: bool
    fallback_used: bool
    ineligible_reason: str | None = None
    # What the observed number *means*, independent of whether it is
    # currently eligible - see app.services.source_semantics. "platform_floor"
    # says the value is the platform's minimum permitted listing price rather
    # than an unconstrained market price. Reported even when the observation
    # is ineligible for some other reason (e.g. stale), so the raw value can
    # still be displayed with the right caveat. Optional with a None default:
    # every existing client that ignores it is unaffected.
    constraint: str | None = None
    # Did this value participate in the numerical aggregate? Deliberately a
    # SECOND field rather than a redefinition of `eligible` above, because the
    # two answer different questions and Market Index v2 is exactly the point
    # at which they stopped having the same answer:
    #
    #   eligible              - is this value admissible evidence at all?
    #   contributes_to_index  - did it go into index_value_jpy?
    #
    # Under v2 an admissible SNKRDUNK listing floor whose `fallback_used` is
    # true stands aside when a non-fallback source is present: it keeps
    # eligible=true, keeps its raw number, stays in source_price_range, and
    # reports contributes_to_index=false. See
    # app.services.market_index._compute_index_fields for the rule.
    #
    # Optional with a None default so the schema stays additive - an existing
    # client that ignores it is unaffected, and None means "this payload
    # predates the field", never "it did not contribute". Every source value
    # emitted by the current resolver carries an explicit true or false,
    # including auxiliary ones (always false).
    contributes_to_index: bool | None = None


class SourcePriceRangeOut(BaseModel):
    """The spread between the cheapest and dearest ADMISSIBLE source values -
    every value that is eligible evidence, whether or not it contributed to the
    index.

    Answers "how far apart are the usable sources?" - the question a single
    index number cannot answer on its own, because with two sources the median
    is their midpoint and a midpoint looks identical whether the sources agreed
    within 5% or disagreed by 1000%.

    DERIVED BEFORE CONTRIBUTOR ROLE IS APPLIED, and that is the whole point
    under Market Index v2 (see app.services.market_index._compute_index_fields).
    A SNKRDUNK listing floor that stands aside from the aggregate is still a
    real, measured number that disagrees with the one Atlas published, and
    dropping it from the range would hide exactly the disagreement this field
    exists to expose. So `source_count = 1` alongside a two-endpoint range is a
    valid, intentional combination: one value contributed, two were admissible.

    Constrained, stale, and otherwise ineligible values are excluded - they are
    not admissible evidence - and auxiliary values (e.g. Yuyu-Tei's dealer buy
    price) never enter either, because they live in a separate list that is not
    an index candidate at all. The excluded values all remain visible in
    source_values with their own reason.

    Absent (null) below two admissible sources: one source cannot disagree with
    itself, and "¥220 - ¥220" states a spread that was never measured."""

    low_jpy: int
    high_jpy: int


class MarketIndexOut(BaseModel):
    card_id: int
    index_version: int
    # The app.services.source_semantics ruleset used to interpret this
    # index's source observations (see MarketIndexSourceValueOut.constraint).
    # Independent of index_version, which versions the combination algorithm.
    source_semantics_version: int
    # The spread of the eligible sources behind index_value_jpy, or null when
    # fewer than two sources were eligible - see SourcePriceRangeOut.
    source_price_range: SourcePriceRangeOut | None = None
    index_value_jpy: int | None
    calculation_method: str
    source_count: int
    coverage_status: Literal["full", "limited", "none"]
    confidence: Literal["high", "medium", "low"]
    source_values: list[MarketIndexSourceValueOut]
    auxiliary_values: list[MarketIndexSourceValueOut]
    freshest_observation_at: datetime | None
    stalest_eligible_source_at: datetime | None
    stale_sources: list[str]
    calculated_at: datetime


class CardCatalogueItemOut(CardOut):
    """CardOut plus its Market Index summary, batch-computed - see GET
    /cards/catalogue. Extends CardOut (rather than duplicating its fields)
    so a catalogue tile and a card-detail page can share one card shape."""

    market_index: MarketIndexOut


class CardCatalogueFacetsOut(BaseModel):
    """Distinct values actually present in the (active) card catalog, for
    building filter dropdowns that can never offer an option with zero
    matching cards - see app.services.card_catalogue.get_catalogue_facets.
    Unaffected by the current q/set_code/rarity/... filters so narrowing one
    filter never hides the others' remaining valid options."""

    set_codes: list[str]
    rarities: list[str]
    languages: list[str]
    variants: list[str]


class CardCatalogueListOut(BaseModel):
    items: list[CardCatalogueItemOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta
    facets: CardCatalogueFacetsOut


# --- Print-centric public read model (see app.services.print_market_index,
# app.services.print_pricing, app.services.print_catalogue) - every shape
# below is keyed by card_print_id/canonical_card_id, never legacy card_id,
# so two prints sharing a legacy card bridge (e.g. a base and a parallel of
# the same canonical card) can never contaminate each other's market data.
# CardOut/MarketIndexOut/PriceObservationOut above remain the legacy,
# card_id-keyed shapes and are unaffected by any of this. ---------------


class CardPrintSiblingOut(BaseModel):
    """A lightweight reference to another CardPrint sharing the same
    canonical_card_id - no market data, just enough to link to it (see
    CardPrintOut.siblings)."""

    model_config = ConfigDict(from_attributes=True)

    card_print_id: int
    # Nullable ahead of treatment becoming optional on card_prints: NULL means
    # "Atlas has not classified this printing", and consumers render no badge
    # and invent no label for it. Every current row is non-null, so today's
    # payloads are unchanged.
    treatment: str | None
    language: str
    verification_status: str
    image_url: str | None


class PrintMarketIndexOut(BaseModel):
    """Print-scoped counterpart to MarketIndexOut - identical fields and
    methodology (see app.services.market_index), keyed by card_print_id
    instead of card_id."""

    card_print_id: int
    index_version: int
    source_semantics_version: int
    source_price_range: SourcePriceRangeOut | None = None
    index_value_jpy: int | None
    calculation_method: str
    source_count: int
    coverage_status: Literal["full", "limited", "none"]
    confidence: Literal["high", "medium", "low"]
    source_values: list[MarketIndexSourceValueOut]
    auxiliary_values: list[MarketIndexSourceValueOut]
    freshest_observation_at: datetime | None
    stalest_eligible_source_at: datetime | None
    stale_sources: list[str]
    calculated_at: datetime


class PrintPriceObservationOut(BaseModel):
    """Print-scoped counterpart to PriceObservationOut - same fields, keyed
    by card_print_id instead of card_id. Deliberately has no stock/inventory
    field: the print-centric public product model does not depend on
    Yuyu-Tei stock (product decision - see docs/market_index.md "Source
    eligibility" and docs/yuyutei_collector_operations.md "Stock is not
    required"). It never had any consumer to keep backwards-compatible, so
    it is omitted outright rather than deprecated-and-nulled.

    Source semantics (constraint/eligible/ineligible_reason)
    --------------------------------------------------------
    Annotations only. The observation above them is returned exactly as
    stored - same source, price_type, price_jpy, observed_at, condition and
    provenance - and nothing here filters, reorders, or rewrites a row. They
    exist so a client can tell a genuine 1000 JPY market price from SNKRDUNK's
    1000 JPY platform minimum, which are indistinguishable from price_jpy
    alone, without reimplementing any source rule of its own.

    Derived at read time by app.services.source_semantics.classify_observation
    - the same classifier app.services.market_index calls - from
    (source, price_type, price_jpy). No threshold, source name, or platform
    minimum is restated here or in the endpoint; a rules change therefore
    reaches this payload with no migration and no backfill.

    WHAT ``eligible`` DOES NOT MEAN. It answers only "is this observation
    disqualified by *source semantics*?", exactly as
    SourceSemantics.eligible does. It is NOT "this observation counted toward
    the Market Index": staleness (YUYUTEI_SELL_MAX_AGE_DAYS,
    SNKRDUNK_FLOOR_MAX_AGE_DAYS) and the sold-sample minimum live in
    market_index's resolvers and are deliberately not applied here, because
    this is a *history* endpoint and an observation that is stale today was
    not stale when it was made. So a fresh-looking eligible=true row may still
    be excluded from today's index. For "what the index actually used", read
    MarketIndexOut.source_values - never this field."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    card_print_id: int
    source_id: int
    source: str
    observed_at: datetime
    price_type: str
    price_jpy: int
    condition_label: str | None
    listing_count: int | None
    raw_snapshot_id: int | None
    # Defaulted to the unconstrained verdict so the three stay optional for
    # any client that predates them, and so a caller that omits them cannot
    # accidentally assert a constraint that was never classified.
    constraint: str | None = None
    eligible: bool = True
    ineligible_reason: str | None = None


class PrintPriceSeriesTrendOut(BaseModel):
    """One (source, price_type) series' trend within a print's price
    history - see app.services.print_pricing.compute_print_price_series_trends.
    sufficient_history is false with only one observation in the series;
    change_*_pct stays null (never fabricated) unless a real observation
    exists at or before that window's cutoff. No stock field - see
    PrintPriceObservationOut's docstring; a trend is price/time based only,
    never a stock transition."""

    source: str
    price_type: str
    latest_price_jpy: int
    latest_observed_at: datetime
    sufficient_history: bool
    change_24h_pct: float | None
    change_7d_pct: float | None
    change_30d_pct: float | None


class PrintPriceHistoryOut(BaseModel):
    card_print_id: int
    observations: list[PrintPriceObservationOut]
    series: list[PrintPriceSeriesTrendOut]


class DisplayImageCanvasOut(BaseModel):
    """Intrinsic pixel size of the display image as published by its host."""

    width: int
    height: int


class DisplayImageCardBoxOut(BaseModel):
    """Where the card actually sits inside the canvas, in canvas pixels.

    Top-left origin, width/height inclusive of both edge columns/rows. Every
    pixel of the card - including the transparent rounded corners, which are
    part of the card's shape - lies inside this box, and everything outside it
    was verified to be fully transparent.
    """

    x: int
    y: int
    width: int
    height: int


class DisplayImageGeometryOut(BaseModel):
    """Enough geometry for a client to present the *card* rather than the
    canvas it was composited onto.

    Only emitted for a verified display image whose retained evidence records
    a canvas and card box that pass validation (see
    app.services.display_image._geometry). Null for canonical Bandai
    fallbacks, whose card already fills the asset, and null whenever the
    recorded geometry is missing or inconsistent - in which case a client
    must fall back to plain contain rendering.
    """

    canvas_px: DisplayImageCanvasOut
    card_bbox_px: DisplayImageCardBoxOut


class DisplayImageOut(BaseModel):
    """Which image to *show* for a print, which is not necessarily the image
    that proves its identity.

    Additive and purely presentational: `image_url`/`artwork_key` on the
    print remain the canonical Bandai identity fields and are unaffected by
    anything here. See app.services.display_image for the selection rule.

    `source` names *where the picture came from*, and "bandai" is now
    ambiguous on its own: it is returned both for a verified official Card
    List asset we mirrored and for the canonical fallback that repeats
    `image_url` (SAMPLE watermark and all). `owned_asset_selected` is what
    separates them - it says whether `url` came from the verified owned-asset
    path or from the original/canonical source URL. It is delivery
    provenance only and changes nothing about identity: `source`,
    `exact_print_verified` and `geometry` all describe the same verified
    asset either way.
    """

    url: str
    source: str
    exact_print_verified: bool
    # False on every path that serves a source or canonical URL, so a client
    # that does not know the field yet keeps the safe reading.
    owned_asset_selected: bool = False
    geometry: DisplayImageGeometryOut | None = None


class CardPrintOut(BaseModel):
    """Public print detail response - see GET /prints/{print_id}. Identity
    fields (card_code/name/card_type/colors) come from the print's
    CanonicalCard, never from the legacy Card table's rarity/variant columns;
    `rarity` resolves per-printing (see below)."""

    card_print_id: int
    canonical_card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    # Optional: THIS PRINTING's rarity - card_prints.official_rarity, the
    # value Bandai publishes for this exact catalogue entry, falling back to
    # the canonical card's summary rarity where the print carries none (see
    # app.services.print_catalogue.effective_rarity). NULL only where the
    # catalogue establishes neither; clients render nothing for it and no
    # placeholder is substituted.
    rarity: str | None
    # Optional: the card-level summary rarity from canonical_cards, served
    # unresolved and independently of `rarity` above.
    #
    # It exists so a client can separate two facts that Bandai publishes in one
    # column. Where `rarity` names a special printing category rather than a
    # scarcity tier ('SPカード', 'TR'), this is the only authoritative place an
    # UNDERLYING rarity can come from - and it is written only where the card's
    # own set publishes exactly one (see app.services.canonical_import_apply
    # "THE RARITY PROBLEM, AS RESOLVED"), so it is NULL rather than guessed
    # wherever the catalogue established none.
    #
    # It is therefore never a fallback for `rarity` and never a default: a
    # client shows it as a separate "Rarity" only when it holds a real ordinary
    # rarity, and shows no rarity at all when it is NULL. It may also equal
    # `rarity` outright for an ordinary print, which is not a second fact.
    canonical_rarity: str | None
    card_type: str
    colors: list[str] | None
    language: str
    treatment: str | None
    # The product THIS printing appeared in. Not the card's set: a reprint
    # carries the later product here, so a UI must not label it "Set".
    release_product_code: str | None
    # The set the card was originally published in, from the canonical card.
    # NULL for promos, which belong to no numbered set.
    original_set_code: str | None
    # Which official Bandai asset this printing carries - 'base', 'pN', 'rN'.
    # Identity-bearing evidence, exposed so a client can tell two printings of
    # one card apart. It is an address, never a classification: a client must
    # not read "parallel" or a rarity out of it (see
    # app.services.official_asset_variant).
    official_asset_variant: str | None
    artwork_key: str | None
    image_url: str | None
    display_image: DisplayImageOut | None
    verification_status: str
    market_index: PrintMarketIndexOut
    siblings: list[CardPrintSiblingOut]


class PrintCatalogueItemOut(BaseModel):
    """One collector-facing catalogue tile - see GET /prints. Sibling prints
    of the same canonical card (e.g. Sanji base and Sanji parallel) each
    appear as their own separate item here, never merged."""

    card_print_id: int
    canonical_card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    # Optional, same reading as CardPrintOut.rarity: this printing's official
    # rarity where it has one, else the canonical card-level value, else NULL.
    rarity: str | None
    # Same reading as CardPrintOut.canonical_rarity: the card-level summary
    # value, NULL where the catalogue established none, never a fallback for
    # `rarity`.
    canonical_rarity: str | None
    card_type: str
    treatment: str | None
    language: str
    # Same reading as CardPrintOut's two: the product this printing appeared
    # in, the set the card came from, and which official asset it carries.
    release_product_code: str | None
    original_set_code: str | None
    official_asset_variant: str | None
    image_url: str | None
    display_image: DisplayImageOut | None
    verification_status: str
    market_index: PrintMarketIndexOut
    source_coverage: list[str]
    latest_observation_at: datetime | None
    # Movement of the MARKET INDEX itself over exactly seven UTC calendar days
    # - never a source price compared to an index. Null unless a snapshot
    # exists at exactly CURRENT_DATE - 7 whose ruleset versions AND eligible
    # (source, reference_type) contributor set match today's, so a change of
    # contributing evidence can never be reported as a change of price. See
    # app.services.market_index_change for every condition and why each exists.
    #
    # A genuine 0.0 is a measurement and is returned as 0.0; null means "no
    # comparable baseline", and the two must never be conflated. Optional with
    # a None default so a client predating this field parses unchanged - the
    # same treatment `constraint` and `source_price_range` were given.
    market_index_change_7d_pct: float | None = None


class PrintCatalogueFacetsOut(BaseModel):
    # Still list[str]: an unclassified print contributes no facet value at
    # all. There is deliberately no synthetic "unclassified"/"other" bucket -
    # a filter option must always name a real, selectable treatment.
    #
    # `rarities` reads the same way: a print for which neither its own
    # official rarity nor the canonical card-level value is established
    # contributes no facet value, and there is no "Unknown" rarity option. See
    # print_catalogue's facet query, which facets on the same expression the
    # tiles display and `?rarity=` filters on, and excludes NULL rather than
    # letting it become a value here.
    treatments: list[str]
    rarities: list[str]
    languages: list[str]
    verification_statuses: list[str]


class PrintCatalogueListOut(BaseModel):
    items: list[PrintCatalogueItemOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta
    facets: PrintCatalogueFacetsOut


class SnkrdunkCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    discovery_run_id: int | None
    source_url: str
    title: str | None
    price_jpy: int | None
    image_url: str | None
    listing_count: int | None
    condition_label: str | None
    raw_text: str | None
    normalized_title: str | None
    detected_card_code: str | None
    detected_set_code: str | None
    detected_rarity: str | None
    detected_variant: str | None
    match_status: str
    matched_card_id: int | None
    match_confidence: float | None
    best_match_card_id: int | None = None
    best_match_score: int | None = None
    best_match_confidence_label: str | None = None
    created_at: datetime
    updated_at: datetime
    matched_card: CardOut | None = None


class SnkrdunkCandidateListOut(BaseModel):
    items: list[SnkrdunkCandidateOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class SnkrdunkCandidateMatchIn(BaseModel):
    # OPTIONAL SINCE c9f31e2a7d04. card_print_id below is what identifies the
    # printing; this is a legacy compatibility pointer and the `cards` table
    # cannot name most of the catalogue, so a print-authoritative approval
    # simply omits it. Supplying it still works and still populates the
    # mapping's legacy column.
    card_id: int | None = None
    # Required, and required on purpose: a mapping is a claim about which
    # printing was priced, and the legacy card_id cannot carry that claim (25
    # cards against 4,281 prints). Approval is refused rather than inferred
    # when the source evidence does not single this print out - see
    # app.services.exact_print_approval.
    card_print_id: int
    manual_verified: bool = True


class MatchExplanationOut(BaseModel):
    positive: list[str]
    negative: list[str]
    caps_applied: list[str]


class CandidateMatchOut(BaseModel):
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    score: int
    confidence_label: str
    ambiguous: bool
    explanation: MatchExplanationOut


class CandidateMatchesOut(BaseModel):
    candidate: SnkrdunkCandidateOut
    matches: list[CandidateMatchOut]


class RematchAllIn(BaseModel):
    status: str | None = None
    limit: int = 100
    dry_run: bool = True


class RematchAllOut(BaseModel):
    would_update: int
    updated: int
    suggested: int
    ambiguous: int
    unmatched: int
    dry_run: bool


class ApproveMatchIn(BaseModel):
    # See SnkrdunkCandidateMatchIn.card_id - same contract, same reason.
    # Omitting it approves a print-authoritative mapping with card_id NULL;
    # the card-level match score is then simply not computed, because there
    # is no legacy card to score the title against.
    card_id: int | None = None
    # See SnkrdunkCandidateMatchIn.card_print_id - same contract, same reason.
    card_print_id: int
    review_notes: str | None = None


class RejectMatchIn(BaseModel):
    review_notes: str | None = None


class MarketPriceOut(BaseModel):
    source: str
    price_type: str
    price_jpy: int
    observed_at: datetime
    condition_label: str | None
    stock_status: str | None
    listing_count: int | None


class MarketSignalsOut(BaseModel):
    change_24h_pct: float | None
    change_7d_pct: float | None
    change_30d_pct: float | None
    yuyutei_spread_jpy: int | None
    snkrdunk_floor_vs_yuyutei_buy_jpy: int | None


class MarketMoverOut(BaseModel):
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    latest_prices: list[MarketPriceOut]
    signals: MarketSignalsOut


class PriceRefreshRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    scraping_mode: str
    source_filter: str | None
    limit_count: int
    dry_run: bool
    mappings_checked: int
    snapshots_created: int
    observations_parsed: int
    observations_inserted: int
    observations_skipped_duplicate: int
    mappings_failed: int
    error_message: str | None


class PriceRefreshRunListOut(BaseModel):
    items: list[PriceRefreshRunOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class AlertEventOut(BaseModel):
    id: int
    created_at: datetime
    event_type: str
    card_id: int | None
    card_code: str | None
    card_name: str | None
    source_name: str | None
    price_observation_id: int | None
    refresh_run_id: int | None
    title: str
    message: str
    dedupe_key: str
    sent_at: datetime | None
    status: str
    error_message: str | None


class AlertEventListOut(BaseModel):
    items: list[AlertEventOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    name: str
    rule_type: str
    source_name: str | None
    price_type: str | None
    threshold_pct: float | None
    is_active: bool


class AlertRuleUpdateIn(BaseModel):
    is_active: bool | None = None
    threshold_pct: float | None = None


class SourceCardMappingOut(BaseModel):
    id: int
    # NULL on a print-authoritative mapping: card_print_id below is the
    # identity, and the legacy `cards` table cannot name most of the
    # catalogue. Populated on every row written so far.
    card_id: int | None = None
    # Additive and read-only here. NULL on every legacy row and populated on
    # every new approval; the PATCH schema deliberately has no counterpart,
    # so a print can only ever be (re)assigned through an approval path that
    # runs the exact-print gate.
    card_print_id: int | None = None
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    source_name: str | None
    source_url: str | None
    source_card_id: str
    manual_verified: bool
    match_confidence: float | None
    match_confidence_label: str | None = None
    last_match_checked_at: datetime | None = None
    is_active: bool
    review_status: str
    review_notes: str | None
    created_at: datetime
    updated_at: datetime
    last_verified_at: datetime | None


class SourceCardMappingListOut(BaseModel):
    items: list[SourceCardMappingOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class SourceCardMappingUpdateIn(BaseModel):
    source_url: str | None = None
    source_card_id: str | None = None
    manual_verified: bool | None = None
    is_active: bool | None = None
    review_status: str | None = None
    review_notes: str | None = None


class MappingQualityItemOut(BaseModel):
    mapping_id: int
    source_name: str | None
    source_url: str | None
    source_card_id: str
    # NULL on a print-authoritative mapping, same as SourceCardMappingOut
    # above: the quality report scores such a mapping and flags it with
    # issue_type "missing_card_reference" rather than omitting it.
    card_id: int | None = None
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    is_active: bool
    manual_verified: bool
    review_status: str
    match_confidence: int | None
    match_confidence_label: str
    risk_level: str
    issue_types: list[str]
    explanation: MatchExplanationOut
    latest_price_observed_at: datetime | None
    last_match_checked_at: datetime | None


class MappingQualitySummaryOut(BaseModel):
    total_mappings: int
    ok_count: int
    review_count: int
    warning_count: int
    critical_count: int
    low_confidence_count: int
    duplicate_source_url_count: int
    stale_mapping_count: int
    unverified_count: int
    inactive_with_recent_price_count: int
    active_without_recent_price_count: int


class MappingQualityListOut(BaseModel):
    summary: MappingQualitySummaryOut
    items: list[MappingQualityItemOut]
    pagination: PaginationMeta


class RecheckQualityIn(BaseModel):
    source: str | None = None
    review_status: str | None = None
    is_active: bool | None = None
    manual_verified: bool | None = None
    limit: int = 100
    dry_run: bool = True


class RecheckQualitySummaryOut(BaseModel):
    selected: int
    would_update: int
    updated: int
    ok: int
    review: int
    warning: int
    critical: int


class RecheckQualityOut(BaseModel):
    dry_run: bool
    summary: RecheckQualitySummaryOut
    preview: list[MappingQualityItemOut]


BulkMappingAction = Literal[
    "approve", "reject", "deactivate", "activate", "mark_verified", "mark_pending"
]


class BulkMappingUpdateIn(BaseModel):
    mapping_ids: list[int]
    action: BulkMappingAction
    review_notes: str | None = None


class BulkMappingUpdateResultOut(BaseModel):
    mapping_id: int
    ok: bool
    error: str | None = None


class BulkMappingUpdateOut(BaseModel):
    action: str
    results: list[BulkMappingUpdateResultOut]


class ReplaceMappingCardIn(BaseModel):
    card_id: int
    review_notes: str | None = None
    approve: bool = False


class SuggestedCardsOut(BaseModel):
    mapping_id: int
    matches: list[CandidateMatchOut]


GradingSubmissionStatus = Literal[
    "planned", "preparing", "submitted", "grading", "shipped_back", "received", "cancelled"
]


class GradingSubmissionOut(BaseModel):
    id: int
    collection_item_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    quantity: int
    grading_company: str
    submission_name: str | None
    submission_status: str
    declared_value_jpy: int | None
    grading_fee_jpy: int | None
    shipping_fee_jpy: int | None
    insurance_fee_jpy: int | None
    other_fee_jpy: int | None
    total_cost_jpy: int | None
    submitted_at: date | None
    received_at: date | None
    expected_return_date: date | None
    tracking_number: str | None
    final_grade: str | None
    cert_number: str | None
    graded_value_jpy: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class GradingSubmissionCreateIn(BaseModel):
    collection_item_id: int
    grading_company: str = Field(min_length=1)
    submission_name: str | None = None
    submission_status: GradingSubmissionStatus = "planned"
    declared_value_jpy: int | None = Field(default=None, ge=0)
    grading_fee_jpy: int | None = Field(default=None, ge=0)
    shipping_fee_jpy: int | None = Field(default=None, ge=0)
    insurance_fee_jpy: int | None = Field(default=None, ge=0)
    other_fee_jpy: int | None = Field(default=None, ge=0)
    submitted_at: date | None = None
    received_at: date | None = None
    expected_return_date: date | None = None
    tracking_number: str | None = None
    final_grade: str | None = None
    cert_number: str | None = None
    graded_value_jpy: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator("grading_company")
    @classmethod
    def _company_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("grading_company must not be blank")
        return cleaned


class GradingSubmissionUpdateIn(BaseModel):
    collection_item_id: int | None = None
    grading_company: str | None = None
    submission_name: str | None = None
    submission_status: GradingSubmissionStatus | None = None
    declared_value_jpy: int | None = Field(default=None, ge=0)
    grading_fee_jpy: int | None = Field(default=None, ge=0)
    shipping_fee_jpy: int | None = Field(default=None, ge=0)
    insurance_fee_jpy: int | None = Field(default=None, ge=0)
    other_fee_jpy: int | None = Field(default=None, ge=0)
    submitted_at: date | None = None
    received_at: date | None = None
    expected_return_date: date | None = None
    tracking_number: str | None = None
    final_grade: str | None = None
    cert_number: str | None = None
    graded_value_jpy: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator("grading_company")
    @classmethod
    def _company_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("grading_company must not be blank")
        return cleaned


class GradingSubmissionListOut(BaseModel):
    items: list[GradingSubmissionOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class GradingSummaryOut(BaseModel):
    total_submissions: int
    by_status: dict[str, int]
    total_declared_value_jpy: int
    total_grading_cost_jpy: int
    total_graded_value_jpy: int
    total_unrealized_gain_after_grading_jpy: int
    average_grade: float | None
    items_waiting_return: int


class GradingInfoOut(BaseModel):
    has_grading_submission: bool
    latest_status: str | None
    grading_company: str | None
    final_grade: str | None
    total_grading_cost_jpy: int | None
    graded_value_jpy: int | None


CollectionItemStatus = Literal["hold", "watch", "sell", "sold", "grading"]


class CollectionItemOut(BaseModel):
    id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    quantity: int
    condition_label: str | None
    purchase_price_jpy: int | None
    purchase_date: date | None
    purchase_source: str | None
    target_sell_price_jpy: int | None
    notes: str | None
    status: str
    tags: list[CollectorTagOut] = []
    groups: list[CollectorGroupOut] = []
    grading_submissions: list[GradingSubmissionOut] = []
    latest_grading_status: str | None = None
    created_at: datetime
    updated_at: datetime


class CollectionItemListOut(BaseModel):
    items: list[CollectionItemOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class CollectionItemCreateIn(BaseModel):
    card_id: int
    quantity: int = Field(default=1, ge=1)
    condition_label: str | None = None
    purchase_price_jpy: int | None = Field(default=None, ge=0)
    purchase_date: date | None = None
    purchase_source: str | None = None
    target_sell_price_jpy: int | None = Field(default=None, ge=0)
    notes: str | None = None
    status: CollectionItemStatus = "hold"


class CollectionItemUpdateIn(BaseModel):
    card_id: int | None = None
    quantity: int | None = Field(default=None, ge=1)
    condition_label: str | None = None
    purchase_price_jpy: int | None = Field(default=None, ge=0)
    purchase_date: date | None = None
    purchase_source: str | None = None
    target_sell_price_jpy: int | None = Field(default=None, ge=0)
    notes: str | None = None
    status: CollectionItemStatus | None = None


class CollectionImportRowErrorOut(BaseModel):
    row_number: int
    card_code: str | None
    error: str


class CollectionImportPreviewRowOut(BaseModel):
    row_number: int
    card_code: str
    matched_card_id: int
    action: str
    quantity: int
    status: str
    tags: list[str] = []
    groups: list[str] = []


class CollectionImportSummaryOut(BaseModel):
    total_rows: int
    valid_rows: int
    error_rows: int
    created: int
    updated: int
    skipped: int


class CollectionImportResponseOut(BaseModel):
    dry_run: bool
    mode: str
    summary: CollectionImportSummaryOut
    errors: list[CollectionImportRowErrorOut]
    preview: list[CollectionImportPreviewRowOut]
    tags_created: list[str] = []
    groups_created: list[str] = []


class CollectionSummaryOut(BaseModel):
    total_items: int
    total_quantity: int
    total_cost_basis_jpy: int
    items_with_purchase_price: int
    items_missing_purchase_price: int
    items_by_status: dict[str, int]


class YuyuteiPriceSnapshotOut(BaseModel):
    price_jpy: int
    observed_at: datetime


class SnkrdunkFloorSnapshotOut(BaseModel):
    price_jpy: int
    observed_at: datetime
    listing_count: int | None
    condition_label: str | None


class ValuationLatestPricesOut(BaseModel):
    yuyutei_sell: YuyuteiPriceSnapshotOut | None
    yuyutei_buy: YuyuteiPriceSnapshotOut | None
    snkrdunk_floor: SnkrdunkFloorSnapshotOut | None


class ValuationDetailOut(BaseModel):
    retail_value_jpy: int | None
    liquidation_value_jpy: int | None
    market_floor_value_jpy: int | None
    pnl_vs_retail_jpy: int | None
    pnl_vs_retail_pct: float | None
    pnl_vs_liquidation_jpy: int | None
    pnl_vs_liquidation_pct: float | None
    pnl_vs_market_floor_jpy: int | None
    pnl_vs_market_floor_pct: float | None


class ValuationFlagsOut(BaseModel):
    missing_yuyutei_sell: bool
    missing_yuyutei_buy: bool
    missing_snkrdunk_floor: bool
    missing_cost_basis: bool
    above_target_sell: bool


ValuationMode = Literal["raw_market", "graded_adjusted"]


class GradedAdjustedValuationOut(BaseModel):
    value_jpy: int | None
    basis: str | None
    grading_submission_id: int | None
    grading_company: str | None
    final_grade: str | None
    graded_value_jpy: int | None
    raw_fallback_basis: str | None
    pnl_jpy: int | None
    pnl_pct: float | None


class PortfolioValuationItemOut(BaseModel):
    collection_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    quantity: int
    condition_label: str | None
    purchase_price_jpy: int | None
    cost_basis_jpy: int | None
    target_sell_price_jpy: int | None
    latest_prices: ValuationLatestPricesOut
    valuations: ValuationDetailOut
    flags: ValuationFlagsOut
    tags: list[CollectorTagOut] = []
    groups: list[CollectorGroupOut] = []
    grading: GradingInfoOut
    graded_adjusted: GradedAdjustedValuationOut


class BestWorstPerformerOut(BaseModel):
    collection_item_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    pnl_jpy: int
    pnl_pct: float | None
    basis: str


class RetailLiquidationGapOut(BaseModel):
    collection_item_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    gap_jpy: int
    gap_pct: float | None


class HighestValueItemOut(BaseModel):
    collection_item_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    value_jpy: int
    basis: str


class PortfolioValuationInsightsOut(BaseModel):
    best_performing_item: BestWorstPerformerOut | None
    worst_performing_item: BestWorstPerformerOut | None
    largest_retail_liquidation_gap: RetailLiquidationGapOut | None
    highest_value_item: HighestValueItemOut | None


class PortfolioValuationSummaryOut(BaseModel):
    total_items: int
    total_quantity: int
    total_cost_basis_jpy: int
    retail_value_jpy: int
    liquidation_value_jpy: int
    market_floor_value_jpy: int
    pnl_vs_retail_jpy: int
    pnl_vs_retail_pct: float
    pnl_vs_liquidation_jpy: int
    pnl_vs_liquidation_pct: float
    pnl_vs_market_floor_jpy: int
    pnl_vs_market_floor_pct: float
    items_missing_yuyutei_sell: int
    items_missing_yuyutei_buy: int
    items_missing_snkrdunk_floor: int
    items_missing_cost_basis: int
    cards_above_target_sell: int
    insights: PortfolioValuationInsightsOut
    valuation_mode: ValuationMode
    graded_adjusted_value_jpy: int
    pnl_vs_graded_adjusted_jpy: int
    pnl_vs_graded_adjusted_pct: float
    items_using_graded_value: int
    items_using_raw_fallback: int
    items_missing_graded_adjusted_value: int


class PortfolioValuationOut(BaseModel):
    summary: PortfolioValuationSummaryOut
    items: list[PortfolioValuationItemOut]


class PortfolioValuationSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    total_items: int
    total_quantity: int
    total_cost_basis_jpy: int | None
    retail_value_jpy: int | None
    liquidation_value_jpy: int | None
    market_floor_value_jpy: int | None
    pnl_vs_retail_jpy: int | None
    pnl_vs_liquidation_jpy: int | None
    pnl_vs_market_floor_jpy: int | None
    items_missing_yuyutei_sell: int
    items_missing_yuyutei_buy: int
    items_missing_snkrdunk_floor: int
    items_missing_cost_basis: int
    cards_above_target_sell: int
    graded_adjusted_value_jpy: int | None
    pnl_vs_graded_adjusted_jpy: int | None
    items_using_graded_value: int | None
    items_using_raw_fallback: int | None
    items_missing_graded_adjusted_value: int | None


class CollectionAnalyticsSummaryOut(BaseModel):
    total_items: int
    total_quantity: int
    total_cost_basis_jpy: int
    raw_market_floor_value_jpy: int
    graded_adjusted_value_jpy: int
    unrealized_pnl_jpy: int
    unrealized_pnl_pct: float
    items_missing_cost_basis: int
    items_missing_market_price: int
    owned_unique_cards: int
    wishlist_unique_cards: int
    grading_active_count: int


class CollectionAnalyticsBreakdownItemOut(BaseModel):
    key: str
    label: str
    item_count: int
    quantity: int
    cost_basis_jpy: int
    value_jpy: int
    pnl_jpy: int
    pnl_pct: float | None
    portfolio_weight_pct: float


class CollectionAnalyticsBreakdownsOut(BaseModel):
    by_set: list[CollectionAnalyticsBreakdownItemOut]
    by_rarity: list[CollectionAnalyticsBreakdownItemOut]
    by_variant: list[CollectionAnalyticsBreakdownItemOut]
    by_language: list[CollectionAnalyticsBreakdownItemOut]
    by_status: list[CollectionAnalyticsBreakdownItemOut]
    by_tag: list[CollectionAnalyticsBreakdownItemOut]
    by_group: list[CollectionAnalyticsBreakdownItemOut]
    by_grading_status: list[CollectionAnalyticsBreakdownItemOut]


class CollectionAnalyticsTopCardOut(BaseModel):
    collection_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    quantity: int
    value_jpy: int
    portfolio_weight_pct: float


class CollectionAnalyticsConcentrationOut(BaseModel):
    top_5_cards_by_value: list[CollectionAnalyticsTopCardOut]
    top_10_cards_value_pct: float
    largest_single_card_value_pct: float
    largest_set_exposure: CollectionAnalyticsBreakdownItemOut | None
    largest_rarity_exposure: CollectionAnalyticsBreakdownItemOut | None


class CollectionAnalyticsHighestCostBasisItemOut(BaseModel):
    collection_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    purchase_price_jpy: int | None
    quantity: int
    cost_basis_jpy: int
    status: str


class CollectionAnalyticsCostBasisOut(BaseModel):
    items_with_cost_basis: int
    items_without_cost_basis: int
    average_cost_basis_jpy: int
    median_cost_basis_jpy: int
    highest_cost_basis_items: list[CollectionAnalyticsHighestCostBasisItemOut]


class CollectionAnalyticsValuationQualityOut(BaseModel):
    items_with_yuyutei_sell: int
    items_with_yuyutei_buy: int
    items_with_snkrdunk_floor: int
    items_using_graded_value: int
    items_using_raw_fallback: int
    coverage_pct: float


class CollectionAnalyticsOut(BaseModel):
    summary: CollectionAnalyticsSummaryOut
    breakdowns: CollectionAnalyticsBreakdownsOut
    concentration: CollectionAnalyticsConcentrationOut
    cost_basis: CollectionAnalyticsCostBasisOut
    valuation_quality: CollectionAnalyticsValuationQualityOut


class CardAuditIssueOut(BaseModel):
    issue_type: str
    severity: str
    card_ids: list[int]
    card_code: str | None = None
    message: str
    suggested_action: str
    details: dict[str, Any] | None = None


class CardAuditSummaryOut(BaseModel):
    total_cards: int
    total_issues: int
    critical_issues: int
    warning_issues: int


# --- catalog coverage --------------------------------------------------
# Defined before CardAuditReportOut (below) since that model embeds
# CatalogCoverageSummaryOut directly - pydantic resolves annotations against
# the module's globals at class-definition time, so the referenced class
# must already exist rather than relying on a forward-reference string.


class CatalogCoverageSummaryOut(BaseModel):
    total_cards: int
    active_cards: int
    inactive_merged_cards: int
    sets_count: int
    cards_with_yuyutei_mapping: int
    cards_with_snkrdunk_mapping: int
    cards_without_any_mapping: int
    cards_with_recent_yuyutei_price: int
    cards_with_recent_snkrdunk_price: int
    cards_without_recent_price: int
    cards_in_collection: int
    cards_on_wishlist: int
    cards_with_missing_metadata: int
    cards_with_duplicate_risk: int
    cards_with_mapping_quality_risk: int
    metadata_completion_pct: float
    mapping_coverage_pct: float
    recent_price_coverage_pct: float


class CardAuditReportOut(BaseModel):
    summary: CardAuditSummaryOut
    issues: list[CardAuditIssueOut]
    catalog_coverage: CatalogCoverageSummaryOut | None = None


class CatalogCoverageBreakdownItemOut(BaseModel):
    key: str
    label: str
    total_cards: int
    active_cards: int
    mapped_cards: int
    unmapped_cards: int
    recent_price_cards: int
    collection_cards: int
    wishlist_cards: int
    missing_metadata_cards: int
    duplicate_risk_cards: int
    mapping_quality_risk_cards: int
    mapping_coverage_pct: float
    recent_price_coverage_pct: float
    metadata_completion_pct: float


class CatalogCoverageGapItemOut(BaseModel):
    card_id: int
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    language: str | None
    issue_types: list[str]
    severity: str
    suggested_action: str


class CatalogCoverageReportOut(BaseModel):
    summary: CatalogCoverageSummaryOut
    coverage_by_set: list[CatalogCoverageBreakdownItemOut]
    coverage_by_rarity: list[CatalogCoverageBreakdownItemOut]
    coverage_by_variant: list[CatalogCoverageBreakdownItemOut]
    coverage_by_language: list[CatalogCoverageBreakdownItemOut]
    metadata_gaps: list[CatalogCoverageGapItemOut]
    mapping_gaps: list[CatalogCoverageGapItemOut]
    price_gaps: list[CatalogCoverageGapItemOut]
    duplicate_risks: list[CatalogCoverageGapItemOut]
    mapping_quality_risks: list[CatalogCoverageGapItemOut]
    # Loosely-typed (not PriceSourceHealthSummaryOut, defined later in this
    # file) rather than reordering every catalog-coverage schema above this
    # one - see app.services.catalog_coverage's price_source_health field,
    # populated from app.services.price_source_health.summarize_price_source_health.
    price_source_health: dict[str, Any] | None = None


class CatalogCoverageGapsOut(BaseModel):
    gap_type: str
    items: list[CatalogCoverageGapItemOut]
    pagination: PaginationMeta


# --- price source health -------------------------------------------------


class PriceSourceHealthSummaryOut(BaseModel):
    sources_count: int
    active_sources_count: int
    total_active_mappings: int
    mappings_with_recent_price: int
    mappings_without_recent_price: int
    stale_price_count: int
    missing_price_count: int
    last_successful_refresh_at: datetime | None
    last_failed_refresh_at: datetime | None
    recent_refresh_success_rate_pct: float
    blocked_source_count: int
    error_source_count: int


class SourceHealthItemOut(BaseModel):
    source_id: int
    source_name: str
    active_mapping_count: int
    recent_price_count: int
    stale_price_count: int
    missing_price_count: int
    latest_price_observed_at: datetime | None
    latest_refresh_status: str | None
    latest_refresh_started_at: datetime | None
    latest_refresh_finished_at: datetime | None
    recent_refresh_success_rate_pct: float
    average_refresh_duration_seconds: float | None
    blocked_count_7d: int
    error_count_7d: int
    health_status: str
    warnings: list[str]


class HealthCoverageBreakdownItemOut(BaseModel):
    key: str
    label: str
    mapped_cards: int
    recent_price_cards: int
    stale_price_cards: int
    missing_price_cards: int
    coverage_pct: float


class PriceGapItemOut(BaseModel):
    mapping_id: int
    card_id: int
    card_code: str | None
    name_en: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    language: str | None
    source_name: str
    source_url: str | None
    latest_price_observed_at: datetime | None
    latest_price_type: str | None
    latest_price_jpy: int | None
    issue_type: str
    severity: str
    suggested_action: str


class RefreshRunSummaryItemOut(BaseModel):
    id: int
    status: str
    source_filter: str | None
    started_at: datetime
    finished_at: datetime | None
    dry_run: bool
    mappings_checked: int
    mappings_failed: int
    error_message: str | None


class PriceSourceHealthReportOut(BaseModel):
    summary: PriceSourceHealthSummaryOut
    sources: list[SourceHealthItemOut]
    coverage_by_set: list[HealthCoverageBreakdownItemOut]
    coverage_by_rarity: list[HealthCoverageBreakdownItemOut]
    stale_prices: list[PriceGapItemOut]
    missing_prices: list[PriceGapItemOut]
    refresh_runs: list[RefreshRunSummaryItemOut]
    warnings: list[str]


class PriceSourceHealthGapsOut(BaseModel):
    gap_type: str
    items: list[PriceGapItemOut]
    pagination: PaginationMeta


class CardCatalogImportRowErrorOut(BaseModel):
    row_number: int
    card_code: str | None
    error: str


class CardCatalogFieldChangeOut(BaseModel):
    old: Any | None
    new: Any | None


class CardCatalogImportPreviewItemOut(BaseModel):
    row_number: int
    card_code: str
    action: str
    changes: dict[str, CardCatalogFieldChangeOut]


class CardCatalogImportSummaryOut(BaseModel):
    total_rows: int
    valid_rows: int
    error_rows: int
    created: int
    updated: int
    skipped: int


class CardCatalogImportResponseOut(BaseModel):
    dry_run: bool
    overwrite: bool
    summary: CardCatalogImportSummaryOut
    errors: list[CardCatalogImportRowErrorOut]
    preview: list[CardCatalogImportPreviewItemOut]


class CardImageImportRowErrorOut(BaseModel):
    row_number: int
    card_code: str | None
    error: str


class CardImageImportPreviewItemOut(BaseModel):
    row_number: int
    card_code: str
    card_id: int
    action: str
    image_url: str
    image_source: str


class CardImageImportSummaryOut(BaseModel):
    total_rows: int
    valid_rows: int
    error_rows: int
    applied: int


class CardImageImportResponseOut(BaseModel):
    dry_run: bool
    summary: CardImageImportSummaryOut
    errors: list[CardImageImportRowErrorOut]
    preview: list[CardImageImportPreviewItemOut]


class AdminCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    image_url: str | None
    image_source: str | None
    image_source_url: str | None
    image_last_verified_at: datetime | None
    image_status: str | None
    release_date: date | None
    artist: str | None
    character: str | None
    color: str | None
    card_type: str | None
    cost: int | None
    power: int | None
    counter: int | None
    attribute: str | None
    effect_text: str | None
    trigger_text: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class AdminCardListSummaryOut(BaseModel):
    total_cards: int
    missing_metadata_count: int
    by_set: dict[str, int]
    by_rarity: dict[str, int]


class AdminCardListResponseOut(BaseModel):
    summary: AdminCardListSummaryOut
    cards: list[AdminCardOut]
    pagination: PaginationMeta


# --- card identity merge / duplicate review -----------------------------


class DuplicateCardSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    is_active: bool
    merged_into_card_id: int | None


class DuplicateExplanationOut(BaseModel):
    positive: list[str]
    negative: list[str]
    caps_applied: list[str]


class DuplicatePairOut(BaseModel):
    source_card: DuplicateCardSummaryOut
    target_card: DuplicateCardSummaryOut
    score: int
    confidence_label: str
    explanation: DuplicateExplanationOut
    recommended_target_card_id: int
    warnings: list[str]


class DuplicateSummaryOut(BaseModel):
    total_pairs: int
    exact_duplicate_count: int
    likely_duplicate_count: int
    possible_duplicate_count: int
    weak_match_count: int
    inactive_merged_cards: int


class DuplicateListOut(BaseModel):
    summary: DuplicateSummaryOut
    pairs: list[DuplicatePairOut]
    pagination: PaginationMeta


class BulkDuplicatePreviewIn(BaseModel):
    min_score: int = 90
    confidence_label: str | None = "exact_duplicate"
    limit: int = 50


class FieldMergePreviewEntryOut(BaseModel):
    source: Any = None
    target: Any = None
    result: Any = None
    action: str


class CardMergePreviewOut(BaseModel):
    source_card: DuplicateCardSummaryOut
    target_card: DuplicateCardSummaryOut
    duplicate_score: int
    confidence_label: str
    explanation: DuplicateExplanationOut
    field_merge_preview: dict[str, FieldMergePreviewEntryOut]
    affected_records: dict[str, int]
    warnings: list[str]


class BulkDuplicatePreviewOut(BaseModel):
    previews: list[CardMergePreviewOut]


class CardMergeIn(BaseModel):
    source_card_id: int
    target_card_id: int
    dry_run: bool = True
    merge_notes: str | None = None
    field_strategy: str = "keep_target"
    approve_low_confidence: bool = False


class CardMergeResultOut(BaseModel):
    dry_run: bool
    merged: bool
    source_card_id: int
    target_card_id: int
    affected_records: dict[str, int]
    field_changes: dict[str, Any]
    warnings: list[str]
    duplicate_score: int
    confidence_label: str


class MarketSignalLatestPricesOut(BaseModel):
    yuyutei_sell: int | None
    yuyutei_buy: int | None
    snkrdunk_floor: int | None


class MarketSignalMetricsOut(BaseModel):
    change_pct: float | None
    spread_pct: float | None
    gap_pct: float | None
    gap_jpy: int | None


class MarketSignalOut(BaseModel):
    signal_type: str
    severity: str
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    owned_quantity: int
    collection_item_id: int | None = None
    latest_prices: MarketSignalLatestPricesOut
    metrics: MarketSignalMetricsOut
    message: str
    suggested_action: str


class MarketSignalsSummaryOut(BaseModel):
    total_signals: int
    by_signal_type: dict[str, int]
    owned_signal_count: int
    market_signal_count: int
    data_quality_signal_count: int


class MarketSignalsResponseOut(BaseModel):
    summary: MarketSignalsSummaryOut
    signals: list[MarketSignalOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class MarketSignalEventOut(BaseModel):
    id: int
    signal_type: str
    status: str
    severity: str
    suggested_action: str | None
    card_id: int | None
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    language: str | None
    collection_item_id: int | None
    owned_quantity: int
    message: str | None
    notes: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    seen_count: int
    last_payload: dict[str, Any] | None
    dismissed_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MarketSignalEventsSummaryOut(BaseModel):
    total_events: int
    open_events: int
    watching_events: int
    dismissed_events: int
    resolved_events: int
    by_signal_type: dict[str, int]
    by_suggested_action: dict[str, int]


class MarketSignalEventListOut(BaseModel):
    summary: MarketSignalEventsSummaryOut
    events: list[MarketSignalEventOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class MarketSignalEventUpdateIn(BaseModel):
    status: str | None = None
    notes: str | None = None


class OpportunitiesSummaryOut(BaseModel):
    total_opportunities: int
    average_score: float
    highest_score: int
    by_category: dict[str, int]
    wishlist_target_hit_count: int = 0


class OpportunityOut(BaseModel):
    score: int
    category: str
    event_id: int
    signal_type: str
    status: str
    severity: str
    suggested_action: str | None
    card_id: int | None
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    language: str | None
    owned_quantity: int
    message: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    seen_count: int
    score_reasons: list[str]
    last_payload: dict[str, Any] | None
    tags: list[CollectorTagOut] = []
    groups: list[CollectorGroupOut] = []
    grading: GradingInfoOut
    wishlist_item_id: int | None = None
    wishlist_priority: str | None = None
    wishlist_target_buy_price_jpy: int | None = None
    wishlist_target_hit: bool = False


class OpportunitiesResponseOut(BaseModel):
    summary: OpportunitiesSummaryOut
    opportunities: list[OpportunityOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class MarketReportPortfolioSnapshotOut(BaseModel):
    total_cost_basis_jpy: int | None
    retail_value_jpy: int | None
    liquidation_value_jpy: int | None
    market_floor_value_jpy: int | None
    pnl_vs_market_floor_jpy: int | None
    pnl_vs_market_floor_pct: float | None
    items_missing_cost_basis: int
    items_missing_prices: int
    graded_adjusted_value_jpy: int | None


class MarketReportOpportunitySummaryOut(BaseModel):
    total_opportunities: int
    highest_score: int | None
    average_score: float | None
    by_category: dict[str, int]
    wishlist_target_hit_count: int = 0


class MarketReportTopOpportunitiesOut(BaseModel):
    top_5: list[OpportunityOut]
    top_buy: OpportunityOut | None
    top_sell: OpportunityOut | None
    top_momentum: OpportunityOut | None
    top_drop: OpportunityOut | None
    top_owned: OpportunityOut | None
    top_data_quality: OpportunityOut | None


class MarketReportCollectionQualityOut(BaseModel):
    missing_purchase_price_count: int
    missing_condition_count: int
    missing_target_sell_count: int
    total_quality_issues: int


class MarketReportSignalEventSummaryOut(BaseModel):
    open_events: int
    watching_events: int
    dismissed_events: int
    resolved_events: int
    most_common_signal_type: str | None
    most_common_suggested_action: str | None


class MarketReportSummaryOut(BaseModel):
    total_opportunities: int
    highest_score: int | None
    average_score: float | None


class MarketReportPayloadOut(BaseModel):
    summary: MarketReportSummaryOut
    portfolio_snapshot: MarketReportPortfolioSnapshotOut
    opportunity_summary: MarketReportOpportunitySummaryOut
    top_opportunities: MarketReportTopOpportunitiesOut
    collection_quality: MarketReportCollectionQualityOut
    signal_event_summary: MarketReportSignalEventSummaryOut
    deterministic_summary_lines: list[str]


class MarketIntelligenceReportOut(BaseModel):
    id: int
    created_at: datetime
    report_date: date
    summary: MarketReportSummaryOut
    portfolio_snapshot: MarketReportPortfolioSnapshotOut
    opportunity_summary: MarketReportOpportunitySummaryOut
    top_opportunities: MarketReportTopOpportunitiesOut
    collection_quality: MarketReportCollectionQualityOut
    signal_event_summary: MarketReportSignalEventSummaryOut
    deterministic_summary_lines: list[str]
    payload: dict[str, Any]


class MarketIntelligenceReportSummaryOut(BaseModel):
    id: int
    created_at: datetime
    report_date: date
    total_opportunities: int
    highest_score: int | None
    average_score: float | None
    buy_opportunities_count: int
    sell_opportunities_count: int
    momentum_count: int
    drop_count: int
    data_quality_count: int
    owned_count: int
    portfolio_market_floor_value_jpy: int | None
    portfolio_retail_value_jpy: int | None
    portfolio_liquidation_value_jpy: int | None
    portfolio_pnl_vs_market_floor_jpy: int | None


class MarketIntelligenceReportListOut(BaseModel):
    reports: list[MarketIntelligenceReportSummaryOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class BackupValidateResponseOut(BaseModel):
    valid: bool
    backup_version: int | None
    summary: dict[str, int]
    warnings: list[str]
    errors: list[str]


class BackupRestoreResponseOut(BaseModel):
    dry_run: bool
    mode: str
    valid: bool
    backup_version: int | None
    summary: dict[str, dict[str, int]]
    warnings: list[str]
    errors: list[str]
    preview: dict[str, dict[str, int]]


class AdminRefreshPricesRequest(BaseModel):
    source: str = "all"
    limit: int | None = Field(default=None, ge=1)
    dry_run: bool = False


class AdminRefreshPricesResponse(BaseModel):
    run_id: int | None
    job_id: str | None
    status: str | None
    warnings: list[str] = []


class AdminSnapshotPortfolioResponse(BaseModel):
    snapshot_id: int


class AdminSnapshotMarketSignalsResponse(BaseModel):
    created_count: int
    updated_count: int
    resolved_count: int


class AdminGenerateMarketReportResponse(BaseModel):
    report_id: int


class AdminFullMarketRefreshRequest(BaseModel):
    source: str = "all"
    limit: int | None = Field(default=None, ge=1)
    dry_run: bool = False


class AdminMarketSignalSnapshotCounts(BaseModel):
    created: int
    updated: int
    resolved: int


class AdminFullMarketRefreshResponse(BaseModel):
    price_refresh_run_id: int | None
    portfolio_snapshot_id: int | None
    market_signal_snapshot: AdminMarketSignalSnapshotCounts
    market_report_id: int | None
    dry_run: bool
    warnings: list[str] = []


class AdminSendMarketReportDigestRequest(BaseModel):
    dry_run: bool = False
    force: bool = False


class AdminSendMarketReportDigestResponse(BaseModel):
    report_id: int | None
    status: str | None
    sent: bool
    skipped_reason: str | None
    message_preview: str | None


class MarketWorkflowRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    source: str
    limit: int | None
    send_telegram: bool
    price_refresh_run_id: int | None
    portfolio_snapshot_id: int | None
    market_report_id: int | None
    signal_events_created: int
    signal_events_updated: int
    signal_events_resolved: int
    telegram_digest_status: str | None
    warnings: list[str]
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class MarketWorkflowRunListOut(BaseModel):
    items: list[MarketWorkflowRunOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class AdminRunMarketWorkflowRequest(BaseModel):
    source: str = "yuyutei"
    limit: int | None = Field(default=None, ge=1)
    send_telegram: bool = False
    dry_run: bool = False


class AdminRunMarketWorkflowResponse(BaseModel):
    market_workflow_run_id: int | None
    status: str | None
    price_refresh_run_id: int | None
    portfolio_snapshot_id: int | None
    market_signal_snapshot: AdminMarketSignalSnapshotCounts
    market_report_id: int | None
    telegram_digest_status: str | None
    warnings: list[str] = []


# --- Wishlist / acquisition tracker -----------------------------------------

WishlistPriority = Literal["low", "medium", "high", "grail"]
WishlistStatus = Literal["watching", "target_hit", "purchased", "passed", "removed"]


class WishlistLatestPricesOut(BaseModel):
    yuyutei_sell: int | None
    yuyutei_buy: int | None
    snkrdunk_floor: int | None


class WishlistItemOut(BaseModel):
    id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    priority: str
    status: str
    target_buy_price_jpy: int | None
    max_buy_price_jpy: int | None
    preferred_condition: str | None
    preferred_source: str | None
    desired_quantity: int
    acquired_quantity: int
    acquired_collection_item_id: int | None
    notes: str | None
    owned_quantity: int
    latest_prices: WishlistLatestPricesOut
    preferred_current_price_jpy: int | None
    preferred_current_price_source: str | None
    target_hit: bool
    gap_to_target_jpy: int | None
    gap_to_target_pct: float | None
    tags: list[CollectorTagOut] = []
    created_at: datetime
    updated_at: datetime


class WishlistItemListOut(BaseModel):
    items: list[WishlistItemOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class WishlistItemCreateIn(BaseModel):
    card_id: int
    priority: WishlistPriority = "medium"
    target_buy_price_jpy: int | None = Field(default=None, ge=0)
    max_buy_price_jpy: int | None = Field(default=None, ge=0)
    preferred_condition: str | None = None
    preferred_source: str | None = None
    desired_quantity: int = Field(default=1, ge=1)
    notes: str | None = None


class WishlistItemUpdateIn(BaseModel):
    priority: WishlistPriority | None = None
    status: WishlistStatus | None = None
    target_buy_price_jpy: int | None = Field(default=None, ge=0)
    max_buy_price_jpy: int | None = Field(default=None, ge=0)
    preferred_condition: str | None = None
    preferred_source: str | None = None
    desired_quantity: int | None = Field(default=None, ge=1)
    notes: str | None = None


class WishlistMarkPurchasedIn(BaseModel):
    collection_item_id: int
    acquired_quantity: int = Field(default=1, ge=1)


class WishlistConvertToCollectionIn(BaseModel):
    quantity: int = Field(default=1, ge=1)
    condition_label: str | None = None
    purchase_price_jpy: int | None = Field(default=None, ge=0)
    purchase_date: date | None = None
    purchase_source: str | None = None
    target_sell_price_jpy: int | None = Field(default=None, ge=0)
    status: CollectionItemStatus = "hold"
    notes: str | None = None


class WishlistConvertToCollectionOut(BaseModel):
    wishlist_item: WishlistItemOut
    collection_item: CollectionItemOut


class WishlistSummaryOut(BaseModel):
    total_wishlist_items: int
    watching: int
    target_hit: int
    purchased: int
    passed: int
    removed: int
    grail_count: int
    high_priority_count: int
    total_target_budget_jpy: int
    total_max_budget_jpy: int
    items_owned_already: int
    items_with_target_hit: int


class WishlistAnalyticsSummaryOut(BaseModel):
    total_items: int
    watching_count: int
    target_hit_count: int
    purchased_count: int
    passed_count: int
    grail_count: int
    high_priority_count: int
    owned_already_count: int
    total_target_budget_jpy: int
    total_max_budget_jpy: int
    total_current_price_jpy: int
    budget_gap_to_target_jpy: int
    budget_gap_to_max_jpy: int
    average_target_price_jpy: int
    median_target_price_jpy: int


class WishlistAnalyticsBreakdownItemOut(BaseModel):
    key: str
    label: str
    item_count: int
    desired_quantity: int
    target_budget_jpy: int
    max_budget_jpy: int
    current_price_jpy: int
    target_hit_count: int
    owned_count: int
    budget_weight_pct: float


class WishlistAnalyticsBreakdownsOut(BaseModel):
    by_priority: list[WishlistAnalyticsBreakdownItemOut]
    by_status: list[WishlistAnalyticsBreakdownItemOut]
    by_set: list[WishlistAnalyticsBreakdownItemOut]
    by_rarity: list[WishlistAnalyticsBreakdownItemOut]
    by_preferred_source: list[WishlistAnalyticsBreakdownItemOut]
    by_preferred_condition: list[WishlistAnalyticsBreakdownItemOut]


class WishlistAnalyticsTargetItemOut(BaseModel):
    wishlist_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    priority: str
    status: str
    desired_quantity: int
    owned_quantity: int
    target_buy_price_jpy: int | None
    max_buy_price_jpy: int | None
    preferred_current_price_jpy: int | None
    preferred_current_price_source: str | None
    target_hit: bool
    gap_to_target_jpy: int | None
    gap_to_target_pct: float | None


class WishlistAnalyticsBudgetPlanOut(BaseModel):
    grail_targets: list[WishlistAnalyticsTargetItemOut]
    high_priority_targets: list[WishlistAnalyticsTargetItemOut]
    best_gap_to_target: list[WishlistAnalyticsTargetItemOut]
    largest_budget_items: list[WishlistAnalyticsTargetItemOut]
    already_owned: list[WishlistAnalyticsTargetItemOut]


class WishlistAnalyticsPriceCoverageOut(BaseModel):
    items_with_current_price: int
    items_missing_current_price: int
    coverage_pct: float


class WishlistAnalyticsOut(BaseModel):
    summary: WishlistAnalyticsSummaryOut
    breakdowns: WishlistAnalyticsBreakdownsOut
    target_hits: list[WishlistAnalyticsTargetItemOut]
    budget_plan: WishlistAnalyticsBudgetPlanOut
    price_coverage: WishlistAnalyticsPriceCoverageOut


SellDecisionAction = Literal["review_sell", "hold", "grade_first", "missing_data", "monitor"]


class SellDecisionSummaryOut(BaseModel):
    total_candidates: int
    review_sell_count: int
    hold_count: int
    grade_first_count: int
    missing_data_count: int
    monitor_count: int
    total_potential_sale_value_jpy: int
    total_unrealized_pnl_jpy: int
    average_score: float


class SellDecisionLatestPricesOut(BaseModel):
    yuyutei_sell: int | None
    yuyutei_buy: int | None
    snkrdunk_floor: int | None


class SellDecisionMarketContextOut(BaseModel):
    yuyutei_spread_pct: float | None
    snkrdunk_vs_yuyutei_sell_gap_pct: float | None
    related_opportunity_score: int | None
    related_signal_types: list[str]


class SellDecisionGradingOut(BaseModel):
    has_active_grading: bool
    latest_status: str | None
    final_grade: str | None
    graded_value_jpy: int | None


class SellDecisionWishlistOverlapOut(BaseModel):
    is_on_wishlist: bool
    priority: str | None
    status: str | None


class SellDecisionCandidateOut(BaseModel):
    collection_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    quantity: int
    status: str
    condition_label: str | None
    score: int
    recommended_action: SellDecisionAction
    current_value_jpy: int | None
    current_value_basis: str | None
    cost_basis_jpy: int | None
    unrealized_pnl_jpy: int | None
    unrealized_pnl_pct: float | None
    target_sell_price_jpy: int | None
    above_target_sell: bool
    latest_prices: SellDecisionLatestPricesOut
    market_context: SellDecisionMarketContextOut
    grading: SellDecisionGradingOut
    wishlist_overlap: SellDecisionWishlistOverlapOut
    tags: list[str]
    groups: list[str]
    score_reasons: list[str]
    warnings: list[str]


class SellDecisionSupportOut(BaseModel):
    summary: SellDecisionSummaryOut
    candidates: list[SellDecisionCandidateOut]
    limit: int
    offset: int
    pagination: PaginationMeta


BuyDecisionAction = Literal["review_buy", "wait", "skip", "missing_data", "monitor"]
BuySourcePreference = Literal["auto", "snkrdunk", "yuyutei"]
BuyDecisionPriorityFilter = Literal["low", "medium", "high", "grail"]


class BuyDecisionSummaryOut(BaseModel):
    total_candidates: int
    review_buy_count: int
    wait_count: int
    skip_count: int
    missing_data_count: int
    monitor_count: int
    target_hit_count: int
    total_target_budget_jpy: int
    total_current_cost_jpy: int
    budget_gap_jpy: int
    average_score: float


class BuyDecisionLatestPricesOut(BaseModel):
    yuyutei_sell: int | None
    yuyutei_buy: int | None
    snkrdunk_floor: int | None


class BuyDecisionMarketContextOut(BaseModel):
    snkrdunk_vs_yuyutei_sell_gap_pct: float | None
    yuyutei_spread_pct: float | None
    related_opportunity_score: int | None
    related_signal_types: list[str]


class BuyDecisionCandidateOut(BaseModel):
    wishlist_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    language: str
    score: int
    recommended_action: BuyDecisionAction
    priority: str
    status: str
    desired_quantity: int
    owned_quantity: int
    remaining_quantity: int
    target_buy_price_jpy: int | None
    max_buy_price_jpy: int | None
    preferred_condition: str | None
    preferred_source: str | None
    current_price_jpy: int | None
    current_price_source: str | None
    target_hit: bool
    gap_to_target_jpy: int | None
    gap_to_target_pct: float | None
    gap_to_max_jpy: int | None
    gap_to_max_pct: float | None
    latest_prices: BuyDecisionLatestPricesOut
    market_context: BuyDecisionMarketContextOut
    tags: list[str]
    groups: list[str]
    score_reasons: list[str]
    warnings: list[str]


class BuyDecisionSupportOut(BaseModel):
    summary: BuyDecisionSummaryOut
    candidates: list[BuyDecisionCandidateOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class GradingAnalyticsSummaryOut(BaseModel):
    total_submissions: int
    active_submissions: int
    received_submissions: int
    cancelled_submissions: int
    total_declared_value_jpy: int
    total_grading_cost_jpy: int
    total_graded_value_jpy: int
    total_raw_cost_basis_jpy: int
    total_roi_jpy: int
    total_roi_pct: float | None
    average_grade: float | None
    median_grade: float | None
    profitable_count: int
    unprofitable_count: int
    missing_graded_value_count: int
    missing_cost_basis_count: int
    items_waiting_return: int


class GradingAnalyticsBreakdownItemOut(BaseModel):
    key: str
    label: str
    submission_count: int
    received_count: int
    active_count: int
    total_cost_jpy: int
    graded_value_jpy: int
    roi_jpy: int
    roi_pct: float | None


class GradingAnalyticsBreakdownsOut(BaseModel):
    by_status: list[GradingAnalyticsBreakdownItemOut]
    by_company: list[GradingAnalyticsBreakdownItemOut]
    by_grade: list[GradingAnalyticsBreakdownItemOut]
    by_set: list[GradingAnalyticsBreakdownItemOut]
    by_rarity: list[GradingAnalyticsBreakdownItemOut]


class GradingAnalyticsFlagsOut(BaseModel):
    profitable: bool
    missing_cost_basis: bool
    missing_graded_value: bool
    overdue: bool
    active: bool


class GradingAnalyticsSubmissionOut(BaseModel):
    grading_submission_id: int
    collection_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    quantity: int
    grading_company: str
    submission_name: str | None
    submission_status: str
    declared_value_jpy: int | None
    grading_fee_jpy: int | None
    shipping_fee_jpy: int | None
    insurance_fee_jpy: int | None
    other_fee_jpy: int | None
    total_cost_jpy: int
    purchase_price_jpy: int | None
    raw_cost_basis_jpy: int | None
    graded_value_jpy: int | None
    roi_jpy: int | None
    roi_pct: float | None
    submitted_at: date | None
    expected_return_date: date | None
    received_at: date | None
    days_in_grading: int | None
    final_grade: str | None
    cert_number: str | None
    tracking_number: str | None
    notes: str | None
    tags: list[str]
    groups: list[str]
    flags: GradingAnalyticsFlagsOut


class GradingAnalyticsRoiOut(BaseModel):
    best_roi_submissions: list[GradingAnalyticsSubmissionOut]
    worst_roi_submissions: list[GradingAnalyticsSubmissionOut]
    highest_graded_value: list[GradingAnalyticsSubmissionOut]
    highest_grading_cost: list[GradingAnalyticsSubmissionOut]
    missing_value_or_cost: list[GradingAnalyticsSubmissionOut]


class GradingAnalyticsPendingOut(BaseModel):
    waiting_return: list[GradingAnalyticsSubmissionOut]
    overdue: list[GradingAnalyticsSubmissionOut]
    expected_next_30d: list[GradingAnalyticsSubmissionOut]


class GradingAnalyticsOut(BaseModel):
    summary: GradingAnalyticsSummaryOut
    breakdowns: GradingAnalyticsBreakdownsOut
    roi: GradingAnalyticsRoiOut
    pending: GradingAnalyticsPendingOut
    submissions: list[GradingAnalyticsSubmissionOut]
    limit: int
    offset: int
    pagination: PaginationMeta


PortfolioRiskLevel = Literal["low", "medium", "high", "critical"]


class PortfolioRiskSummaryOut(BaseModel):
    risk_score: int
    risk_level: PortfolioRiskLevel
    total_value_jpy: int
    total_cost_basis_jpy: int
    largest_single_card_weight_pct: float
    top_5_weight_pct: float
    top_10_weight_pct: float
    largest_set_weight_pct: float
    largest_rarity_weight_pct: float
    missing_price_count: int
    missing_cost_basis_count: int
    stale_price_count: int
    wide_spread_count: int
    active_grading_count: int
    wishlist_overlap_count: int


class PortfolioRiskCardOut(BaseModel):
    """The spec's generic "related card item shape" - used for concentration's
    top_cards and every data_quality detail list."""

    card_id: int
    collection_item_id: int
    card_code: str
    name_en: str | None
    set_code: str
    rarity: str
    quantity: int
    value_jpy: int | None
    portfolio_weight_pct: float | None
    cost_basis_jpy: int | None
    warnings: list[str] = []


class PortfolioRiskDataQualityCardOut(PortfolioRiskCardOut):
    issue: str
    latest_observed_at: datetime | None
    suggested_action: str


class PortfolioRiskLiquidityCardOut(PortfolioRiskCardOut):
    yuyutei_sell_jpy: int | None
    yuyutei_buy_jpy: int | None
    spread_pct: float | None
    snkrdunk_floor_jpy: int | None
    listing_count: int | None


class PortfolioRiskGradingCardOut(PortfolioRiskCardOut):
    grading_company: str | None
    submission_status: str | None
    grading_cost_jpy: int | None
    expected_return_date: date | None
    overdue: bool


class PortfolioRiskWishlistCardOut(BaseModel):
    wishlist_item_id: int
    card_id: int
    card_code: str
    name_en: str | None
    set_code: str
    rarity: str
    wishlist_priority: str
    wishlist_status: str
    owned_quantity: int
    desired_quantity: int
    suggested_action: str


class PortfolioRiskExposureItemOut(BaseModel):
    key: str
    label: str
    quantity: int
    value_jpy: int
    cost_basis_jpy: int
    portfolio_weight_pct: float
    pnl_jpy: int
    pnl_pct: float | None
    risk_flags: list[str] = []


class PortfolioRiskConcentrationOut(BaseModel):
    score: int
    level: PortfolioRiskLevel
    warnings: list[str]
    top_cards: list[PortfolioRiskCardOut]
    top_sets: list[PortfolioRiskExposureItemOut]
    top_rarities: list[PortfolioRiskExposureItemOut]


class PortfolioRiskDataQualityOut(BaseModel):
    score: int
    level: PortfolioRiskLevel
    warnings: list[str]
    missing_prices: list[PortfolioRiskDataQualityCardOut]
    missing_cost_basis: list[PortfolioRiskDataQualityCardOut]
    stale_prices: list[PortfolioRiskDataQualityCardOut]


class PortfolioRiskLiquidityProxyOut(BaseModel):
    score: int
    level: PortfolioRiskLevel
    warnings: list[str]
    wide_spread_cards: list[PortfolioRiskLiquidityCardOut]
    low_listing_cards: list[PortfolioRiskLiquidityCardOut]


class PortfolioRiskGradingExposureOut(BaseModel):
    score: int
    level: PortfolioRiskLevel
    warnings: list[str]
    active_grading_items: list[PortfolioRiskGradingCardOut]
    high_cost_pending_items: list[PortfolioRiskGradingCardOut]


class PortfolioRiskWishlistOverlapOut(BaseModel):
    score: int
    level: PortfolioRiskLevel
    warnings: list[str]
    owned_wishlist_items: list[PortfolioRiskWishlistCardOut]


class PortfolioRiskBreakdownOut(BaseModel):
    concentration: PortfolioRiskConcentrationOut
    data_quality: PortfolioRiskDataQualityOut
    liquidity_proxy: PortfolioRiskLiquidityProxyOut
    grading_exposure: PortfolioRiskGradingExposureOut
    wishlist_overlap: PortfolioRiskWishlistOverlapOut


class PortfolioRiskExposuresOut(BaseModel):
    by_set: list[PortfolioRiskExposureItemOut]
    by_rarity: list[PortfolioRiskExposureItemOut]
    by_variant: list[PortfolioRiskExposureItemOut]
    by_language: list[PortfolioRiskExposureItemOut]
    by_tag: list[PortfolioRiskExposureItemOut]
    by_group: list[PortfolioRiskExposureItemOut]


PortfolioRiskFlagType = Literal[
    "high_concentration",
    "high_set_concentration",
    "high_rarity_concentration",
    "missing_prices",
    "missing_cost_basis",
    "stale_prices",
    "wide_spread",
    "low_liquidity",
    "grading_exposure",
    "overdue_grading",
    "wishlist_overlap",
]
PortfolioRiskFlagSeverity = Literal["info", "warning", "critical"]
PortfolioRiskSuggestedAction = Literal[
    "review_concentration",
    "fix_missing_prices",
    "fix_cost_basis",
    "review_stale_prices",
    "review_wide_spreads",
    "review_grading_exposure",
    "update_wishlist_status",
    "none",
]


class PortfolioRiskFlagOut(BaseModel):
    flag_type: PortfolioRiskFlagType
    severity: PortfolioRiskFlagSeverity
    message: str
    related_cards: list[str] = []
    suggested_action: PortfolioRiskSuggestedAction


class PortfolioRiskOut(BaseModel):
    summary: PortfolioRiskSummaryOut
    risk_breakdown: PortfolioRiskBreakdownOut
    exposures: PortfolioRiskExposuresOut
    recommendation_flags: list[PortfolioRiskFlagOut]


class AnalyticsDigestSummaryOut(BaseModel):
    valuation_mode: ValuationMode
    generated_at: datetime
    collection_value_jpy: int
    graded_adjusted_value_jpy: int
    portfolio_risk_score: int
    portfolio_risk_level: PortfolioRiskLevel
    wishlist_target_hits: int
    buy_review_count: int
    sell_review_count: int
    grading_roi_jpy: int
    grading_active_count: int
    missing_cost_basis_count: int
    missing_price_count: int


class AnalyticsDigestCollectionSectionOut(BaseModel):
    total_items: int
    total_quantity: int
    total_cost_basis_jpy: int
    raw_market_value_jpy: int
    graded_adjusted_value_jpy: int
    largest_set_exposure: CollectionAnalyticsBreakdownItemOut | None
    largest_rarity_exposure: CollectionAnalyticsBreakdownItemOut | None


class AnalyticsDigestWishlistSectionOut(BaseModel):
    total_items: int
    grail_count: int
    high_priority_count: int
    target_hit_count: int
    total_target_budget_jpy: int
    price_coverage_pct: float


class AnalyticsDigestBuyDecisionsSectionOut(BaseModel):
    review_buy_count: int
    wait_count: int
    missing_data_count: int
    top_review_buy: list[BuyDecisionCandidateOut]


class AnalyticsDigestSellDecisionsSectionOut(BaseModel):
    review_sell_count: int
    grade_first_count: int
    missing_data_count: int
    top_review_sell: list[SellDecisionCandidateOut]


class AnalyticsDigestGradingSectionOut(BaseModel):
    active_submissions: int
    received_submissions: int
    total_grading_cost_jpy: int
    total_graded_value_jpy: int
    total_roi_jpy: int
    overdue_count: int
    best_roi: list[GradingAnalyticsSubmissionOut]
    worst_roi: list[GradingAnalyticsSubmissionOut]


class AnalyticsDigestPortfolioRiskSectionOut(BaseModel):
    risk_score: int
    risk_level: PortfolioRiskLevel
    concentration_score: int
    data_quality_score: int
    liquidity_proxy_score: int
    grading_exposure_score: int
    wishlist_overlap_score: int
    top_recommendation_flags: list[PortfolioRiskFlagOut]


class AnalyticsDigestSectionsOut(BaseModel):
    collection: AnalyticsDigestCollectionSectionOut
    wishlist: AnalyticsDigestWishlistSectionOut
    buy_decisions: AnalyticsDigestBuyDecisionsSectionOut
    sell_decisions: AnalyticsDigestSellDecisionsSectionOut
    grading: AnalyticsDigestGradingSectionOut
    portfolio_risk: AnalyticsDigestPortfolioRiskSectionOut


class AnalyticsDigestPriorityItemOut(BaseModel):
    card_id: int | None
    card_code: str | None
    name_en: str | None
    score: int | None
    risk_level: str | None
    severity: str | None
    message: str
    link: str


class AnalyticsDigestPriorityItemsOut(BaseModel):
    top_buy_decisions: list[AnalyticsDigestPriorityItemOut]
    top_sell_decisions: list[AnalyticsDigestPriorityItemOut]
    top_risk_flags: list[AnalyticsDigestPriorityItemOut]
    wishlist_target_hits: list[AnalyticsDigestPriorityItemOut]
    grading_overdue: list[AnalyticsDigestPriorityItemOut]
    missing_data: list[AnalyticsDigestPriorityItemOut]


class AnalyticsDigestOut(BaseModel):
    summary: AnalyticsDigestSummaryOut
    sections: AnalyticsDigestSectionsOut
    priority_items: AnalyticsDigestPriorityItemsOut
    deterministic_summary_lines: list[str]


class AnalyticsDigestReportOut(BaseModel):
    id: int
    created_at: datetime
    valuation_mode: ValuationMode
    summary: AnalyticsDigestSummaryOut
    sections: AnalyticsDigestSectionsOut
    priority_items: AnalyticsDigestPriorityItemsOut
    deterministic_summary_lines: list[str]
    payload: dict[str, Any]


class AnalyticsDigestReportSummaryOut(BaseModel):
    id: int
    created_at: datetime
    valuation_mode: ValuationMode
    collection_value_jpy: int | None
    graded_adjusted_value_jpy: int | None
    portfolio_risk_score: int | None
    portfolio_risk_level: str | None
    wishlist_target_hits: int
    buy_review_count: int
    sell_review_count: int
    grading_roi_jpy: int | None


class AnalyticsDigestReportListOut(BaseModel):
    reports: list[AnalyticsDigestReportSummaryOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class AdminGenerateAnalyticsDigestRequest(BaseModel):
    valuation_mode: ValuationMode = "raw_market"


class AdminGenerateAnalyticsDigestResponse(BaseModel):
    report_id: int
    valuation_mode: ValuationMode
    portfolio_risk_score: int
    buy_review_count: int
    sell_review_count: int


class WishlistImportRowErrorOut(BaseModel):
    row_number: int
    card_code: str | None
    error: str


class WishlistImportPreviewRowOut(BaseModel):
    row_number: int
    card_code: str
    matched_card_id: int
    action: str
    priority: str
    status: str


class WishlistImportSummaryOut(BaseModel):
    total_rows: int
    valid_rows: int
    error_rows: int
    created: int
    updated: int
    skipped: int


class WishlistImportResponseOut(BaseModel):
    dry_run: bool
    mode: str
    summary: WishlistImportSummaryOut
    errors: list[WishlistImportRowErrorOut]
    preview: list[WishlistImportPreviewRowOut]


# --- Dashboard personalization -----------------------------------------

DashboardTimeframe = Literal["7d", "30d", "90d", "all"]


class DashboardPreferencesOut(BaseModel):
    layout: list[str]
    hidden_widgets: list[str]
    pinned_cards: list[int]
    default_timeframe: str
    show_raw_market_value: bool
    show_graded_adjusted_value: bool
    show_wishlist_budget: bool
    show_grading_costs: bool


class DashboardPreferencesUpdateIn(BaseModel):
    layout: list[str] | None = None
    hidden_widgets: list[str] | None = None
    pinned_cards: list[int] | None = None
    default_timeframe: DashboardTimeframe | None = None
    show_raw_market_value: bool | None = None
    show_graded_adjusted_value: bool | None = None
    show_wishlist_budget: bool | None = None
    show_grading_costs: bool | None = None


class PortfolioSummaryWidgetOut(BaseModel):
    total_cost_basis_jpy: int | None
    market_floor_value_jpy: int | None
    graded_adjusted_value_jpy: int | None
    pnl_vs_market_floor_jpy: int | None
    pnl_vs_market_floor_pct: float | None
    pnl_vs_graded_adjusted_jpy: int | None
    pnl_vs_graded_adjusted_pct: float | None


class PortfolioChartPointOut(BaseModel):
    created_at: datetime
    market_floor_value_jpy: int | None
    graded_adjusted_value_jpy: int | None


class PortfolioChartWidgetOut(BaseModel):
    timeframe: str
    points: list[PortfolioChartPointOut]


class WishlistTargetsWidgetOut(BaseModel):
    items: list[WishlistItemOut]
    total_target_hit: int
    total_target_budget_jpy: int
    total_max_budget_jpy: int


class TopOpportunitiesWidgetOut(BaseModel):
    opportunities: list[OpportunityOut]


class GradingStatusWidgetOut(BaseModel):
    total_submissions: int
    submitted_or_grading_count: int
    received_count: int
    total_grading_cost_jpy: int


class MarketReportWidgetOut(BaseModel):
    report_id: int | None
    report_date: date | None
    total_opportunities: int | None
    highest_score: int | None
    deterministic_summary_lines: list[str]


class CollectionQualityWidgetOut(BaseModel):
    missing_purchase_price_count: int
    missing_condition_count: int
    missing_target_sell_count: int


class RecentSignalEventsWidgetOut(BaseModel):
    events: list[MarketSignalEventOut]


class DataFreshnessWidgetOut(BaseModel):
    latest_refresh_at: datetime | None
    latest_refresh_status: str | None
    missing_recent_price_count: int
    stale_mapping_price_count: int


class BackupStatusWidgetOut(BaseModel):
    tracked: bool
    last_backup_at: datetime | None = None
    message: str | None = None


class WorkflowStatusWidgetOut(BaseModel):
    run_id: int | None
    status: str | None
    market_report_id: int | None
    telegram_digest_status: str | None
    finished_at: datetime | None
    error_count_24h: int = 0
    warning_count_24h: int = 0


class DashboardWidgetsOut(BaseModel):
    portfolio_summary: PortfolioSummaryWidgetOut
    portfolio_chart: PortfolioChartWidgetOut
    wishlist_targets: WishlistTargetsWidgetOut
    top_opportunities: TopOpportunitiesWidgetOut
    grading_status: GradingStatusWidgetOut
    market_report: MarketReportWidgetOut
    collection_quality: CollectionQualityWidgetOut
    recent_signal_events: RecentSignalEventsWidgetOut
    data_freshness: DataFreshnessWidgetOut
    backup_status: BackupStatusWidgetOut
    workflow_status: WorkflowStatusWidgetOut
    recent_activity: RecentActivityWidgetOut


class DashboardOverviewOut(BaseModel):
    preferences: DashboardPreferencesOut
    widgets: DashboardWidgetsOut


# --- search --------------------------------------------------------------


class SearchResultOut(BaseModel):
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
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchSummaryOut(BaseModel):
    total_results: int
    by_type: dict[str, int]


class SearchResponseOut(BaseModel):
    query: str
    summary: SearchSummaryOut
    results: list[SearchResultOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class SearchSuggestionOut(BaseModel):
    label: str
    type: str
    url: str


class SearchSuggestionsResponseOut(BaseModel):
    suggestions: list[SearchSuggestionOut]


# --- system check ----------------------------------------------------------


class SystemCheckResultOut(BaseModel):
    name: str
    status: str
    severity: str
    message: str


class SystemCheckSummaryOut(BaseModel):
    checks_total: int
    checks_passed: int
    warnings: int
    critical: int


class CatalogOperationsSummaryOut(BaseModel):
    card_audit_status: str
    duplicate_risk_count: int
    mapping_quality_critical_count: int
    metadata_completion_pct: float
    mapping_coverage_pct: float
    recent_price_coverage_pct: float
    price_source_health_status: str
    latest_import_validation_status: str
    warnings: list[str]


class SystemCheckResponseOut(BaseModel):
    status: str
    summary: SystemCheckSummaryOut
    checks: list[SystemCheckResultOut]
    catalog_operations: CatalogOperationsSummaryOut


# --- env check ---------------------------------------------------------


class EnvCheckResultOut(BaseModel):
    name: str
    status: str
    severity: str
    message: str


class EnvCheckResponseOut(BaseModel):
    status: str
    app_env: str
    checks: list[EnvCheckResultOut]
    warnings: list[str]
    errors: list[str]


# --- db backups ---------------------------------------------------------


class DbBackupFileOut(BaseModel):
    filename: str
    size_bytes: int
    created_at: datetime


class DbBackupListOut(BaseModel):
    backup_dir: str
    backups: list[DbBackupFileOut]
    limit: int
    offset: int
    pagination: PaginationMeta


# --- app logs / observability -------------------------------------------


class AppLogEventOut(BaseModel):
    id: int
    created_at: datetime
    level: str
    service: str
    event_type: str
    message: str
    context: dict[str, Any] | None
    traceback: str | None
    related_run_id: int | None
    related_entity_type: str | None
    related_entity_id: int | None


class AppLogSummaryOut(BaseModel):
    total_logs: int
    error_count: int
    warning_count: int
    critical_count: int
    by_service: dict[str, int]
    by_event_type: dict[str, int]


class AppLogListOut(BaseModel):
    summary: AppLogSummaryOut
    logs: list[AppLogEventOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class CollectionAttemptOut(BaseModel):
    """One durable collector attempt.

    The stored ids (source_id, source_card_mapping_id) are always present and
    authoritative. The resolved context beside them - source_name, card_print_id,
    card_code - is best-effort: `mapping_resolved` is False and those fields are
    null when the mapping the attempt referred to can no longer be found, rather
    than the API inventing an identity for it.
    """

    id: int
    batch_run_id: str
    selection_ordinal: int
    source_id: int
    source_name: str | None
    source_card_mapping_id: int
    mapping_resolved: bool
    card_print_id: int | None
    card_code: str | None
    selected_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # Derived at read time from started_at/finished_at - never stored.
    duration_seconds: float | None
    status: str
    failure_stage: str | None
    failure_reason: str | None
    source_denied: bool
    price_observation_id: int | None


class CollectionAttemptSummaryOut(BaseModel):
    """Aggregated over the whole filtered set, not the returned page - so
    filtering to one batch_run_id answers "what happened in that run?"."""

    total_attempts: int
    started: int
    written: int
    skipped: int
    source_denied: int
    still_selected: int
    by_status: dict[str, int]
    by_failure_stage: dict[str, int]
    earliest_selected_at: datetime | None
    latest_finished_at: datetime | None


class CollectionAttemptListOut(BaseModel):
    summary: CollectionAttemptSummaryOut
    attempts: list[CollectionAttemptOut]
    limit: int
    offset: int
    pagination: PaginationMeta


class AppLogPruneRequestIn(BaseModel):
    older_than_days: int = 30
    dry_run: bool = True
    confirm: str | None = None


class AppLogPruneResponseOut(BaseModel):
    dry_run: bool
    older_than_days: int
    would_delete: int
    deleted: int


class ObservabilityLast24hOut(BaseModel):
    critical: int
    error: int
    warning: int
    info: int


class ObservabilitySummaryOut(BaseModel):
    status: str
    last_24h: ObservabilityLast24hOut
    latest_error: AppLogEventOut | None
    latest_market_workflow_run: dict[str, Any] | None
    latest_price_refresh_run: dict[str, Any] | None
    latest_backup: dict[str, Any] | None
    latest_system_check_status: str | None


# --- rate limiting --------------------------------------------------------


class RateLimitWindowOut(BaseModel):
    group: str
    limit: int
    window_seconds: int
    active_keys: int


class RateLimitStatusOut(BaseModel):
    enabled: bool
    windows: list[RateLimitWindowOut]


# --- version / release status -------------------------------------------


class VersionOut(BaseModel):
    app: str
    version: str
    git_commit: str
    build_time: str
    app_env: str


class ReleaseReadinessOut(BaseModel):
    system_check_status: str
    critical_logs_last_24h: int
    latest_backup_available: bool


class ReleaseStatusOut(BaseModel):
    version: str
    git_commit: str
    build_time: str
    app_env: str
    latest_market_workflow_run: dict[str, Any] | None
    latest_system_check: SystemCheckResponseOut
    latest_backup: dict[str, Any] | None
    latest_error: AppLogEventOut | None
    release_readiness: ReleaseReadinessOut


# --- db index audit / performance -------------------------------------


class DbIndexCheckOut(BaseModel):
    table: str
    index: str
    status: str
    severity: str
    message: str


class DbIndexAuditSummaryOut(BaseModel):
    total_checks: int
    passed: int
    warnings: int
    critical: int


class DbIndexAuditResponseOut(BaseModel):
    summary: DbIndexAuditSummaryOut
    checks: list[DbIndexCheckOut]


class SlowRequestOut(BaseModel):
    created_at: datetime
    message: str
    context: dict[str, Any] | None


class PerformanceDatabaseCountsOut(BaseModel):
    price_observations_count: int
    raw_snapshots_count: int
    market_signal_events_count: int
    collector_activity_events_count: int
    app_log_events_count: int


class PerformanceIndexAuditSummaryOut(BaseModel):
    warnings: int
    critical: int


class LargestResponseOut(BaseModel):
    created_at: datetime
    method: str | None
    path: str | None
    size_bytes: int | None


class PerformanceSummaryOut(BaseModel):
    status: str
    database: PerformanceDatabaseCountsOut
    latest_slow_requests: list[SlowRequestOut]
    index_audit: PerformanceIndexAuditSummaryOut
    response_size_warnings_last_24h: int = 0
    slow_requests_last_24h: int = 0
    largest_recent_responses: list[LargestResponseOut] = []
    active_job_locks: int = 0
    expired_job_locks: int = 0
    cache_enabled: bool = True
    cache_backend: str = "none"
    cache_keys: int | None = None
    file_jobs_by_status: dict[str, int] = {}
    stale_running_file_jobs: int = 0


# --- job locks -------------------------------------------------------------


class JobLockOut(BaseModel):
    lock_name: str
    owner_id: str
    acquired_at: datetime
    expires_at: datetime
    status: str
    metadata: dict[str, Any] | None


class JobLockListOut(BaseModel):
    locks: list[JobLockOut]


class JobLockCleanupResponseOut(BaseModel):
    cleaned_up_count: int


class JobLockForceReleaseRequestIn(BaseModel):
    confirm: str | None = None


class JobLockForceReleaseResponseOut(BaseModel):
    released: bool
    lock_name: str


# --- data retention / pruning -------------------------------------------


class DataRetentionPolicyOut(BaseModel):
    table: str
    retention_days: int
    mode: str
    protected_records: str
    enabled: bool


class DataRetentionPolicyResponseOut(BaseModel):
    policies: list[DataRetentionPolicyOut]


class DataRetentionPruneRequestIn(BaseModel):
    dry_run: bool = True
    tables: list[str] | None = None
    confirm: str | None = None


class DataRetentionPruneResultOut(BaseModel):
    table: str
    retention_days: int | None
    rows_would_delete: int
    rows_deleted: int
    status: str
    warning: str | None


class DataRetentionPruneSummaryOut(BaseModel):
    tables_checked: int
    total_rows_would_delete: int
    total_rows_deleted: int
    warnings: int


class DataRetentionPruneResponseOut(BaseModel):
    dry_run: bool
    summary: DataRetentionPruneSummaryOut
    results: list[DataRetentionPruneResultOut]


# --- cache ---------------------------------------------------------------


class CacheStatsOut(BaseModel):
    keys: int
    hits: int
    misses: int


class CacheTtlOut(BaseModel):
    dashboard: int
    market: int
    collection: int


class CacheStatusOut(BaseModel):
    enabled: bool
    backend: str
    stats: CacheStatsOut
    ttl: CacheTtlOut


class CacheClearRequestIn(BaseModel):
    prefix: str | None = None
    confirm: str | None = None


class CacheClearResponseOut(BaseModel):
    success: bool
    prefix: str | None
    deleted_count: int | None


# --- file jobs -------------------------------------------------------------


class FileJobOut(BaseModel):
    id: int
    job_type: str
    status: str
    original_filename: str | None
    output_filename: str | None
    content_type: str | None
    dry_run: bool
    mode: str | None
    progress_current: int
    progress_total: int | None
    download_ready: bool
    summary: dict[str, Any] | None
    errors: Any | None
    warnings: Any | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FileJobListOut(BaseModel):
    jobs: list[FileJobOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class FileJobCreatedOut(BaseModel):
    file_job_id: int
    status: str


class FileJobCancelResponseOut(BaseModel):
    id: int
    status: str


class BackupExportJobRequestIn(BaseModel):
    include_prices: bool = False
    include_raw_snapshots: bool = False
    include_refresh_runs: bool = False
    include_logs: bool = False
    include_validation_reports: bool = False


class CollectionExportJobRequestIn(BaseModel):
    filters: dict[str, Any] | None = None


class WishlistExportJobRequestIn(BaseModel):
    filters: dict[str, Any] | None = None


class FileJobCleanupRequestIn(BaseModel):
    older_than_days: int = 7
    dry_run: bool = True
    confirm: str | None = None


class FileJobCleanupResponseOut(BaseModel):
    dry_run: bool
    older_than_days: int
    would_delete: int
    deleted: int


# --- Import templates / validation --------------------------------------


class ImportTemplateOut(BaseModel):
    template_type: str
    filename: str
    description: str
    required_columns: list[str]
    optional_columns: list[str]
    download_url: str
    notes: list[str]


class ImportTemplateListOut(BaseModel):
    templates: list[ImportTemplateOut]


class ImportRowIssueOut(BaseModel):
    row_number: int
    field: str | None
    value: Any
    code: str
    message: str


class ImportPreviewRowOut(BaseModel):
    row_number: int
    action: str
    normalized_values: dict[str, Any]
    warnings: list[str]
    errors: list[str]


class ImportValidationSummaryOut(BaseModel):
    total_rows: int
    valid_rows: int
    error_rows: int
    warning_rows: int
    duplicate_rows: int
    would_create: int
    would_update: int
    would_skip: int


class ImportValidationColumnsOut(BaseModel):
    required_columns: list[str]
    optional_columns: list[str]
    received_columns: list[str]
    missing_required_columns: list[str]
    unknown_columns: list[str]


class ImportValidationResponseOut(BaseModel):
    import_type: str
    valid: bool
    summary: ImportValidationSummaryOut
    columns: ImportValidationColumnsOut
    errors: list[ImportRowIssueOut]
    warnings: list[ImportRowIssueOut]
    preview: list[ImportPreviewRowOut]


class ImportValidationReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    import_type: str
    filename: str | None
    valid: bool
    strict: bool
    total_rows: int
    valid_rows: int
    error_rows: int
    warning_rows: int
    duplicate_rows: int


class ImportValidationReportDetailOut(ImportValidationReportOut):
    report_payload_json: dict[str, Any]


class ImportValidationReportListOut(BaseModel):
    reports: list[ImportValidationReportOut]
    pagination: PaginationMeta


# --- saved views -----------------------------------------------------------


class SavedViewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None
    route_path: str
    view_type: str
    scope: str
    filters_json: dict[str, Any] | None
    sort_json: dict[str, Any] | None
    columns_json: dict[str, Any] | None
    density: str
    is_default: bool
    pinned: bool
    last_used_at: datetime | None
    usage_count: int
    notes: str | None


class SavedViewListOut(BaseModel):
    items: list[SavedViewOut]
    pagination: PaginationMeta


class SavedViewCreateIn(BaseModel):
    name: str
    description: str | None = None
    route_path: str
    view_type: str
    scope: Literal["collector", "admin", "analytics", "market"] = "collector"
    filters_json: dict[str, Any] | None = None
    sort_json: dict[str, Any] | None = None
    columns_json: dict[str, Any] | None = None
    density: Literal["compact", "comfortable"] = "compact"
    is_default: bool = False
    pinned: bool = False
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class SavedViewUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    filters_json: dict[str, Any] | None = None
    sort_json: dict[str, Any] | None = None
    columns_json: dict[str, Any] | None = None
    density: Literal["compact", "comfortable"] | None = None
    is_default: bool | None = None
    pinned: bool | None = None
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class ClearDefaultSavedViewIn(BaseModel):
    route_path: str
    view_type: str


class AdminLoginVerifyIn(BaseModel):
    """POST /auth/admin/verify request body - see app.api.admin_login.
    Length caps are a safety measure, not a UX validation: Argon2 hashing
    cost scales with input size, so an unbounded password is a cheap DoS
    vector against the verify call itself."""

    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class AdminLoginVerifyOut(BaseModel):
    """Deliberately minimal - see app.api.admin_login's module docstring
    for the full list of what this must never include (ADMIN_TOKEN,
    password hash, API_JWT_SECRET, session/DB/Redis internals)."""

    id: str
    email: str
    role: Literal["admin"]


# --- exact-print mapping approval -------------------------------------------
# The operator's decision aid. Everything here answers "which physical card is
# this listing selling?", so it is card facts a collector would recognise -
# artwork, names, product, printing - and never raw internal identifiers as
# the primary cue. `card_print_id` is present because it is what the approval
# call must send, not because it is what the operator reads.


class ApprovalSourceCandidateOut(BaseModel):
    """The listing side of the decision, exactly as the source published it."""

    candidate_id: int
    source: str
    title: str | None
    source_url: str
    source_image_url: str | None
    detected_card_code: str | None
    detected_set_code: str | None
    detected_variant: str | None
    detected_rarity: str | None
    price_jpy: int | None


class ApprovalPrintOptionOut(BaseModel):
    """One printing the listing could be describing, presented so an operator
    can tell it apart from its siblings by eye."""

    card_print_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    # The full uncropped artwork, same resolution path the public catalogue
    # uses - a thumbnail is not enough to tell two alternate arts apart.
    display_image: DisplayImageOut | None
    image_url: str | None
    found_in_product: str | None
    rarity: str | None
    special_print: str | None
    printing: str | None
    # Only where it is actually needed to separate two otherwise identical
    # rows on screen; None when the printing already reads uniquely.
    art_ordinal: int | None
    language: str
    # Whether THIS option can be approved from the evidence currently stored,
    # and if not, why. The list is not filtered down to the approvable one:
    # seeing the rejected siblings is how an operator understands that the
    # source simply did not say which of them it meant.
    approvable: bool
    refusal_code: str | None
    refusal_detail: str | None


class ArtworkPreviewOut(BaseModel):
    """Advisory artwork evidence for the approval screen.

    ADVISORY MEANS ADVISORY. Nothing here participates in approval: the
    resolver does not read it, it is not stored, and `advisory_only` is part
    of the payload so a client cannot render it as a decision by accident.
    There is deliberately no confidence percentage and no "safe"/"approved"
    field - the widened validation showed the accept threshold is nearly
    inert on its own, so a single number would overstate what this proves.
    """

    status: str  # exact | ambiguous | no_match | unusable
    summary: str
    method_version: str
    listing_image_url: str | None
    considered_card_print_ids: list[int]
    winning_card_print_ids: list[int]
    # True when the matched artwork belongs to more than one printing (a
    # reprint). Artwork can never separate those, however good the score.
    winning_class_is_shared: bool
    # Present only when exactly one surviving print carries the matched
    # artwork; it is what the image CORROBORATES, never what it approves.
    corroborates_card_print_id: int | None
    best_score: int | None
    runner_up_score: int | None
    margin: int | None
    detail: str | None
    fetch_errors: list[str]
    advisory_only: bool = True


class ApprovalContextOut(BaseModel):
    candidate: ApprovalSourceCandidateOut
    options: list[ApprovalPrintOptionOut]
    # Populated only when exactly one option is approvable - the UI uses it to
    # pre-select, never to auto-approve.
    resolvable_card_print_id: int | None
    ambiguity_reason: str | None


class YuyuteiMatchedPrintOut(BaseModel):
    """The printing a print_matched candidate names, as the reviewer needs to
    see it: enough to tell WHICH printing this is (code, product, variant,
    treatment) and whether it is still priceable (active + verified). Not
    CardPrintSiblingOut, which omits the product and the code and exists for a
    different screen."""

    card_print_id: int
    card_code: str | None
    treatment: str | None
    language: str
    release_product_code: str | None
    official_asset_variant: str | None
    verification_status: str
    is_active: bool
    image_url: str | None


class YuyuteiCandidateOut(BaseModel):
    """One Yuyu-Tei discovery candidate, as the admin review screen reads it.

    `approved` and `mapping_id` are DERIVED, not stored: the candidate table
    has no approval column and deliberately does not grow one - its
    `match_status` vocabulary is catalogue cardinality, not review state, so
    approval is the existence of a mapping for the listing. See
    app.services.yuyutei_candidate_approval.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    discovery_run_id: int | None
    set_slug: str
    product_id: str
    source_url: str
    detected_card_code: str | None
    detected_rarity: str | None
    name_jp: str | None
    image_url: str | None
    price_jpy: int | None
    availability: str | None
    match_status: str
    matched_card_print_id: int | None
    match_explanation_json: dict | None = None
    created_at: datetime
    updated_at: datetime

    # Derived, never columns.
    approved: bool = False
    mapping_id: int | None = None
    matched_print: YuyuteiMatchedPrintOut | None = None


class YuyuteiCandidateListOut(BaseModel):
    items: list[YuyuteiCandidateOut]
    total: int
    limit: int
    offset: int
    pagination: PaginationMeta


class YuyuteiApproveIn(BaseModel):
    """The approval request carries NO print id, unlike ApproveMatchIn.

    The printing is not the operator's to choose here: discovery wrote
    `matched_card_print_id` only where the card code resolved to exactly one
    active print, and a DB check constraint makes any other value
    unrepresentable. Accepting a print id from the request would open a way to
    approve a printing the classification never established. The decision
    being recorded is *whether* to approve, not *what* to approve onto.
    """

    review_notes: str | None = None


class YuyuteiApprovalOut(BaseModel):
    candidate: YuyuteiCandidateOut
    mapping_id: int
    card_print_id: int
    source_card_id: str
    source_url: str
    # False on a repeat approval of a listing that already had a mapping - the
    # difference between a new priced listing and a no-op.
    mapping_created: bool
    review_notes: str | None
    evidence_used: list[str]
