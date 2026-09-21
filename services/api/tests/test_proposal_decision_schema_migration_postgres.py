"""PostgreSQL contract coverage for proposal-decision audit revision a7f936027b8f.

The database is disposable and local. The tests never connect to staging.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError


ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
DATABASE = "opcg_test_proposal_decision_schema"
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"
DATABASE_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
PREVIOUS = "f4c8a2d91b60"
REVISION = "a7f936027b8f"

DECISION_COLUMNS = {
    "reviewed_at",
    "reviewed_by",
    "review_notes",
    "selected_alternative_id",
    "decision_basis_updated_at",
}


def _alembic(*args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _seed_previous_revision(engine) -> dict[str, object]:
    with engine.begin() as conn:
        source_id = conn.scalar(
            text("SELECT id FROM sources WHERE name = 'snkrdunk'")
        )
        release_id = conn.scalar(
            text(
                "INSERT INTO release_products "
                "(source_catalogue, official_code, display_name, first_seen_name, "
                " source_series_id, source_url, verification_status) "
                "VALUES ('bandai_jp', 'TEST-DECISION', 'Decision test', "
                "        'Decision test', 'decision-test', "
                "        'https://example.test/releases/decision', 'verified') "
                "RETURNING id"
            )
        )
        card_id = conn.scalar(
            text(
                "INSERT INTO canonical_cards (card_code, name_en, card_type) "
                "VALUES ('TEST-001', 'Decision test card', 'Character') RETURNING id"
            )
        )
        print_ids = [
            conn.scalar(
                text(
                    "INSERT INTO card_prints "
                    "(canonical_card_id, language, release_product_code, release_product_id, "
                    " artwork_key, official_asset_variant, verification_status, is_active) "
                    "VALUES (:card_id, 'jp', 'TEST-DECISION', :release_id, :artwork, "
                    "        :variant, 'verified', true) RETURNING id"
                ),
                {
                    "card_id": card_id,
                    "release_id": release_id,
                    "artwork": f"sha256:decision:{variant}",
                    "variant": variant,
                },
            )
            for variant in ("base", "p1")
        ]
        group_ids = []
        alternative_ids = []
        for number in (1, 2):
            group_id = conn.scalar(
                text(
                    "INSERT INTO source_mapping_proposal_groups "
                    "(source_id, canonical_source_listing_identity, source_url, "
                    " source_candidate_type, source_candidate_id, canonical_card_id, "
                    " release_product_id, resolution_status, review_status, resolver_version, "
                    " evidence_digest, evidence_summary_json, resolution_reasons_json) "
                    "VALUES (:source_id, :identity, :url, 'snkrdunk_candidate', :candidate_id, "
                    "        :card_id, :release_id, 'exact', 'pending', "
                    "        'source-mapping-proposals/1.0', :digest, '{}'::json, '[]'::json) "
                    "RETURNING id"
                ),
                {
                    "source_id": source_id,
                    "identity": f"migration-pending-{number}",
                    "url": f"https://example.test/listings/migration-{number}",
                    "candidate_id": number,
                    "card_id": card_id,
                    "release_id": release_id,
                    "digest": f"{number:064x}",
                },
            )
            alternative_id = conn.scalar(
                text(
                    "INSERT INTO source_mapping_proposal_alternatives "
                    "(proposal_group_id, card_print_id, recommended, supporting_evidence_json, "
                    " missing_evidence_json, conflict_reasons_json, review_disposition) "
                    "VALUES (:group_id, :print_id, true, '[]'::json, '[]'::json, "
                    "        '[]'::json, 'pending') RETURNING id"
                ),
                {"group_id": group_id, "print_id": print_ids[0]},
            )
            group_ids.append(group_id)
            alternative_ids.append(alternative_id)
        return {
            "source_id": source_id,
            "release_id": release_id,
            "card_id": card_id,
            "print_ids": print_ids,
            "group_ids": group_ids,
            "alternative_ids": alternative_ids,
        }


def _proposal_fingerprint(conn) -> tuple[list[tuple], list[tuple]]:
    groups = conn.execute(
        text(
            "SELECT id, source_id, canonical_source_listing_identity, source_candidate_id, "
            "       review_status, resolver_version, evidence_digest, "
            "       resulting_source_card_mapping_id "
            "FROM source_mapping_proposal_groups ORDER BY id"
        )
    ).all()
    alternatives = conn.execute(
        text(
            "SELECT id, proposal_group_id, card_print_id, recommended, review_disposition "
            "FROM source_mapping_proposal_alternatives ORDER BY id"
        )
    ).all()
    return list(groups), list(alternatives)


@pytest.fixture(scope="module")
def migrated():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{DATABASE}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip(f"No disposable PostgreSQL at {HOST}:{PORT}")

    engine = create_engine(DATABASE_URL)
    _alembic("upgrade", PREVIOUS)
    seed = _seed_previous_revision(engine)
    with engine.connect() as conn:
        before = _proposal_fingerprint(conn)

    _alembic("upgrade", REVISION)
    with engine.connect() as conn:
        after_first_upgrade = _proposal_fingerprint(conn)
        null_decisions = conn.scalar(
            text(
                "SELECT count(*) FROM source_mapping_proposal_groups WHERE "
                "reviewed_at IS NULL AND reviewed_by IS NULL AND review_notes IS NULL AND "
                "selected_alternative_id IS NULL AND decision_basis_updated_at IS NULL"
            )
        )

    _alembic("downgrade", PREVIOUS)
    columns_after_downgrade = {
        column["name"]
        for column in inspect(engine).get_columns("source_mapping_proposal_groups")
    }
    with engine.connect() as conn:
        after_downgrade = _proposal_fingerprint(conn)

    _alembic("upgrade", REVISION)
    with engine.connect() as conn:
        after_second_upgrade = _proposal_fingerprint(conn)

    try:
        yield {
            "engine": engine,
            "seed": seed,
            "before": before,
            "after_first_upgrade": after_first_upgrade,
            "null_decisions": null_decisions,
            "columns_after_downgrade": columns_after_downgrade,
            "after_downgrade": after_downgrade,
            "after_second_upgrade": after_second_upgrade,
        }
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)'))
        admin.dispose()


def _insert_pending(conn, migrated, identity: str, *, alternatives: int = 1):
    seed = migrated["seed"]
    digest = hashlib.sha256(identity.encode()).hexdigest()
    group_id = conn.scalar(
        text(
            "INSERT INTO source_mapping_proposal_groups "
            "(source_id, canonical_source_listing_identity, source_url, "
            " source_candidate_type, source_candidate_id, canonical_card_id, "
            " release_product_id, resolution_status, review_status, resolver_version, "
            " evidence_digest, evidence_summary_json, resolution_reasons_json) "
            "VALUES (:source_id, :identity, :url, 'snkrdunk_candidate', 9001, :card_id, "
            "        :release_id, 'exact', 'pending', 'source-mapping-proposals/1.0', "
            "        :digest, '{}'::json, '[]'::json) RETURNING id"
        ),
        {
            "source_id": seed["source_id"],
            "identity": identity,
            "url": f"https://example.test/listings/{identity}",
            "card_id": seed["card_id"],
            "release_id": seed["release_id"],
            "digest": digest,
        },
    )
    alternative_ids = []
    for print_id in seed["print_ids"][:alternatives]:
        alternative_ids.append(
            conn.scalar(
                text(
                    "INSERT INTO source_mapping_proposal_alternatives "
                    "(proposal_group_id, card_print_id, recommended, supporting_evidence_json, "
                    " missing_evidence_json, conflict_reasons_json, review_disposition) "
                    "VALUES (:group_id, :print_id, true, '[]'::json, '[]'::json, "
                    "        '[]'::json, 'pending') RETURNING id"
                ),
                {"group_id": group_id, "print_id": print_id},
            )
        )
    return group_id, alternative_ids


def _insert_mapping(conn, migrated, identity: str) -> int:
    seed = migrated["seed"]
    return conn.scalar(
        text(
            "INSERT INTO source_card_mappings "
            "(source_id, card_print_id, source_card_id, source_url, manual_verified, "
            " is_active, review_status) "
            "VALUES (:source_id, :print_id, :source_card_id, :url, true, true, 'approved') "
            "RETURNING id"
        ),
        {
            "source_id": seed["source_id"],
            "print_id": seed["print_ids"][0],
            "source_card_id": identity,
            "url": f"https://example.test/mappings/{identity}",
        },
    )


def _approve_group(conn, group_id: int, alternative_id: int, mapping_id: int) -> None:
    conn.execute(
        text(
            "UPDATE source_mapping_proposal_alternatives SET "
            "review_disposition = 'approved', reviewed_at = now() WHERE id = :alt"
        ),
        {"alt": alternative_id},
    )
    conn.execute(
        text(
            "UPDATE source_mapping_proposal_groups SET review_status = 'approved', "
            "reviewed_at = now(), reviewed_by = 'admin@example.test', "
            "selected_alternative_id = :alt, decision_basis_updated_at = updated_at, "
            "resulting_source_card_mapping_id = :mapping WHERE id = :group_id"
        ),
        {"alt": alternative_id, "mapping": mapping_id, "group_id": group_id},
    )


def test_pending_rows_survive_upgrade_downgrade_upgrade_without_backfill(migrated):
    assert migrated["before"] == migrated["after_first_upgrade"]
    assert migrated["before"] == migrated["after_downgrade"]
    assert migrated["before"] == migrated["after_second_upgrade"]
    assert migrated["null_decisions"] == 2
    assert DECISION_COLUMNS.isdisjoint(migrated["columns_after_downgrade"])


def test_migration_installs_named_constraints_and_partial_index(migrated):
    engine = migrated["engine"]
    with engine.connect() as conn:
        constraint_names = set(
            conn.scalars(
                text(
                    "SELECT conname FROM pg_constraint WHERE conname IN ("
                    "'ck_mapping_proposal_groups_decision_lifecycle', "
                    "'fk_mapping_proposal_groups_selected_alternative_same_group', "
                    "'uq_mapping_proposal_alternatives_id_group')"
                )
            )
        )
        indexdef = conn.scalar(
            text(
                "SELECT indexdef FROM pg_indexes WHERE indexname = "
                "'uq_mapping_proposal_alternatives_one_approved_per_group'"
            )
        )
    assert constraint_names == {
        "ck_mapping_proposal_groups_decision_lifecycle",
        "fk_mapping_proposal_groups_selected_alternative_same_group",
        "uq_mapping_proposal_alternatives_id_group",
    }
    assert "UNIQUE" in indexdef
    assert "review_disposition" in indexdef and "approved" in indexdef


def test_decision_columns_are_nullable_without_server_defaults(migrated):
    engine = migrated["engine"]
    with engine.connect() as conn:
        columns = {
            name: (is_nullable, column_default, data_type)
            for name, is_nullable, column_default, data_type in conn.execute(
                text(
                    "SELECT column_name, is_nullable, column_default, data_type "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'source_mapping_proposal_groups' "
                    "AND column_name IN ('reviewed_at', 'reviewed_by', 'review_notes', "
                    "'selected_alternative_id', 'decision_basis_updated_at')"
                )
            ).all()
        }
        deferrable, initially_deferred = conn.execute(
            text(
                "SELECT condeferrable, condeferred FROM pg_constraint WHERE conname = "
                "'fk_mapping_proposal_groups_selected_alternative_same_group'"
            )
        ).one()
    assert set(columns) == DECISION_COLUMNS
    assert all(nullable == "YES" and default is None for nullable, default, _ in columns.values())
    assert columns["reviewed_at"][2] == "timestamp with time zone"
    assert columns["decision_basis_updated_at"][2] == "timestamp with time zone"
    assert deferrable is True and initially_deferred is True


def test_valid_approved_state_and_same_group_selection_commit(migrated):
    engine = migrated["engine"]
    with engine.begin() as conn:
        group_id, alternatives = _insert_pending(conn, migrated, "valid-approved")
        mapping_id = _insert_mapping(conn, migrated, "valid-approved")
        _approve_group(conn, group_id, alternatives[0], mapping_id)
        conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    with engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT review_status, selected_alternative_id, "
                "resulting_source_card_mapping_id, reviewed_by "
                "FROM source_mapping_proposal_groups WHERE id = :id"
            ),
            {"id": group_id},
        ).one() == (
            "approved",
            alternatives[0],
            mapping_id,
            "admin@example.test",
        )


def test_valid_rejected_state_commits(migrated):
    engine = migrated["engine"]
    with engine.begin() as conn:
        group_id, _ = _insert_pending(conn, migrated, "valid-rejected")
        conn.execute(
            text(
                "UPDATE source_mapping_proposal_groups SET review_status = 'rejected', "
                "reviewed_at = now(), reviewed_by = 'admin@example.test', "
                "review_notes = 'Insufficient source evidence', "
                "decision_basis_updated_at = updated_at WHERE id = :id"
            ),
            {"id": group_id},
        )


INVALID_UPDATES = (
    pytest.param(
        "review_status = 'approved', reviewed_at = now(), "
        "reviewed_by = 'admin@example.test', selected_alternative_id = :alt, "
        "decision_basis_updated_at = updated_at",
        id="approved-without-resulting-mapping",
    ),
    pytest.param(
        "review_status = 'approved', reviewed_at = now(), "
        "reviewed_by = 'admin@example.test', decision_basis_updated_at = updated_at, "
        "resulting_source_card_mapping_id = :mapping",
        id="approved-without-selected-alternative",
    ),
    pytest.param(
        "review_status = 'approved', reviewed_at = now(), reviewed_by = '   ', "
        "selected_alternative_id = :alt, decision_basis_updated_at = updated_at, "
        "resulting_source_card_mapping_id = :mapping",
        id="approved-with-blank-reviewer",
    ),
    pytest.param(
        "review_status = 'approved', reviewed_by = 'admin@example.test', "
        "selected_alternative_id = :alt, decision_basis_updated_at = updated_at, "
        "resulting_source_card_mapping_id = :mapping",
        id="approved-without-review-time",
    ),
    pytest.param(
        "review_status = 'rejected', reviewed_at = now(), "
        "reviewed_by = 'admin@example.test', review_notes = '   ', "
        "decision_basis_updated_at = updated_at",
        id="rejected-without-nonblank-reason",
    ),
    pytest.param(
        "review_status = 'rejected', reviewed_at = now(), "
        "reviewed_by = 'admin@example.test', review_notes = 'reason', "
        "decision_basis_updated_at = updated_at, "
        "resulting_source_card_mapping_id = :mapping",
        id="rejected-with-resulting-mapping",
    ),
    pytest.param("reviewed_at = now()", id="pending-with-review-metadata"),
    pytest.param(
        "resulting_source_card_mapping_id = :mapping",
        id="pending-with-resulting-mapping",
    ),
    pytest.param("selected_alternative_id = :alt", id="pending-with-selected-alternative"),
)


@pytest.mark.parametrize("assignments", INVALID_UPDATES)
def test_invalid_lifecycle_shapes_fail_at_database_boundary(migrated, assignments):
    engine = migrated["engine"]
    connection = engine.connect()
    transaction = connection.begin()
    try:
        group_id, alternatives = _insert_pending(connection, migrated, "invalid-shape")
        mapping_id = _insert_mapping(connection, migrated, "invalid-shape")
        with pytest.raises(IntegrityError, match="decision_lifecycle"):
            connection.execute(
                text(
                    f"UPDATE source_mapping_proposal_groups SET {assignments} "
                    "WHERE id = :group_id"
                ),
                {
                    "group_id": group_id,
                    "alt": alternatives[0],
                    "mapping": mapping_id,
                },
            )
    finally:
        transaction.rollback()
        connection.close()


def test_cross_group_selected_alternative_fails(migrated):
    engine = migrated["engine"]
    connection = engine.connect()
    transaction = connection.begin()
    try:
        first_group, _ = _insert_pending(connection, migrated, "same-group-owner")
        _second_group, second_alternatives = _insert_pending(
            connection, migrated, "different-group-owner"
        )
        mapping_id = _insert_mapping(connection, migrated, "cross-group")
        connection.execute(
            text(
                "UPDATE source_mapping_proposal_groups SET review_status = 'approved', "
                "reviewed_at = now(), reviewed_by = 'admin@example.test', "
                "selected_alternative_id = :alt, decision_basis_updated_at = updated_at, "
                "resulting_source_card_mapping_id = :mapping WHERE id = :group_id"
            ),
            {
                "alt": second_alternatives[0],
                "mapping": mapping_id,
                "group_id": first_group,
            },
        )
        with pytest.raises(IntegrityError, match="selected_alternative_same_group"):
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    finally:
        transaction.rollback()
        connection.close()


def test_two_approved_alternatives_in_one_group_fail(migrated):
    engine = migrated["engine"]
    connection = engine.connect()
    transaction = connection.begin()
    try:
        _group_id, alternatives = _insert_pending(
            connection, migrated, "two-approved-alternatives", alternatives=2
        )
        connection.execute(
            text(
                "UPDATE source_mapping_proposal_alternatives "
                "SET review_disposition = 'approved' WHERE id = :id"
            ),
            {"id": alternatives[0]},
        )
        with pytest.raises(
            IntegrityError,
            match="uq_mapping_proposal_alternatives_one_approved_per_group",
        ):
            connection.execute(
                text(
                    "UPDATE source_mapping_proposal_alternatives "
                    "SET review_disposition = 'approved' WHERE id = :id"
                ),
                {"id": alternatives[1]},
            )
    finally:
        transaction.rollback()
        connection.close()


def test_multiple_pending_or_rejected_alternatives_remain_valid(migrated):
    engine = migrated["engine"]
    connection = engine.connect()
    transaction = connection.begin()
    try:
        _group_id, alternatives = _insert_pending(
            connection, migrated, "multiple-non-approved", alternatives=2
        )
        assert len(alternatives) == 2
        connection.execute(
            text(
                "UPDATE source_mapping_proposal_alternatives SET "
                "review_disposition = 'rejected', review_notes = 'Not selected', "
                "reviewed_at = now() WHERE id = ANY(:ids)"
            ),
            {"ids": alternatives},
        )
    finally:
        transaction.rollback()
        connection.close()
