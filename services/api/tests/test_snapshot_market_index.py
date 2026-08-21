"""Market Index snapshot foundation (see app.models.market_index_snapshot and
app.snapshot_market_index).

The dataset here is deliberately shaped like the real staging catalogue rather
than like a convenient fixture: a two-source print, a Yuyu-Tei-only print, a
print whose SNKRDUNK floor sits exactly at the platform minimum (constrained,
archived, but excluded from the index), a print with no observations at all,
and an unverified print that must never be snapshotted. Those are the five
cases whose distinctions the snapshot exists to preserve - a test suite that
only covered the happy two-source case would pass just as well against a
schema that stored nothing but a number.
"""

import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    MarketIndexSnapshot,
    PriceObservation,
    Source,
    SourceCardMapping,
)
from app.services.job_locks import LockHeldError, acquire_lock
from app.services.market_index import CALCULATION_METHOD, INDEX_VERSION
from app.services.print_market_index import get_market_index_for_prints
from app.services.source_semantics import SOURCE_SEMANTICS_VERSION
from app.snapshot_market_index import (
    build_snapshot_row,
    main,
    select_snapshottable_print_ids,
    snapshot_market_index,
)

NOW = datetime.now(timezone.utc)


def make_source(db_session, name: str) -> Source:
    source = db_session.query(Source).filter_by(name=name).one_or_none()
    if source is not None:
        return source
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def make_canonical(db_session, card_code: str, **overrides) -> CanonicalCard:
    fields = dict(
        card_code=card_code,
        name_en=f"Character {card_code}",
        original_set_code="OP01",
        rarity="R",
        card_type="Character",
        colors=["red"],
    )
    fields.update(overrides)
    canonical = CanonicalCard(**fields)
    db_session.add(canonical)
    db_session.commit()
    db_session.refresh(canonical)
    return canonical


def make_print(db_session, canonical: CanonicalCard, **overrides) -> CardPrint:
    fields = dict(
        canonical_card_id=canonical.id,
        language="jp",
        treatment="base",
        verification_status="verified",
        release_product_code="OP-01",
        artwork_key=f"art-{canonical.card_code}",
        image_url="https://images.example.com/print.jpg",
    )
    fields.update(overrides)
    print_row = CardPrint(**fields)
    db_session.add(print_row)
    db_session.commit()
    db_session.refresh(print_row)
    return print_row


def make_legacy_card(db_session, card_code: str) -> Card:
    card = Card(card_code=card_code, set_code="OP01", rarity="R", language="jp")
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_mapping(db_session, legacy_card, source, card_print) -> SourceCardMapping:
    mapping = SourceCardMapping(
        card_id=legacy_card.id,
        source_id=source.id,
        card_print_id=card_print.id,
        source_card_id=f"ext-{source.name}-{card_print.id}",
    )
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(mapping)
    return mapping


def add_observation(
    db_session, legacy_card, source, mapping, card_print, *, price_type, price_jpy, observed_at
) -> PriceObservation:
    obs = PriceObservation(
        card_id=legacy_card.id,
        source_id=source.id,
        price_type=price_type,
        price_jpy=price_jpy,
        observed_at=observed_at,
        source_card_mapping_id=mapping.id,
        card_print_id=card_print.id,
    )
    db_session.add(obs)
    db_session.commit()
    db_session.refresh(obs)
    return obs


