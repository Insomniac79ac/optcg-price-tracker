from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app import historical_lineage_inventory as inventory_cli
from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    PriceObservation,
    RawSnapshot,
    ReleaseProduct,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
)
from app.services.historical_lineage_inventory import (
    build_historical_lineage_inventory,
)


def _card(code: str, name: str) -> Card:
    return Card(
        card_code=code,
        name_en=name,
        name_jp=None,
        set_code="TEST",
        rarity="R",
        variant="base",
        language="jp",
    )


def _canonical(code: str, name: str) -> CanonicalCard:
    return CanonicalCard(
        card_code=code,
        name_en=name,
        name_jp=None,
        original_set_code="TEST",
        rarity="R",
        card_type="Character",
    )


def _observation(source_id: int, **overrides) -> PriceObservation:
    fields = {
        "source_id": source_id,
        "price_type": "sell",
        "price_jpy": 1000,
    }
    fields.update(overrides)
    return PriceObservation(**fields)


@pytest.fixture()
def inventory_rows(db_session):
    yuyutei = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    snkrdunk = Source(name="snkrdunk", base_url="https://snkrdunk.com")
    card_a = _card("TEST-001", "Card A")
    card_b = _card("TEST-002", "Card B")
    canonical_a = _canonical("TEST-001", "Card A")
    canonical_b = _canonical("TEST-002", "Card B")
    product = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code="TEST-INVENTORY",
        display_name="Inventory fixture product",
        first_seen_name="Inventory fixture product",
        source_series_id="TEST",
        source_url="https://example.invalid/inventory/product",
        verification_status="verified",
    )
    db_session.add_all(
        [yuyutei, snkrdunk, card_a, card_b, canonical_a, canonical_b, product]
    )
    db_session.flush()

    print_a = CardPrint(
        canonical_card_id=canonical_a.id,
        language="jp",
        treatment="normal",
        release_product_code="TEST-INVENTORY",
        release_product_id=product.id,
        artwork_key="inventory-fixture-a",
        official_asset_variant="base",
        verification_status="verified",
        is_active=True,
    )
    print_b = CardPrint(
        canonical_card_id=canonical_b.id,
        language="jp",
        treatment="normal",
        release_product_code="TEST-INVENTORY",
        release_product_id=product.id,
        artwork_key="inventory-fixture-b",
        official_asset_variant="base",
        verification_status="verified",
        is_active=True,
    )
    db_session.add_all([print_a, print_b])
    db_session.flush()

    exact_yuyu_a = SourceCardMapping(
        card_id=card_a.id,
        source_id=yuyutei.id,
        card_print_id=print_a.id,
        source_card_id="TEST-001",
        source_url="https://yuyu-tei.jp/inventory/a",
        review_status="approved",
    )
    exact_snkr_b = SourceCardMapping(
        card_id=card_a.id,
        source_id=snkrdunk.id,
        card_print_id=print_b.id,
        source_card_id="TEST-002",
        source_url="https://snkrdunk.com/inventory/b",
        review_status="approved",
    )
    exact_snkr_a_other_card = SourceCardMapping(
        card_id=card_b.id,
        source_id=snkrdunk.id,
        card_print_id=print_a.id,
        source_card_id="TEST-001-alt",
        source_url="https://snkrdunk.com/inventory/a",
        review_status="approved",
    )
    legacy = SourceCardMapping(
        card_id=card_a.id,
        source_id=yuyutei.id,
        card_print_id=None,
        source_card_id="TEST-LEGACY",
        source_url="https://yuyu-tei.jp/inventory/legacy",
        review_status="approved",
    )
    entityless = SourceCardMapping(
        card_id=None,
        source_id=yuyutei.id,
        card_print_id=None,
        source_card_id="TEST-ENTITYLESS",
        source_url="https://yuyu-tei.jp/inventory/entityless",
        review_status="needs_review",
    )
    invalid_exact = SourceCardMapping(
        card_id=card_a.id,
        source_id=yuyutei.id,
        card_print_id=999_999,
        source_card_id="TEST-BROKEN",
        source_url="https://yuyu-tei.jp/inventory/broken",
        review_status="approved",
    )
    db_session.add_all(
        [
            exact_yuyu_a,
            exact_snkr_b,
            exact_snkr_a_other_card,
            legacy,
            entityless,
            invalid_exact,
        ]
    )
    db_session.flush()

    unique_snapshot = RawSnapshot(
        source_id=yuyutei.id,
        source_url=exact_yuyu_a.source_url,
        http_status=200,
        content_hash="unique-snapshot",
        raw_content="not loaded by inventory",
    )
    ambiguous_snapshot = RawSnapshot(
        source_id=snkrdunk.id,
        source_url=exact_snkr_b.source_url,
        http_status=200,
        content_hash="ambiguous-snapshot",
        raw_content="not loaded by inventory",
    )
    unique_candidate = SnkrdunkCandidate(
        source_url=exact_snkr_b.source_url,
        match_status="matched",
    )
    ambiguous_candidate = SnkrdunkCandidate(
        source_url=exact_snkr_a_other_card.source_url,
        match_status="matched",
    )
    db_session.add_all(
        [
            unique_snapshot,
            ambiguous_snapshot,
            unique_candidate,
            ambiguous_candidate,
        ]
    )
    db_session.flush()

    exact_observation = _observation(
        yuyutei.id,
        card_id=card_a.id,
        source_card_mapping_id=exact_yuyu_a.id,
        card_print_id=print_a.id,
    )
    broken_observation = _observation(
        yuyutei.id,
        card_id=card_a.id,
        source_card_mapping_id=exact_yuyu_a.id,
        card_print_id=print_b.id,
    )
    unique_snapshot_observation = _observation(
        yuyutei.id,
        card_id=card_a.id,
        raw_snapshot_id=unique_snapshot.id,
    )
    unique_candidate_observation = _observation(
        snkrdunk.id,
        card_id=card_a.id,
        candidate_id=unique_candidate.id,
    )
    ambiguous_observation = _observation(
        snkrdunk.id,
        card_id=card_a.id,
        raw_snapshot_id=ambiguous_snapshot.id,
        candidate_id=ambiguous_candidate.id,
    )
    legacy_observation = _observation(yuyutei.id, card_id=card_a.id)
    entityless_observation = _observation(yuyutei.id, card_id=None)
    db_session.add_all(
        [
            exact_observation,
            broken_observation,
            unique_snapshot_observation,
            unique_candidate_observation,
            ambiguous_observation,
            legacy_observation,
            entityless_observation,
        ]
    )
    db_session.commit()

    return {
        "mappings": {
            "exact": exact_yuyu_a,
            "legacy": legacy,
            "entityless": entityless,
            "invalid": invalid_exact,
        },
        "observations": {
            "exact": exact_observation,
            "broken": broken_observation,
            "unique_snapshot": unique_snapshot_observation,
            "unique_candidate": unique_candidate_observation,
            "ambiguous": ambiguous_observation,
            "legacy": legacy_observation,
            "entityless": entityless_observation,
        },
        "cards": {"a": card_a, "b": card_b},
        "prints": {"a": print_a, "b": print_b},
    }


