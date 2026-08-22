"""GET /admin/data-retention/policy, POST /admin/data-retention/prune, and
app.services.data_retention - see that module's docstring for the full
retention policy."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    AppLogEvent,
    CanonicalCard,
    Card,
    CardPrint,
    CollectorActivityEvent,
    MarketSignalEvent,
    PortfolioValuationSnapshot,
    PriceObservation,
    RawSnapshot,
    ReleaseProduct,
    Source,
    SourceCardMapping,
)
from app.services.data_retention import PRUNABLE_TABLES, prune_tables
from app.services.job_locks import acquire_lock

NOW = datetime.now(timezone.utc)


def make_card(db_session, **overrides) -> Card:
    fields = dict(card_code="OP01-001", set_code="OP01", rarity="L", language="en")
    fields.update(overrides)
    card = Card(**fields)
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


def make_sibling_prints(db_session, card, source) -> tuple[tuple, tuple]:
    """Two exact prints of one canonical card - a base and a parallel - both
    bridging through the SAME legacy `card` row and the same source, each
    with its own source_card_mapping. This is the real staging shape: 20
    card_prints across only 15 legacy cards.

    Returns two (CardPrint, SourceCardMapping) pairs, since a print-linked
    observation has to carry both ids together.
    """
    canonical = CanonicalCard(
        card_code="OP01-013",
        name_en="Sanji",
        original_set_code="OP01",
        rarity="SR",
        card_type="Character",
    )
    db_session.add(canonical)
    db_session.commit()
    db_session.refresh(canonical)

    product = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code="OP-01",
        display_name="Booster OP-01",
        first_seen_name="Booster OP-01",
        source_series_id="550101",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
        verification_status="verified",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    pairs = []
    for treatment, variant in (("base", "base"), ("parallel", "p1")):
        # release_product_id/official_asset_variant/artwork_key are required
        # for a print to be `verified` (ck_card_prints_verified_requires_fields),
        # and two verified prints of one canonical card must differ somewhere in
        # uq_card_prints_active_verified_identity - which is the artwork
        # variant here, not the treatment.
        print_row = CardPrint(
            canonical_card_id=canonical.id,
            language="jp",
            treatment=treatment,
            release_product_code="OP-01",
            release_product_id=product.id,
            official_asset_variant=variant,
            artwork_key=f"{treatment}-artwork-digest",
            verification_status="verified",
        )
        db_session.add(print_row)
        db_session.commit()
        db_session.refresh(print_row)

        mapping = SourceCardMapping(
            card_id=card.id,
            source_id=source.id,
            card_print_id=print_row.id,
            source_card_id=f"OP01-013-{treatment}",
            source_url=f"https://example.test/{treatment}",
        )
        db_session.add(mapping)
        db_session.commit()
        db_session.refresh(mapping)
        pairs.append((print_row, mapping))

    return pairs[0], pairs[1]


def print_observation(card, source, pair, *, price_jpy: int, observed_at) -> PriceObservation:
    """A print-linked observation - card_print_id and source_card_mapping_id
    are only ever set together (ck_price_observations_lineage_paired)."""
    print_row, mapping = pair
    return PriceObservation(
        card_id=card.id,
        source_id=source.id,
        card_print_id=print_row.id,
        source_card_mapping_id=mapping.id,
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
    """Make the daily-thinning fetch return its rows in reverse-id order.

    The defect these tests pin is that the thinning survivor depended on the
    order the database returned rows in. SQLite happens to return rows in
    rowid order, which accidentally agrees with the id-ASC tiebreak - so on
    SQLite alone a tie test passes either way and proves nothing. Reversing
    the fetch stands in for the plan or backend that does not (an unordered
    SELECT is guaranteed no order at all), and makes these tests fail
    against the old observed_at-only sort.

    Matched by exact column list, so only the daily-thinning SELECT is
    touched: the portfolio-valuation fetch, the DELETE, and the tests' own
    assertion queries all pass straight through.
    """
    real_execute = db_session.execute

    def execute(statement, *args, **kwargs):
        columns = getattr(statement, "selected_columns", None)
        if columns is not None and [c.name for c in columns] == _THINNING_COLUMNS:
            return _ReversedRows(real_execute(statement, *args, **kwargs).all()[::-1])
        return real_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", execute)


# --- policy endpoint ---------------------------------------------------------


def test_policy_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/data-retention/policy")
    assert response.status_code == 401


def test_policy_returns_policies(client, db_session):
    response = client.get("/admin/data-retention/policy")

    assert response.status_code == 200
    data = response.json()
    tables = {p["table"] for p in data["policies"]}
    # file_jobs is an informational-only entry (see 'Large import/export
    # jobs' in docs/operations.md) - its actual cleanup mechanism is POST
    # /admin/file-jobs/cleanup, not the generic prune_tables() engine, so it
    # isn't in PRUNABLE_TABLES.
    assert tables == set(PRUNABLE_TABLES) | {"file_jobs"}

    never_pruned = {
        "cards",
        "sources",
        "source_card_mappings",
        "collection_items",
        "wishlist_items",
        "grading_submissions",
        "collector_tags",
        "collector_groups",
        "collector_notes",
        "alert_rules",
        "dashboard_preferences",
    }
    assert tables.isdisjoint(never_pruned)

    raw_snapshots_policy = next(p for p in data["policies"] if p["table"] == "raw_snapshots")
    assert raw_snapshots_policy["retention_days"] == 30
    assert raw_snapshots_policy["enabled"] is True


# --- prune endpoint: dry-run / confirm gating -------------------------------


def test_prune_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.post("/admin/data-retention/prune", json={"dry_run": True})
    assert response.status_code == 401


def test_prune_dry_run_does_not_delete(client, db_session):
    source = make_source(db_session)
    db_session.add(
        RawSnapshot(
            source_id=source.id,
            source_url="https://example.com/1",
            fetched_at=NOW - timedelta(days=100),
            http_status=200,
            content_hash="abc",
            raw_content="<html></html>",
        )
    )
    db_session.commit()

    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": True, "tables": ["raw_snapshots"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    result = data["results"][0]
    assert result["rows_would_delete"] == 1
    assert result["rows_deleted"] == 0

    assert db_session.query(RawSnapshot).count() == 1


def test_prune_returns_409_when_lock_held(client, db_session):
    acquire_lock("data_retention_prune", "data_retention_prune:other", 1800)

    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": True, "tables": ["raw_snapshots"]},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "Job already running"
    assert body["lock_name"] == "data_retention_prune"


def test_prune_apply_requires_confirm(client, db_session):
    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": False, "tables": ["raw_snapshots"]},
    )
    assert response.status_code == 400


def test_prune_apply_with_wrong_confirm_rejected(client, db_session):
    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": False, "tables": ["raw_snapshots"], "confirm": "wrong"},
    )
    assert response.status_code == 400


def test_prune_apply_with_confirm_deletes(client, db_session):
    source = make_source(db_session)
    db_session.add(
        RawSnapshot(
            source_id=source.id,
            source_url="https://example.com/1",
            fetched_at=NOW - timedelta(days=100),
            http_status=200,
            content_hash="abc",
            raw_content="<html></html>",
        )
    )
    db_session.commit()

    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": False, "tables": ["raw_snapshots"], "confirm": "PRUNE"},
    )

    assert response.status_code == 200
    data = response.json()
    result = data["results"][0]
    assert result["rows_deleted"] == 1
    assert db_session.query(RawSnapshot).count() == 0


def test_protected_tables_cannot_be_pruned(client, db_session):
    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": True, "tables": ["cards", "collection_items"]},
    )

    assert response.status_code == 200
    data = response.json()
    for result in data["results"]:
        assert result["status"] == "skipped"
        assert result["rows_would_delete"] == 0


def test_omitted_tables_evaluates_all_prunable_tables(client, db_session):
    response = client.post("/admin/data-retention/prune", json={"dry_run": True})

    assert response.status_code == 200
    data = response.json()
    tables = {r["table"] for r in data["results"]}
    assert tables == set(PRUNABLE_TABLES)
    assert data["summary"]["tables_checked"] == len(PRUNABLE_TABLES)


# --- raw_snapshots / app_log_events counting and deletion -------------------


def test_raw_snapshots_old_rows_counted_and_deleted(db_session):
    source = make_source(db_session)
    db_session.add_all(
        [
            RawSnapshot(
                source_id=source.id,
                source_url="https://example.com/old",
                fetched_at=NOW - timedelta(days=31),
                http_status=200,
                content_hash="old",
                raw_content="<html></html>",
            ),
            RawSnapshot(
                source_id=source.id,
                source_url="https://example.com/new",
                fetched_at=NOW - timedelta(days=1),
                http_status=200,
                content_hash="new",
                raw_content="<html></html>",
            ),
        ]
    )
    db_session.commit()

    dry_run_result = prune_tables(db_session, dry_run=True, tables=["raw_snapshots"], now=NOW)
    assert dry_run_result.results[0].rows_would_delete == 1
    assert db_session.query(RawSnapshot).count() == 2

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["raw_snapshots"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 1
    remaining = db_session.query(RawSnapshot).all()
    assert len(remaining) == 1
    assert remaining[0].content_hash == "new"


def test_app_log_events_old_rows_counted_and_deleted(db_session):
    db_session.add_all(
        [
            AppLogEvent(
                created_at=NOW - timedelta(days=61),
                level="info",
                service="api",
                event_type="test",
                message="old info",
            ),
            AppLogEvent(
                created_at=NOW - timedelta(days=1),
                level="info",
                service="api",
                event_type="test",
                message="new info",
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["app_log_events"], now=NOW)
    assert result.results[0].rows_would_delete == 1


def test_app_log_events_keeps_critical_logs_for_180_days(db_session):
    db_session.add_all(
        [
            AppLogEvent(
                created_at=NOW - timedelta(days=90),  # older than 60d default, within 180d
                level="critical",
                service="api",
                event_type="test",
                message="critical but recent-ish",
            ),
            AppLogEvent(
                created_at=NOW - timedelta(days=200),  # older than 180d
                level="error",
                service="api",
                event_type="test",
                message="error, truly old",
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["app_log_events"], now=NOW)
    assert result.results[0].rows_would_delete == 1  # only the 200-day-old error row

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["app_log_events"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 1
    # Not an exact count: prune_tables acquires/releases the
    # data_retention_prune job lock around each call above, and those
    # acquire/release events are themselves logged to app_log_events (see
    # app.services.job_locks) - freshly created, so they're never pruned by
    # this 180-day-old cutoff and legitimately show up alongside the row
    # this test actually cares about.
    remaining_messages = {log.message for log in db_session.query(AppLogEvent).all()}
    assert "critical but recent-ish" in remaining_messages
    assert "error, truly old" not in remaining_messages


# --- price_observations: latest-per-series protection -----------------------


def test_latest_price_observation_is_protected(db_session):
    card = make_card(db_session)
    source = make_source(db_session)

    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id,
                source_id=source.id,
                price_type="sell",
                price_jpy=100,
                observed_at=NOW - timedelta(days=500),  # only observation ever - must survive
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["price_observations"], now=NOW)
    assert result.results[0].rows_would_delete == 0
    assert db_session.query(PriceObservation).count() == 1


def test_old_non_latest_price_observation_is_pruned(db_session):
    card = make_card(db_session)
    source = make_source(db_session)

    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id,
                source_id=source.id,
                price_type="sell",
                price_jpy=100,
                observed_at=NOW - timedelta(days=500),  # old, NOT latest -> prunable
            ),
            PriceObservation(
                card_id=card.id,
                source_id=source.id,
                price_type="sell",
                price_jpy=150,
                observed_at=NOW - timedelta(days=1),  # latest -> protected
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["price_observations"], now=NOW)
    assert result.results[0].rows_would_delete == 1

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 1
    remaining = db_session.query(PriceObservation).all()
    assert len(remaining) == 1
    assert remaining[0].price_jpy == 150


def test_price_observations_thinning_keeps_one_per_day_when_old(db_session):
    card = make_card(db_session)
    source = make_source(db_session)

    # Anchored to midnight UTC (not NOW's own time-of-day) so the +8h offset
    # below can never roll past midnight into the next calendar day - this
    # test's "three same-day rows" premise would otherwise be time-of-day
    # dependent (flaky depending on what time of day the suite happens to
    # run).
    base_day = (NOW - timedelta(days=200)).replace(hour=0, minute=0, second=0, microsecond=0)
    # Three observations on the same day, all older than the 90-day fresh
    # window and younger than the 365-day hard cutoff - thinning should keep
    # only one of these three. Plus one recent, definitely-latest row.
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
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=120,
                observed_at=base_day + timedelta(hours=8),
            ),
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=999,
                observed_at=NOW - timedelta(days=1),
            ),
        ]
    )
    db_session.commit()

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2  # 3 same-day rows thinned to 1

    remaining = db_session.query(PriceObservation).order_by(PriceObservation.observed_at).all()
    assert len(remaining) == 2
    assert remaining[0].price_jpy == 100  # earliest of the day kept
    assert remaining[1].price_jpy == 999  # latest row, always kept


def test_price_observations_within_fresh_window_not_thinned(db_session):
    card = make_card(db_session)
    source = make_source(db_session)

    base_day = NOW - timedelta(days=10)  # within the 90-day fresh window
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
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["price_observations"], now=NOW)
    assert result.results[0].rows_would_delete == 0
    assert db_session.query(PriceObservation).count() == 2


# --- price_observations: exact-print series isolation ------------------------
# Regression coverage for retention grouping being keyed on the legacy
# card_id. Two card_prints routinely bridge through one `cards` row (a base
# and a parallel print of the same canonical card), and every public read
# path already scopes by card_print_id - retention was the last place still
# merging them. Each test below states what the pre-fix, card_id-keyed
# grouping would have done.


def test_sibling_prints_each_keep_their_own_latest_observation(db_session):
    """Protection is per exact print, not per legacy card.

    Pre-fix: protection partitioned by (card_id, source_id, price_type), so
    the two prints shared ONE protected slot - only the parallel print's
    newer row won it, and the base print's single observation was pruned
    outright, leaving that print with no price at all.
    """
    card = make_card(db_session)
    source = make_source(db_session)
    base, parallel = make_sibling_prints(db_session, card, source)

    db_session.add_all(
        [
            # Each print's ONLY observation, both past the 365-day hard
            # cutoff - each must be protected as its own print's last-known
            # price.
            print_observation(card, source, base, price_jpy=100, observed_at=NOW - timedelta(days=500)),
            print_observation(
                card, source, parallel, price_jpy=900, observed_at=NOW - timedelta(days=400)
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["price_observations"], now=NOW)
    assert result.results[0].rows_would_delete == 0

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 0

    surviving_prints = {
        obs.card_print_id for obs in db_session.query(PriceObservation).all()
    }
    assert surviving_prints == {base[0].id, parallel[0].id}


def test_sibling_prints_are_thinned_independently(db_session):
    """Daily thinning groups per exact print, not per legacy card.

    Pre-fix: the day-group key was (card_id, source_id, price_type, day), so
    the base print's three observations and the parallel print's single
    observation on the same day landed in ONE group of four - only the
    earliest survived, and the parallel print lost its only row for that day
    to a sibling's busier day.
    """
    card = make_card(db_session)
    source = make_source(db_session)
    base, parallel = make_sibling_prints(db_session, card, source)

    # Anchored to midnight UTC so the hour offsets can't roll into the next
    # calendar day - same reasoning as the single-print thinning test above.
    base_day = (NOW - timedelta(days=200)).replace(hour=0, minute=0, second=0, microsecond=0)

    db_session.add_all(
        [
            # Base print: three rows on one day, inside the thinning zone.
            print_observation(card, source, base, price_jpy=100, observed_at=base_day),
            print_observation(
                card, source, base, price_jpy=110, observed_at=base_day + timedelta(hours=4)
            ),
            print_observation(
                card, source, base, price_jpy=120, observed_at=base_day + timedelta(hours=8)
            ),
            # Parallel print: exactly one row that same day, deliberately the
            # LATEST of the four so a card_id-keyed group would discard it.
            print_observation(
                card, source, parallel, price_jpy=5000, observed_at=base_day + timedelta(hours=12)
            ),
            # A recent row per print, so the thinning-zone rows above are not
            # incidentally protected as their series' latest.
            print_observation(card, source, base, price_jpy=130, observed_at=NOW - timedelta(days=1)),
            print_observation(
                card, source, parallel, price_jpy=5500, observed_at=NOW - timedelta(days=1)
            ),
        ]
    )
    db_session.commit()

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    # Only the base print's own 3-row day is thinned to 1. The parallel
    # print's single row that day is a group of one and is left alone.
    assert apply_result.results[0].rows_deleted == 2

    remaining = db_session.query(PriceObservation).all()
    base_prices = sorted(o.price_jpy for o in remaining if o.card_print_id == base[0].id)
    parallel_prices = sorted(o.price_jpy for o in remaining if o.card_print_id == parallel[0].id)

    assert base_prices == [100, 130]  # earliest of the thinned day + the recent row
    assert parallel_prices == [5000, 5500]  # its own day row survived untouched


def test_legacy_observations_without_print_lineage_group_by_legacy_card(db_session):
    """card_print_id IS NULL rows keep their historical behaviour exactly.

    They still thin per legacy card, they are still protected per legacy
    card, and two unrelated legacy cards are never merged into one series.
    """
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP02-002")
    source = make_source(db_session)

    base_day = (NOW - timedelta(days=200)).replace(hour=0, minute=0, second=0, microsecond=0)

    def legacy(card, price_jpy, observed_at):
        return PriceObservation(
            card_id=card.id,
            source_id=source.id,
            price_type="sell",
            price_jpy=price_jpy,
            observed_at=observed_at,
        )

    db_session.add_all(
        [
            # Card A: three same-day rows in the thinning zone + a recent row.
            legacy(card_a, 100, base_day),
            legacy(card_a, 110, base_day + timedelta(hours=4)),
            legacy(card_a, 120, base_day + timedelta(hours=8)),
            legacy(card_a, 130, NOW - timedelta(days=1)),
            # Card B: one very old row, its only one - protected forever, and
            # never pulled into card A's group.
            legacy(card_b, 777, NOW - timedelta(days=500)),
        ]
    )
    db_session.commit()

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2  # card A's day thinned 3 -> 1

    remaining = db_session.query(PriceObservation).all()
    assert sorted(o.price_jpy for o in remaining if o.card_id == card_a.id) == [100, 130]
    assert [o.price_jpy for o in remaining if o.card_id == card_b.id] == [777]
    assert all(o.card_print_id is None for o in remaining)


def test_legacy_and_print_observations_on_one_card_are_separate_series(db_session):
    """A lineage-less row and a print-linked row on the same legacy card are
    two different series, so neither can prune the other away. Guards the
    ("card", id) / ("print", id) tag in _series_identity - card_prints.id and
    cards.id are independent sequences and would otherwise collide."""
    card = make_card(db_session)
    source = make_source(db_session)
    base, _parallel = make_sibling_prints(db_session, card, source)

    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id,
                source_id=source.id,
                price_type="sell",
                price_jpy=100,
                observed_at=NOW - timedelta(days=500),  # legacy series' only row
            ),
            print_observation(
                card, source, base, price_jpy=200, observed_at=NOW - timedelta(days=450)
            ),  # print series' only row
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["price_observations"], now=NOW)
    assert result.results[0].rows_would_delete == 0
    assert db_session.query(PriceObservation).count() == 2


# --- price_observations: deterministic latest-row protection -----------------


def test_protection_breaks_observed_at_ties_by_highest_id(db_session):
    """On an identical observed_at, the HIGHER id is the protected row.

    Pre-fix the protection window ordered by observed_at DESC alone, so
    ROW_NUMBER's choice among tied rows was unspecified - retention could
    protect a different row than app.services.latest_prices/print_pricing
    serve as "latest" (both of which already order observed_at DESC, id
    DESC), and then delete the row collectors actually see. Identical
    timestamps are not hypothetical: a batch import stamps every row with the
    same fetch timestamp.
    """
    card = make_card(db_session)
    source = make_source(db_session)

    tied_at = NOW - timedelta(days=500)  # past the hard cutoff, so only protection saves a row
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
    assert newer.id > older.id  # premise: same series, same instant, different ids

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 1

    remaining = db_session.query(PriceObservation).all()
    assert len(remaining) == 1
    assert remaining[0].id == newer.id
    assert remaining[0].price_jpy == 200


def test_protection_tie_break_agrees_with_latest_prices_read_path(db_session):
    """The protected row and the row the read path calls "latest" must be the
    same row - that agreement is the whole point of matching the ordering."""
    from app.services.latest_prices import get_latest_price_map

    card = make_card(db_session)
    source = make_source(db_session, name="yuyutei")

    tied_at = NOW - timedelta(days=500)
    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=100,
                observed_at=tied_at,
            ),
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=200,
                observed_at=tied_at,
            ),
        ]
    )
    db_session.commit()

    latest = get_latest_price_map(db_session, [card.id])[card.id][("yuyutei", "sell")]

    prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )

    remaining = db_session.query(PriceObservation).all()
    assert len(remaining) == 1
    assert remaining[0].id == latest.id


def test_sibling_prints_break_observed_at_ties_independently(db_session):
    """The tie-break is applied per exact-print series, not globally - each
    sibling print keeps its own highest-id row at the tied instant."""
    card = make_card(db_session)
    source = make_source(db_session)
    base, parallel = make_sibling_prints(db_session, card, source)

    tied_at = NOW - timedelta(days=500)
    rows = [
        print_observation(card, source, base, price_jpy=100, observed_at=tied_at),
        print_observation(card, source, base, price_jpy=200, observed_at=tied_at),
        print_observation(card, source, parallel, price_jpy=5000, observed_at=tied_at),
        print_observation(card, source, parallel, price_jpy=6000, observed_at=tied_at),
    ]
    db_session.add_all(rows)
    db_session.commit()
    for row in rows:
        db_session.refresh(row)

    expected = {
        base[0].id: max(r.id for r in rows if r.card_print_id == base[0].id),
        parallel[0].id: max(r.id for r in rows if r.card_print_id == parallel[0].id),
    }

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2  # one per print

    remaining = db_session.query(PriceObservation).all()
    assert {r.card_print_id: r.id for r in remaining} == expected


# --- price_observations: deterministic daily thinning ------------------------


@pytest.mark.parametrize("reverse_fetch", [False, True])
def test_thinning_breaks_observed_at_ties_by_lowest_id(db_session, monkeypatch, reverse_fetch):
    """Within one thinning day, an identical observed_at is broken by LOWEST id.

    The policy is unchanged - the EARLIEST observation of the day is kept.
    Pre-fix the day's rows were sorted by observed_at alone, so among rows
    sharing the earliest timestamp the survivor was whichever the database
    returned first: the same data could thin to a different survivor on a
    different run or backend. Identical timestamps are not hypothetical - a
    batch import stamps every row with the same fetch timestamp.

    Run under both fetch orders: the survivor must be the same row either
    way. See reverse_thinning_fetch for why the reversed case is the one
    that actually pins this on SQLite.
    """
    card = make_card(db_session)
    source = make_source(db_session)

    # Anchored to midnight UTC so the hour offset can't roll into the next
    # calendar day - same reasoning as the thinning tests above.
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
    assert tied_high.id > tied_low.id  # premise: same series, same instant, different ids
    survivor_id, survivor_price = tied_low.id, tied_low.price_jpy
    recent_id = recent.id

    if reverse_fetch:
        reverse_thinning_fetch(db_session, monkeypatch)

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2  # 3 same-day rows thinned to 1

    remaining = db_session.query(PriceObservation).order_by(PriceObservation.observed_at).all()
    assert [o.id for o in remaining] == [survivor_id, recent_id]
    assert remaining[0].price_jpy == survivor_price  # earliest of the day, lowest id of the tie


@pytest.mark.parametrize("reverse_fetch", [False, True])
def test_thinning_tie_break_prefers_earlier_timestamp_over_lower_id(
    db_session, monkeypatch, reverse_fetch
):
    """id is only a tiebreaker - a strictly earlier observed_at still wins even
    when it carries the HIGHER id, so keep-earliest is not quietly turned into
    keep-lowest-id."""
    card = make_card(db_session)
    source = make_source(db_session)

    base_day = (NOW - timedelta(days=200)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Inserted later (higher id) but observed EARLIER in the day.
    later_row = PriceObservation(
        card_id=card.id, source_id=source.id, price_type="sell", price_jpy=110,
        observed_at=base_day + timedelta(hours=8),
    )
    db_session.add(later_row)
    db_session.commit()
    earliest_row = PriceObservation(
        card_id=card.id, source_id=source.id, price_type="sell", price_jpy=100,
        observed_at=base_day,
    )
    db_session.add_all(
        [
            earliest_row,
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=999,
                observed_at=NOW - timedelta(days=1),
            ),
        ]
    )
    db_session.commit()
    db_session.refresh(later_row)
    db_session.refresh(earliest_row)
    assert earliest_row.id > later_row.id  # premise: earliest row has the higher id

    if reverse_fetch:
        reverse_thinning_fetch(db_session, monkeypatch)

    prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )

    remaining = db_session.query(PriceObservation).order_by(PriceObservation.observed_at).all()
    assert [o.price_jpy for o in remaining] == [100, 999]  # earliest kept, not lowest id


@pytest.mark.parametrize("reverse_fetch", [False, True])
def test_sibling_prints_break_thinning_ties_independently(
    db_session, monkeypatch, reverse_fetch
):
    """The thinning tiebreak is applied per exact-print series, so it composes
    with the exact-print day grouping: each sibling print keeps its own
    lowest-id row at its own tied earliest instant."""
    card = make_card(db_session)
    source = make_source(db_session)
    base, parallel = make_sibling_prints(db_session, card, source)

    base_day = (NOW - timedelta(days=200)).replace(hour=0, minute=0, second=0, microsecond=0)

    tied = [
        print_observation(card, source, base, price_jpy=100, observed_at=base_day),
        print_observation(card, source, base, price_jpy=200, observed_at=base_day),
        print_observation(card, source, parallel, price_jpy=5000, observed_at=base_day),
        print_observation(card, source, parallel, price_jpy=6000, observed_at=base_day),
    ]
    db_session.add_all(tied)
    db_session.commit()
    # A recent row per print, so the tied rows above are not incidentally
    # protected as their series' latest.
    db_session.add_all(
        [
            print_observation(card, source, base, price_jpy=130, observed_at=NOW - timedelta(days=1)),
            print_observation(
                card, source, parallel, price_jpy=5500, observed_at=NOW - timedelta(days=1)
            ),
        ]
    )
    db_session.commit()
    for row in tied:
        db_session.refresh(row)

    expected_survivor = {
        base[0].id: min(r.id for r in tied if r.card_print_id == base[0].id),
        parallel[0].id: min(r.id for r in tied if r.card_print_id == parallel[0].id),
    }
    thinned_day = base_day.date()

    if reverse_fetch:
        reverse_thinning_fetch(db_session, monkeypatch)

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2  # one per print

    thinned = [
        o
        for o in db_session.query(PriceObservation).all()
        if o.observed_at.date() == thinned_day
    ]
    assert {o.card_print_id: o.id for o in thinned} == expected_survivor


# --- portfolio_valuation_snapshots: weekly thinning -------------------------


def test_portfolio_valuation_snapshots_thinning_keeps_one_per_week_when_old(db_session):
    # Anchor to the Monday of that ISO week so `base` and `base + 1 day`
    # can never straddle an ISO week boundary (which happens whenever
    # NOW - 200 days happens to fall on a Sunday) - otherwise this test is
    # flaky depending on what day it's run.
    base = NOW - timedelta(days=200)
    base = base - timedelta(days=base.isoweekday() - 1)
    db_session.add_all(
        [
            PortfolioValuationSnapshot(
                created_at=base,
                total_items=1, total_quantity=1,
                items_missing_yuyutei_sell=0, items_missing_yuyutei_buy=0,
                items_missing_snkrdunk_floor=0, items_missing_cost_basis=0,
                cards_above_target_sell=0,
            ),
            PortfolioValuationSnapshot(
                created_at=base + timedelta(days=1),
                total_items=1, total_quantity=1,
                items_missing_yuyutei_sell=0, items_missing_yuyutei_buy=0,
                items_missing_snkrdunk_floor=0, items_missing_cost_basis=0,
                cards_above_target_sell=0,
            ),
            PortfolioValuationSnapshot(
                created_at=NOW - timedelta(days=1),
                total_items=1, total_quantity=1,
                items_missing_yuyutei_sell=0, items_missing_yuyutei_buy=0,
                items_missing_snkrdunk_floor=0, items_missing_cost_basis=0,
                cards_above_target_sell=0,
            ),
        ]
    )
    db_session.commit()

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["portfolio_valuation_snapshots"], confirm="PRUNE", now=NOW
    )
    # The two same-week old snapshots thin to 1; the recent one is untouched.
    assert apply_result.results[0].rows_deleted == 1
    assert db_session.query(PortfolioValuationSnapshot).count() == 2


# --- market_signal_events: open/watching protected, old dismissed pruned ---


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


def test_old_dismissed_and_resolved_signal_events_are_pruned(db_session):
    old = NOW - timedelta(days=400)
    recent = NOW - timedelta(days=10)
    db_session.add_all(
        [
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="old-dismissed", status="dismissed",
                first_seen_at=old, last_seen_at=old,
            ),
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="old-resolved", status="resolved",
                first_seen_at=old, last_seen_at=old,
            ),
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="recent-dismissed", status="dismissed",
                first_seen_at=recent, last_seen_at=recent,
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["market_signal_events"], now=NOW)
    assert result.results[0].rows_would_delete == 2

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["market_signal_events"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2
    remaining = db_session.query(MarketSignalEvent).all()
    assert len(remaining) == 1
    assert remaining[0].dedupe_key == "recent-dismissed"


# --- collector_activity_events (simple cutoff table, sanity check) ---------


def test_collector_activity_events_old_rows_pruned(db_session):
    db_session.add_all(
        [
            CollectorActivityEvent(
                event_type="note_created", event_source="note",
                title="old", created_at=NOW - timedelta(days=400),
            ),
            CollectorActivityEvent(
                event_type="note_created", event_source="note",
                title="new", created_at=NOW - timedelta(days=1),
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["collector_activity_events"], now=NOW)
    assert result.results[0].rows_would_delete == 1
