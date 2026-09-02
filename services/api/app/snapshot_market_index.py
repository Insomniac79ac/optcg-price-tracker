"""Writes today's exact-print Market Index snapshots - one immutable row per
active, verified, *priced* card_print per UTC day (see
app.models.market_index_snapshot, and select_snapshottable_print_ids below for
what "priced" means and why verified alone stopped being enough).

Operational shape mirrors app.snapshot_portfolio_valuation: SessionLocal, a
named job lock, a --dry-run flag, and a plain-text report on stdout. Intended
to be invoked once a day by a scheduler, comfortably after both collectors
have finished their own runs.

What this module does NOT do
-----------------------------
It does not calculate a Market Index. Every number it stores comes from
app.services.print_market_index.get_market_index_for_prints - the exact same
function GET /prints/{id}/market-index and the print catalogue call - so a
snapshot can never disagree with what the API served at that moment. Nothing
here reimplements eligibility, medians, rounding, staleness or source
semantics, and nothing here should ever start to: if a stored value looks
wrong, the calculation is wrong, and this module must keep faithfully
recording it rather than quietly correcting it.

It also offers no --date and no backfill. Snapshots are written forward only,
for the current UTC day, because a past day's index is not recomputable - see
the model's "No backfill".

Idempotency
------------
Insertion is ON CONFLICT (card_print_id, snapshot_date) DO NOTHING. A second
run on the same UTC day writes nothing and changes nothing; the first
snapshot of a day is the one Atlas stands behind. There is deliberately no
upsert and no UPDATE anywhere in this module - a retry after a partial
failure fills in only the prints that are still missing, and never touches a
row that already exists.
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import CardPrint, MarketIndexSnapshot, PriceObservation, Source
from app.schemas import PrintMarketIndexOut
from app.services.job_locks import LockHeldError, with_job_lock
from app.services.print_market_index import (
    INDEX_EVIDENCE_PRICE_TYPES,
    get_market_index_for_prints,
)

LOCK_NAME = "market_index_snapshot"


@dataclass
class SnapshotRunResult:
    """Plain summary of one job run, safe to read after the session has been
    committed or rolled back (same reasoning as RefreshRunSummary in the
    worker's refresh job - no ORM instances escape the session)."""

    snapshot_date: date | None
    calculated_at: datetime | None
    prints_selected: int
    rows_created: int
    rows_skipped_existing: int
    dry_run: bool

    def report_lines(self) -> list[str]:
        return [
            f"snapshot_date: {self.snapshot_date}",
            f"calculated_at: {self.calculated_at}",
            f"prints_selected: {self.prints_selected}",
            f"rows_created: {self.rows_created}",
            f"rows_skipped_existing: {self.rows_skipped_existing}",
            f"dry_run: {self.dry_run}",
        ]


def _has_market_facing_observation():
    """EXISTS: this print carries at least one market-facing pricing
    observation - a price that could represent Market Index evidence.

    The (source, price_type) pairs come from
    app.services.print_market_index.INDEX_EVIDENCE_PRICE_TYPES, which that
    module derives from the resolver's own inputs by removing the
    auxiliary-only ones. Nothing about sources or price types is decided here;
    this function only asks the question in SQL.

    A MAPPING IS NOT EVIDENCE. An approved, active source mapping says Atlas
    knows which product on a source corresponds to this print - it is an
    identity claim, and it is made before any collector has run. Qualifying a
    print on a mapping would mean that approving mappings across the imported
    catalogue creates thousands of valueless immutable rows on the next
    nightly run, which is the same failure the verified-only predicate had,
    reached one step later. A print enters its own price history when a price
    is first observed for it, not when someone decides where to look.

    Deliberately "has evidence", not "has ELIGIBLE evidence": freshness
    windows, the sold-sample minimum and the SNKRDUNK platform-floor rule all
    live in the resolver and are re-evaluated on every run. A stale or
    platform-constrained observation still means a market-facing price was
    genuinely observed for this print, so it keeps recording a row - whose
    index value may legitimately be NULL - rather than vanishing from its own
    history on the day its data aged out. Restating any of those thresholds
    here would be the second, drifting rule this module exists to avoid.
    """
    return (
        select(PriceObservation.id)
        .join(Source, Source.id == PriceObservation.source_id)
        .where(
            PriceObservation.card_print_id == CardPrint.id,
            or_(
                *[
                    and_(
                        Source.name == source_name,
                        PriceObservation.price_type.in_(price_types),
                    )
                    for source_name, price_types in INDEX_EVIDENCE_PRICE_TYPES.items()
                ]
            ),
        )
        .exists()
    )


def select_snapshottable_print_ids(db: Session) -> list[int]:
    """Every active, verified card_print that Atlas actually prices.

    Active and verified remain necessary - they are the same two predicates
    the collectors gate their writes on (see yuyutei_collector/
    snkrdunk_collector batch.select_eligible_mappings and
    writer.validate_mapping_for_write, which refuse to anchor an observation
    to a print that is not verified), and a demoted print must still drop
    out. They are no longer sufficient.

    WHY THEY STOPPED BEING SUFFICIENT. This function used to select on
    verified alone, justified by the claim that "a print outside this set
    cannot have accumulated exact-print observations in the first place".
    That held while every verified print was one an operator had hand-
    verified and mapped to a price source. After the Bandai catalogue import
    (4D-8) *verified* means "Bandai published this printing", not "Atlas
    prices this printing": 4,281 prints are verified and 20 carry pricing
    evidence. Selecting on verified alone would have written 4,261
    coverage_status="none" rows every day - rows that are, by the model's own
    "No backfill" contract, immutable once written and therefore not
    correctable by a later, better-behaved run.

    WHAT REPLACES IT. A print qualifies when at least one market-facing
    pricing observation exists for it - see _has_market_facing_observation,
    which takes its source and price_type rules from
    app.services.print_market_index.INDEX_EVIDENCE_PRICE_TYPES rather than
    restating them. A print without one produces no row at all, which is the
    honest answer: Atlas has never observed a price for it and never claimed
    to.

    Note what is NOT in the predicate. Not a source mapping - that is an
    identity claim made before any price exists, and the next phase will
    approve mappings across the imported catalogue, so admitting them would
    reintroduce mass valueless rows one step later. Not current eligibility -
    a stale or platform-constrained observation is still an observation, and
    the row it produces may legitimately carry a NULL index value.

    Nothing is hardcoded: eligibility is entirely a database query, so a print
    is picked up on the run after its first observation lands and drops out if
    it is deactivated or demoted - the same self-maintaining property the
    verified-only predicate had. Deterministic order (print id ascending) so a
    run against unchanged state always builds rows in the same sequence.
    """
    stmt = (
        select(CardPrint.id)
        .where(
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
            _has_market_facing_observation(),
        )
        .order_by(CardPrint.id.asc())
    )
    return list(db.scalars(stmt).all())


def _as_utc(value: datetime) -> datetime:
    """Normalize a payload timestamp to an aware UTC instant.

    _compute_index_fields already returns calculated_at as aware UTC, and
    observed_at values come back aware from Postgres - but tz-naive from the
    SQLite the test suite runs on (the same split app.services.market_index._naive_utc
    exists to absorb). Treating a naive value as UTC here matches how every
    other module in the pricing path reads these columns, and keeps
    snapshot_date derivation correct on both backends.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _eligible_contributors(market_index: PrintMarketIndexOut) -> list:
    """The ADMISSIBLE source_values - every one that is usable evidence.

    Predicate is `eligible and value_jpy is not None`, character-for-character
    the one _compute_index_fields uses to build its own `admissible` list.
    Asked of the returned payload rather than recomputed from observations, so
    the set behind a stored freshness bound can never describe different values
    than the stored source_price_range it sits beside.

    NOT the same set as the v2 index contributors, and deliberately so. The two
    columns this feeds - freshest_eligible_source_at and
    stalest_eligible_source_at - bound the freshness of the evidence the
    snapshot DISPLAYS, which is the same set source_price_range spans; that is
    what their names have always meant and what every already-written row
    records. Narrowing them to contributors would silently redefine a column
    across historical rows that no migration touched. Which values actually
    entered the aggregate is recorded per-value in the provenance archive's
    `contributes_to_index`, and read from there by
    app.services.market_index_change.

    auxiliary_values are never consulted here: they are by definition never
    eligible for the index (Yuyu-Tei dealer buy is the current example), so
    letting one widen a freshness bound would describe the index as resting on
    evidence it explicitly excluded.
    """
    return [
        sv
        for sv in market_index.source_values
        if sv.eligible and sv.value_jpy is not None
    ]


def build_snapshot_row(market_index: PrintMarketIndexOut) -> dict:
    """One market_index_snapshots row, as a plain dict of column values.

    Every index field is copied verbatim from the payload - including
    index_version and source_semantics_version, which are taken as *emitted*
    rather than re-read from the INDEX_VERSION/SOURCE_SEMANTICS_VERSION
    constants. That distinction matters: the row must record which ruleset
    actually produced the number, so that a future release whose constants
    have moved on cannot retroactively relabel an older snapshot.

    Only three things are derived rather than copied, and each is derived from
    the payload alone:
      - snapshot_date, the UTC calendar date of calculated_at
      - the flattened source_price_range low/high pair
      - the two eligible-contributor freshness bounds
    """
    eligible = _eligible_contributors(market_index)
    observed_ats = [
        _as_utc(sv.observed_at) for sv in eligible if sv.observed_at is not None
    ]
    # Both bounds come from the same eligible list, so they can never bracket
    # different evidence than index_value_jpy rests on. freshest is therefore
    # NOT market_index.freshest_observation_at, which deliberately spans every
    # source_value including ineligible ones for display purposes - a stale or
    # platform-floor-constrained observation must not be able to make a
    # snapshot look better-evidenced than it was.
    freshest = max(observed_ats) if observed_ats else None
    stalest = min(observed_ats) if observed_ats else None

    price_range = market_index.source_price_range

    calculated_at = _as_utc(market_index.calculated_at)

    # Built complete, in one expression, and only then handed to the row dict
    # below - never assigned first and mutated afterwards. In-place mutation
    # of an already-assigned JSON structure is silently dropped by SQLAlchemy
    # (no UPDATE is emitted for it), which here would mean writing a
    # provenance archive missing exactly the entries added last.
    provenance = {
        "source_values": [
            sv.model_dump(mode="json") for sv in market_index.source_values
        ],
        "auxiliary_values": [
            av.model_dump(mode="json") for av in market_index.auxiliary_values
        ],
    }

    return {
        "card_print_id": market_index.card_print_id,
        "calculated_at": calculated_at,
        "snapshot_date": calculated_at.date(),
        "index_value_jpy": market_index.index_value_jpy,
        "calculation_method": market_index.calculation_method,
        "source_count": market_index.source_count,
        "coverage_status": market_index.coverage_status,
        "confidence": market_index.confidence,
        "source_price_range_low_jpy": price_range.low_jpy if price_range else None,
        "source_price_range_high_jpy": price_range.high_jpy if price_range else None,
        "index_version": market_index.index_version,
        "source_semantics_version": market_index.source_semantics_version,
        "freshest_eligible_source_at": freshest,
        "stalest_eligible_source_at": stalest,
        "provenance": provenance,
    }


def _insert_ignoring_existing(db: Session, rows: list[dict]) -> None:
    """One multi-row INSERT ... ON CONFLICT (card_print_id, snapshot_date) DO
    NOTHING - the whole job's write, in a single atomic statement.

    The dialect-specific insert() construct is required because
    on_conflict_do_nothing is not on the generic sqlalchemy.insert(); both
    Postgres (staging/production) and SQLite (tests) implement it with the
    same signature, and no other backend is supported by this repository.

    DO NOTHING, never DO UPDATE: the conflict case is "this print already has
    today's snapshot", and that row is by contract the one Atlas stands
    behind. Suppressing the write is the correct outcome, not a fallback.
    """
    if not rows:
        return

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:  # pragma: no cover - no other backend is used by this service
        raise RuntimeError(
            f"market_index_snapshot insert does not support dialect {dialect!r}; "
            "expected postgresql or sqlite."
        )

    stmt = dialect_insert(MarketIndexSnapshot.__table__).values(rows)
    db.execute(
        stmt.on_conflict_do_nothing(index_elements=["card_print_id", "snapshot_date"])
    )


def _count_for_date(db: Session, snapshot_date: date) -> int:
    return db.scalar(
        select(func.count())
        .select_from(MarketIndexSnapshot)
        .where(MarketIndexSnapshot.snapshot_date == snapshot_date)
    )


def snapshot_market_index(
    db: Session, *, dry_run: bool = False, skip_lock: bool = False
) -> SnapshotRunResult:
    """Snapshots today's Market Index for every active verified print.

    Acquires the 'market_index_snapshot' concurrency lock for the call (see
    'Worker job concurrency locking' in docs/operations.md). skip_lock is
    test/dev-CLI only, never exposed to the admin UI/API - same convention as
    snapshot_portfolio_valuation.

    The entire run is one transaction: one batch calculation, one INSERT, one
    commit. A failure part-way therefore leaves no partial day behind, and
    since the calculation is a single get_market_index_for_prints call every
    row shares one calculated_at.
    """
    with with_job_lock(LOCK_NAME, skip_lock=skip_lock):
        return _snapshot_market_index_locked(db, dry_run=dry_run)


def _snapshot_market_index_locked(db: Session, *, dry_run: bool) -> SnapshotRunResult:
    print_ids = select_snapshottable_print_ids(db)
    if not print_ids:
        return SnapshotRunResult(
            snapshot_date=None,
            calculated_at=None,
            prints_selected=0,
            rows_created=0,
            rows_skipped_existing=0,
            dry_run=dry_run,
        )

    # One batch call for every print - get_market_index_for_prints issues a
    # fixed number of queries regardless of how many ids it is given, and
    # loops of the single-print variant would be an N+1 against the exact
    # helper built to avoid it.
    indexes = get_market_index_for_prints(db, print_ids)

    rows = [build_snapshot_row(indexes[print_id]) for print_id in print_ids]
    snapshot_date = rows[0]["snapshot_date"]
    calculated_at = rows[0]["calculated_at"]

    if dry_run:
        # Nothing is inserted and nothing is committed. The rollback discards
        # any state the read queries left on the session, so a --dry-run can
        # never leave a write behind even if this function is extended later.
        db.rollback()
        return SnapshotRunResult(
            snapshot_date=snapshot_date,
            calculated_at=calculated_at,
            prints_selected=len(print_ids),
            rows_created=0,
            rows_skipped_existing=0,
            dry_run=True,
        )

    # Measured rather than inferred from rowcount: with ON CONFLICT DO
    # NOTHING, "rows attempted" and "rows actually written" differ, and
    # rowcount's meaning for a partially-ignored multi-row insert is not
    # something to rely on across two dialects. Counting before and after
    # gives the true number on both.
    before = _count_for_date(db, snapshot_date)
    _insert_ignoring_existing(db, rows)
    db.commit()
    after = _count_for_date(db, snapshot_date)

    created = after - before
    return SnapshotRunResult(
        snapshot_date=snapshot_date,
        calculated_at=calculated_at,
        prints_selected=len(print_ids),
        rows_created=created,
        rows_skipped_existing=len(rows) - created,
        dry_run=False,
    )


def print_report(result: SnapshotRunResult) -> None:
    for line in result.report_lines():
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Snapshot today's exact-print Market Index for every active verified "
            "print. Writes forward only - there is no backfill and no --date."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate and report without writing any snapshot rows.",
    )
    parser.add_argument(
        "--skip-lock",
        action="store_true",
        help=(
            "Skip the market_index_snapshot concurrency lock. Test/dev only - "
            "never use in production."
        ),
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        try:
            result = snapshot_market_index(
                db, dry_run=args.dry_run, skip_lock=args.skip_lock
            )
        except LockHeldError as exc:
            print(f"Job already running: {exc.lock_name}")
            sys.exit(2)
    finally:
        db.close()

    print_report(result)


if __name__ == "__main__":
    main()
