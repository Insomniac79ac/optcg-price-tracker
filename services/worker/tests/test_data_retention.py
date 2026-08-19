"""worker.data_retention - mirrors app.services.data_retention on the api
service (see that module's docstring for the full policy). These tests
focus on the protections most likely to break in a hand-duplicated copy:
latest-price and open/watching-signal-event protection, and the confirm
gate - the exhaustive per-table policy coverage lives in the api service's
tests/test_data_retention.py, since the logic is identical."""

from datetime import datetime, timedelta, timezone

import pytest

from worker.data_retention import PruneConfirmationRequired, prune_tables
from worker.models import Card, MarketSignalEvent, PriceObservation, RawSnapshot, Source

NOW = datetime.now(timezone.utc)


def make_card(db_session) -> Card:
    card = Card(card_code="OP01-001", name_en=None, name_jp=None, set_code="OP01", rarity="L", variant=None, language="en")
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_source(db_session, name: str = "yuyutei") -> Source:
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def test_apply_without_confirm_raises(db_session):
    with pytest.raises(PruneConfirmationRequired):
        prune_tables(db_session, dry_run=False, tables=["raw_snapshots"], now=NOW)


def test_dry_run_does_not_delete(db_session):
    source = make_source(db_session)
    db_session.add(
        RawSnapshot(
            source_id=source.id, source_url="https://example.com/1",
            fetched_at=NOW - timedelta(days=100), http_status=200,
            content_hash="old", raw_content="<html></html>",
        )
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["raw_snapshots"], now=NOW)

    assert result.results[0].rows_would_delete == 1
    assert db_session.query(RawSnapshot).count() == 1


def test_latest_price_observation_is_protected(db_session):
    card = make_card(db_session)
    source = make_source(db_session)
    db_session.add(
        PriceObservation(
            card_id=card.id, source_id=source.id, price_type="sell", price_jpy=100,
            observed_at=NOW - timedelta(days=500),
        )
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["price_observations"], now=NOW)

    assert result.results[0].rows_would_delete == 0


def print_observation(card, source, card_print_id, *, price_jpy, observed_at):
    """A print-linked observation. worker.models mirrors card_print_id /
    source_card_mapping_id as plain nullable Integers (the api's
    b858237e3706 migration owns the real constraints), so no CardPrint row
    is needed here - but the two are still only ever set together, matching
    ck_price_observations_lineage_paired."""
    return PriceObservation(
        card_id=card.id,
        source_id=source.id,
        card_print_id=card_print_id,
        source_card_mapping_id=card_print_id,
        price_type="sell",
        price_jpy=price_jpy,
        observed_at=observed_at,
    )


_THINNING_COLUMNS = ["id", "card_id", "card_print_id", "source_id", "price_type", "observed_at"]


class _ReversedRows:
    """Stands in for a Result whose .all() hands the rows back reversed."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def reverse_thinning_fetch(db_session, monkeypatch):
    """Make the daily-thinning fetch return its rows in reverse-id order, so
    the tie tests below actually pin the tiebreak on SQLite (which otherwise
    returns rows in rowid order and agrees with id-ASC by accident). Matched
    by exact column list, so only the thinning SELECT is touched. Mirrors the
    api service's helper of the same name."""
    real_execute = db_session.execute

    def execute(statement, *args, **kwargs):
        columns = getattr(statement, "selected_columns", None)
        if columns is not None and [c.name for c in columns] == _THINNING_COLUMNS:
            return _ReversedRows(real_execute(statement, *args, **kwargs).all()[::-1])
        return real_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", execute)