def _sample_ids(report, section: str, category: str) -> set[int]:
    return set(report.to_dict()[section]["categories"][category]["sample_ids"])


def test_mapping_and_observation_categories(inventory_rows, db_session):
    report = build_historical_lineage_inventory(
        db_session,
        sample_limit=20,
        now=datetime(2026, 9, 15, tzinfo=timezone.utc),
    )
    payload = report.to_dict()

    assert {
        category: bucket["count"]
        for category, bucket in payload["mappings"]["categories"].items()
    } == {
        "exact_valid": 3,
        "exact_but_invalid": 1,
        "legacy_card_only": 1,
        "entityless": 1,
    }
    assert {
        category: bucket["count"]
        for category, bucket in payload["observations"]["categories"].items()
    } == {
        "exact": 1,
        "exact_broken": 1,
        "unique_evidence_candidate": 2,
        "ambiguous": 1,
        "legacy_only": 1,
        "entityless": 1,
    }

    mappings = inventory_rows["mappings"]
    assert mappings["exact"].id in _sample_ids(report, "mappings", "exact_valid")
    assert mappings["invalid"].id in _sample_ids(
        report, "mappings", "exact_but_invalid"
    )
    assert mappings["legacy"].id in _sample_ids(
        report, "mappings", "legacy_card_only"
    )
    assert mappings["entityless"].id in _sample_ids(
        report, "mappings", "entityless"
    )

    observations = inventory_rows["observations"]
    assert observations["exact"].id in _sample_ids(report, "observations", "exact")
    assert observations["broken"].id in _sample_ids(
        report, "observations", "exact_broken"
    )
    assert observations["legacy"].id in _sample_ids(
        report, "observations", "legacy_only"
    )
    assert observations["entityless"].id in _sample_ids(
        report, "observations", "entityless"
    )


