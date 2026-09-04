"""GET /prints/{print_id}/series - the exact-print multi-platform history API.

The invariant every test below defends: THE USER SELECTS A PLATFORM AND THE
SERVER PRESERVES THE INSTRUMENT. A collector picks "SNKRDUNK"; they must not
get a line that silently welds a listing floor to a completed-sale median, a
dealer buy quote into a retail series, or Market Index v1 onto v3 - each of
which would draw a change of measuring instrument as a change of price.

The second invariant is that nothing is invented: no averaged point, no
forward-filled day, no zero standing in for a missing price, and no
recomputation of a historical index under today's algorithm.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import event

import pytest

from app.models import MarketIndexSnapshot, PriceObservation
from app.services import print_series
from app.services.market_index import (
    _resolve_snkrdunk,
    _resolve_yuyutei_buy,
    _resolve_yuyutei_sell,
)
from app.services.print_series import (
    SeriesKeyError,
    get_print_series,
    parse_series_key,
)
from app.services.source_instruments import (
    ROLE_AUXILIARY,
    ROLE_PRIMARY,
    SOURCE_INSTRUMENTS,
    describe_instrument,
    primary_price_types,
)
from tests.test_prints import (
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_observation,
    make_print,
    make_source,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def day(offset: int, hour: int = 12) -> datetime:
    """`offset` days before NOW, at a fixed hour - so a test can put two
    observations on one UTC day without either drifting into another."""
    return (NOW - timedelta(days=offset)).replace(hour=hour, minute=0, second=0, microsecond=0)


@pytest.fixture()
def world(db_session):
    """One print with two sources mapped, plus a sibling print bridging the
    same legacy card - the contamination trap test_prints.py describes."""
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    canonical = make_canonical(db_session, card_code="OP01-013", name_en="Sanji")
    legacy = make_legacy_card(db_session, card_code="OP01-013")
    base = make_print(db_session, canonical, treatment="base", artwork_key="sanji-base")
    parallel = make_print(
        db_session, canonical, treatment="parallel", artwork_key="sanji-parallel"
    )
    return {
        "yuyutei": yuyutei,
        "snkrdunk": snkrdunk,
        "legacy": legacy,
        "base": base,
        "parallel": parallel,
        "yuyutei_base": make_mapping(db_session, legacy, yuyutei, base),
        "snkrdunk_base": make_mapping(db_session, legacy, snkrdunk, base),
        "yuyutei_parallel": make_mapping(db_session, legacy, yuyutei, parallel),
    }


def observe(db_session, world, source_key, print_key, mapping_key, **overrides):
    return make_observation(
        db_session,
        world["legacy"],
        world[source_key],
        world[mapping_key],
        world[print_key],
        **overrides,
    )


def _same_instant(actual, expected) -> bool:
    """Compare two timestamps without caring which side carries a tzinfo.

    SQLite hands DateTime(timezone=True) columns back naive while Postgres
    returns them aware, and this module - like every other read path in the
    app - returns whatever the driver gave it rather than rewriting stored
    instants. So the assertion is about the instant, not the representation.
    """
    left = actual.replace(tzinfo=None) if actual.tzinfo is not None else actual
    right = expected.replace(tzinfo=None) if expected.tzinfo is not None else expected
    return left == right


def series_by_key(payload: dict) -> dict[str, dict]:
    return {entry["key"]: entry for entry in payload["series"]}


def all_points(entry: dict) -> list[dict]:
    return [point for segment in entry["segments"] for point in segment["points"]]


def fetch(db_session, print_id, keys=None, window="all"):
    requests = [parse_series_key(key) for key in keys] if keys else None
    return get_print_series(db_session, print_id, series=requests, window=window, now=NOW)


# ---------------------------------------------------------------- A, B, C ---
class TestDailyNormalisation:
    """Latest stored observation per UTC day, per print, per source, per
    price_type. Never an average, never a forward-fill."""

    def test_yuyutei_multiple_same_day_keeps_only_the_latest(self, db_session, world):
        # A. Three readings on one UTC day - a nightly cron plus two manual
        # re-runs. The chart must show the day, not the polling schedule.
        for hour, price in ((3, 800), (12, 900), (21, 950)):
            observe(
                db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=price, observed_at=day(1, hour),
            )
        entry = series_by_key(fetch(db_session, world["base"].id))["source:yuyutei"]
        points = all_points(entry)
        assert len(points) == 1
        # The LATEST, never the mean (883) nor the first.
        assert points[0]["value_jpy"] == 950
        assert points[0]["observations_in_day"] == 3

    def test_snkrdunk_multiple_same_day_keeps_only_the_latest(self, db_session, world):
        # B. SNKRDUNK polls three times a day in production; without this rule
        # it would appear three times as volatile as Yuyu-Tei by construction.
        for hour, price in ((3, 2000), (11, 2100), (19, 2500)):
            observe(
                db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=price, observed_at=day(2, hour),
            )
        entry = series_by_key(fetch(db_session, world["base"].id))["source:snkrdunk"]
        points = all_points(entry)
        assert len(points) == 1
        assert points[0]["value_jpy"] == 2500
        assert points[0]["observations_in_day"] == 3

    def test_a_missing_day_produces_no_point(self, db_session, world):
        # C. Two observations five days apart. The four days between them are
        # absent - not zero, not carried forward, not interpolated.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=500, observed_at=day(6))
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=700, observed_at=day(1))
        points = all_points(series_by_key(fetch(db_session, world["base"].id))["source:yuyutei"])
        assert [p["value_jpy"] for p in points] == [500, 700]
        assert len(points) == 2
        assert {p["day"] for p in points} == {day(6).date(), day(1).date()}
        # Nothing anywhere in the payload stands in for the missing days.
        assert all(point["value_jpy"] is not None for point in points)
        assert 0 not in [point["value_jpy"] for point in points]

    def test_distinct_price_types_on_one_day_both_survive(self, db_session, world):
        # Normalisation is per price_type as well as per day: collapsing to one
        # point per day would silently discard a whole instrument. Asserted in
        # the PUBLIC vocabulary - the stored price_type is not published, and a
        # test that read it back from the payload would be pinning the leak
        # this contract removed.
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=2000, observed_at=day(1, 9))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="sold", price_jpy=1800, observed_at=day(1, 10))
        points = all_points(series_by_key(fetch(db_session, world["base"].id))["source:snkrdunk"])
        assert {p["reference_type"] for p in points} == {"listing_floor", "transaction_median"}
        assert {p["value_jpy"] for p in points} == {2000, 1800}


# ------------------------------------------------------------------- D, E ---
class TestSourceSemanticsArePreservedNotReimplemented:
    def test_platform_floor_stays_constrained_and_ineligible(self, db_session, world):
        # D. ¥1,000 is SNKRDUNK's platform minimum, not a market price. It must
        # remain visible AND remain marked, so no client can mistake it for an
        # ordinary listing - and this module must reach that verdict through
        # classify_observation rather than by knowing the number itself.
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=1000, observed_at=day(1))
        point = all_points(series_by_key(fetch(db_session, world["base"].id))["source:snkrdunk"])[0]
        assert point["value_jpy"] == 1000
        assert point["constraint"] == "platform_floor"
        assert point["eligible"] is False
        assert point["ineligible_reason"] == "platform_floor"

    def test_eligible_snkrdunk_listing_is_retained_unmarked(self, db_session, world):
        # E. A floor above the platform minimum is an ordinary usable price.
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=2500, observed_at=day(1))
        point = all_points(series_by_key(fetch(db_session, world["base"].id))["source:snkrdunk"])[0]
        assert point["value_jpy"] == 2500
        assert point["eligible"] is True
        assert point["constraint"] is None
        assert point["ineligible_reason"] is None

    def test_below_minimum_and_sale_verdicts_come_from_the_classifier(self, db_session, world):
        # Two more classifier verdicts this module never restates: a
        # below-minimum floor fails closed, and a Yuyu-Tei sale price is
        # DESCRIBED without being excluded.
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=800, observed_at=day(3))
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=120, promotion_state="sale", observed_at=day(3))
        payload = series_by_key(fetch(db_session, world["base"].id))
        snk = all_points(payload["source:snkrdunk"])[0]
        assert snk["constraint"] == "below_platform_minimum"
        assert snk["eligible"] is False
        yuyu = all_points(payload["source:yuyutei"])[0]
        assert yuyu["constraint"] == "sale_price"
        # A sale price is a real, buyable price - described, never excluded.
        assert yuyu["eligible"] is True

    def test_sample_size_is_null_because_no_stored_row_is_an_aggregate(
        self, db_session, world
    ):
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=500, observed_at=day(1))
        point = all_points(series_by_key(fetch(db_session, world["base"].id))["source:yuyutei"])[0]
        assert point["sample_size"] is None


# ---------------------------------------------------------------------- F ---
class TestGenericSourceResolution:
    def test_a_future_source_charts_with_no_code_change(self, db_session, world):
        # F + M. "cardrush" appears in no registry, no enum and no allowlist.
        # It gets a real series the moment it has a sources row and an
        # observation - unlabelled, because Atlas has no instrument rule for
        # it, but with every real number intact.
        cardrush = make_source(db_session, "cardrush")
        mapping = make_mapping(db_session, world["legacy"], cardrush, world["base"])
        make_observation(
            db_session, world["legacy"], cardrush, mapping, world["base"],
            price_type="listing", price_jpy=4200, observed_at=day(1),
        )
        entry = series_by_key(fetch(db_session, world["base"].id))["source:cardrush"]
        assert entry["available"] is True
        assert entry["source"] == "cardrush"
        assert entry["role"] == ROLE_PRIMARY
        point = all_points(entry)[0]
        assert point["value_jpy"] == 4200
        # Honestly unlabelled rather than given an invented instrument...
        assert point["reference_type"] is None
        assert point["evidence_type"] is None
        # ...and classify_observation fails open, so it is not falsely
        # constrained either.
        assert point["eligible"] is True
        assert point["constraint"] is None

    def test_no_source_name_allowlist_exists_in_the_module(self):
        # M. The regression this guards is a VALID_SOURCES tuple like the one
        # in the legacy /market/movers endpoint, where adding a source means
        # editing a list.
        #
        # Scanned as an AST rather than as text, so the module's own prose may
        # freely NAME the sources it refuses to branch on - the assertion is
        # about executable code, and a grep would only measure the docstring.
        import ast

        tree = ast.parse(open(print_series.__file__).read())
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        code_strings = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
        assigned = {
            target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        } | {
            node.target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }

        assert not any("VALID_SOURCES" in name for name in assigned)
        # No executable string in the module is a source name, so no code path
        # can compare against one or hold a list of them.
        for name in ("yuyutei", "snkrdunk", "bandai", "cardrush", "mercado", "cardmarket"):
            assert name not in code_strings, f"{name!r} appears in executable code"

    def test_two_unlabelled_instruments_are_not_welded_into_one_line(
        self, db_session, world
    ):
        # The failure mode a label-only segmentation rule has: an unconfigured
        # source describes EVERY price_type as reference_type=None, so testing
        # the label alone reports "same instrument" for a listing line and a
        # sold line and draws one stroke through the change - the exact error
        # this module exists to prevent, arriving through the generic path
        # rather than the configured one.
        cardrush = make_source(db_session, "cardrush")
        mapping = make_mapping(db_session, world["legacy"], cardrush, world["base"])
        for offset, price_type, price in (
            (4, "listing", 4200), (3, "listing", 4300), (2, "sold", 3100)
        ):
            make_observation(
                db_session, world["legacy"], cardrush, mapping, world["base"],
                price_type=price_type, price_jpy=price, observed_at=day(offset),
            )
        entry = series_by_key(fetch(db_session, world["base"].id))["source:cardrush"]

        assert len(entry["segments"]) == 2, "two instruments, two strokes"
        assert [p["value_jpy"] for p in entry["segments"][0]["points"]] == [4200, 4300]
        assert [p["value_jpy"] for p in entry["segments"][1]["points"]] == [3100]
        # Both sides are honestly unlabelled - and unlabelled is not "the same".
        assert entry["segments"][0]["reference_type"] is None
        assert entry["segments"][1]["reference_type"] is None
        # So the boundary is reported under its own reason rather than as a
        # reference_type_change from null to null, which would read as a no-op.
        assert [b["reason"] for b in entry["breaks"]] == [
            print_series.BREAK_INSTRUMENT_CHANGE
        ]
        assert _same_instant(entry["breaks"][0]["at"], day(2))

    def test_one_unlabelled_instrument_stays_one_unbroken_segment(
        self, db_session, world
    ):
        # The other half: splitting per stored instrument must not break an
        # unknown series at every point. One price_type is one segment, which
        # is every source that exists today.
        cardrush = make_source(db_session, "cardrush")
        mapping = make_mapping(db_session, world["legacy"], cardrush, world["base"])
        for offset in (3, 2, 1):
            make_observation(
                db_session, world["legacy"], cardrush, mapping, world["base"],
                price_type="listing", price_jpy=4200 + offset, observed_at=day(offset),
            )
        entry = series_by_key(fetch(db_session, world["base"].id))["source:cardrush"]
        assert len(entry["segments"]) == 1
        assert len(entry["segments"][0]["points"]) == 3
        assert entry["breaks"] == []

    def test_default_selection_is_discovered_from_data_not_a_list(self, db_session, world):
        mercado = make_source(db_session, "mercado")
        mapping = make_mapping(db_session, world["legacy"], mercado, world["base"])
        make_observation(
            db_session, world["legacy"], mercado, mapping, world["base"],
            price_type="listing", price_jpy=999, observed_at=day(1),
        )
        keys = list(series_by_key(fetch(db_session, world["base"].id)))
        assert "source:mercado" in keys
        assert keys[0] == "market_index"


# ---------------------------------------------------------------------- G ---
class TestInstrumentSegmentation:
    def test_reference_type_switch_creates_separate_segments_and_a_break(
        self, db_session, world
    ):
        # G. The load-bearing case: SNKRDUNK reports a listing floor, then
        # acquires enough sold history to report a transaction median. Those
        # are different quantities. One stroke through the change would draw a
        # change of measuring instrument as a price movement.
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=2000, observed_at=day(4))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=2100, observed_at=day(3))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="sold", price_jpy=1700, observed_at=day(2))
        entry = series_by_key(fetch(db_session, world["base"].id))["source:snkrdunk"]

        assert len(entry["segments"]) == 2
        assert entry["segments"][0]["reference_type"] == "listing_floor"
        assert entry["segments"][0]["evidence_type"] == "listing"
        assert [p["value_jpy"] for p in entry["segments"][0]["points"]] == [2000, 2100]
        assert entry["segments"][1]["reference_type"] == "transaction_median"
        assert entry["segments"][1]["evidence_type"] == "transaction"
        assert [p["value_jpy"] for p in entry["segments"][1]["points"]] == [1700]

        assert len(entry["breaks"]) == 1
        brk = entry["breaks"][0]
        assert brk["reason"] == "reference_type_change"
        assert brk["from_reference_type"] == "listing_floor"
        assert brk["to_reference_type"] == "transaction_median"
        # Timestamped at the first point AFTER the change, so a client can
        # place a marker without re-deriving the boundary.
        assert brk["at"] == entry["segments"][1]["points"][0]["t"]

    def test_one_instrument_throughout_is_one_unbroken_segment(self, db_session, world):
        for offset, price in ((3, 500), (2, 520), (1, 480)):
            observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                    price_jpy=price, observed_at=day(offset))
        entry = series_by_key(fetch(db_session, world["base"].id))["source:yuyutei"]
        assert len(entry["segments"]) == 1
        assert entry["breaks"] == []
        assert len(entry["segments"][0]["points"]) == 3

    def test_every_registry_entry_matches_the_shipped_resolver(self, db_session, world):
        # The registry restates reference_type/evidence_type strings that live
        # as literals inside market_index's resolvers, because those resolvers
        # answer only for the latest value and cannot be called per historical
        # point. This test is what keeps the restatement honest: it asks the
        # SHIPPED resolvers what they call each instrument and compares.
        # market_index._naive_utc strips the tz off the observation, so the
        # `now` handed to a resolver must be naive too - same convention the
        # index endpoints use.
        naive_now = NOW.replace(tzinfo=None)
        sell = _resolve_yuyutei_sell(
            PriceObservation(price_type="sell", price_jpy=500, observed_at=naive_now), naive_now
        )
        buy = _resolve_yuyutei_buy(
            PriceObservation(price_type="buy", price_jpy=200, observed_at=naive_now)
        )
        floor = _resolve_snkrdunk(
            [],
            PriceObservation(price_type="floor", price_jpy=2500, observed_at=naive_now),
            naive_now,
        )
        sold = _resolve_snkrdunk(
            [
                PriceObservation(price_type="sold", price_jpy=p, observed_at=naive_now)
                for p in (1500, 1600, 1700)
            ],
            None,
            naive_now,
        )
        expected = {
            ("yuyutei", "sell"): (sell.reference_type, sell.evidence_type),
            ("yuyutei", "buy"): (buy.reference_type, buy.evidence_type),
            ("snkrdunk", "floor"): (floor.reference_type, floor.evidence_type),
            ("snkrdunk", "sold"): (sold.reference_type, sold.evidence_type),
        }
        assert set(SOURCE_INSTRUMENTS) == set(expected)
        for key, (reference_type, evidence_type) in expected.items():
            instrument = SOURCE_INSTRUMENTS[key]
            assert instrument.reference_type == reference_type, key
            assert instrument.evidence_type == evidence_type, key


# ------------------------------------------------------------------- H, I ---
class TestMarketIndexHistory:
    def snapshot(self, db_session, print_id, offset, value, index_version, semantics=1):
        calculated_at = day(offset)
        row = MarketIndexSnapshot(
            card_print_id=print_id,
            calculated_at=calculated_at,
            snapshot_date=calculated_at.date(),
            index_value_jpy=value,
            calculation_method="median_of_sources",
            source_count=1 if value is not None else 0,
            coverage_status="limited" if value is not None else "none",
            confidence="medium" if value is not None else "low",
            index_version=index_version,
            source_semantics_version=semantics,
            provenance={"source_values": []},
        )
        db_session.add(row)
        db_session.commit()
        return row

    def test_v1_v2_v3_produce_explicit_breaks(self, db_session, world):
        # H. Staging really does hold v1, v2 and v3 inside one 14-day table.
        # An unsegmented line would draw two methodology changes as price
        # movement, which is exactly what this refuses to do.
        self.snapshot(db_session, world["base"].id, 5, 1000, 1)
        self.snapshot(db_session, world["base"].id, 4, 1100, 1)
        self.snapshot(db_session, world["base"].id, 3, 900, 2)
        self.snapshot(db_session, world["base"].id, 2, 780, 3, semantics=2)
        entry = series_by_key(fetch(db_session, world["base"].id))["market_index"]

        assert [seg["index_version"] for seg in entry["segments"]] == [1, 2, 3]
        assert [len(seg["points"]) for seg in entry["segments"]] == [2, 1, 1]

        reasons = [b["reason"] for b in entry["breaks"]]
        assert reasons.count("index_version_change") == 2
        # v3 bumped the semantics ruleset too, and both are reported so a
        # client never has to guess which methodology moved.
        assert "source_semantics_version_change" in reasons
        version_breaks = [b for b in entry["breaks"] if b["reason"] == "index_version_change"]
        assert (version_breaks[0]["from_index_version"], version_breaks[0]["to_index_version"]) == (1, 2)
        assert (version_breaks[1]["from_index_version"], version_breaks[1]["to_index_version"]) == (2, 3)

    def test_points_are_archived_values_never_recomputed(self, db_session, world):
        # I. The observations below would produce a completely different index
        # if anything recomputed one. The archived number must survive intact.
        self.snapshot(db_session, world["base"].id, 2, 1234, 1)
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=99999, observed_at=day(2))
        entry = series_by_key(fetch(db_session, world["base"].id))["market_index"]
        point = all_points(entry)[0]
        assert point["value_jpy"] == 1234
        assert point["index_version"] == 1
        assert point["source_semantics_version"] == 1
        assert point["source_count"] == 1
        assert point["coverage_status"] == "limited"

    def test_a_null_archived_index_is_a_result_not_a_zero(self, db_session, world):
        # coverage_status='none' means no source was eligible that day. That is
        # a recorded outcome; rendering it as ¥0 would invent a price.
        self.snapshot(db_session, world["base"].id, 2, None, 3, semantics=2)
        point = all_points(series_by_key(fetch(db_session, world["base"].id))["market_index"])[0]
        assert point["value_jpy"] is None
        assert point["coverage_status"] == "none"

    def test_index_series_carries_no_quality_score(self, db_session, world):
        # market_index_snapshots.confidence is a 1:1 relabelling of
        # coverage_status, not a reliability measure, so it is deliberately not
        # surfaced as one here.
        self.snapshot(db_session, world["base"].id, 2, 1000, 3, semantics=2)
        entry = series_by_key(fetch(db_session, world["base"].id))["market_index"]
        assert "confidence" not in entry["coverage"]
        assert not any("quality" in key or "reliab" in key for key in entry["coverage"])
        assert all("confidence" not in point for point in all_points(entry))


# ---------------------------------------------------------------------- J ---
class TestAuxiliaryInstrumentIsolation:
    def test_dealer_buy_never_enters_the_yuyutei_platform_series(self, db_session, world):
        # J. A dealer buy quote is what a shop PAYS. Letting it into the retail
        # line would halve a card's apparent price with no visible cause.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_type="sell", price_jpy=1000, observed_at=day(1))
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_type="buy", price_jpy=400, observed_at=day(1))
        entry = series_by_key(fetch(db_session, world["base"].id))["source:yuyutei"]
        assert entry["role"] == ROLE_PRIMARY
        values = [p["value_jpy"] for p in all_points(entry)]
        assert values == [1000]
        assert 400 not in values
        assert all(p["reference_type"] == "retail_sell" for p in all_points(entry))

    def test_no_public_selector_can_reach_an_auxiliary_instrument(self, db_session, world):
        # The stored-price_type key form is gone from the public contract, so
        # there is no request syntax that reaches dealer buy at all. The
        # extension point is a request-level flag (see parse_series_key), not a
        # wider key grammar that would leak storage vocabulary.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_type="sell", price_jpy=1000, observed_at=day(1))
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_type="buy", price_jpy=400, observed_at=day(1))
        with pytest.raises(SeriesKeyError):
            parse_series_key("source:yuyutei:buy")
        # And the value is absent from every series the contract can produce.
        payload = fetch(db_session, world["base"].id)
        assert 400 not in [
            point["value_jpy"]
            for entry in payload["series"]
            for point in all_points(entry)
        ]

    def test_no_public_request_syntax_depends_on_stored_price_type(self):
        # Storage vocabulary must never appear in a request. Every stored
        # price_type is rejected as a key suffix, so a source that renamed one
        # could not break a saved chart URL.
        for stored in ("sell", "buy", "floor", "sold", "listing"):
            with pytest.raises(SeriesKeyError):
                parse_series_key(f"source:yuyutei:{stored}")
            with pytest.raises(SeriesKeyError):
                parse_series_key(f"source:snkrdunk:{stored}")

    def test_stored_price_type_is_absent_from_the_entire_public_payload(
        self, db_session, world
    ):
        # The response side of the same rule the key grammar enforces. A
        # published price_type is a field clients branch on within a week,
        # which would re-create the coupling one layer down and leave it
        # undetectable: the request would look clean while every saved chart
        # still broke when a collector renamed a stored value. What a point IS
        # is said in reference_type/evidence_type, and nowhere else.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=1000, observed_at=day(1))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=2000, observed_at=day(1))
        payload = fetch(db_session, world["base"].id)

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    assert key != "price_type", "stored vocabulary in the payload"
                    yield from walk(value)
            elif isinstance(node, list):
                for item in node:
                    yield from walk(item)
            elif isinstance(node, str):
                yield node

        published = set(walk(payload))
        for stored in ("sell", "buy", "floor", "sold"):
            assert stored not in published, f"{stored!r} is stored vocabulary"
        # The public vocabulary is present in its place, so the instrument is
        # not simply missing.
        assert {"retail_sell", "listing_floor"} <= published

    def test_the_registry_agrees_that_buy_is_the_only_auxiliary(self):
        assert describe_instrument("yuyutei", "buy").role == ROLE_AUXILIARY
        assert describe_instrument("yuyutei", "sell").role == ROLE_PRIMARY
        assert primary_price_types("yuyutei") == ("sell",)
        assert set(primary_price_types("snkrdunk")) == {"floor", "sold"}


# ---------------------------------------------------------------------- K ---
class TestWindows:
    def test_windows_include_and_exclude_by_boundary(self, db_session, world):
        # K. One observation in each band: inside 7d, inside 30d only, and
        # older than 30d.
        for offset, price in ((3, 100), (20, 200), (45, 300)):
            observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                    price_jpy=price, observed_at=day(offset))

        def values(window):
            payload = fetch(db_session, world["base"].id, window=window)
            return [p["value_jpy"] for p in all_points(series_by_key(payload)["source:yuyutei"])]

        assert values("7d") == [100]
        assert values("30d") == [200, 100]
        assert values("all") == [300, 200, 100]

    def test_window_start_is_null_only_for_all(self, db_session, world):
        assert fetch(db_session, world["base"].id, window="all")["window_start"] is None
        assert _same_instant(
            fetch(db_session, world["base"].id, window="7d")["window_start"],
            NOW - timedelta(days=7),
        )

    def test_90d_is_not_offered_yet(self):
        assert "90d" not in print_series.WINDOW_DAYS
        with pytest.raises(SeriesKeyError):
            get_print_series(None, 1, window="90d")


# ---------------------------------------------------------------------- L ---
class TestExactPrintIsolation:
    def test_sibling_printings_never_share_history(self, db_session, world):
        # L. Both prints bridge through ONE legacy card row, which is the real
        # staging shape and the trap a card_id-keyed query falls into.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=120, observed_at=day(1))
        observe(db_session, world, "yuyutei", "parallel", "yuyutei_parallel",
                price_jpy=9800, observed_at=day(1))

        base_values = [
            p["value_jpy"]
            for p in all_points(series_by_key(fetch(db_session, world["base"].id))["source:yuyutei"])
        ]
        parallel_values = [
            p["value_jpy"]
            for p in all_points(
                series_by_key(fetch(db_session, world["parallel"].id))["source:yuyutei"]
            )
        ]
        assert base_values == [120]
        assert parallel_values == [9800]

    def test_a_legacy_lineage_less_observation_is_unreachable(self, db_session, world):
        # card_print_id IS NULL can never match a print filter, so a legacy row
        # cannot leak into any series.
        make_observation(
            db_session, world["legacy"], world["yuyutei"], None, None,
            price_jpy=7777, observed_at=day(1),
        )
        entry = series_by_key(fetch(db_session, world["base"].id)).get("source:yuyutei")
        assert entry is None or 7777 not in [p["value_jpy"] for p in all_points(entry)]


# ---------------------------------------------------------------------- N ---
class TestUnavailableSeriesAreHonest:
    def test_uncollected_platform_returns_an_unavailable_series_not_a_404(
        self, db_session, world
    ):
        # N. Atlas has no Cardmarket source row. The honest answer is a named,
        # empty, explicitly-unavailable series - never fabricated points, and
        # never an error that would make the whole request fail.
        payload = fetch(db_session, world["base"].id, keys=["source:cardmarket"])
        entry = series_by_key(payload)["source:cardmarket"]
        assert entry["available"] is False
        assert entry["unavailable_reason"] == "source_not_configured"
        assert entry["source"] == "cardmarket"
        assert entry["segments"] == []
        assert entry["breaks"] == []
        assert entry["coverage"]["point_count"] == 0
        assert entry["coverage"]["earliest"] is None

    def test_configured_source_with_no_history_is_distinguished(self, db_session, world):
        # A different fact from the above, and reported differently: Atlas does
        # collect SNKRDUNK, this print simply has none.
        entry = series_by_key(fetch(db_session, world["base"].id, keys=["source:snkrdunk"]))[
            "source:snkrdunk"
        ]
        assert entry["available"] is False
        assert entry["unavailable_reason"] == "no_history_in_window"

    def test_unparseable_keys_are_client_errors(self):
        for bad in (
            "", "   ", "sources:yuyutei", "yuyutei", "source:",
            "source:a:b:c", "source:yuyutei:sell",
        ):
            with pytest.raises(SeriesKeyError):
                parse_series_key(bad)

    def test_a_duplicate_selector_returns_one_series(self, db_session, world):
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=100, observed_at=day(1))
        payload = fetch(
            db_session, world["base"].id, keys=["source:yuyutei", "source:yuyutei"]
        )
        assert len(payload["series"]) == 1


# ------------------------------------------------------------------ COVERAGE ---
class TestCoverageIsFactual:
    def coverage_for(self, db_session, world, offsets, window="all"):
        for offset in offsets:
            observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                    price_jpy=100 + offset, observed_at=day(offset))
        payload = fetch(db_session, world["base"].id, window=window)
        return series_by_key(payload)["source:yuyutei"]["coverage"]

    def test_coverage_reports_measured_facts(self, db_session, world):
        coverage = self.coverage_for(db_session, world, (5, 3, 1))
        assert coverage["distinct_days"] == 3
        assert coverage["point_count"] == 3
        assert _same_instant(coverage["earliest"], day(5))
        assert _same_instant(coverage["latest"], day(1))

    def test_exactly_seven_days_covers_the_seven_day_window(self, db_session, world):
        # The boundary itself: a point on the UTC day that is exactly 7 days
        # back reaches the window's edge, so it covers it.
        coverage = self.coverage_for(db_session, world, (7, 1))
        assert coverage["covers_7d"] is True

    def test_just_under_seven_days_does_not_cover_it(self, db_session, world):
        coverage = self.coverage_for(db_session, world, (6, 1))
        assert coverage["covers_7d"] is False

    def test_exactly_thirty_days_covers_the_thirty_day_window(self, db_session, world):
        coverage = self.coverage_for(db_session, world, (30, 1))
        assert coverage["covers_30d"] is True

    def test_just_under_thirty_days_does_not_cover_it(self, db_session, world):
        coverage = self.coverage_for(db_session, world, (29, 1))
        assert coverage["covers_30d"] is False

    def test_sparse_history_spanning_the_window_still_covers_it(self, db_session, world):
        # Two points, 30 days apart, nothing in between. Coverage is about
        # SPAN, not density - a point on every day is never required and the
        # 28 missing days stay honest gaps with no invented points.
        coverage = self.coverage_for(db_session, world, (30, 0))
        assert coverage["covers_7d"] is True
        assert coverage["covers_30d"] is True
        assert coverage["distinct_days"] == 2

    def test_fourteen_days_covers_seven_but_not_thirty(self, db_session, world):
        # The exact staging case this correction was written for: 14 days of
        # Market Index history covered 7 and did NOT cover 30, while the old
        # naming reported "sufficient_for_30d: true".
        coverage = self.coverage_for(db_session, world, tuple(range(14)))
        assert coverage["distinct_days"] == 14
        assert coverage["covers_7d"] is True
        assert coverage["covers_30d"] is False

    def test_a_series_first_seen_yesterday_covers_nothing(self, db_session, world):
        coverage = self.coverage_for(db_session, world, (1,))
        assert coverage["covers_7d"] is False
        assert coverage["covers_30d"] is False

    def test_a_narrow_window_cannot_answer_a_wider_question(self, db_session, world):
        # window=7d truncates at 7 days by construction, so it can say nothing
        # about 30-day history. Null, never a false that would read as "no
        # 30-day history exists".
        coverage = self.coverage_for(db_session, world, (30, 5, 1), window="7d")
        assert coverage["covers_7d"] is False
        assert coverage["covers_30d"] is None

    def test_a_window_answers_about_its_own_edge(self, db_session, world):
        # A point on the UTC day 30 days back, but EARLIER in that day than
        # `generated_at`, sits before `now - 30 days` and is truncated out of
        # window=30d by construction. covers_30d is then false for that
        # request and true for window=all, and both are correct: each answers
        # about the series it actually returned. Pinned so the difference is a
        # decision rather than a surprise.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=300, observed_at=day(30, hour=3))
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=310, observed_at=day(1))

        def coverage(window):
            payload = fetch(db_session, world["base"].id, window=window)
            return series_by_key(payload)["source:yuyutei"]["coverage"]

        assert coverage("30d")["covers_30d"] is False
        assert coverage("30d")["point_count"] == 1
        assert coverage("all")["covers_30d"] is True
        assert coverage("all")["point_count"] == 2

    def test_an_empty_series_covers_nothing(self, db_session, world):
        coverage = series_by_key(
            fetch(db_session, world["base"].id, keys=["source:snkrdunk"])
        )["source:snkrdunk"]["coverage"]
        assert coverage["covers_7d"] is False
        assert coverage["covers_30d"] is False
        assert coverage["point_count"] == 0

    def test_nothing_is_named_sufficient_any_more(self, db_session, world):
        # The old name meant "enough points to draw a line" and was read as a
        # claim about the window. It must not survive in any form.
        coverage = self.coverage_for(db_session, world, (2, 1))
        assert not any("sufficient" in key for key in coverage)


# ------------------------------------------------------------ QUERY SHAPE ---
class TestQueryShape:
    """A fixed, small number of queries regardless of how much history exists.

    The cost that matters is round trips, not rows: this endpoint will be
    called per print detail page and the catalogue already knows what an
    O(catalogue) scan costs. Selecting N platforms must cost a CONSTANT number
    of queries - not one per platform, and never one per day, per point or per
    segment.
    """

    @staticmethod
    def _record(db_session):
        """Count every statement the session issues, as raw SQL."""
        counts: list[str] = []
        engine = db_session.get_bind()

        @event.listens_for(engine, "before_cursor_execute")
        def listener(conn, cursor, statement, *args, **kwargs):  # pragma: no cover
            counts.append(statement)

        return engine, listener, counts

    def test_query_count_is_constant_in_depth_and_platform_count(self, db_session, world):
        # 60 days x 3 readings a day, on two sources - deeper than anything in
        # production, where the oldest observation is 27 days old.
        for offset in range(60):
            for hour in (3, 12, 20):
                observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                        price_jpy=500 + offset, observed_at=day(offset, hour))
                observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                        price_type="floor", price_jpy=2000 + offset,
                        observed_at=day(offset, hour))

        # Read the id BEFORE the listener is attached: the fixture's commits
        # expire the ORM instance, so touching it later would emit a refresh
        # SELECT and be counted as if this service had issued it.
        print_id = world["base"].id

        engine, listener, counts = self._record(db_session)
        try:
            payload = fetch(
                db_session,
                print_id,
                keys=["market_index", "source:yuyutei", "source:snkrdunk"],
            )
        finally:
            event.remove(engine, "before_cursor_execute", listener)

        points = sum(
            len(segment["points"])
            for entry in payload["series"]
            for segment in entry["segments"]
        )
        assert points == 120, "60 days x 2 sources, one point per source per day"
        # THREE queries for a full request, and the count does not grow with
        # the number of platforms selected: the source catalogue once, every
        # requested platform's observations once (one OR-ed query, partitioned
        # in Python), and the snapshot archive once.
        assert len(counts) == 3, f"expected 3 queries, got {len(counts)}: {counts}"

    def test_the_default_request_costs_no_extra_round_trip(self, db_session, world):
        # The shape a print detail page actually sends - no series parameter,
        # so the server must first discover which platforms hold history for
        # this print. That discovery is folded into the source-catalogue read
        # rather than issued as a fourth query, so the commonest request is
        # not the most expensive one.
        for offset in range(5):
            observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                    price_jpy=500 + offset, observed_at=day(offset))
            observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                    price_type="floor", price_jpy=2000 + offset, observed_at=day(offset))
        print_id = world["base"].id

        engine, listener, counts = self._record(db_session)
        try:
            payload = fetch(db_session, print_id)
        finally:
            event.remove(engine, "before_cursor_execute", listener)

        # The default selection is still discovered from the data.
        assert list(series_by_key(payload)) == [
            "market_index", "source:snkrdunk", "source:yuyutei",
        ]
        assert len(counts) == 3, f"expected 3 queries, got {len(counts)}: {counts}"


# --------------------------------------------------------------- ENDPOINT ---
class TestEndpoint:
    def test_returns_the_contract_over_http(self, client, db_session, world):
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=780, observed_at=datetime.now(timezone.utc) - timedelta(days=1))
        response = client.get(f"/prints/{world['base'].id}/series?window=7d")
        assert response.status_code == 200
        body = response.json()
        assert body["card_print_id"] == world["base"].id
        assert body["window"] == "7d"
        entry = series_by_key(body)["source:yuyutei"]
        assert entry["kind"] == "source"
        assert entry["role"] == "primary"
        assert entry["segments"][0]["reference_type"] == "retail_sell"

    def test_repeatable_series_parameter(self, client, db_session, world):
        response = client.get(
            f"/prints/{world['base'].id}/series",
            params=[("series", "market_index"), ("series", "source:snkrdunk")],
        )
        assert response.status_code == 200
        assert list(series_by_key(response.json())) == ["market_index", "source:snkrdunk"]

    def test_bad_window_and_bad_key_are_400(self, client, world):
        assert client.get(f"/prints/{world['base'].id}/series?window=90d").status_code == 400
        assert (
            client.get(f"/prints/{world['base'].id}/series?series=nonsense").status_code == 400
        )

    def test_unknown_print_is_404(self, client, db_session):
        assert client.get("/prints/99999999/series").status_code == 404