def test_sibling_prints_each_keep_their_own_latest_observation(db_session):
    """Two exact prints bridging through ONE legacy card_id are separate
    series. Pre-fix, protection partitioned by card_id alone, so only the
    newer print's row was protected and the other print was pruned to
    nothing. Mirrors the api service's test of the same name."""
    card = make_card(db_session)
    source = make_source(db_session)

    db_session.add_all(
        [
            print_observation(card, source, 11, price_jpy=100, observed_at=NOW - timedelta(days=500)),
            print_observation(card, source, 22, price_jpy=900, observed_at=NOW - timedelta(days=400)),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["price_observations"], now=NOW)

    assert result.results[0].rows_would_delete == 0


def test_sibling_prints_are_thinned_independently(db_session):
    """Daily thinning groups per exact print. Pre-fix, print 22's single row
    for the day joined print 11's three in one card_id-keyed group and was
    thinned away."""
    card = make_card(db_session)
    source = make_source(db_session)

    base_day = (NOW - timedelta(days=200)).replace(hour=0, minute=0, second=0, microsecond=0)
    db_session.add_all(
        [
            print_observation(card, source, 11, price_jpy=100, observed_at=base_day),
            print_observation(
                card, source, 11, price_jpy=110, observed_at=base_day + timedelta(hours=4)
            ),
            print_observation(
                card, source, 11, price_jpy=120, observed_at=base_day + timedelta(hours=8)
            ),
            # Print 22's only row that day, deliberately the latest of the four.
            print_observation(
                card, source, 22, price_jpy=5000, observed_at=base_day + timedelta(hours=12)
            ),
            # Recent rows so the above aren't protected as their series' latest.
            print_observation(card, source, 11, price_jpy=130, observed_at=NOW - timedelta(days=1)),
            print_observation(card, source, 22, price_jpy=5500, observed_at=NOW - timedelta(days=1)),
        ]
    )
    db_session.commit()

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2  # only print 11's own day is thinned

    remaining = db_session.query(PriceObservation).all()
    assert sorted(o.price_jpy for o in remaining if o.card_print_id == 11) == [100, 130]
    assert sorted(o.price_jpy for o in remaining if o.card_print_id == 22) == [5000, 5500]


def test_legacy_observations_without_print_lineage_group_by_legacy_card(db_session):
    """card_print_id IS NULL rows keep their historical per-legacy-card
    grouping, and are never merged with a print series on the same card."""
    card = make_card(db_session)
    source = make_source(db_session)

    base_day = (NOW - timedelta(days=200)).replace(hour=0, minute=0, second=0, microsecond=0)
    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=100,
                observed_at=base_day,
            ),
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=110,
                observed_at=base_day + timedelta(hours=4),
            ),
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=130,
                observed_at=NOW - timedelta(days=1),
            ),
            # Same legacy card, but its own print series - must survive on
            # its own, not be thinned into the legacy rows above.
            print_observation(card, source, 11, price_jpy=5000, observed_at=base_day),
        ]
    )
    db_session.commit()

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 1  # the legacy day thinned 2 -> 1

    remaining = db_session.query(PriceObservation).all()
    legacy = sorted(o.price_jpy for o in remaining if o.card_print_id is None)
    assert legacy == [100, 130]
    assert [o.price_jpy for o in remaining if o.card_print_id == 11] == [5000]


def test_protection_breaks_observed_at_ties_by_highest_id(db_session):
    """On an identical observed_at the HIGHER id is protected, matching the
    api service's app.services.latest_prices/print_pricing ordering
    (observed_at DESC, id DESC). Pre-fix this window ordered by observed_at
    alone, leaving the choice among tied rows unspecified. Mirrors the api
    service's test of the same name."""
    card = make_card(db_session)
    source = make_source(db_session)

    tied_at = NOW - timedelta(days=500)  # past the hard cutoff; only protection saves a row
    older = PriceObservation(
        card_id=card.id, source_id=source.id, price_type="sell", price_jpy=100,
        observed_at=tied_at,
    )
    newer = PriceObservation(
        card_id=card.id, source_id=source.id, price_type="sell", price_jpy=200,
        observed_at=tied_at,
    )
    db_session.add_all([older, newer])
    db_session.commit()
    db_session.refresh(older)
    db_session.refresh(newer)
    assert newer.id > older.id

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 1

    remaining = db_session.query(PriceObservation).all()
    assert len(remaining) == 1
    assert remaining[0].id == newer.id
    assert remaining[0].price_jpy == 200


def test_sibling_prints_break_observed_at_ties_independently(db_session):
    """The tie-break applies per exact-print series - each sibling print
    keeps its own highest-id row at the tied instant."""
    card = make_card(db_session)
    source = make_source(db_session)

    tied_at = NOW - timedelta(days=500)
    rows = [
        print_observation(card, source, 11, price_jpy=100, observed_at=tied_at),
        print_observation(card, source, 11, price_jpy=200, observed_at=tied_at),
        print_observation(card, source, 22, price_jpy=5000, observed_at=tied_at),
        print_observation(card, source, 22, price_jpy=6000, observed_at=tied_at),
    ]
    db_session.add_all(rows)
    db_session.commit()
    for row in rows:
        db_session.refresh(row)

    expected = {
        11: max(r.id for r in rows if r.card_print_id == 11),
        22: max(r.id for r in rows if r.card_print_id == 22),
    }

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2

    remaining = db_session.query(PriceObservation).all()
    assert {r.card_print_id: r.id for r in remaining} == expected