@pytest.fixture()
def catalogue(db_session):
    """Five prints covering every coverage/eligibility case the snapshot must
    distinguish. Returns them by name."""
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")

    # 1. Two eligible sources -> full/high, with a real price range.
    both_canonical = make_canonical(db_session, "OP01-001")
    both_legacy = make_legacy_card(db_session, "OP01-001")
    both = make_print(db_session, both_canonical)
    add_observation(
        db_session, both_legacy, yuyutei,
        make_mapping(db_session, both_legacy, yuyutei, both), both,
        price_type="sell", price_jpy=1980, observed_at=NOW - timedelta(hours=2),
    )
    add_observation(
        db_session, both_legacy, snkrdunk,
        make_mapping(db_session, both_legacy, snkrdunk, both), both,
        price_type="floor", price_jpy=1500, observed_at=NOW - timedelta(hours=1),
    )

    # 2. Yuyu-Tei only -> limited/medium, no range.
    solo_canonical = make_canonical(db_session, "OP01-002")
    solo_legacy = make_legacy_card(db_session, "OP01-002")
    solo = make_print(db_session, solo_canonical)
    add_observation(
        db_session, solo_legacy, yuyutei,
        make_mapping(db_session, solo_legacy, yuyutei, solo), solo,
        price_type="sell", price_jpy=780, observed_at=NOW - timedelta(hours=3),
    )

    # 3. SNKRDUNK floor exactly at the platform minimum -> constrained,
    #    ineligible, but still archived in provenance.
    constrained_canonical = make_canonical(db_session, "OP01-003")
    constrained_legacy = make_legacy_card(db_session, "OP01-003")
    constrained = make_print(db_session, constrained_canonical)
    add_observation(
        db_session, constrained_legacy, yuyutei,
        make_mapping(db_session, constrained_legacy, yuyutei, constrained), constrained,
        price_type="sell", price_jpy=220, observed_at=NOW - timedelta(hours=4),
    )
    add_observation(
        db_session, constrained_legacy, snkrdunk,
        make_mapping(db_session, constrained_legacy, snkrdunk, constrained), constrained,
        price_type="floor", price_jpy=1000, observed_at=NOW - timedelta(minutes=30),
    )

    # 4. Verified print with no observations at all -> none/low, NULL value.
    empty_canonical = make_canonical(db_session, "OP01-004")
    empty = make_print(db_session, empty_canonical)

    # 5. Unverified print -> must never be snapshotted.
    unverified_canonical = make_canonical(db_session, "OP01-005")
    unverified = make_print(
        db_session, unverified_canonical,
        verification_status="unverified", release_product_code=None, artwork_key=None,
    )

    return {
        "both": both,
        "solo": solo,
        "constrained": constrained,
        "empty": empty,
        "unverified": unverified,
        "yuyutei": yuyutei,
        "snkrdunk": snkrdunk,
        "both_legacy": both_legacy,
        "solo_legacy": solo_legacy,
        "constrained_legacy": constrained_legacy,
    }


def _by_print(db_session) -> dict[int, MarketIndexSnapshot]:
    return {
        row.card_print_id: row
        for row in db_session.query(MarketIndexSnapshot).all()
    }


# --- population selection -------------------------------------------------


def test_selects_only_active_verified_prints(db_session, catalogue):
    ids = select_snapshottable_print_ids(db_session)

    assert catalogue["unverified"].id not in ids
    assert ids == sorted(ids), "print ids must be selected in deterministic ascending order"
    assert set(ids) == {
        catalogue["both"].id,
        catalogue["solo"].id,
        catalogue["constrained"].id,
        catalogue["empty"].id,
    }


def test_inactive_print_is_not_snapshotted(db_session, catalogue):
    catalogue["solo"].is_active = False
    db_session.commit()

    snapshot_market_index(db_session, skip_lock=True)

    assert catalogue["solo"].id not in _by_print(db_session)


def test_one_snapshot_per_active_verified_print(db_session, catalogue):
    result = snapshot_market_index(db_session, skip_lock=True)

    assert result.prints_selected == 4
    assert result.rows_created == 4
    assert result.rows_skipped_existing == 0
    assert db_session.query(MarketIndexSnapshot).count() == 4
    assert set(_by_print(db_session)) == {
        catalogue["both"].id,
        catalogue["solo"].id,
        catalogue["constrained"].id,
        catalogue["empty"].id,
    }


