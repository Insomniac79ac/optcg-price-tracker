import argparse
from dataclasses import dataclass, field

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    Card,
    PriceObservation,
    RawSnapshot,
    SnkrdunkCandidate,
    SnkrdunkDiscoveryRun,
    SourceCardMapping,
)
from app.seed import seed_sources
from app.settings import settings

DEV_ENVIRONMENT_VALUE = "development"

# ORM-backed tables, deleted in FK-safe order (children before parents).
MODEL_DELETE_ORDER: list[tuple[str, type]] = [
    ("price_observations", PriceObservation),
    ("raw_snapshots", RawSnapshot),
    ("source_card_mappings", SourceCardMapping),
    ("snkrdunk_candidates", SnkrdunkCandidate),
    ("snkrdunk_discovery_runs", SnkrdunkDiscoveryRun),
    ("cards", Card),
]

# Tables from a possible future Yuyu-Tei discovery pipeline (mirroring the
# SNKRDUNK one). Deleted only if present, so this script doesn't break before
# those tables exist.
OPTIONAL_TABLES = ["yuyutei_candidates", "yuyutei_discovery_runs"]


@dataclass
class ResetSummary:
    deleted: dict[str, int] = field(default_factory=dict)
    skipped_missing_tables: list[str] = field(default_factory=list)
    sources_reseeded: bool = False

    def print_report(self) -> None:
        for table_name, count in self.deleted.items():
            print(f"deleted {table_name}: {count}")
        for table_name in self.skipped_missing_tables:
            print(f"skipped {table_name}: table does not exist")
        print(f"sources_reseeded: {self.sources_reseeded}")


def _is_development_environment() -> bool:
    env = (settings.ENVIRONMENT or settings.APP_ENV or "").strip().lower()
    return env == DEV_ENVIRONMENT_VALUE


def reset_dev_db(db: Session, confirm: bool = False, reseed_sources: bool = True) -> ResetSummary:
    """Deletes local dev data (cards, mappings, snapshots, price observations,
    SNKRDUNK discovery data). Refuses to run without explicit confirmation,
    and refuses to run outside a development environment - this is
    destructive and must never touch a real database."""
    if not confirm:
        raise RuntimeError(
            "Refusing to reset the database: pass confirm=True (CLI: --confirm)."
        )

    if not _is_development_environment():
        raise RuntimeError(
            "Refusing to reset the database: ENVIRONMENT or APP_ENV must be "
            f"'{DEV_ENVIRONMENT_VALUE}' (got ENVIRONMENT={settings.ENVIRONMENT!r}, "
            f"APP_ENV={settings.APP_ENV!r})."
        )

    summary = ResetSummary()

    for table_name, model in MODEL_DELETE_ORDER:
        summary.deleted[table_name] = db.query(model).delete(synchronize_session=False)

    # Inspect the session's own live connection (not a fresh engine-level
    # connection) so schema reflection shares the in-flight transaction
    # instead of opening a second one - a separate connection would tear
    # itself down with a ROLLBACK that, on a pooled/shared connection (e.g.
    # SQLite StaticPool in tests), wipes out the deletes above.
    existing_tables = set(inspect(db.connection()).get_table_names())
    for table_name in OPTIONAL_TABLES:
        if table_name not in existing_tables:
            summary.skipped_missing_tables.append(table_name)
            continue
        result = db.execute(text(f"DELETE FROM {table_name}"))
        summary.deleted[table_name] = result.rowcount

    if reseed_sources:
        seed_sources(db)
        summary.sources_reseeded = True

    db.commit()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete local dev data (cards, source mappings, raw snapshots, price "
        "observations, SNKRDUNK discovery data). Only runs when ENVIRONMENT or APP_ENV is "
        "'development'. Never deletes user CSV files - only database rows."
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Required. Confirms you intend to delete local dev data.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        try:
            summary = reset_dev_db(db, confirm=args.confirm)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from None
    finally:
        db.close()

    summary.print_report()


if __name__ == "__main__":
    main()