@pytest.mark.parametrize("reverse_fetch", [False, True])
def test_thinning_breaks_observed_at_ties_by_lowest_id(db_session, monkeypatch, reverse_fetch):
    """Within one thinning day the keep-earliest policy is unchanged; an
    identical observed_at is broken by LOWEST id so the survivor no longer
    depends on database row-return order. Run under both fetch orders.
    Mirrors the api service's test of the same name."""
    card = make_card(db_session)
    source = make_source(db_session)

    # Anchored to midnight UTC so the hour offset can't roll into the next
    # calendar day.
    base_day = (NOW - timedelta(days=200)).replace(hour=0, minute=0, second=0, microsecond=0)

    tied_low = PriceObservation(
        card_id=card.id, source_id=source.id, price_type="sell", price_jpy=100,
        observed_at=base_day,
    )
    tied_high = PriceObservation(
        card_id=card.id, source_id=source.id, price_type="sell", price_jpy=200,
        observed_at=base_day,  # same instant as tied_low, inserted after it
    )
    later_same_day = PriceObservation(
        card_id=card.id, source_id=source.id, price_type="sell", price_jpy=300,
        observed_at=base_day + timedelta(hours=8),
    )
    recent = PriceObservation(
        card_id=card.id, source_id=source.id, price_type="sell", price_jpy=999,
        observed_at=NOW - timedelta(days=1),
    )
    db_session.add_all([tied_low, tied_high, later_same_day, recent])
    db_session.commit()
    for row in (tied_low, tied_high, later_same_day, recent):
        db_session.refresh(row)
    assert tied_high.id > tied_low.id
    survivor_id, recent_id = tied_low.id, recent.id

    if reverse_fetch:
        reverse_thinning_fetch(db_session, monkeypatch)

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2

    remaining = db_session.query(PriceObservation).order_by(PriceObservation.observed_at).all()
    assert [o.id for o in remaining] == [survivor_id, recent_id]
    assert remaining[0].price_jpy == 100  # earliest of the day, lowest id of the tie


@pytest.mark.parametrize("reverse_fetch", [False, True])
def test_sibling_prints_break_thinning_ties_independently(db_session, monkeypatch, reverse_fetch):
    """The thinning tiebreak applies per exact-print series - each sibling
    print keeps its own lowest-id row at its own tied earliest instant."""
    card = make_card(db_session)
    source = make_source(db_session)

    base_day = (NOW - timedelta(days=200)).replace(hour=0, minute=0, second=0, microsecond=0)

    tied = [
        print_observation(card, source, 11, price_jpy=100, observed_at=base_day),
        print_observation(card, source, 11, price_jpy=200, observed_at=base_day),
        print_observation(card, source, 22, price_jpy=5000, observed_at=base_day),
        print_observation(card, source, 22, price_jpy=6000, observed_at=base_day),
    ]
    db_session.add_all(tied)
    db_session.commit()
    # A recent row per print, so the tied rows are not incidentally protected
    # as their series' latest.
    db_session.add_all(
        [
            print_observation(card, source, 11, price_jpy=130, observed_at=NOW - timedelta(days=1)),
            print_observation(card, source, 22, price_jpy=5500, observed_at=NOW - timedelta(days=1)),
        ]
    )
    db_session.commit()
    for row in tied:
        db_session.refresh(row)

    expected_survivor = {
        11: min(r.id for r in tied if r.card_print_id == 11),
        22: min(r.id for r in tied if r.card_print_id == 22),
    }
    thinned_day = base_day.date()

    if reverse_fetch:
        reverse_thinning_fetch(db_session, monkeypatch)

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2

    thinned = [
        o
        for o in db_session.query(PriceObservation).all()
        if o.observed_at.date() == thinned_day
    ]
    assert {o.card_print_id: o.id for o in thinned} == expected_survivor


def test_open_and_watching_signal_events_are_protected(db_session):
    old = NOW - timedelta(days=500)
    db_session.add_all(
        [
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="a", status="open",
                first_seen_at=old, last_seen_at=old,
            ),
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="b", status="watching",
                first_seen_at=old, last_seen_at=old,
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["market_signal_events"], now=NOW)

    assert result.results[0].rows_would_delete == 0


def test_old_dismissed_signal_events_are_pruned(db_session):
    old = NOW - timedelta(days=400)
    db_session.add(
        MarketSignalEvent(
            signal_type="price_up_7d", dedupe_key="a", status="dismissed",
            first_seen_at=old, last_seen_at=old,
        )
    )
    db_session.commit()

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["market_signal_events"], confirm="PRUNE", now=NOW
    )

    assert apply_result.results[0].rows_deleted == 1
    assert db_session.query(MarketSignalEvent).count() == 0


def test_unknown_table_is_skipped_not_pruned(db_session):
    result = prune_tables(db_session, dry_run=True, tables=["cards"], now=NOW)

    assert result.results[0].status == "skipped"
    assert result.results[0].rows_would_delete == 0
