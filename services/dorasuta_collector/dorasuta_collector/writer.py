"""What a parsed Dorasuta list page writes (plan §2.1, §2.2, §3.1).

Per row: the source product (verbatim name and parsed facts), its group, and one variant per
condition (grade_key). A price observation only for a `raw:A` row of a product that is exact or
manual AND carries an approved, active mapping to that print; mappings are approved separately,
never here. Graded rows stay in variants only (N10, PSA10 OFF). Identity is not resolved during a
run, because a page seen before its siblings would let the two-way-unique rule decide on half the
evidence; `dorasuta_collector.resolve` re-resolves every stored product after each run instead.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import PriceObservation, RawSnapshot, Source, SourceCardMapping
from app.source_products import dorasuta_rules, grade_keys
from app.source_products.listing_identity import NotAListing, canonical_listing_identity
from app.source_products.models import (
    SourceProduct,
    SourceProductGroup,
    SourceProductVariant,
    price_observation_grade_keys,
)
from source_collector_kit.health import RunReport
from source_collector_kit.registry import ListingRow, ParsedPage

COUNTED_GRADE = grade_keys.raw("A")
PRICE_TYPE = "sell"
_SLAB = re.compile(r"(PSA|BGS|CGC|ARS)\s*([0-9]{1,2}(?:\.5)?)")


def grade_key_for(row: ListingRow, kind: str) -> str | None:
    if kind == "graded":
        slab = _SLAB.search(row.title)
        return grade_keys.graded(slab.group(1), slab.group(2)) if slab else grade_keys.GRADED_UNKNOWN
    return dorasuta_rules.grade_key_for_condition(row.condition_label or "")


def _group(db: Session, source: Source, parsed: ParsedPage, page_url: str, now: datetime) -> None:
    group = db.scalar(
        select(SourceProductGroup).where(
            SourceProductGroup.source_id == source.id, SourceProductGroup.group_key == parsed.group_key
        )
    )
    if group is None:
        # The release is set by review, never derived here: a new group names none, so its
        # products quarantine as release_group_unresolved until it does.
        db.add(SourceProductGroup(
            source_id=source.id, group_key=parsed.group_key, url=page_url[:1024],
            title=parsed.group_title or parsed.group_key, kind="series", first_seen_at=now, last_seen_at=now,
        ))
    else:
        group.last_seen_at = now
        if parsed.group_title:
            group.title = parsed.group_title


def _product(db: Session, source: Source, row: ListingRow, identity: str, group_key: str, now: datetime, report):
    parsed = dorasuta_rules.parse_title(row.title)
    product = db.scalar(
        select(SourceProduct).where(
            SourceProduct.source_id == source.id, SourceProduct.source_product_key == row.source_product_key
        )
    )
    if product is None:
        product = SourceProduct(
            source_id=source.id, source_product_key=row.source_product_key, canonical_listing_identity=identity,
            match_status="pending", first_seen_at=now, group_keys=[],
        )
        db.add(product)
        report.products_new += 1
    product.url = row.url[:1024]
    product.name = row.title
    product.parsed_code = parsed.card_code
    product.rarity = parsed.rarity
    product.variant_markers = list(parsed.markers)
    product.qualifier = parsed.qualifier
    product.listing_kind = parsed.kind
    if group_key not in (product.group_keys or []):
        product.group_keys = sorted({*(product.group_keys or []), group_key})
    product.last_seen_at = now
    return product, parsed


def _variant(db, product: SourceProduct, grade_key: str, row: ListingRow, raw: RawSnapshot, now: datetime):
    variant = db.scalar(
        select(SourceProductVariant).where(
            SourceProductVariant.source_product_id == product.id, SourceProductVariant.grade_key == grade_key
        )
    )
    if variant is None:
        variant = SourceProductVariant(source_product_id=product.id, grade_key=grade_key)
        db.add(variant)
    variant.last_price_jpy = row.price_jpy if row.price_jpy and row.price_jpy > 0 else None
    variant.stock = 0 if row.sold_out else row.stock
    variant.on_sale = row.on_sale
    variant.last_seen_at = now
    variant.last_raw_snapshot_id = raw.id


def _current_mappings(db: Session, source: Source) -> dict[str, list[SourceCardMapping]]:
    """Approved, active, current mappings for the source, keyed by listing identity.

    The identity is derived here from each mapping's source_url with the new-source rules
    (app.source_products.listing_identity). The stored canonical_source_listing_identity column
    cannot be used: the shared ORM hook derives it with opcg_source_identity, which knows only the
    two live sources and so writes None for Dorasuta, and teaching it Dorasuta would redeploy every
    live collector (plan §2.3).
    """
    by_identity: dict[str, list[SourceCardMapping]] = {}
    for mapping in db.scalars(
        select(SourceCardMapping).where(
            SourceCardMapping.source_id == source.id,
            SourceCardMapping.review_status == "approved",
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.superseded_at.is_(None),
        )
    ):
        try:
            identity = canonical_listing_identity(mapping.source_url)
        except NotAListing:
            continue
        by_identity.setdefault(identity, []).append(mapping)
    return by_identity


def _mapping(mappings: dict[str, list[SourceCardMapping]], product: SourceProduct) -> SourceCardMapping | None:
    """The one mapping that lets this product count, or None. Two current mappings for one listing
    is a review conflict, never resolved here."""
    if product.match_status not in {"exact", "manual"} or product.card_print_id is None:
        return None
    candidates = mappings.get(product.canonical_listing_identity, [])
    if len(candidates) != 1 or candidates[0].card_print_id != product.card_print_id:
        return None
    return candidates[0]


def _observe(db, source, product, mapping, row: ListingRow, raw: RawSnapshot, now: datetime) -> None:
    observation = PriceObservation(
        card_id=mapping.card_id,
        source_id=source.id,
        observed_at=now,
        price_type=PRICE_TYPE,
        price_jpy=row.price_jpy,
        condition_label=row.condition_label,
        stock_status="out_of_stock" if row.sold_out or row.stock == 0 else "in_stock",
        raw_snapshot_id=raw.id,
        source_card_mapping_id=mapping.id,
        card_print_id=product.card_print_id,
        promotion_state="sale" if row.on_sale else "none",
    )
    db.add(observation)
    db.flush()
    # grade_key is not on the shared ORM model (plan §2.1, §2.7); set it through the writer's table.
    db.execute(
        update(price_observation_grade_keys)
        .where(price_observation_grade_keys.c.id == observation.id)
        .values(grade_key=COUNTED_GRADE)
    )


def handle_page(db: Session, source: Source, parsed: ParsedPage, raw: RawSnapshot, report: RunReport) -> None:
    now = raw.fetched_at
    _group(db, source, parsed, raw.source_url, now)
    mappings = _current_mappings(db, source)
    for row in parsed.rows:
        try:
            identity = canonical_listing_identity(row.url)
        except NotAListing:
            report.outcomes["row_not_a_listing"] += 1
            continue
        product, title = _product(db, source, row, identity, parsed.group_key, now, report)
        db.flush()
        grade_key = grade_key_for(row, title.kind)
        if grade_key is None:
            report.outcomes["row_condition_unknown"] += 1
            continue
        _variant(db, product, grade_key, row, raw, now)
        report.variants_written += 1
        if grade_key != COUNTED_GRADE or not row.price_jpy or row.price_jpy <= 0:
            continue
        mapping = _mapping(mappings, product)
        if mapping is not None:
            _observe(db, source, product, mapping, row, raw, now)
            report.observations_written += 1
    db.flush()
