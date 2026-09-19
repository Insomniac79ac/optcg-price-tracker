from __future__ import annotations

import json
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.db import Base
from app.models import (
    CanonicalCard,
    CardPirateIndexPoint,
    CardPrint,
    MarketIndexSnapshot,
    PriceObservation,
    RawSnapshot,
    ReleaseProduct,
    SnkrdunkCandidate,
    SourceCardMapping,
    SourceCollectionAttempt,
)
from app.services.backup import (
    BACKUP_REGISTRY,
    BACKUP_VERSION,
    RAW_PROVENANCE_INCLUDED,
    RAW_PROVENANCE_OMITTED,
    REQUIRED_TABLES,
    TABLE_INSERT_ORDER,
    backup_registry_errors,
    export_backup,
    restore_backup,
    validate_backup,
)
from app.services.system_check import _check_backup_tables_included
from tests._backup_exact_lineage_helpers import seed_exact_lineage


def exact_archive(*, include_prices: bool = False) -> dict:
    tables: dict[str, list[dict]] = {table: [] for table in REQUIRED_TABLES}
    tables.update(
        canonical_cards=[{"id": 1}],
        release_products=[{"id": 1}],
        card_prints=[
            {
                "id": 1,
                "canonical_card_id": 1,
                "release_product_id": 1,
                "verification_status": "verified",
            }
        ],
        sources=[{"id": 1}],
        source_card_mappings=[
            {"id": 1, "card_id": None, "source_id": 1, "card_print_id": 1}
        ],
    )
    if include_prices:
        tables.update(
            price_observations=[
                {
                    "id": 1,
                    "card_id": None,
                    "source_id": 1,
                    "source_card_mapping_id": 1,
                    "card_print_id": 1,
                    "candidate_id": 1,
                    "raw_snapshot_id": None,
                }
            ],
            source_collection_attempts=[],
            market_index_snapshots=[{"id": 1, "card_print_id": 1}],
            card_pirate_index_points=[],
            snkrdunk_candidates=[{"id": 1, "discovery_run_id": None}],
        )
    return {
        "metadata": {
            "app": "opcg-price-tracker",
            "backup_version": BACKUP_VERSION,
            "created_at": "2026-09-16T12:00:00+00:00",
            "include_prices": include_prices,
            "include_raw_snapshots": False,
            "include_refresh_runs": False,
            "include_logs": False,
            "include_validation_reports": False,
            "raw_snapshot_provenance": {
                "mode": RAW_PROVENANCE_OMITTED,
                "price_observation_references_nullified": 0,
                "source_collection_attempt_references_nullified": 0,
            },
        },
        "tables": tables,
    }


def test_modern_exact_mapping_with_null_legacy_card_validates():
    result = validate_backup(exact_archive())

    assert result.valid is True
    assert result.summary["source_card_mappings_exact"] == 1
    assert result.summary["source_card_mappings_legacy_compatibility"] == 0


def test_mapping_with_missing_card_print_is_rejected():
    archive = exact_archive()
    archive["tables"]["source_card_mappings"][0]["card_print_id"] = 999

    result = validate_backup(archive)

    assert result.valid is False
    assert any("missing card_print_id 999" in error for error in result.errors)


def test_observation_mapping_print_mismatch_is_rejected():
    archive = exact_archive(include_prices=True)
    archive["tables"]["card_prints"].append(
        {
            "id": 2,
            "canonical_card_id": 1,
            "release_product_id": 1,
            "verification_status": "verified",
        }
    )
    archive["tables"]["price_observations"][0]["card_print_id"] = 2

    result = validate_backup(archive)

    assert result.valid is False
    assert any("does not match source_card_mapping_id" in error for error in result.errors)


def test_observation_source_mapping_mismatch_is_rejected():
    archive = exact_archive(include_prices=True)
    archive["tables"]["sources"].append({"id": 2})
    archive["tables"]["price_observations"][0]["source_id"] = 2

    result = validate_backup(archive)

    assert result.valid is False
    assert any("source_id 2 does not match" in error for error in result.errors)


def test_observation_with_missing_candidate_parent_is_rejected():
    archive = exact_archive(include_prices=True)
    archive["tables"]["snkrdunk_candidates"] = []

    result = validate_backup(archive)

    assert result.valid is False
    assert any("missing candidate_id 1" in error for error in result.errors)


