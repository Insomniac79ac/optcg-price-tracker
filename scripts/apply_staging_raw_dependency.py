#!/usr/bin/env python3
"""One allowlisted additive migration inside the serialized staging lease.

No general SQL/revision override, source job, config change or evidence rewrite.
The ordinary state generator retains its strict repository-head default. Only
this checksum-pinned transition accepts its reviewed parent for the BEFORE
observation; both observations record the actual database revision.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

import generate_staging_state as state
import staging_db_read_check as guard

PARENT = "c4e8a1d7b902"
REVISION = "e8c2d4f6a901"
MIGRATION = (
    "services/api/alembic/versions/e8c2d4f6a901_protect_raw_dictionary_dependencies.py"
)


def selection(manifest):
    requested = manifest.get("deployment_verification", {}).get(
        "raw_dependency_migration"
    )
    if requested is None:
        return None
    if (
        manifest.get("target") != "staging"
        or manifest.get("classification") != "AMBER"
        or requested.get("revision") != REVISION
        or requested.get("parent") != PARENT
        or requested.get("file") != MIGRATION
        or set(requested) != {"revision", "parent", "file", "sha256"}
        or manifest["deployment_verification"]["revision"] != REVISION
    ):
        raise state.VerificationError("Unapproved RAW dependency migration")
    path = state.ROOT / MIGRATION
    if hashlib.sha256(path.read_bytes()).hexdigest() != requested["sha256"]:
        raise state.VerificationError("Reviewed migration checksum mismatch")
    return requested


def require_writers_off(service_id):
    values = state.command_json(
        [
            "railway",
            "variable",
            "list",
            "-p",
            state.PROJECT,
            "-e",
            state.ENVIRONMENT,
            "-s",
            service_id,
            "--json",
        ]
    )
    try:
        if (
            values.get("APP_ENV") not in (None, "staging")
            or values.get("RAILWAY_ENVIRONMENT_ID") != state.ENVIRONMENT
            or values.get("RAW_DICTIONARY_STORAGE_ENABLED", "false").lower() != "false"
        ):
            raise state.VerificationError(
                "Pinned staging writer OFF required before schema delivery"
            )
    finally:
        values.clear()


def migrate(connection, migration_path):
    """Execute only this additive revision in the caller's bounded transaction."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    connection.execute(text("SET LOCAL lock_timeout='2s'"))
    connection.execute(text("SET LOCAL statement_timeout='30s'"))
    if not connection.scalar(text("SELECT pg_try_advisory_xact_lock(734027411)")):
        raise state.VerificationError("RAW schema migration lease unavailable")
    revisions = (
        connection.execute(text("SELECT version_num FROM alembic_version FOR UPDATE"))
        .scalars()
        .all()
    )
    if revisions == [REVISION]:
        validate_schema(connection)
        return False
    if (
        revisions != [PARENT]
        or connection.scalar(text("SELECT to_regclass('raw_snapshot_dictionaries')"))
        is not None
    ):
        raise state.VerificationError(
            "RAW dependency schema is not the reviewed parent"
        )
    spec = importlib.util.spec_from_file_location(
        "reviewed_raw_dependency_migration", migration_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.revision != REVISION or module.down_revision != PARENT:
        raise state.VerificationError("RAW migration revision identity mismatch")
    # Bind this reviewed module to this exact connection. Do not depend on
    # process-global Alembic facade functions (which may be replaced by tests
    # or another migration runner in the importing process).
    module.op = Operations(MigrationContext.configure(connection))
    module.upgrade()
    result = connection.execute(
        text("UPDATE alembic_version SET version_num=:new WHERE version_num=:old"),
        {"new": REVISION, "old": PARENT},
    )
    if result.rowcount != 1:
        raise state.VerificationError("RAW migration revision update was not singular")
    validate_schema(connection)
    if connection.scalar(text("SELECT count(*) FROM raw_snapshot_dictionaries")) != 0:
        raise state.VerificationError("Additive dependency table must begin empty")
    return True


def validate_schema(connection):
    from sqlalchemy import inspect

    inspector = inspect(connection)
    columns = {
        column["name"] for column in inspector.get_columns("raw_snapshot_dictionaries")
    }
    expected = {
        "id",
        "base_snapshot_id",
        "original_sha256",
        "base_sha256",
        "original_bytes",
        "encoded_bytes",
        "created_at",
        "expanded_at",
    }
    foreign_keys = inspector.get_foreign_keys("raw_snapshot_dictionaries")
    if (
        columns != expected
        or len(foreign_keys) != 2
        or {tuple(key["constrained_columns"]) for key in foreign_keys}
        != {("id",), ("base_snapshot_id",)}
        or any(
            key["referred_table"] != "raw_snapshots"
            or key["options"].get("ondelete") != "RESTRICT"
            for key in foreign_keys
        )
    ):
        raise state.VerificationError("RAW dependency schema protection mismatch")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text())
    if selection(manifest) is None:
        return 0
    if not re.fullmatch("[0-9a-f]{40}", args.expected):
        raise state.VerificationError("Full merged revision required")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    branch = state.command_json(
        ["gh", "api", f"repos/{state.REPOSITORY}/branches/staging"]
    )
    if head != args.expected or branch["commit"]["sha"] != args.expected:
        raise state.VerificationError("Obsolete or unmerged RAW migration checkout")
    allowed = frozenset({PARENT, REVISION})
    before = state.collect_live(database_expected_revisions=allowed)
    state.write_snapshot(before, state.CANONICAL_OUTPUT)
    services = before["railway"]["services"]
    writers = [
        row["service_id"]
        for row in services
        if row["name"] == "optcg-price-tracker"
        or row["name"] == "snkrdunk-collector"
        or row["name"].startswith("yuyutei-collector-shard-")
    ]
    if len(writers) != 11 or len(set(writers)) != 11:
        raise state.VerificationError(
            "Complete existing staging writer census required"
        )
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(require_writers_off, writers))
    proxies = state.railway(
        f'query {{ tcpProxies(environmentId:"{state.ENVIRONMENT}",serviceId:"{state.POSTGRES}") {{ domain proxyPort applicationPort }} }}'
    )["tcpProxies"]
    if len(proxies) != 1 or proxies[0]["applicationPort"] != 5432:
        raise state.VerificationError("Staging database endpoint ambiguous")
    values = state.command_json(
        [
            "railway",
            "variable",
            "list",
            "-p",
            state.PROJECT,
            "-e",
            state.ENVIRONMENT,
            "-s",
            state.POSTGRES,
            "--json",
        ]
    )
    try:
        from sqlalchemy import URL, create_engine

        url = URL.create(
            "postgresql+psycopg",
            username=values["PGUSER"],
            password=values["PGPASSWORD"],
            host=proxies[0]["domain"],
            port=proxies[0]["proxyPort"],
            database=values["PGDATABASE"],
        )
        engine = create_engine(
            url,
            connect_args={"connect_timeout": 15, "options": "-c search_path=public"},
        )
        try:
            with engine.begin() as connection:
                # Before switching this transaction to writes, repeat all
                # database fingerprints on the exact connection being mutated.
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                checks = guard.evaluate(
                    guard.collect_facts(connection.connection.driver_connection),
                    allowed,
                )
                if not all(check.ok for check in checks):
                    raise state.VerificationError(
                        "Staging database migration fingerprint failed"
                    )
            with engine.begin() as connection:
                changed = migrate(connection, state.ROOT / MIGRATION)
        finally:
            engine.dispose()
    except state.VerificationError:
        raise
    except Exception as exc:
        raise state.VerificationError(
            "RAW additive migration failed: " + type(exc).__name__
        ) from None
    finally:
        values.clear()
    after = state.collect_live()
    state.write_snapshot(after, state.CANONICAL_OUTPUT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "status": "SUCCESS",
                "observed_at": state.timestamp(),
                "environment_id": state.ENVIRONMENT,
                "postgres_service_id": state.POSTGRES,
                "merged_sha": args.expected,
                "revision": REVISION,
                "changed": changed,
                "before_collected_at": before["collected_at"],
                "after_collected_at": after["collected_at"],
                "existing_evidence_rewritten": 0,
                "source_requests": 0,
                "writers_enabled": False,
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except state.VerificationError as exc:
        raise SystemExit(str(exc))
