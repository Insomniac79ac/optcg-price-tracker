from __future__ import annotations

from datetime import datetime, timezone

from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
    Source,
    SourceCardMapping,
)


def make_source(db, name: str = "yuyutei") -> Source:
    existing = db.query(Source).filter_by(name=name).one_or_none()
    if existing is not None:
        return existing
    row = Source(name=name, base_url=f"https://{name}.example")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_product(db, code: str = "OP-01") -> ReleaseProduct:
    existing = (
        db.query(ReleaseProduct)
        .filter_by(source_catalogue="bandai_jp", official_code=code)
        .one_or_none()
    )
    if existing is not None:
        return existing
    row = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code=code,
        display_name=f"Product {code}",
        first_seen_name=f"Product {code}",
        source_series_id=code.replace("-", ""),
        source_url=f"https://bandai.example/{code}",
        verification_status="verified",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_canonical(db, card_code: str, **overrides) -> CanonicalCard:
    fields = dict(
        card_code=card_code,
        name_en=f"Card {card_code}",
        name_jp=None,
        original_set_code="OP-01",
        rarity="R",
        card_type="Character",
    )
    fields.update(overrides)
    row = CanonicalCard(**fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_print(
    db,
    canonical: CanonicalCard,
    *,
    product_code: str = "OP-01",
    asset_variant: str = "base",
    treatment: str | None = "base",
    language: str = "jp",
    rarity: str | None = "R",
    active: bool = True,
    verification_status: str = "verified",
) -> CardPrint:
    product = make_product(db, product_code)
    row = CardPrint(
        canonical_card_id=canonical.id,
        language=language,
        treatment=treatment,
        release_product_code=product_code,
        release_product_id=product.id,
        artwork_key=f"sha256:{canonical.card_code}:{product_code}:{asset_variant}",
        official_asset_variant=asset_variant,
        official_rarity=rarity,
        verification_status=verification_status,
        is_active=active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_compatibility_card(db, card_code: str, **overrides) -> Card:
    fields = dict(
        card_code=card_code,
        name_en=f"Legacy {card_code}",
        set_code="OP01",
        rarity="R",
        variant="base",
        language="jp",
    )
    fields.update(overrides)
    row = Card(**fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_exact_mapping(
    db,
    card_print: CardPrint,
    source: Source,
    *,
    compatibility_card: Card | None = None,
    suffix: str | None = None,
    **overrides,
) -> SourceCardMapping:
    token = suffix or str(card_print.id)
    fields = dict(
        card_id=compatibility_card.id if compatibility_card is not None else None,
        card_print_id=card_print.id,
        source_id=source.id,
        source_card_id=f"listing-{token}",
        source_url=f"https://{source.name}.example/{token}",
        review_status="approved",
        is_active=True,
    )
    fields.update(overrides)
    row = SourceCardMapping(**fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_legacy_mapping(
    db, card: Card, source: Source, **overrides
) -> SourceCardMapping:
    fields = dict(
        card_id=card.id,
        card_print_id=None,
        source_id=source.id,
        source_card_id=card.card_code,
        source_url=f"https://{source.name}.example/legacy-{card.id}",
        review_status="approved",
        is_active=True,
    )
    fields.update(overrides)
    row = SourceCardMapping(**fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_exact_observation(
    db,
    mapping: SourceCardMapping,
    *,
    observed_at: datetime | None = None,
    price_jpy: int = 1000,
    price_type: str = "sell",
) -> PriceObservation:
    row = PriceObservation(
        card_id=mapping.card_id,
        source_id=mapping.source_id,
        source_card_mapping_id=mapping.id,
        card_print_id=mapping.card_print_id,
        price_type=price_type,
        price_jpy=price_jpy,
        observed_at=observed_at or datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