def test_market_index_snapshot_with_missing_print_is_rejected():
    archive = exact_archive(include_prices=True)
    archive["tables"]["market_index_snapshots"][0]["card_print_id"] = 999

    result = validate_backup(archive)

    assert result.valid is False
    assert any(
        "market_index_snapshots[0] references missing card_print_id 999" in error
        for error in result.errors
    )


def test_grandfathered_card_only_mapping_is_explicit_compatibility_record():
    archive = exact_archive()
    archive["tables"]["cards"] = [{"id": 7}]
    archive["tables"]["source_card_mappings"].append(
        {"id": 2, "card_id": 7, "source_id": 1, "card_print_id": None}
    )

    result = validate_backup(archive)

    assert result.valid is True
    assert result.summary["source_card_mappings_exact"] == 1
    assert result.summary["source_card_mappings_legacy_compatibility"] == 1
    assert any("not modern exact-pricing lineage" in warning for warning in result.warnings)


def test_current_archive_missing_identity_parent_table_is_rejected():
    archive = exact_archive()
    del archive["tables"]["canonical_cards"]

    result = validate_backup(archive)

    assert result.valid is False
    assert "Missing required table: canonical_cards" in result.errors


def test_current_archive_unknown_table_is_rejected():
    archive = exact_archive()
    archive["tables"]["silently_ignored_table"] = []

    result = validate_backup(archive)

    assert result.valid is False
    assert any("Unknown table" in error for error in result.errors)


def test_old_version_is_rejected_instead_of_reinterpreted_as_current():
    archive = exact_archive()
    archive["metadata"]["backup_version"] = BACKUP_VERSION - 1

    result = validate_backup(archive)

    assert result.valid is False
    assert any("Unsupported backup_version" in error for error in result.errors)


def test_registry_is_fk_safe_and_has_required_exact_lineage_order():
    order = {table: position for position, table in enumerate(TABLE_INSERT_ORDER)}
    modern_tables = {
        "canonical_cards",
        "release_products",
        "release_product_aliases",
        "card_prints",
        "sources",
        "raw_snapshots",
        "snkrdunk_discovery_runs",
        "snkrdunk_candidates",
        "yuyutei_discovery_runs",
        "yuyutei_candidates",
        "source_card_mappings",
        "price_observations",
        "source_collection_attempts",
        "market_index_snapshots",
        "card_pirate_index_points",
    }

    assert backup_registry_errors() == []
    assert len(BACKUP_REGISTRY) == len(TABLE_INSERT_ORDER)
    assert modern_tables <= set(TABLE_INSERT_ORDER)
    assert order["canonical_cards"] < order["card_prints"]
    assert order["release_products"] < order["card_prints"]
    assert order["sources"] < order["source_card_mappings"]
    assert order["card_prints"] < order["source_card_mappings"]
    assert order["snkrdunk_discovery_runs"] < order["snkrdunk_candidates"]
    assert order["yuyutei_discovery_runs"] < order["yuyutei_candidates"]
    assert order["snkrdunk_candidates"] < order["price_observations"]
    assert order["source_card_mappings"] < order["price_observations"]
    assert order["raw_snapshots"] < order["price_observations"]
    assert order["price_observations"] < order["source_collection_attempts"]
    assert order["card_prints"] < order["market_index_snapshots"]
    assert order["market_index_snapshots"] < order["card_pirate_index_points"]


def test_system_check_uses_the_authoritative_registry():
    check = _check_backup_tables_included(None)

    assert check.status == "pass"
    assert f"All {len(BACKUP_REGISTRY)} registered tables" in check.message