def test_immutable_url_provenance_is_conservative(inventory_rows, db_session):
    report = build_historical_lineage_inventory(db_session, sample_limit=20)
    observations = inventory_rows["observations"]

    unique = _sample_ids(report, "observations", "unique_evidence_candidate")
    assert observations["unique_snapshot"].id in unique
    assert observations["unique_candidate"].id in unique
    assert observations["ambiguous"].id in _sample_ids(
        report, "observations", "ambiguous"
    )

    signals = report.to_dict()["observations"]["provenance_signals"]
    assert signals == {
        "raw_snapshot_references": 2,
        "resolved_raw_snapshots": 2,
        "candidate_references": 2,
        "resolved_candidates": 2,
        "observations_with_usable_url_evidence": 3,
    }


def test_snkrdunk_published_url_forms_share_exact_listing_identity(
    inventory_rows, db_session
):
    mapping = SourceCardMapping(
        card_id=inventory_rows["cards"]["a"].id,
        source_id=inventory_rows["observations"]["unique_candidate"].source_id,
        card_print_id=inventory_rows["prints"]["a"].id,
        source_card_id="SNK-4242",
        source_url="https://snkrdunk.com/apparels/4242",
        review_status="approved",
    )
    candidate = SnkrdunkCandidate(
        source_url=(
            "https://snkrdunk.com/en/trading-cards/4242"
            "?slide=right&query_id=inventory"
        ),
        match_status="matched",
    )
    db_session.add_all([mapping, candidate])
    db_session.flush()
    observation = _observation(
        mapping.source_id,
        card_id=mapping.card_id,
        candidate_id=candidate.id,
    )
    db_session.add(observation)
    db_session.commit()

    report = build_historical_lineage_inventory(db_session, sample_limit=20)

    assert observation.id in _sample_ids(
        report, "observations", "unique_evidence_candidate"
    )


def test_multiple_mappings_for_one_provenance_identity_are_ambiguous(
    inventory_rows, db_session
):
    source_id = inventory_rows["observations"]["unique_candidate"].source_id
    mapping_a = SourceCardMapping(
        card_id=inventory_rows["cards"]["a"].id,
        source_id=source_id,
        card_print_id=inventory_rows["prints"]["a"].id,
        source_card_id="SNK-9898-JP",
        source_url="https://snkrdunk.com/apparels/9898",
        review_status="approved",
    )
    mapping_b = SourceCardMapping(
        card_id=inventory_rows["cards"]["a"].id,
        source_id=source_id,
        card_print_id=inventory_rows["prints"]["b"].id,
        source_card_id="SNK-9898-EN",
        source_url="https://snkrdunk.com/en/trading-cards/9898",
        review_status="approved",
    )
    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/en/trading-cards/9898?query_id=inventory",
        match_status="matched",
    )
    db_session.add_all([mapping_a, mapping_b, candidate])
    db_session.flush()
    observation = _observation(
        source_id,
        card_id=inventory_rows["cards"]["a"].id,
        candidate_id=candidate.id,
    )
    db_session.add(observation)
    db_session.commit()

    report = build_historical_lineage_inventory(db_session, sample_limit=20)

    assert observation.id in _sample_ids(report, "observations", "ambiguous")


