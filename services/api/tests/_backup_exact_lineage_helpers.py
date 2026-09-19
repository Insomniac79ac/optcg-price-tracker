from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    CanonicalCard,
    Card,
    CardPirateIndexPoint,
    CardPrint,
    MarketIndexSnapshot,
    PriceObservation,
    RawSnapshot,
    ReleaseProduct,
    ReleaseProductAlias,
    SnkrdunkCandidate,
    SnkrdunkDiscoveryRun,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
)


def seed_exact_lineage(session: Session) -> dict[str, int]:
    """Seed one complete exact chain plus one legacy compatibility mapping."""
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    legacy_card = Card(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        set_code="OP01",
        rarity="L",
        language="en",
    )
    canonical = CanonicalCard(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        original_set_code="OP-01",
        rarity="L",
        card_type="Leader",
    )
    product = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code="OP-01",
        display_name="ROMANCE DAWN",
        first_seen_name="ROMANCE DAWN",
        source_series_id="556101",
        source_url="https://example.test/products/op-01",
        verification_status="verified",
    )
    source = Source(name="snkrdunk", base_url="https://snkrdunk.example.test")
    discovery_run = SnkrdunkDiscoveryRun(
        status="completed",
        seed_url="https://snkrdunk.example.test/search",
        pages_fetched=1,
        candidates_found=1,
        candidates_matched=1,
        finished_at=now,
    )
    session.add_all([legacy_card, canonical, product, source, discovery_run])
    session.flush()

    session.add(
        ReleaseProductAlias(
            product_id=product.id,
            alias_name="ROMANCE DAWN",
            alias_kind="bandai_official",
            source_url=product.source_url,
        )
    )
    card_print = CardPrint(
        canonical_card_id=canonical.id,
        language="jp",
        release_product_code="OP-01",
        release_product_id=product.id,
        artwork_key="sha256:exact-print-artwork",
        official_asset_variant="base",
        verification_status="verified",
    )
    raw_snapshot = RawSnapshot(
        source_id=source.id,
        source_url="https://snkrdunk.example.test/products/exact",
        fetched_at=now,
        http_status=200,
        content_hash="a" * 64,
        raw_content="<html>private provenance body</html>",
        parser_version="test-v1",
    )
    candidate = SnkrdunkCandidate(
        discovery_run_id=discovery_run.id,
        source_url="https://snkrdunk.example.test/products/exact",
        title="OP01-001 exact print",
        match_status="unmatched",
    )
    session.add_all([card_print, raw_snapshot, candidate])
    session.flush()

    exact_mapping = SourceCardMapping(
        card_id=None,
        source_id=source.id,
        card_print_id=card_print.id,
        source_card_id="snk-exact-1",
        source_url="https://snkrdunk.example.test/products/exact",
        manual_verified=True,
        review_status="approved",
    )
    legacy_mapping = SourceCardMapping(
        card_id=legacy_card.id,
        source_id=source.id,
        card_print_id=None,
        source_card_id="snk-legacy-1",
        source_url="https://snkrdunk.example.test/products/legacy",
        manual_verified=True,
        review_status="approved",
    )
    session.add_all([exact_mapping, legacy_mapping])
    session.flush()

    observation = PriceObservation(
        card_id=None,
        source_id=source.id,
        observed_at=now,
        price_type="market",
        price_jpy=1234,
        raw_snapshot_id=raw_snapshot.id,
        candidate_id=candidate.id,
        source_card_mapping_id=exact_mapping.id,
        card_print_id=card_print.id,
    )
    market_snapshot = MarketIndexSnapshot(
        card_print_id=card_print.id,
        calculated_at=now,
        snapshot_date=date(2026, 9, 16),
        index_value_jpy=1234,
        calculation_method="median",
        source_count=1,
        coverage_status="full",
        confidence="high",
        index_version=1,
        source_semantics_version=1,
        freshest_eligible_source_at=now,
        stalest_eligible_source_at=now,
        provenance={"source_values": [], "auxiliary_values": []},
    )
    pirate_point = CardPirateIndexPoint(
        scope_kind="overall",
        scope_key="",
        methodology_version=1,
        index_version=1,
        source_semantics_version=1,
        point_date=date(2026, 9, 16),
        index_value=Decimal("1000.0000"),
        is_base=True,
        constituent_count=0,
        eligible_print_count=0,
        calculated_at=now,
    )
    session.add_all([observation, market_snapshot, pirate_point])
    session.flush()

    attempt = SourceCollectionAttempt(
        batch_run_id="exact-backup-test",
        source_id=source.id,
        source_card_mapping_id=exact_mapping.id,
        selection_ordinal=1,
        selected_at=now,
        started_at=now,
        finished_at=now,
        status="written",
        price_observation_id=observation.id,
        raw_snapshot_id=raw_snapshot.id,
    )
    session.add(attempt)
    session.commit()

    return {
        "legacy_card_id": legacy_card.id,
        "canonical_card_id": canonical.id,
        "release_product_id": product.id,
        "card_print_id": card_print.id,
        "source_id": source.id,
        "raw_snapshot_id": raw_snapshot.id,
        "candidate_id": candidate.id,
        "exact_mapping_id": exact_mapping.id,
        "legacy_mapping_id": legacy_mapping.id,
        "observation_id": observation.id,
        "attempt_id": attempt.id,
        "market_snapshot_id": market_snapshot.id,
        "pirate_point_id": pirate_point.id,
    }
