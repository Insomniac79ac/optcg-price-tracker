"""Persisted mock archive and real C1B0 receipts for forward publication tests."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.market_value_writer import run_writer
from app.models import CanonicalCard, CardPrint, MarketIndexSnapshot, ReleaseProduct
from app.models.job_lock import JobLock
from app.models.market_index_snapshot_completion import MarketIndexSnapshotCompletion
from app.models.market_value_point import MarketValuePoint
from app.services.market_index_completion import (
    CONTENT_FIELDS,
    batch_facts,
)

D25, D26, D27, D28, D29 = (date(2026, 9, n) for n in range(25, 30))


def stamp(day):
    return datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)


def table_rows(db, model):
    rows = tuple(
        tuple(row) for row in db.execute(select(model.__table__).order_by(model.id))
    )
    db.rollback()
    return rows


def receipt(db, day):
    t = MarketIndexSnapshot.__table__
    rows = list(
        db.execute(
            select(*(t.c[key] for key in CONTENT_FIELDS)).where(
                t.c.snapshot_date == day
            )
        ).mappings()
    )
    db.add(
        MarketIndexSnapshotCompletion(
            **batch_facts(rows, day),
            expected_print_count=len(rows),
            completed_at=stamp(day) + timedelta(seconds=1),
            run_id=f"fixture-{day}",
            receipt_kind="atomic",
        )
    )
    db.commit()


def seed(db, receipt_days=(D29,), *, published=True, repeating=False):
    db.add(
        ReleaseProduct(
            id=1,
            source_catalogue="bandai_jp",
            official_code="OP-01",
            display_name="Mock release",
            first_seen_name="Mock release",
            source_series_id="forward-test",
            source_url="https://example.invalid/release",
            verification_status="verified",
        )
    )
    for pid in range(1, 5):
        db.add(
            CanonicalCard(
                id=pid,
                card_code=f"OP01-{pid:03}",
                name_en=f"Mock {pid}",
                card_type="CHARACTER",
            )
        )
    db.flush()
    for pid in range(1, 5):
        db.add(
            CardPrint(
                id=pid,
                canonical_card_id=pid,
                language="jp",
                release_product_id=1,
                artwork_key="a" * 64,
                official_asset_variant="base",
                verification_status="verified",
                is_active=True,
            )
        )
    db.flush()
    for day in (D25, D26, D27, D28, D29):
        for pid in range(1, 5):
            # SQLite cannot retain 50-digit repeating decimals. Exercise exact
            # binary ratios there; PostgreSQL also exercises repeating ratios.
            value = (
                (day.day - 20) * 100 + pid * 10
                if repeating
                else pid * 100 * 2 ** (day.day - 25)
            )
            db.add(
                MarketIndexSnapshot(
                    card_print_id=pid,
                    snapshot_date=day,
                    calculated_at=stamp(day),
                    index_value_jpy=value,
                    calculation_method="median",
                    source_count=1,
                    coverage_status="full",
                    confidence="high",
                    index_version=3,
                    source_semantics_version=2,
                    provenance={
                        "source_values": [
                            {
                                "source": "yuyutei",
                                "reference_type": "retail_ask",
                                "contributes_to_index": True,
                                "value_jpy": value,
                            }
                        ],
                        "auxiliary_values": [],
                    },
                )
            )
    db.add(
        JobLock(
            lock_name="market_index_snapshot",
            owner_id="mock-producer",
            acquired_at=stamp(D25),
            expires_at=stamp(D26),
            released_at=stamp(D26),
            status="released",
        )
    )
    db.commit()
    for day in receipt_days:
        receipt(db, day)
    if published:
        run_writer(db, mode="write", through=D26, skip_lock=True)


def archive_state(db):
    return {
        model.__tablename__: table_rows(db, model)
        for model in (
            MarketIndexSnapshot,
            MarketIndexSnapshotCompletion,
            MarketValuePoint,
        )
    }
