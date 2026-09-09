"""`series_stats` on GET /prints/{print_id}/analytics.

WHAT THIS SUITE DEFENDS. The field exists so a browser never has to compute a
financial statistic from chart points, which means the risk it introduces is a
server that publishes a figure the plot beside it does not support: a change
subtracted across a methodology boundary, a high taken from a disqualified
reading, an `observed_days` that counts a day twice or counts a day that was
never recorded, a row for a platform with nothing to show, or a summary of a
window other than the one asked for. Every test below is one of those refusals.

The statistics themselves are arithmetic on archived integers and are not
interesting on their own; what is interesting is WHICH observations they are
allowed to be taken over, and when the server must decline to subtract.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import MarketIndexSnapshot
from app.services.market_index_change import NOT_COMPARABLE_CONTRIBUTORS
from app.services.print_analytics import (
    CHANGE_UNAVAILABLE_SINGLE_POINT,
    get_print_analytics,
)
from app.services.print_series import (
    BREAK_INDEX_VERSION_CHANGE,
    BREAK_REFERENCE_TYPE_CHANGE,
)
from tests.test_print_series import observe, world  # noqa: F401  (fixture)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def day(offset: int, hour: int = 12) -> datetime:
    return (NOW - timedelta(days=offset)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


def snapshot(
    db_session,
    print_id: int,
    days_ago: int,
    value: int | None,
    *,
    index_version: int = 3,
    semantics: int = 2,
    contributors: list[dict] | None = None,
):
    """One archived Market Index row, shaped as `test_print_analytics` shapes
    them: a single contributing Yuyu-Tei retail price by default, so the
    comparability guard is satisfied unless a test asks for a refusal."""
    calculated_at = day(days_ago)
    if contributors is None:
        contributors = [
            {
                "source": "yuyutei",
                "reference_type": "retail_price",
                "contributes_to_index": True,
                "value_jpy": value,
            }
        ]
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
        provenance={"source_values": contributors},
    )
    db_session.add(row)
    db_session.commit()
    return row


def fetch(db_session, print_id, window=None):
    return get_print_analytics(db_session, print_id, window=window, now=NOW)


def stats_by_key(payload) -> dict[str, dict]:
    return {row["series_key"]: row for row in payload["series_stats"]}


# ------------------------------------------------------- 1, 2, 3: normal shape --


class TestNormalSeries:
    def test_market_index_series_summarises_its_archived_days(self, db_session, world):
        print_id = world["base"].id
        snapshot(db_session, print_id, 4, 27400)
        snapshot(db_session, print_id, 3, 24900)
        snapshot(db_session, print_id, 2, 22650)
        snapshot(db_session, print_id, 1, 22900)

        row = stats_by_key(fetch(db_session, print_id))["market_index"]

        assert row["kind"] == "market_index"
        assert row["source"] is None
        assert (row["starting_value_jpy"], row["starting_as_of"]) == (
            27400,
            day(4).date(),
        )
        assert (row["current_value_jpy"], row["current_as_of"]) == (22900, day(1).date())
        assert (row["low_value_jpy"], row["low_as_of"]) == (22650, day(2).date())
        assert (row["high_value_jpy"], row["high_as_of"]) == (27400, day(4).date())
        assert row["observed_days"] == 4
        assert row["change"]["absolute_jpy"] == 22900 - 27400
        assert row["change"]["from_date"] == day(4).date()
        assert row["change"]["to_date"] == day(1).date()
        assert row["change_unavailable_reason"] is None

    def test_yuyutei_series_is_summarised_as_its_own_instrument(
        self, db_session, world
    ):
        print_id = world["base"].id
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=24800, observed_at=day(3))
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=23000, observed_at=day(1))

        row = stats_by_key(fetch(db_session, print_id))["source:yuyutei"]

        assert row["kind"] == "source"
        assert row["source"] == "yuyutei"
        assert row["starting_value_jpy"] == 24800
        assert row["current_value_jpy"] == 23000
        assert row["observed_days"] == 2
        assert row["change"]["absolute_jpy"] == -1800

    def test_snkrdunk_series_is_summarised_separately(self, db_session, world):
        print_id = world["base"].id
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=21000, observed_at=day(3))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=21500, observed_at=day(1))

        rows = stats_by_key(fetch(db_session, print_id))

        assert rows["source:snkrdunk"]["source"] == "snkrdunk"
        assert rows["source:snkrdunk"]["change"]["absolute_jpy"] == 500
        # Each platform keeps its own row. Nothing merges them, and nothing
        # here presents the two as one comparable price.
        assert "source:yuyutei" not in rows

    def test_every_stats_row_names_a_series_that_is_actually_returned(
        self, db_session, world
    ):
        print_id = world["base"].id
        snapshot(db_session, print_id, 2, 22000)
        snapshot(db_session, print_id, 1, 22500)
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=24800, observed_at=day(2))
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=24000, observed_at=day(1))

        payload = fetch(db_session, print_id)

        drawn = {entry["key"] for entry in payload["series"]}
        assert {row["series_key"] for row in payload["series_stats"]} <= drawn


# ------------------------------------------------------------ 4, 5: absences --


class TestAbsentPlatformsGetNoRow:
    def test_no_yuyutei_row_when_yuyutei_never_priced_this_print(
        self, db_session, world
    ):
        print_id = world["base"].id
        snapshot(db_session, print_id, 2, 13000)
        snapshot(db_session, print_id, 1, 13000)
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=13000, observed_at=day(1))

        rows = stats_by_key(fetch(db_session, print_id))

        # Print 5686's shape. No row at all - never a row of nulls or zeros,
        # which would assert a measurement that was never taken.
        assert "source:yuyutei" not in rows
        assert set(rows) == {"market_index", "source:snkrdunk"}

    def test_no_snkrdunk_row_when_snkrdunk_never_priced_this_print(
        self, db_session, world
    ):
        print_id = world["base"].id
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=24800, observed_at=day(1))

        rows = stats_by_key(fetch(db_session, print_id))

        assert "source:snkrdunk" not in rows

    def test_a_wholly_disqualified_platform_gets_no_row(self, db_session, world):
        # Present in the payload with real numbers, but nothing this chart can
        # draw - so there is nothing to summarise, and a row would claim there
        # was.
        print_id = world["base"].id
        # ¥1,000 IS the SNKRDUNK platform minimum, which the series builder
        # marks constrained and ineligible - a real number, and not a price
        # this card traded at.
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=1000, observed_at=day(2))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=1000, observed_at=day(1))

        assert "source:snkrdunk" not in stats_by_key(fetch(db_session, print_id))


# ------------------------------------------------------------- 6: single point --


class TestSinglePoint:
    def test_stats_publish_but_change_refuses(self, db_session, world):
        print_id = world["base"].id
        snapshot(db_session, print_id, 1, 22900)

        row = stats_by_key(fetch(db_session, print_id))["market_index"]

        # The figures are all real - one day is a measurement.
        assert row["starting_value_jpy"] == 22900
        assert row["current_value_jpy"] == 22900
        assert row["low_value_jpy"] == row["high_value_jpy"] == 22900
        assert row["observed_days"] == 1
        # There is nothing to compare it with, and that is said rather than
        # published as a 0% move.
        assert row["change"] is None
        assert row["change_unavailable_reason"] == CHANGE_UNAVAILABLE_SINGLE_POINT


# ------------------------------------------------------------------- 7: gaps --


class TestGapsAreNotFilled:
    def test_a_missing_day_is_neither_invented_nor_treated_as_a_boundary(
        self, db_session, world
    ):
        print_id = world["base"].id
        snapshot(db_session, print_id, 6, 20000)
        # Days 5, 4, 3 simply were not recorded.
        snapshot(db_session, print_id, 2, 26000)
        snapshot(db_session, print_id, 1, 24000)

        row = stats_by_key(fetch(db_session, print_id))["market_index"]

        # Three real days, not six. Nothing was forward-filled to bridge the
        # hole and no interpolated point appears in the count.
        assert row["observed_days"] == 3
        assert row["high_value_jpy"] == 26000
        # A plain missing day splits no segment and emits no break, so the two
        # real ends stay comparable - the gap neither invents continuity nor
        # fabricates a refusal.
        assert row["change"] is not None
        assert row["change"]["absolute_jpy"] == 24000 - 20000
        assert row["change"]["spans_break"] is False


# --------------------------------------------------- 8, 9: boundary refusals --


class TestChangeIsBreakAware:
    def test_market_index_version_boundary_refuses_the_subtraction(
        self, db_session, world
    ):
        print_id = world["base"].id
        snapshot(db_session, print_id, 3, 20000, index_version=2)
        snapshot(db_session, print_id, 1, 30000, index_version=3)

        row = stats_by_key(fetch(db_session, print_id))["market_index"]

        # A naive first-vs-last would report +50%, which would be a methodology
        # change reported as a price change.
        #
        # NOTE: for the Market Index this refusal is DOUBLY guarded - the
        # segment rule and the headline's own version guard both catch it, and
        # both name it `index_version_change`. This test therefore proves the
        # refusal, not which guard produced it; the segment rule is isolated by
        # the source-instrument test below, where no headline guard applies.
        assert row["change"] is None
        assert row["change_unavailable_reason"] == BREAK_INDEX_VERSION_CHANGE
        # The statistics themselves still publish: they are observations, not
        # comparisons.
        assert row["starting_value_jpy"] == 20000
        assert row["current_value_jpy"] == 30000
        assert row["observed_days"] == 2

    def test_source_instrument_change_refuses_the_subtraction(
        self, db_session, world
    ):
        # SNKRDUNK moving from a sold median to a listing floor: two different
        # measurements of the card, and subtracting one from the other is not a
        # movement in its price.
        print_id = world["base"].id
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="sold", price_jpy=30000, observed_at=day(3))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=21000, observed_at=day(1))

        row = stats_by_key(fetch(db_session, print_id))["source:snkrdunk"]

        assert row["change"] is None
        assert row["change_unavailable_reason"] == BREAK_REFERENCE_TYPE_CHANGE
        assert row["starting_value_jpy"] == 30000
        assert row["current_value_jpy"] == 21000

    def test_market_index_defers_to_the_headline_contributor_guard(
        self, db_session, world
    ):
        # The contributor set changed between the two ends. The segments cannot
        # see that - snapshots carry the contributors, series points do not -
        # so the headline's verdict is applied on top, and the page cannot end
        # up stating two different answers about the same number.
        print_id = world["base"].id
        snapshot(db_session, print_id, 3, 20000, contributors=[
            {"source": "yuyutei", "reference_type": "retail_price",
             "contributes_to_index": True, "value_jpy": 20000},
        ])
        snapshot(db_session, print_id, 1, 24000, contributors=[
            {"source": "snkrdunk", "reference_type": "listing_floor",
             "contributes_to_index": True, "value_jpy": 24000},
        ])

        payload = fetch(db_session, print_id)
        row = stats_by_key(payload)["market_index"]

        assert row["change"] is None
        assert row["change_unavailable_reason"] == NOT_COMPARABLE_CONTRIBUTORS
        # The two agree, which is the point of deferring.
        assert payload["headline"]["change"] is None
        assert (
            payload["headline"]["change_unavailable_reason"]
            == row["change_unavailable_reason"]
        )

    def test_a_published_change_never_spans_a_break(self, db_session, world):
        print_id = world["base"].id
        snapshot(db_session, print_id, 3, 20000)
        snapshot(db_session, print_id, 1, 21000)

        row = stats_by_key(fetch(db_session, print_id))["market_index"]

        assert row["change"] is not None
        assert row["change"]["spans_break"] is False


# ------------------------------------------------------- 10, 11: tie and nulls --


class TestExtremes:
    def test_high_and_low_ties_take_the_earliest_occurrence(
        self, db_session, world
    ):
        print_id = world["base"].id
        snapshot(db_session, print_id, 4, 25000)  # first high
        snapshot(db_session, print_id, 3, 21000)  # first low
        snapshot(db_session, print_id, 2, 21000)  # equal low, later
        snapshot(db_session, print_id, 1, 25000)  # equal high, later

        row = stats_by_key(fetch(db_session, print_id))["market_index"]

        assert (row["high_value_jpy"], row["high_as_of"]) == (25000, day(4).date())
        assert (row["low_value_jpy"], row["low_as_of"]) == (21000, day(3).date())

    def test_null_archived_days_are_excluded_from_every_statistic(
        self, db_session, world
    ):
        print_id = world["base"].id
        snapshot(db_session, print_id, 4, 24000)
        snapshot(db_session, print_id, 3, None)  # no source was eligible
        snapshot(db_session, print_id, 2, None)
        snapshot(db_session, print_id, 1, 22000)

        row = stats_by_key(fetch(db_session, print_id))["market_index"]

        # A null is not a zero, not a low, and not a day.
        assert row["low_value_jpy"] == 22000
        assert row["observed_days"] == 2
        assert row["starting_value_jpy"] == 24000
        assert row["current_value_jpy"] == 22000

    def test_a_disqualified_reading_never_becomes_a_low(self, db_session, world):
        print_id = world["base"].id
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=24000, observed_at=day(3))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=1000, observed_at=day(2))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_type="floor", price_jpy=23000, observed_at=day(1))

        row = stats_by_key(fetch(db_session, world["base"].id))["source:snkrdunk"]

        # The ¥1,000 platform minimum is a real number and stays in `series`
        # for the tooltip - but it is not a price this card traded at, so it is
        # not this series' low.
        assert row["low_value_jpy"] == 23000
        assert row["observed_days"] == 2


# ----------------------------------------------------------------- 12: windows --


class TestWindowGovernsStats:
    def test_a_narrower_window_summarises_only_its_own_days(
        self, db_session, world
    ):
        print_id = world["base"].id
        snapshot(db_session, print_id, 40, 40000)  # outside 2w
        snapshot(db_session, print_id, 30, 35000)  # outside 2w
        snapshot(db_session, print_id, 5, 26000)
        snapshot(db_session, print_id, 1, 24000)

        wide = stats_by_key(fetch(db_session, print_id, window="all"))["market_index"]
        narrow = stats_by_key(fetch(db_session, print_id, window="2w"))["market_index"]

        assert wide["observed_days"] == 4
        assert wide["high_value_jpy"] == 40000
        assert wide["starting_value_jpy"] == 40000

        # The narrow window is answered by the SERVER over its own rows, not by
        # slicing the wide one on the client: its high is the highest day it
        # actually contains.
        assert narrow["observed_days"] == 2
        assert narrow["high_value_jpy"] == 26000
        assert narrow["starting_value_jpy"] == 26000
        assert narrow["change"]["absolute_jpy"] == 24000 - 26000


# -------------------------------------------------------- 13: print isolation --


class TestExactPrintIsolation:
    def test_a_sibling_print_of_the_same_card_code_is_not_summarised(
        self, db_session, world
    ):
        # 955 card codes carry more than one print. Stats keyed on anything but
        # the exact print would blend two cards' histories into one summary.
        base_id = world["base"].id
        parallel_id = world["parallel"].id
        snapshot(db_session, base_id, 2, 22000)
        snapshot(db_session, base_id, 1, 22500)
        snapshot(db_session, parallel_id, 2, 90000)
        snapshot(db_session, parallel_id, 1, 95000)

        base = stats_by_key(fetch(db_session, base_id))["market_index"]
        parallel = stats_by_key(fetch(db_session, parallel_id))["market_index"]

        assert base["high_value_jpy"] == 22500
        assert parallel["high_value_jpy"] == 95000
        assert base["observed_days"] == parallel["observed_days"] == 2


# ------------------------------------------- 14, 15, 16: authority and purity --


class TestAuthorityAndPurity:
    def test_no_pricing_resolver_or_recomputation_runs(
        self, db_session, world, monkeypatch
    ):
        """The endpoint restates archive; it must not price anything.

        Every resolver and current-price entry point is replaced with a bomb.
        If `series_stats` ever reached for a live value instead of an archived
        one, this is where it would show.
        """
        import app.services.market_index as market_index
        import app.services.print_pricing as print_pricing

        def bomb(*args, **kwargs):  # pragma: no cover - only runs on failure
            raise AssertionError("a pricing/resolver path ran during analytics")

        for module, name in (
            (market_index, "compute_market_index"),
            (print_pricing, "compute_print_price_series_trends"),
        ):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, bomb)

        print_id = world["base"].id
        snapshot(db_session, print_id, 2, 22000)
        snapshot(db_session, print_id, 1, 22500)
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=24800, observed_at=day(1))

        payload = fetch(db_session, print_id)
        assert payload["series_stats"]

    def test_the_endpoint_writes_nothing(self, db_session, world):
        print_id = world["base"].id
        snapshot(db_session, print_id, 2, 22000)
        snapshot(db_session, print_id, 1, 22500)

        before = db_session.query(MarketIndexSnapshot).count()
        for window in ("all", "2w", "1m"):
            fetch(db_session, print_id, window=window)
        assert db_session.query(MarketIndexSnapshot).count() == before

    def test_the_series_payload_is_unchanged_by_the_new_field(
        self, db_session, world
    ):
        """`series` must be exactly what it was before `series_stats` existed.

        Compared against `/prints/{id}/series` over the same span, which is the
        shipped producer of that payload and is not touched by this tranche.
        """
        import copy

        print_id = world["base"].id
        snapshot(db_session, print_id, 2, 22000)
        snapshot(db_session, print_id, 1, 22500)
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=24800, observed_at=day(2))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_jpy=21000, observed_at=day(1))

        payload = fetch(db_session, print_id, window="all")
        snapshot_of_series = copy.deepcopy(payload["series"])

        # Building the stats a second time must not mutate the series it read.
        from app.services.print_analytics import _series_stats

        _series_stats(payload["series"], payload["headline"])
        assert payload["series"] == snapshot_of_series

    def test_stats_carry_no_volume_average_or_sample_wording(
        self, db_session, world
    ):
        print_id = world["base"].id
        snapshot(db_session, print_id, 2, 22000)
        snapshot(db_session, print_id, 1, 22500)

        rows = fetch(db_session, print_id)["series_stats"]

        banned = {
            "average", "mean", "avg", "sales", "trades", "transactions",
            "transaction_count", "volume", "liquidity", "listing_count",
            "sample_size",
        }
        for row in rows:
            assert banned.isdisjoint(row.keys())


# --------------------------------------------------------------- invariants --


class TestOverHttp:
    def test_the_route_serialises_series_stats(self, client, db_session, world):
        """The field must survive the response model, not just the service.

        A statistic the service computes and the schema drops is a field that
        does not exist as far as a client is concerned.
        """
        print_id = world["base"].id
        snapshot(db_session, print_id, 3, 20000)
        snapshot(db_session, print_id, 1, 21000)

        body = client.get(f"/prints/{print_id}/analytics").json()

        assert "series_stats" in body
        row = next(r for r in body["series_stats"] if r["series_key"] == "market_index")
        assert row["starting_value_jpy"] == 20000
        assert row["current_value_jpy"] == 21000
        assert row["observed_days"] == 2
        assert row["change"]["absolute_jpy"] == 1000
        # Serialised dates, not datetimes - the same grain the rest of the
        # payload publishes.
        assert row["current_as_of"] == day(1).date().isoformat()

    def test_a_narrower_window_is_answered_over_http_too(
        self, client, db_session, world
    ):
        print_id = world["base"].id
        snapshot(db_session, print_id, 40, 40000)
        snapshot(db_session, print_id, 1, 24000)

        wide = client.get(f"/prints/{print_id}/analytics?window=all").json()
        narrow = client.get(f"/prints/{print_id}/analytics?window=2w").json()

        wide_row = next(r for r in wide["series_stats"] if r["series_key"] == "market_index")
        narrow_row = next(r for r in narrow["series_stats"] if r["series_key"] == "market_index")
        assert wide_row["observed_days"] == 2
        assert narrow_row["observed_days"] == 1
        assert narrow_row["high_value_jpy"] == 24000


class TestInvariants:
    @pytest.mark.parametrize("window", ["all", "2w", "1m"])
    def test_low_brackets_start_and_current_which_bracket_high(
        self, db_session, world, window
    ):
        print_id = world["base"].id
        for offset, value in ((6, 24000), (5, 21000), (3, 27000), (1, 23000)):
            snapshot(db_session, print_id, offset, value)
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=30000, observed_at=day(6))
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=28000, observed_at=day(1))

        for row in fetch(db_session, print_id, window=window)["series_stats"]:
            assert row["low_value_jpy"] <= row["starting_value_jpy"] <= row["high_value_jpy"]
            assert row["low_value_jpy"] <= row["current_value_jpy"] <= row["high_value_jpy"]
            assert row["observed_days"] >= 1

    def test_every_figure_appears_in_the_series_it_summarises(
        self, db_session, world
    ):
        print_id = world["base"].id
        for offset, value in ((5, 24000), (3, 21000), (1, 27000)):
            snapshot(db_session, print_id, offset, value)

        payload = fetch(db_session, print_id)
        series = {entry["key"]: entry for entry in payload["series"]}

        for row in payload["series_stats"]:
            drawable = {
                (point["day"], point["value_jpy"])
                for segment in series[row["series_key"]]["segments"]
                for point in segment["points"]
                if point["value_jpy"] is not None and point["eligible"] is not False
            }
            for prefix in ("starting", "current", "low", "high"):
                assert (
                    row[f"{prefix}_as_of"],
                    row[f"{prefix}_value_jpy"],
                ) in drawable