# --- copied index fields --------------------------------------------------


def test_copies_index_fields_verbatim_from_market_index(db_session, catalogue):
    print_id = catalogue["both"].id
    expected = get_market_index_for_prints(db_session, [print_id])[print_id]

    snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[print_id]

    assert row.index_value_jpy == expected.index_value_jpy == 1740
    assert row.source_count == expected.source_count == 2
    assert row.coverage_status == expected.coverage_status == "full"
    assert row.confidence == expected.confidence == "high"
    assert row.calculation_method == expected.calculation_method == CALCULATION_METHOD
    assert row.index_version == expected.index_version == INDEX_VERSION
    assert (
        row.source_semantics_version
        == expected.source_semantics_version
        == SOURCE_SEMANTICS_VERSION
    )


def test_snapshot_date_is_utc_date_of_calculated_at(db_session, catalogue):
    result = snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[catalogue["both"].id]

    assert row.snapshot_date == result.calculated_at.date()
    assert row.snapshot_date == datetime.now(timezone.utc).date()


def test_all_rows_in_one_run_share_one_calculated_at(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)

    calculated = {row.calculated_at for row in db_session.query(MarketIndexSnapshot).all()}
    assert len(calculated) == 1, "a run's rows must be one coherent cross-section"


# --- source price range flattening ----------------------------------------


