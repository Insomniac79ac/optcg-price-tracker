"""Daily monetary attribution and exact-print basket decomposition contracts."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest
from sqlalchemy import select

from app.models import CardPrint, MarketIndexSnapshot
from app.models.market_value_point import MarketValuePoint
from app.services import market_value_rankings as service
from app.services.market_value import (
    MarketValueDay,
    MarketValueObservation,
    MarketValueScope,
    compute_monetary_step,
)
from app.services.market_value_provenance import (
    ActivePrintIdentity,
    membership_revision,
)
from tests._market_value_ranking_helpers import AS_OF, CALCULATED, PRIOR, seed_rankings


@pytest.fixture
def ranked_db(db_session):
    seed_rankings(db_session)
    return db_session


def point(db, release_id=None):
    return db.scalar(
        select(MarketValuePoint).where(
            MarketValuePoint.release_product_id == release_id,
            MarketValuePoint.point_date == AS_OF,
        )
    )


def snapshot(db, pid, day=AS_OF):
    return db.scalar(
        select(MarketIndexSnapshot).where(
            MarketIndexSnapshot.card_print_id == pid,
            MarketIndexSnapshot.snapshot_date == day,
        )
    )


@pytest.mark.parametrize(
    "release_id,p,q,c", [(None, 200000, 210000, 300), (1, 125000, 135000, 60)]
)
def test_latest_daily_step_reconciles_full_panel(ranked_db, release_id, p, q, c):
    out = service.get_market_value_movers(
        ranked_db, release_product_id=release_id, order="impact", limit=50
    )
    assert out.available and out.reason == "publishable"
    assert (out.scope_as_of, out.prior_date, out.step_date) == (AS_OF, PRIOR, AS_OF)
    assert (
        out.panel.prior_value_jpy,
        out.panel.current_value_jpy,
        out.panel.comparable_print_count,
    ) == (p, q, c)
    assert sum(r.delta_jpy for r in out.movers) == q - p == out.panel.basket_delta_jpy
    assert (
        sum(r.percentage_point_contribution for r in out.movers)
        == Decimal(100 * (q - p)) / p
        == out.panel.basket_move_pct
    )
    assert out.total_ranked == out.returned == 5
    assert not out.truncated
    assert out.release_code == ("OP-01" if release_id else None)


@pytest.mark.parametrize(
    "order,ids",
    [("gainers", [2, 3, 1]), ("losers", [4, 5]), ("impact", [1, 2, 3, 4, 5])],
)
def test_rankings_ties_full_population_and_truncation(ranked_db, order, ids):
    full = service.get_market_value_movers(ranked_db, order=order)
    short = service.get_market_value_movers(ranked_db, order=order, limit=1)
    assert [r.card_print_id for r in full.movers] == ids
    assert [r.rank for r in full.movers] == list(range(1, len(ids) + 1))
    assert short.movers == full.movers[:1]
    assert short.total_ranked == len(ids) and short.returned == 1 and short.truncated
    assert all(r.delta_jpy != 0 for r in full.movers)
    assert all(
        r.direction == ("up" if r.delta_jpy > 0 else "down") for r in full.movers
    )


def test_large_jpy_impact_beats_large_percentage_move(ranked_db):
    gainers = service.get_market_value_movers(ranked_db)
    impact = service.get_market_value_movers(ranked_db, order="impact")
    cheap, expensive = gainers.movers[0], impact.movers[0]
    assert (cheap.prior_value_jpy, cheap.move_pct, cheap.delta_jpy) == (500, 100, 500)
    assert (expensive.prior_value_jpy, expensive.move_pct, expensive.delta_jpy) == (
        100000,
        10,
        10000,
    )
    assert expensive.percentage_point_contribution == 5
    assert cheap.percentage_point_contribution == Decimal("0.25")


def test_older_published_step_is_not_claimed_as_latest_scope_date(ranked_db):
    latest = point(ranked_db)
    values = {
        c.name: getattr(latest, c.name)
        for c in MarketValuePoint.__table__.columns
        if c.name not in {"id", "created_at"}
    }
    values.update(
        point_date=AS_OF + timedelta(days=1),
        prior_point_date=AS_OF,
        step_publication_eligible=False,
        publication_reasons="insufficient_comparable_prints",
        performance_factor=Decimal(1),
        segment_number=2,
    )
    ranked_db.add(MarketValuePoint(**values))
    ranked_db.commit()
    out = service.get_market_value_movers(ranked_db)
    assert out.step_date == AS_OF and out.scope_as_of == AS_OF + timedelta(days=1)


@pytest.mark.parametrize("release_id", [None, 1])
def test_no_published_step_has_null_panel_not_fake_zero(ranked_db, release_id):
    latest = point(ranked_db, release_id)
    latest.step_publication_eligible = False
    latest.publication_reasons = "insufficient_comparable_prints"
    latest.performance_factor = 1
    ranked_db.commit()
    out = service.get_market_value_movers(ranked_db, release_product_id=release_id)
    assert not out.available and out.reason == "no_published_daily_step"
    assert out.movers == [] and out.step_date is None and out.prior_date is None
    assert all(v is None for v in out.panel.model_dump().values())


@pytest.mark.parametrize("order", ["gainers", "losers", "impact"])
def test_published_flat_release_is_available_with_real_zero(db_session, order):
    seed_rankings(db_session, flat=True)
    out = service.get_market_value_movers(db_session, release_product_id=1, order=order)
    assert out.available and out.reason == "publishable" and out.movers == []
    assert out.total_ranked == out.returned == 0 and not out.truncated
    assert out.panel.basket_move_pct == 0 and out.panel.basket_delta_jpy == 0
    assert out.panel.comparable_print_count == 60


def test_nonadjacent_persisted_dates_fail_closed(ranked_db):
    latest = point(ranked_db)
    latest.prior_point_date = PRIOR - timedelta(days=1)
    latest.step_days = 2
    ranked_db.commit()
    with pytest.raises(
        service.MarketValueIntegrityError, match="persisted_step_mismatch"
    ):
        service.get_market_value_movers(ranked_db)


def test_most_valuable_snapshot_version_disagrees_with_persistence(ranked_db):
    snapshot(ranked_db, 300).index_version = 2
    ranked_db.commit()
    with pytest.raises(
        service.MarketValueIntegrityError, match="snapshot_version_mismatch"
    ):
        service.get_market_value_most_valuable(ranked_db, limit=1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("prior_comparable_value_jpy", 199999),
        ("current_comparable_value_jpy", 209999),
        ("comparable_print_count", 299),
        ("step_ratio", Decimal("1.06")),
        ("prior_version_pairs", "2:2"),
        ("current_version_pairs", "2:2"),
        ("prior_priced_print_count", 301),
        ("prior_total_physical_print_count", 303),
        ("prior_tracked_value_jpy", 200001),
        ("tracked_value_jpy", 210001),
        ("priced_print_count", 301),
        ("publication_reasons", "publishable|insufficient_comparable_prints"),
    ],
)
def test_persisted_step_disagreement_fails_closed(ranked_db, field, value):
    setattr(point(ranked_db), field, value)
    if field != "publication_reasons":
        ranked_db.commit()
    with pytest.raises(
        service.MarketValueIntegrityError, match="persisted_step_mismatch"
    ):
        service.get_market_value_movers(ranked_db, limit=1)


@pytest.mark.parametrize("change", ["missing", "contributors", "version", "price"])
def test_archive_change_fails_closed_without_reimplementing_comparability(
    ranked_db, change
):
    row = snapshot(ranked_db, 1)
    if change == "missing":
        ranked_db.delete(row)
    elif change == "contributors":
        row.provenance = {}
    elif change == "version":
        row.source_semantics_version = 3
    else:
        row.index_value_jpy += 1
    ranked_db.commit()
    with pytest.raises(
        service.MarketValueIntegrityError, match="persisted_step_mismatch"
    ):
        service.get_market_value_movers(ranked_db)


@pytest.mark.parametrize(
    "fn", [service.get_market_value_movers, service.get_market_value_most_valuable]
)
@pytest.mark.parametrize("release_id", [None, 1])
@pytest.mark.parametrize("change", ["fk", "active", "verified", "language", "digest"])
def test_frozen_membership_mismatch_fails_closed(ranked_db, fn, release_id, change):
    p = ranked_db.get(
        CardPrint, 300
    )  # Outside OP-01: initial replay used a GLOBAL digest.
    if change == "fk":
        p.release_product_id = 5
    elif change == "active":
        p.is_active = False
    elif change == "verified":
        p.verification_status = "unverified"
    elif change == "language":
        p.language = "en"
    else:
        point(ranked_db, release_id).membership_revision = "wrong"
    ranked_db.commit()
    with pytest.raises(
        service.MarketValueIntegrityError, match="membership_revision_mismatch"
    ):
        fn(ranked_db, release_product_id=release_id)


@pytest.mark.parametrize(
    "release_id,total,value", [(None, 300, 210000), (1, 60, 135000)]
)
def test_most_valuable_full_cohort_reconciles_before_pagination(
    ranked_db, release_id, total, value
):
    first = service.get_market_value_most_valuable(
        ranked_db, release_product_id=release_id
    )
    assert first.total_eligible == total and first.limit == 10 and first.offset == 0
    assert first.as_of == AS_OF and first.calculated_at == CALCULATED
    all_items = []
    for offset in range(0, total, 50):
        out = service.get_market_value_most_valuable(
            ranked_db, release_product_id=release_id, offset=offset, limit=50
        )
        all_items.extend(out.items)
    assert sum(r.value_jpy for r in all_items) == value
    assert len({r.card_print_id for r in all_items}) == total
    assert all_items == sorted(all_items, key=lambda r: (-r.value_jpy, r.card_print_id))
    assert first.items == all_items[:10]
    assert all(r.calculated_at == CALCULATED for r in all_items)
    assert (
        service.get_market_value_most_valuable(
            ranked_db, release_product_id=release_id, offset=total
        ).items
        == []
    )


def test_exact_siblings_release_fk_and_print_metadata(ranked_db):
    out = service.get_market_value_most_valuable(ranked_db, release_product_id=1)
    siblings = [r for r in out.items if r.canonical_card_id == 1]
    assert {r.card_print_id for r in siblings} == {1, 2, 3}
    assert {r.official_asset_variant for r in siblings} == {"base", "p1", "p2"}
    assert all(
        r.release_product_id == 1
        and r.release_code == "OP-01"
        and r.card_code.startswith("EB04")
        for r in siblings
    )
    assert all(r.rarity == "SP" and r.treatment is None for r in siblings)
    assert all(
        r.display_image.url.endswith(f"/{r.card_print_id}.png") for r in siblings
    )
    # Print rarity is not guessed from a canonical sibling's rarity.
    assert next(r for r in out.items if r.card_print_id == 4).rarity is None


@pytest.mark.parametrize(
    "fn", [service.get_market_value_movers, service.get_market_value_most_valuable]
)
def test_newer_snapshot_does_not_move_frozen_valuation_date(ranked_db, fn):
    row = snapshot(ranked_db, 1)
    values = {
        c.name: getattr(row, c.name)
        for c in MarketIndexSnapshot.__table__.columns
        if c.name not in {"id", "created_at"}
    }
    values.update(
        snapshot_date=AS_OF + timedelta(days=1),
        calculated_at=CALCULATED + timedelta(days=1),
        index_value_jpy=9999999,
    )
    ranked_db.add(MarketIndexSnapshot(**values))
    ranked_db.commit()
    out = fn(ranked_db)
    assert (out.scope_as_of if hasattr(out, "scope_as_of") else out.as_of) == AS_OF
    assert "9999999" not in out.model_dump_json()


@pytest.mark.parametrize(
    "field,value", [("priced_print_count", 301), ("tracked_value_jpy", 210001)]
)
def test_most_valuable_count_and_sum_mismatch(ranked_db, field, value):
    setattr(point(ranked_db), field, value)
    ranked_db.commit()
    with pytest.raises(
        service.MarketValueIntegrityError, match="tracked_value_mismatch"
    ):
        service.get_market_value_most_valuable(ranked_db, limit=1, offset=299)


@pytest.mark.parametrize(
    "pid,change", [(300, timedelta(seconds=1)), (1, timedelta(days=1))]
)
def test_mixed_batch_fails_even_outside_returned_page(ranked_db, pid, change):
    snapshot(ranked_db, pid).calculated_at = CALCULATED + change
    ranked_db.commit()
    with pytest.raises(
        service.MarketValueIntegrityError, match="mixed_valuation_batch"
    ):
        service.get_market_value_most_valuable(ranked_db, limit=1)


def test_null_and_nonpositive_prices_are_excluded_from_eligible_cohort(ranked_db):
    for pid, value in ((301, 0), (302, -1)):
        row = snapshot(ranked_db, pid)
        row.index_value_jpy = value
        row.coverage_status = "limited"
        row.calculated_at = CALCULATED + timedelta(seconds=1)
    ranked_db.commit()
    assert service.get_market_value_most_valuable(ranked_db).total_eligible == 300


def test_no_prices_returns_empty_not_fake_zero(ranked_db):
    for row in ranked_db.scalars(
        select(MarketIndexSnapshot).where(MarketIndexSnapshot.snapshot_date == AS_OF)
    ):
        row.index_value_jpy = None
        row.coverage_status = "none"
    latest = point(ranked_db)
    latest.tracked_value_jpy = None
    latest.priced_print_count = 0
    latest.current_version_pairs = ""
    latest.comparable_print_count = 0
    latest.prior_comparable_value_jpy = 0
    latest.current_comparable_value_jpy = 0
    latest.step_ratio = None
    latest.step_publication_eligible = False
    latest.publication_reasons = "non_positive_comparable_value"
    latest.performance_factor = 1
    ranked_db.commit()
    out = service.get_market_value_most_valuable(ranked_db)
    assert out.items == [] and out.total_eligible == 0 and out.calculated_at is None


@pytest.mark.parametrize("kind", ["delta", "contribution", "count", "duplicate"])
def test_reconciliation_failure_returns_no_partial_payload(
    ranked_db, monkeypatch, kind
):
    compute = service.compute_monetary_step

    def corrupt(*args, **kwargs):
        step = compute(*args, **kwargs)
        rows = list(step.contributions)
        if kind == "delta":
            rows[0] = replace(rows[0], delta_jpy=9999)
        elif kind == "contribution":
            rows[0] = replace(
                rows[0], percentage_point_contribution=Decimal("5.00000001")
            )
        elif kind == "count":
            rows.pop()
        else:
            rows[-1] = rows[0]
        return replace(step, contributions=tuple(rows))

    monkeypatch.setattr(service, "compute_monetary_step", corrupt)
    with pytest.raises(
        service.MarketValueIntegrityError, match="panel_reconciliation_failed"
    ):
        service.get_market_value_movers(ranked_db, limit=1)


def test_decimal_context_does_not_change_ranking_or_values(ranked_db):
    expected = service.get_market_value_movers(ranked_db).model_dump()
    with localcontext() as context:
        context.prec = 6
        assert service.get_market_value_movers(ranked_db).model_dump() == expected


def test_full_panel_decimal_reconciliation_allows_only_frozen_rounding():
    def day(day_date, value):
        return MarketValueDay(
            day_date,
            tuple(
                MarketValueObservation(
                    pid, value, 3, 2, frozenset({("yuyutei", "retail_ask")}), 1
                )
                for pid in range(1, 302)
            ),
            301,
            "same-revision",
        )

    step = compute_monetary_step(
        day(PRIOR, 3), day(AS_OF, 4), scope=MarketValueScope.overall()
    )
    with localcontext() as context:
        context.prec = 50
        expected = Decimal(100) / 3
    with localcontext() as context:
        context.prec = 120
        # Independently rounded fractions genuinely differ in the last digits
        # from the independently rounded aggregate.
        assert (
            sum(r.percentage_point_contribution for r in step.contributions) != expected
        )
    assert service._reconcile_panel(step) == expected
    rows = list(step.contributions)
    with localcontext() as context:
        context.prec = 120
        rows[0] = replace(
            rows[0],
            percentage_point_contribution=rows[0].percentage_point_contribution
            + Decimal("1e-48"),
        )
    with pytest.raises(
        service.MarketValueIntegrityError, match="panel_reconciliation_failed"
    ):
        service._reconcile_panel(replace(step, contributions=tuple(rows)))


def test_membership_serializer_is_byte_identical_and_order_independent():
    import hashlib

    expected = (
        "current-corrected-card-print-release-v1:"
        + hashlib.sha256(b"1:2\n3:4").hexdigest()
    )
    assert (
        membership_revision([ActivePrintIdentity(3, 4), ActivePrintIdentity(1, 2)])
        == expected
    )