def test_compatibility_conflicts_are_reported_without_choosing_a_card(
    inventory_rows, db_session
):
    report = build_historical_lineage_inventory(db_session, sample_limit=20).to_dict()
    conflicts = report["mappings"]["compatibility_conflicts"]

    by_print = conflicts["card_print_with_multiple_card_ids"]
    assert by_print["count"] == 1
    assert by_print["samples"][0]["card_print_id"] == inventory_rows["prints"]["a"].id
    assert by_print["samples"][0]["card_ids"] == sorted(
        [inventory_rows["cards"]["a"].id, inventory_rows["cards"]["b"].id]
    )

    by_card = conflicts["card_with_multiple_card_print_ids"]
    assert by_card["count"] == 1
    assert by_card["samples"][0]["card_id"] == inventory_rows["cards"]["a"].id
    assert by_card["samples"][0]["card_print_ids"] == sorted(
        [inventory_rows["prints"]["a"].id, inventory_rows["prints"]["b"].id]
    )
    assert conflicts["total_groups"] == 2


def test_output_has_source_counts_and_capped_samples(inventory_rows, db_session):
    report = build_historical_lineage_inventory(db_session, sample_limit=1).to_dict()

    assert report["read_only"] is True
    assert "not automatically safe to backfill" in report["provenance_notice"]
    assert report["mappings"]["total"] == 6
    assert report["observations"]["total"] == 7
    assert set(report["mappings"]["by_source"]) == {"snkrdunk", "yuyutei"}
    assert set(report["observations"]["by_source"]) == {"snkrdunk", "yuyutei"}
    assert all(
        len(bucket["sample_ids"]) <= 1
        for bucket in report["observations"]["categories"].values()
    )


def test_inventory_executes_selects_only_and_does_not_mutate_rows(
    inventory_rows, db_session
):
    mapping = inventory_rows["mappings"]["legacy"]
    observation = inventory_rows["observations"]["legacy"]
    before = (
        mapping.card_id,
        mapping.card_print_id,
        mapping.review_status,
        observation.card_id,
        observation.card_print_id,
        observation.source_card_mapping_id,
    )
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().upper())

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        build_historical_lineage_inventory(db_session)
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    db_session.refresh(mapping)
    db_session.refresh(observation)
    after = (
        mapping.card_id,
        mapping.card_print_id,
        mapping.review_status,
        observation.card_id,
        observation.card_print_id,
        observation.source_card_mapping_id,
    )
    assert after == before
    assert statements
    assert all(statement.startswith("SELECT") for statement in statements)
    assert all("RAW_CONTENT" not in statement for statement in statements)
    assert all("RAW_TEXT" not in statement for statement in statements)
    assert all("IMAGE_URL" not in statement for statement in statements)
    assert not db_session.new
    assert not db_session.dirty
    assert not db_session.deleted


def test_inventory_does_not_autoflush_callers_pending_changes(
    inventory_rows, db_session
):
    mapping = inventory_rows["mappings"]["legacy"]
    original_status = mapping.review_status
    mapping.review_status = "rejected"
    pending_mapping = SourceCardMapping(
        card_id=inventory_rows["cards"]["a"].id,
        source_id=mapping.source_id,
        source_card_id="PENDING-NOT-FLUSHED",
        source_url="https://yuyu-tei.jp/inventory/pending-not-flushed",
        review_status="needs_review",
    )
    db_session.add(pending_mapping)
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lstrip().upper())

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        build_historical_lineage_inventory(db_session)
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert statements
    assert all(statement.startswith("SELECT") for statement in statements)
    assert mapping in db_session.dirty
    assert mapping.review_status != original_status
    assert pending_mapping in db_session.new
    assert pending_mapping.id is None


def test_cli_outputs_the_structured_inventory(
    inventory_rows, db_session, monkeypatch, capsys
):
    cli_session_factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, autocommit=False
    )
    monkeypatch.setattr(inventory_cli, "SessionLocal", cli_session_factory)

    assert inventory_cli.main(["--sample-limit", "1", "--compact"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["read_only"] is True
    assert payload["sample_limit"] == 1
    assert payload["mappings"]["total"] == 6
    assert payload["observations"]["total"] == 7