def test_source_price_range_flattened_into_low_high(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[catalogue["both"].id]

    assert row.source_price_range_low_jpy == 1500
    assert row.source_price_range_high_jpy == 1980


def test_source_price_range_null_when_absent(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)
    rows = _by_print(db_session)

    # One eligible source: no spread to report between a value and itself.
    solo = rows[catalogue["solo"].id]
    assert solo.source_price_range_low_jpy is None
    assert solo.source_price_range_high_jpy is None

    # Zero eligible sources: likewise absent, never a fabricated zero.
    empty = rows[catalogue["empty"].id]
    assert empty.source_price_range_low_jpy is None
    assert empty.source_price_range_high_jpy is None


# --- provenance -----------------------------------------------------------


def test_provenance_contains_contributing_source_values(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[catalogue["both"].id]

    assert set(row.provenance) == {"source_values", "auxiliary_values"}

    by_source = {sv["source"]: sv for sv in row.provenance["source_values"]}
    assert by_source["yuyutei"]["value_jpy"] == 1980
    assert by_source["yuyutei"]["eligible"] is True
    assert by_source["yuyutei"]["reference_type"] == "retail_sell"
    assert by_source["snkrdunk"]["value_jpy"] == 1500
    assert by_source["snkrdunk"]["eligible"] is True
    assert by_source["snkrdunk"]["reference_type"] == "listing_floor"
    # observed_at is serialized, not left as a datetime object.
    assert isinstance(by_source["yuyutei"]["observed_at"], str)


def test_constrained_ineligible_source_is_still_archived(db_session, catalogue):
    print_id = catalogue["constrained"].id
    snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[print_id]

    # The platform-floor value did not enter the index...
    assert row.source_count == 1
    assert row.coverage_status == "limited"
    assert row.index_value_jpy == 220

    # ...but it is preserved as provenance, with the reason it was excluded.
    snkrdunk = next(
        sv for sv in row.provenance["source_values"] if sv["source"] == "snkrdunk"
    )
    assert snkrdunk["value_jpy"] == 1000
    assert snkrdunk["eligible"] is False
    assert snkrdunk["constraint"] == "platform_floor"
    assert snkrdunk["ineligible_reason"] == "platform_floor"


def test_auxiliary_values_archived_separately(db_session, catalogue):
    # A Yuyu-Tei buy observation becomes an auxiliary value - never eligible
    # for the index, but recorded alongside it.
    add_observation(
        db_session,
        catalogue["both_legacy"],
        catalogue["yuyutei"],
        db_session.query(SourceCardMapping)
        .filter_by(card_print_id=catalogue["both"].id, source_id=catalogue["yuyutei"].id)
        .one(),
        catalogue["both"],
        price_type="buy",
        price_jpy=900,
        observed_at=NOW - timedelta(hours=2),
    )

    snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[catalogue["both"].id]

    auxiliary = row.provenance["auxiliary_values"]
    assert len(auxiliary) == 1
    assert auxiliary[0]["source"] == "yuyutei"
    assert auxiliary[0]["reference_type"] == "dealer_buy"
    assert auxiliary[0]["value_jpy"] == 900
    assert auxiliary[0]["eligible"] is False

    # It must not have leaked into the contributing set or moved the index.
    assert {sv["reference_type"] for sv in row.provenance["source_values"]} == {
        "retail_sell",
        "listing_floor",
    }
    assert row.source_count == 2
    assert row.index_value_jpy == 1740


def test_empty_print_archives_both_ineligible_sources(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[catalogue["empty"].id]

    assert [sv["eligible"] for sv in row.provenance["source_values"]] == [False, False]
    assert {sv["ineligible_reason"] for sv in row.provenance["source_values"]} == {
        "no_observation",
        "insufficient_sold_and_no_floor",
    }
    assert row.provenance["auxiliary_values"] == []


# --- eligible freshness bounds --------------------------------------------


def test_freshness_bounds_use_eligible_contributors_only(db_session, catalogue):
    print_id = catalogue["constrained"].id
    expected = get_market_index_for_prints(db_session, [print_id])[print_id]

    snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[print_id]

    yuyutei_at = next(
        sv.observed_at for sv in expected.source_values if sv.source == "yuyutei"
    )

    # Only Yuyu-Tei was eligible, so both bounds collapse onto its timestamp -
    # even though the constrained SNKRDUNK floor is half an hour NEWER and is
    # what freshest_observation_at reports for display.
    assert row.freshest_eligible_source_at == row.stalest_eligible_source_at
    assert row.freshest_eligible_source_at.replace(tzinfo=None) == yuyutei_at.replace(
        tzinfo=None
    )
    assert expected.freshest_observation_at != yuyutei_at, (
        "fixture must keep an ineligible source as the freshest overall, "
        "or this test cannot distinguish the two definitions"
    )


def test_freshness_bounds_bracket_two_eligible_contributors(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[catalogue["both"].id]

    assert row.freshest_eligible_source_at > row.stalest_eligible_source_at
    # snkrdunk at -1h is freshest, yuyutei at -2h is stalest.
    delta = row.freshest_eligible_source_at - row.stalest_eligible_source_at
    assert abs(delta - timedelta(hours=1)) < timedelta(minutes=1)


def test_freshness_bounds_null_when_nothing_eligible(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[catalogue["empty"].id]

    assert row.freshest_eligible_source_at is None
    assert row.stalest_eligible_source_at is None


def test_stalest_matches_market_index_payload(db_session, catalogue):
    print_id = catalogue["both"].id
    expected = get_market_index_for_prints(db_session, [print_id])[print_id]

    snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[print_id]

    assert row.stalest_eligible_source_at.replace(
        tzinfo=None
    ) == expected.stalest_eligible_source_at.replace(tzinfo=None)


# --- zero-eligible snapshots ----------------------------------------------


def test_zero_eligible_snapshots_with_null_index_value(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)
    row = _by_print(db_session)[catalogue["empty"].id]

    assert row.index_value_jpy is None
    assert row.coverage_status == "none"
    assert row.confidence == "low"
    assert row.source_count == 0
    # The row still exists and still records the ruleset - "no evidence today"
    # is itself a fact worth preserving.
    assert row.index_version == INDEX_VERSION
    assert row.source_semantics_version == SOURCE_SEMANTICS_VERSION


# --- idempotency ----------------------------------------------------------


def test_repeated_run_same_day_creates_no_duplicate(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)
    second = snapshot_market_index(db_session, skip_lock=True)

    assert second.rows_created == 0
    assert second.rows_skipped_existing == 4
    assert db_session.query(MarketIndexSnapshot).count() == 4


def test_repeated_run_does_not_overwrite_first_snapshot(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)
    original = _by_print(db_session)[catalogue["solo"].id]
    original_id = original.id
    original_value = original.index_value_jpy
    original_calculated_at = original.calculated_at

    # The market moves between runs - a naive upsert would rewrite history.
    add_observation(
        db_session,
        catalogue["solo_legacy"],
        catalogue["yuyutei"],
        db_session.query(SourceCardMapping)
        .filter_by(card_print_id=catalogue["solo"].id, source_id=catalogue["yuyutei"].id)
        .one(),
        catalogue["solo"],
        price_type="sell",
        price_jpy=99999,
        observed_at=NOW,
    )

    snapshot_market_index(db_session, skip_lock=True)

    db_session.expire_all()
    rows = db_session.query(MarketIndexSnapshot).filter_by(
        card_print_id=catalogue["solo"].id
    ).all()
    assert len(rows) == 1
    assert rows[0].id == original_id
    assert rows[0].index_value_jpy == original_value != 99999
    assert rows[0].calculated_at == original_calculated_at


def test_partial_retry_fills_only_missing_prints(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)
    # Simulate a run that had failed to write one print.
    db_session.query(MarketIndexSnapshot).filter_by(
        card_print_id=catalogue["empty"].id
    ).delete()
    db_session.commit()

    result = snapshot_market_index(db_session, skip_lock=True)

    assert result.rows_created == 1
    assert result.rows_skipped_existing == 3
    assert db_session.query(MarketIndexSnapshot).count() == 4


# --- dry run --------------------------------------------------------------


def test_dry_run_writes_nothing(db_session, catalogue):
    result = snapshot_market_index(db_session, dry_run=True, skip_lock=True)

    assert result.dry_run is True
    assert result.prints_selected == 4
    assert result.rows_created == 0
    assert db_session.query(MarketIndexSnapshot).count() == 0


def test_dry_run_then_real_run_writes(db_session, catalogue):
    snapshot_market_index(db_session, dry_run=True, skip_lock=True)
    result = snapshot_market_index(db_session, skip_lock=True)

    assert result.rows_created == 4
    assert db_session.query(MarketIndexSnapshot).count() == 4


# --- CLI ------------------------------------------------------------------


def test_main_dry_run_writes_nothing(db_session, catalogue, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["snapshot_market_index", "--dry-run", "--skip-lock"])
    monkeypatch.setattr(
        "app.snapshot_market_index.SessionLocal", lambda: db_session
    )

    main()

    out = capsys.readouterr().out
    assert "dry_run: True" in out
    assert "rows_created: 0" in out
    assert db_session.query(MarketIndexSnapshot).count() == 0


def test_main_writes_and_reports(db_session, catalogue, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["snapshot_market_index", "--skip-lock"])
    monkeypatch.setattr(
        "app.snapshot_market_index.SessionLocal", lambda: db_session
    )

    main()

    out = capsys.readouterr().out
    assert "prints_selected: 4" in out
    assert "rows_created: 4" in out
    assert db_session.query(MarketIndexSnapshot).count() == 4


def test_snapshot_raises_lock_held_error_when_locked(db_session, catalogue):
    acquire_lock("market_index_snapshot", "market_index_snapshot:other", 600)

    with pytest.raises(LockHeldError):
        snapshot_market_index(db_session)

    assert db_session.query(MarketIndexSnapshot).count() == 0


def test_snapshot_skip_lock_bypasses_lock(db_session, catalogue):
    acquire_lock("market_index_snapshot", "market_index_snapshot:other", 600)

    result = snapshot_market_index(db_session, skip_lock=True)

    assert result.rows_created == 4


def test_main_exits_2_when_lock_held(db_session, catalogue, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["snapshot_market_index"])
    monkeypatch.setattr(
        "app.snapshot_market_index.SessionLocal", lambda: db_session
    )
    acquire_lock("market_index_snapshot", "market_index_snapshot:other", 600)

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    assert db_session.query(MarketIndexSnapshot).count() == 0


# --- empty catalogue ------------------------------------------------------


def test_no_prints_is_a_clean_no_op(db_session):
    result = snapshot_market_index(db_session, skip_lock=True)

    assert result.prints_selected == 0
    assert result.rows_created == 0
    assert result.snapshot_date is None
    assert db_session.query(MarketIndexSnapshot).count() == 0


# --- schema ---------------------------------------------------------------


def test_table_has_expected_constraints_and_indexes(db_session):
    inspector = inspect(db_session.get_bind())

    unique = {c["name"]: c["column_names"] for c in inspector.get_unique_constraints(
        "market_index_snapshots"
    )}
    assert unique["uq_market_index_snapshots_print_date"] == [
        "card_print_id",
        "snapshot_date",
    ]

    indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes(
        "market_index_snapshots"
    )}
    assert indexes["ix_market_index_snapshots_print_calculated"] == [
        "card_print_id",
        "calculated_at",
    ]

    fks = inspector.get_foreign_keys("market_index_snapshots")
    card_print_fk = next(fk for fk in fks if fk["constrained_columns"] == ["card_print_id"])
    assert card_print_fk["referred_table"] == "card_prints"
    assert card_print_fk["options"]["ondelete"] == "RESTRICT"


def test_unique_constraint_rejects_duplicate_print_day(db_session, catalogue):
    snapshot_market_index(db_session, skip_lock=True)
    existing = _by_print(db_session)[catalogue["solo"].id]

    duplicate = MarketIndexSnapshot(
        card_print_id=existing.card_print_id,
        calculated_at=existing.calculated_at,
        snapshot_date=existing.snapshot_date,
        index_value_jpy=1,
        calculation_method=CALCULATION_METHOD,
        source_count=1,
        coverage_status="limited",
        confidence="medium",
        index_version=INDEX_VERSION,
        source_semantics_version=SOURCE_SEMANTICS_VERSION,
        provenance={"source_values": [], "auxiliary_values": []},
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize(
    "coverage_status, index_value_jpy",
    [("none", 500), ("limited", None)],
)
def test_value_presence_check_rejects_mismatch(
    db_session, catalogue, coverage_status, index_value_jpy
):
    """index_value_jpy must be NULL if and only if coverage is 'none'."""
    row = MarketIndexSnapshot(
        card_print_id=catalogue["solo"].id,
        calculated_at=NOW,
        snapshot_date=NOW.date(),
        index_value_jpy=index_value_jpy,
        calculation_method=CALCULATION_METHOD,
        source_count=1,
        coverage_status=coverage_status,
        confidence="medium",
        index_version=INDEX_VERSION,
        source_semantics_version=SOURCE_SEMANTICS_VERSION,
        provenance={"source_values": [], "auxiliary_values": []},
    )
    db_session.add(row)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def _range_row(catalogue, **overrides) -> MarketIndexSnapshot:
    """A schema-valid snapshot row whose only variable is the source price
    range pair - every other column is held at a value the other CHECK
    constraints accept, so a rejection can only ever be the range constraints
    talking."""
    fields = dict(
        card_print_id=catalogue["solo"].id,
        calculated_at=NOW,
        snapshot_date=NOW.date(),
        index_value_jpy=1740,
        calculation_method=CALCULATION_METHOD,
        source_count=2,
        coverage_status="full",
        confidence="high",
        source_price_range_low_jpy=None,
        source_price_range_high_jpy=None,
        index_version=INDEX_VERSION,
        source_semantics_version=SOURCE_SEMANTICS_VERSION,
        provenance={"source_values": [], "auxiliary_values": []},
    )
    fields.update(overrides)
    return MarketIndexSnapshot(**fields)


@pytest.mark.parametrize(
    "low, high, label",
    [
        (None, None, "both absent"),
        (1500, 1980, "low below high"),
        (1980, 1980, "equal endpoints are a real, measured zero spread"),
    ],
)
def test_range_constraints_accept_valid_pairs(db_session, catalogue, low, high, label):
    db_session.add(
        _range_row(catalogue, source_price_range_low_jpy=low, source_price_range_high_jpy=high)
    )
    db_session.commit()

    stored = db_session.query(MarketIndexSnapshot).one()
    assert stored.source_price_range_low_jpy == low, label
    assert stored.source_price_range_high_jpy == high, label


@pytest.mark.parametrize(
    "low, high, label",
    [
        (1500, None, "low populated, high missing"),
        (None, 1980, "high populated, low missing"),
    ],
)
def test_range_pairing_constraint_rejects_half_a_range(
    db_session, catalogue, low, high, label
):
    db_session.add(
        _range_row(catalogue, source_price_range_low_jpy=low, source_price_range_high_jpy=high)
    )

    with pytest.raises(IntegrityError) as exc:
        db_session.commit()
    assert "ck_market_index_snapshots_range_pairing" in str(exc.value), label
    db_session.rollback()
    assert db_session.query(MarketIndexSnapshot).count() == 0


def test_range_order_constraint_rejects_low_above_high(db_session, catalogue):
    db_session.add(
        _range_row(
            catalogue, source_price_range_low_jpy=1980, source_price_range_high_jpy=1500
        )
    )

    with pytest.raises(IntegrityError) as exc:
        db_session.commit()
    assert "ck_market_index_snapshots_range_order" in str(exc.value)
    db_session.rollback()
    assert db_session.query(MarketIndexSnapshot).count() == 0


def test_source_count_is_not_coupled_to_range_presence(db_session, catalogue):
    """Deliberately NOT constrained: source_count and the range are related by
    the calculation, not by the schema. A row with two eligible sources and no
    stored range must remain insertable, so that a future methodology change
    to when a range is emitted cannot be blocked by a constraint that outlived
    the rule it encoded."""
    db_session.add(_range_row(catalogue, source_count=2))
    db_session.commit()

    stored = db_session.query(MarketIndexSnapshot).one()
    assert stored.source_count == 2
    assert stored.source_price_range_low_jpy is None


@pytest.mark.parametrize(
    "field, value",
    [("coverage_status", "partial"), ("confidence", "certain")],
)
def test_enum_checks_reject_unknown_values(db_session, catalogue, field, value):
    fields = dict(
        card_print_id=catalogue["solo"].id,
        calculated_at=NOW,
        snapshot_date=NOW.date(),
        index_value_jpy=500,
        calculation_method=CALCULATION_METHOD,
        source_count=1,
        coverage_status="limited",
        confidence="medium",
        index_version=INDEX_VERSION,
        source_semantics_version=SOURCE_SEMANTICS_VERSION,
        provenance={"source_values": [], "auxiliary_values": []},
    )
    fields[field] = value
    db_session.add(MarketIndexSnapshot(**fields))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- build_snapshot_row purity --------------------------------------------


def test_build_snapshot_row_copies_versions_as_emitted(db_session, catalogue):
    print_id = catalogue["both"].id
    market_index = get_market_index_for_prints(db_session, [print_id])[print_id]

    # Versions are taken from the payload, not re-read from the constants, so
    # a payload reporting an older ruleset is recorded as that older ruleset.
    mutated = market_index.model_copy(
        update={"index_version": 7, "source_semantics_version": 9}
    )
    row = build_snapshot_row(mutated)

    assert row["index_version"] == 7
    assert row["source_semantics_version"] == 9