@pytest.mark.parametrize("include_raw_snapshots", [True, False])
def test_exact_lineage_clean_database_round_trip(include_raw_snapshots):
    source_engine = create_engine("sqlite:///:memory:")
    target_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(source_engine)
    Base.metadata.create_all(target_engine)
    SessionFactory = sessionmaker(autoflush=False, autocommit=False)

    try:
        with SessionFactory(bind=source_engine) as source_session:
            ids = seed_exact_lineage(source_session)
            exported = export_backup(
                source_session,
                include_prices=True,
                include_raw_snapshots=include_raw_snapshots,
            )

            # Excluding bodies transforms the archive only, never source rows.
            source_observation = source_session.get(PriceObservation, ids["observation_id"])
            source_attempt = source_session.get(SourceCollectionAttempt, ids["attempt_id"])
            assert source_observation.raw_snapshot_id == ids["raw_snapshot_id"]
            assert source_attempt.raw_snapshot_id == ids["raw_snapshot_id"]

        # Exercise the real JSON boundary; NUMERIC index values must not leak
        # as Python Decimal objects that json.dumps cannot encode.
        archive = json.loads(json.dumps(exported))
        validation = validate_backup(archive)
        assert validation.valid is True, validation.errors

        raw_metadata = archive["metadata"]["raw_snapshot_provenance"]
        if include_raw_snapshots:
            assert raw_metadata == {
                "mode": RAW_PROVENANCE_INCLUDED,
                "price_observation_references_nullified": 0,
                "source_collection_attempt_references_nullified": 0,
            }
            assert archive["tables"]["price_observations"][0]["raw_snapshot_id"] == ids[
                "raw_snapshot_id"
            ]
            assert archive["tables"]["source_collection_attempts"][0][
                "raw_snapshot_id"
            ] == ids["raw_snapshot_id"]
        else:
            assert "raw_snapshots" not in archive["tables"]
            assert raw_metadata == {
                "mode": RAW_PROVENANCE_OMITTED,
                "price_observation_references_nullified": 1,
                "source_collection_attempt_references_nullified": 1,
            }
            assert archive["tables"]["price_observations"][0]["raw_snapshot_id"] is None
            assert archive["tables"]["source_collection_attempts"][0][
                "raw_snapshot_id"
            ] is None

        with SessionFactory(bind=target_engine) as target_session:
            restored = restore_backup(
                target_session,
                archive,
                dry_run=False,
                mode="merge",
                skip_lock=True,
            )
            assert restored.valid is True, restored.errors

            exact_mapping = target_session.get(
                SourceCardMapping, ids["exact_mapping_id"]
            )
            legacy_mapping = target_session.get(
                SourceCardMapping, ids["legacy_mapping_id"]
            )
            observation = target_session.get(
                PriceObservation, ids["observation_id"]
            )
            attempt = target_session.get(SourceCollectionAttempt, ids["attempt_id"])
            canonical = target_session.get(CanonicalCard, ids["canonical_card_id"])
            product = target_session.get(ReleaseProduct, ids["release_product_id"])
            card_print = target_session.get(CardPrint, ids["card_print_id"])

            assert canonical.id == ids["canonical_card_id"]
            assert product.id == ids["release_product_id"]
            assert card_print.canonical_card_id == canonical.id
            assert card_print.release_product_id == product.id
            assert exact_mapping.card_id is None
            assert exact_mapping.card_print_id == ids["card_print_id"]
            assert legacy_mapping.card_id == ids["legacy_card_id"]
            assert legacy_mapping.card_print_id is None
            assert observation.card_id is None
            assert observation.source_card_mapping_id == ids["exact_mapping_id"]
            assert observation.card_print_id == ids["card_print_id"]
            assert observation.source_id == ids["source_id"]
            assert observation.candidate_id == ids["candidate_id"]
            assert target_session.get(SnkrdunkCandidate, ids["candidate_id"])
            assert target_session.get(MarketIndexSnapshot, ids["market_snapshot_id"])
            assert target_session.get(CardPirateIndexPoint, ids["pirate_point_id"])
            restored_raw_snapshot = target_session.scalar(select(RawSnapshot).limit(1))
            if include_raw_snapshots:
                assert restored_raw_snapshot is not None
            else:
                assert restored_raw_snapshot is None
            expected_snapshot_id = ids["raw_snapshot_id"] if include_raw_snapshots else None
            assert observation.raw_snapshot_id == expected_snapshot_id
            assert attempt.raw_snapshot_id == expected_snapshot_id
            restored_point = target_session.get(
                CardPirateIndexPoint, ids["pirate_point_id"]
            )
            assert restored_point.index_value == Decimal("1000.0000")
    finally:
        Base.metadata.drop_all(source_engine)
        Base.metadata.drop_all(target_engine)
        source_engine.dispose()
        target_engine.dispose()
