"""GET /prints/{print_id}/analytics - the exact-print historical analytics API.

WHAT THIS SUITE DEFENDS. The endpoint restates history Atlas already archived,
so the failure worth guarding is not "a number looks wrong" but "the server
started producing figures it has no right to": a change computed across a
methodology boundary, a NULL archived index rendered as ¥0, an interpolated
day, an averaged price, a sales count, or a window that silently answers with a
different window's data. Every test below is one of those refusals.

The second invariant is EXACT-PRINT ISOLATION. 955 card codes in the catalogue
carry more than one print, so a suite that only ever exercised one print per
code would pass while the endpoint leaked a sibling's history.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import MarketIndexSnapshot
from app.services import print_analytics
from app.services.card_pirate_index_read import WINDOW_DAYS
from app.services.market_index_change import (
    NOT_COMPARABLE_CONTRIBUTORS,
    NOT_COMPARABLE_INDEX_VERSION,
    NOT_COMPARABLE_SOURCE_SEMANTICS_VERSION,
)
from app.services.print_analytics import (
    CHANGE_UNAVAILABLE_NO_VALUE,
    CHANGE_UNAVAILABLE_SINGLE_POINT,
    get_print_analytics,
)
from app.services.print_series import get_print_series
from tests.test_print_series import observe, world  # noqa: F401  (fixture)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)

ALL_TOKENS = ["2w", "1m", "3m", "6m", "1y", "2y", "all"]


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
    coverage_status: str | None = None,
):
    """One archived Market Index row.

    `contributors` is the archived `source_values` list. It defaults to a
    single contributing Yuyu-Tei retail price so the comparability guard - which
    requires a provable, non-empty, IDENTICAL contributor set at both ends - is
    satisfied by default and a test that wants a refusal has to ask for one.
    """
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
        coverage_status=coverage_status
        or ("limited" if value is not None else "none"),
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


def windows_by_token(payload) -> dict[str, dict]:
    return {row["token"]: row for row in payload["windows"]}


def series_by_key(payload) -> dict[str, dict]:
    return {entry["key"]: entry for entry in payload["series"]}


# ------------------------------------------------------------------ 1, 2, 3 --
class TestWindowContract:
    """The seven-token grammar, the server-chosen default, and the refusal to
    substitute one token's data for another's."""

    def test_all_seven_tokens_are_published_in_the_frozen_order(
        self, db_session, world
    ):
        # 1. Order is part of the contract - a client re-imposing 2W..All from
        # a mapping's keys would be re-deciding a server rule.
        snapshot(db_session, world["base"].id, 3, 1000)
        payload = fetch(db_session, world["base"].id)
        assert [row["token"] for row in payload["windows"]] == ALL_TOKENS

    def test_every_token_is_accepted_and_echoed_back(self, db_session, world):
        # 1. Each of the seven is a legal request even where it is unavailable,
        # and each answers as ITSELF.
        snapshot(db_session, world["base"].id, 3, 1000)
        for token in ALL_TOKENS:
            payload = fetch(db_session, world["base"].id, window=token)
            assert payload["requested_window"] == token

    def test_window_vocabulary_is_the_index_vocabulary(self):
        # 1. Borrowed, not restated: a token added to the Index appears here
        # with no change, and neither can drift.
        assert print_analytics.WINDOW_TOKENS == tuple(WINDOW_DAYS)

    def test_default_is_all_while_history_is_short(self, db_session, world):
        # 2. The Index's own ladder: `all` until 3M of history exists.
        snapshot(db_session, world["base"].id, 3, 1000)
        snapshot(db_session, world["base"].id, 1, 1100)
        payload = fetch(db_session, world["base"].id)
        assert payload["default_window"] == "all"
        assert payload["requested_window"] == "all"

    def test_default_becomes_3m_once_the_print_has_that_history(
        self, db_session, world
    ):
        # 2. The transition is automatic and derived from THIS print's extent,
        # not from a flag anybody has to remember to flip.
        snapshot(db_session, world["base"].id, 200, 900)
        snapshot(db_session, world["base"].id, 1, 1100)
        payload = fetch(db_session, world["base"].id)
        assert payload["default_window"] == "3m"
        assert payload["requested_window"] == "3m"

    def test_unavailable_longer_windows_stay_explicit(self, db_session, world):
        # 3. Six days of history cannot answer 1Y. The row says so with the
        # numbers behind it rather than vanishing from the map.
        snapshot(db_session, world["base"].id, 5, 1000)
        snapshot(db_session, world["base"].id, 0, 1100)
        rows = windows_by_token(fetch(db_session, world["base"].id))
        assert rows["all"]["available"] is True
        for token in ("2w", "1m", "3m", "6m", "1y", "2y"):
            assert rows[token]["available"] is False, token
        assert rows["1y"]["required_days"] == 365
        assert rows["1y"]["covered_days"] == 6

    def test_requesting_an_unavailable_window_is_not_substituted(
        self, db_session, world
    ):
        # 3. The honest answer to "2Y please" on six days of history is 2Y with
        # whatever really falls inside it - never another token's data wearing
        # the 2Y label.
        snapshot(db_session, world["base"].id, 5, 1000)
        snapshot(db_session, world["base"].id, 0, 1100)
        payload = fetch(db_session, world["base"].id, window="2y")
        assert payload["requested_window"] == "2y"
        assert windows_by_token(payload)["2y"]["available"] is False
        # Data is still returned - the window is wider than the history, not
        # emptier than it.
        assert payload["headline"]["observed_days"] == 2

    def test_narrow_window_truncates_rather_than_reporting_the_whole_history(
        self, db_session, world
    ):
        # 3. 2W must not quietly answer with `all`.
        snapshot(db_session, world["base"].id, 40, 500)
        snapshot(db_session, world["base"].id, 2, 1000)
        payload = fetch(db_session, world["base"].id, window="2w")
        assert payload["headline"]["observed_days"] == 1
        assert payload["headline"]["starting_value_jpy"] == 1000
        assert fetch(db_session, world["base"].id, window="all")["headline"][
            "observed_days"
        ] == 2


# --------------------------------------------------------------------- 4, 5 --
class TestAvailabilityIsPerPrint:
    """Availability is a span test over THIS print's own history, and the
    per-series coverage discloses which series reaches how far."""

    def test_availability_is_derived_from_this_prints_history(
        self, db_session, world
    ):
        # 4. Two prints, one card code, different depths. A sibling's long
        # history must not make this print's 1M available.
        snapshot(db_session, world["parallel"].id, 200, 900)
        snapshot(db_session, world["parallel"].id, 0, 950)
        snapshot(db_session, world["base"].id, 2, 1000)

        base_rows = windows_by_token(fetch(db_session, world["base"].id))
        parallel_rows = windows_by_token(fetch(db_session, world["parallel"].id))
        assert base_rows["1m"]["available"] is False
        assert parallel_rows["1m"]["available"] is True

    def test_availability_spans_every_series_not_just_the_index(
        self, db_session, world
    ):
        # 4. A print with a month of Yuyu-Tei history and a week of index
        # history genuinely has a month to chart. Marking 1M unavailable would
        # hide real data the chart is about to draw.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=800, observed_at=day(35))
        snapshot(db_session, world["base"].id, 2, 1000)
        rows = windows_by_token(fetch(db_session, world["base"].id))
        assert rows["1m"]["available"] is True

    def test_series_coverage_discloses_differing_depth_per_platform(
        self, db_session, world
    ):
        # 5. Market Index shorter than Yuyu-Tei, SNKRDUNK shorter than both.
        # The single availability bit cannot say this; per-series coverage can,
        # and must.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=800, observed_at=day(20))
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=850, observed_at=day(1))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_jpy=1200, price_type="floor", observed_at=day(2))
        snapshot(db_session, world["base"].id, 8, 1000)
        snapshot(db_session, world["base"].id, 1, 1100)

        entries = series_by_key(fetch(db_session, world["base"].id, window="all"))
        assert entries["source:yuyutei"]["coverage"]["distinct_days"] == 2
        assert entries["source:snkrdunk"]["coverage"]["distinct_days"] == 1
        assert entries["market_index"]["coverage"]["distinct_days"] == 2
        # And the spans differ, which is the point of publishing them.
        assert entries["source:yuyutei"]["coverage"]["covers_7d"] is True
        assert entries["source:snkrdunk"]["coverage"]["covers_7d"] is False


# ------------------------------------------------------------------ 6, 7, 8 --
class TestHeadline:
    """Current/start/high/low read off archived values, and a change that
    refuses itself where the methodology says it must."""

    def test_current_start_high_low_come_from_archived_values(
        self, db_session, world
    ):
        # 6. Nothing is resolved or recomputed - these are the stored integers.
        snapshot(db_session, world["base"].id, 6, 1000)
        snapshot(db_session, world["base"].id, 4, 1400)
        snapshot(db_session, world["base"].id, 2, 800)
        snapshot(db_session, world["base"].id, 0, 1200)

        head = fetch(db_session, world["base"].id, window="all")["headline"]
        assert head["starting_value_jpy"] == 1000
        assert head["starting_as_of"] == day(6).date()
        assert head["current_value_jpy"] == 1200
        assert head["current_as_of"] == day(0).date()
        assert head["high_value_jpy"] == 1400
        assert head["high_as_of"] == day(4).date()
        assert head["low_value_jpy"] == 800
        assert head["low_as_of"] == day(2).date()
        assert head["observed_days"] == 4
        assert head["coverage_status"] == "limited"

    def test_change_is_start_to_current_with_dates(self, db_session, world):
        # 6. Absolute and percentage from the two published ends, and a real
        # 0.0 is a measurement rather than an absence.
        snapshot(db_session, world["base"].id, 5, 1000)
        snapshot(db_session, world["base"].id, 0, 1250)
        head = fetch(db_session, world["base"].id, window="all")["headline"]
        assert head["change"]["absolute_jpy"] == 250
        assert head["change"]["pct"] == pytest.approx(25.0)
        assert head["change"]["from_date"] == day(5).date()
        assert head["change"]["to_date"] == day(0).date()
        assert head["change"]["spans_break"] is False
        assert head["change_unavailable_reason"] is None

    def test_index_version_change_makes_change_unavailable(
        self, db_session, world
    ):
        # 7. THE central refusal. v2 to v3 is a change of ruleset; reporting
        # the difference as a percentage would draw a methodology change as a
        # price change.
        snapshot(db_session, world["base"].id, 5, 1000, index_version=2)
        snapshot(db_session, world["base"].id, 0, 1250, index_version=3)
        head = fetch(db_session, world["base"].id, window="all")["headline"]
        assert head["change"] is None
        assert head["change_unavailable_reason"] == NOT_COMPARABLE_INDEX_VERSION
        # The values themselves are still published - only the comparison is
        # refused.
        assert head["starting_value_jpy"] == 1000
        assert head["current_value_jpy"] == 1250

    def test_source_semantics_version_change_makes_change_unavailable(
        self, db_session, world
    ):
        # 7. The other version axis, refused for the same reason and named
        # separately so a client can say which layer moved.
        snapshot(db_session, world["base"].id, 5, 1000, semantics=1)
        snapshot(db_session, world["base"].id, 0, 1250, semantics=2)
        head = fetch(db_session, world["base"].id, window="all")["headline"]
        assert head["change"] is None
        assert (
            head["change_unavailable_reason"]
            == NOT_COMPARABLE_SOURCE_SEMANTICS_VERSION
        )

    def test_contributor_set_change_makes_change_unavailable(
        self, db_session, world
    ):
        # 7. Same versions, same source_count, DIFFERENT evidence: a Yuyu-Tei
        # retail price replaced by a SNKRDUNK listing floor. -40% here would be
        # describing a change of measuring instrument.
        snapshot(db_session, world["base"].id, 5, 1000)
        snapshot(
            db_session, world["base"].id, 0, 600,
            contributors=[{
                "source": "snkrdunk", "reference_type": "listing_floor",
                "contributes_to_index": True, "value_jpy": 600,
            }],
        )
        head = fetch(db_session, world["base"].id, window="all")["headline"]
        assert head["change"] is None
        assert head["change_unavailable_reason"] == NOT_COMPARABLE_CONTRIBUTORS

    def test_unreadable_provenance_refuses_rather_than_assumes(
        self, db_session, world
    ):
        # 7. "The archive did not say" is not "nothing contributed". Fail
        # closed.
        snapshot(db_session, world["base"].id, 5, 1000, contributors=[])
        snapshot(db_session, world["base"].id, 0, 1250, contributors=[])
        head = fetch(db_session, world["base"].id, window="all")["headline"]
        assert head["change"] is None
        assert head["change_unavailable_reason"] == NOT_COMPARABLE_CONTRIBUTORS

    def test_spans_break_is_reported_on_the_refusal_too(self, db_session, world):
        # 7. "A boundary lies inside this window" is true whether or not a
        # number came out, but it never licenses the comparison.
        snapshot(db_session, world["base"].id, 5, 1000, index_version=2)
        snapshot(db_session, world["base"].id, 0, 1250, index_version=3)
        payload = fetch(db_session, world["base"].id, window="all")
        assert payload["headline"]["change"] is None
        index_breaks = series_by_key(payload)["market_index"]["breaks"]
        assert any(b["reason"] == "index_version_change" for b in index_breaks)

    def test_single_point_window_is_not_a_zero_change(self, db_session, world):
        # 7. One day is not a change, and a baseline is never borrowed from a
        # wider window or another series to manufacture one.
        snapshot(db_session, world["base"].id, 1, 1000)
        head = fetch(db_session, world["base"].id, window="all")["headline"]
        assert head["change"] is None
        assert head["change_unavailable_reason"] == CHANGE_UNAVAILABLE_SINGLE_POINT
        assert head["current_value_jpy"] == 1000
        assert head["starting_value_jpy"] == 1000

    def test_gaps_are_not_interpolated(self, db_session, world):
        # 8. Two archived days ten days apart stay two points. No invented day
        # appears between them, in the headline count or in the series.
        snapshot(db_session, world["base"].id, 12, 1000)
        snapshot(db_session, world["base"].id, 2, 1400)
        payload = fetch(db_session, world["base"].id, window="all")
        assert payload["headline"]["observed_days"] == 2
        points = [
            point
            for segment in series_by_key(payload)["market_index"]["segments"]
            for point in segment["points"]
        ]
        assert len(points) == 2
        assert [p["day"] for p in points] == [day(12).date(), day(2).date()]


# --------------------------------------------------------------------- 9, 10 --
class TestNullsAndEmptiness:
    """A recorded null is a result. An absent print is an absence. Neither is
    a zero."""

    def test_null_archived_values_are_never_zero(self, db_session, world):
        # 9. A day on which no source was eligible is archived as NULL. It must
        # not become ¥0 - which would be a new all-time low and a fabricated
        # crash.
        snapshot(db_session, world["base"].id, 5, 1000)
        snapshot(db_session, world["base"].id, 3, None)
        snapshot(db_session, world["base"].id, 0, 1200)
        head = fetch(db_session, world["base"].id, window="all")["headline"]
        assert head["low_value_jpy"] == 1000
        assert head["high_value_jpy"] == 1200
        assert head["current_value_jpy"] == 1200
        assert head["observed_days"] == 2  # the null day is not a usable day
        assert head["change"]["absolute_jpy"] == 200

    def test_a_window_of_only_nulls_has_no_headline_and_no_zero(
        self, db_session, world
    ):
        # 9. Every field null, an explicit reason, and nothing coerced.
        snapshot(db_session, world["base"].id, 3, None)
        snapshot(db_session, world["base"].id, 1, None)
        head = fetch(db_session, world["base"].id, window="all")["headline"]
        assert head["current_value_jpy"] is None
        assert head["low_value_jpy"] is None
        assert head["high_value_jpy"] is None
        assert head["observed_days"] == 0
        assert head["change_unavailable_reason"] == CHANGE_UNAVAILABLE_NO_VALUE
        # The coverage answer survives - it is why there is no number.
        assert head["coverage_status"] == "none"

    def test_print_with_no_history_at_all(self, db_session, world):
        # 10. Not an error and not a zero: a real print Atlas has never priced.
        payload = fetch(db_session, world["base"].id)
        assert payload["headline"]["current_value_jpy"] is None
        assert payload["headline"]["observed_days"] == 0
        assert (
            payload["headline"]["change_unavailable_reason"]
            == CHANGE_UNAVAILABLE_NO_VALUE
        )
        assert payload["headline"]["coverage_status"] is None
        assert payload["default_window"] == "all"
        assert all(row["available"] is False for row in payload["windows"][:-1])
        # Market Index is still NAMED, and named as explicitly unavailable -
        # the same shape /prints/{id}/series gives. An empty list would leave a
        # client unable to tell "not tracked" from "nothing came back".
        entries = series_by_key(payload)
        assert list(entries) == ["market_index"]
        assert entries["market_index"]["available"] is False
        assert entries["market_index"]["unavailable_reason"] == "no_history_in_window"


# ----------------------------------------------------------------- 11, 12, 17 --
class TestEndpoint:
    """The HTTP surface: identity, isolation, read-only, and client errors."""

    def test_unknown_print_is_404(self, client, db_session):
        # 11.
        assert client.get("/prints/98765432/analytics").status_code == 404

    def test_unsupported_window_is_400(self, client, db_session, world):
        snapshot(db_session, world["base"].id, 1, 1000)
        response = client.get(f"/prints/{world['base'].id}/analytics?window=7d")
        assert response.status_code == 400
        # The seven legal tokens are named, so a client can correct itself.
        detail = response.json()["detail"]
        assert "2w" in detail and "2y" in detail
        assert "7d" not in detail

    def test_endpoint_returns_the_contract(self, client, db_session, world):
        snapshot(db_session, world["base"].id, 3, 1000)
        snapshot(db_session, world["base"].id, 0, 1200)
        body = client.get(f"/prints/{world['base'].id}/analytics").json()
        assert body["card_print_id"] == world["base"].id
        assert body["requested_window"] == "all"
        assert body["default_window"] == "all"
        assert [row["token"] for row in body["windows"]] == ALL_TOKENS
        assert body["headline"]["current_value_jpy"] == 1200
        assert body["headline"]["change"]["absolute_jpy"] == 200

    def test_exact_print_isolation_across_one_card_code(
        self, client, db_session, world
    ):
        # 12. Two prints of OP01-013 bridging one legacy card. The endpoint is
        # keyed by card_print_id; a code-keyed query would merge these.
        snapshot(db_session, world["base"].id, 3, 1000)
        snapshot(db_session, world["base"].id, 0, 1100)
        snapshot(db_session, world["parallel"].id, 3, 5000)
        snapshot(db_session, world["parallel"].id, 0, 5500)

        base = client.get(f"/prints/{world['base'].id}/analytics").json()
        parallel = client.get(f"/prints/{world['parallel'].id}/analytics").json()
        assert base["headline"]["current_value_jpy"] == 1100
        assert parallel["headline"]["current_value_jpy"] == 5500
        assert base["headline"]["observed_days"] == 2
        assert parallel["headline"]["observed_days"] == 2

    def test_exact_print_isolation_of_source_series(
        self, client, db_session, world
    ):
        # 12. Same trap on the source side: the sibling's Yuyu-Tei observations
        # must not appear on this print's series.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=800, observed_at=day(2))
        observe(db_session, world, "yuyutei", "parallel", "yuyutei_parallel",
                price_jpy=9000, observed_at=day(2))
        body = client.get(f"/prints/{world['base'].id}/analytics").json()
        points = [
            point
            for entry in body["series"] if entry["key"] == "source:yuyutei"
            for segment in entry["segments"] for point in segment["points"]
        ]
        assert [p["value_jpy"] for p in points] == [800]

    def test_endpoint_is_read_only(self, client, db_session, world):
        # 17. A GET that mutates would be a far worse bug than a wrong number.
        snapshot(db_session, world["base"].id, 3, 1000)
        before = {
            "snapshots": db_session.query(MarketIndexSnapshot).count(),
        }
        for token in ALL_TOKENS:
            assert client.get(
                f"/prints/{world['base'].id}/analytics?window={token}"
            ).status_code == 200
        db_session.expire_all()
        assert db_session.query(MarketIndexSnapshot).count() == before["snapshots"]
        # And the archived row itself is untouched.
        row = db_session.query(MarketIndexSnapshot).one()
        assert row.index_value_jpy == 1000
        assert row.index_version == 3

    def test_only_get_is_routed(self, client, db_session, world):
        # 17. No POST/PUT/PATCH/DELETE exists on this path.
        path = f"/prints/{world['base'].id}/analytics"
        for verb in (client.post, client.put, client.patch, client.delete):
            assert verb(path).status_code == 405


# ------------------------------------------------------------- 13, 14, 15, 16 --
class TestSeriesAndVocabulary:
    """Which series appear, and which words must never appear."""

    def test_yuyutei_absent_while_another_series_exists(self, db_session, world):
        # 13. Absence is a real answer, not a blank line and not an error.
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_jpy=1200, price_type="floor", observed_at=day(2))
        snapshot(db_session, world["base"].id, 2, 1200)
        entries = series_by_key(fetch(db_session, world["base"].id, window="all"))
        assert "source:yuyutei" not in entries
        assert entries["source:snkrdunk"]["available"] is True
        assert entries["market_index"]["available"] is True

    def test_snkrdunk_absent_while_another_series_exists(self, db_session, world):
        # 14. The mirror case.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=800, observed_at=day(2))
        snapshot(db_session, world["base"].id, 2, 800)
        entries = series_by_key(fetch(db_session, world["base"].id, window="all"))
        assert "source:snkrdunk" not in entries
        assert entries["source:yuyutei"]["available"] is True

    def test_series_shape_is_the_shipped_one(self, db_session, world):
        # The series must be byte-identical to what /prints/{id}/series builds
        # for the same span - one builder, no second DTO.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=800, observed_at=day(2))
        snapshot(db_session, world["base"].id, 2, 800)
        analytics = fetch(db_session, world["base"].id, window="all")
        legacy = get_print_series(db_session, world["base"].id, window="all", now=NOW)
        assert analytics["series"] == legacy["series"]

    def test_instrument_and_eligibility_semantics_survive(self, db_session, world):
        # Segments keep reference_type/evidence_type and points keep their
        # constraint/eligibility verdict - the analytics wrapper adds no
        # classification of its own.
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_jpy=1000, price_type="floor", observed_at=day(2))
        entries = series_by_key(fetch(db_session, world["base"].id, window="all"))
        segment = entries["source:snkrdunk"]["segments"][0]
        assert segment["reference_type"] == "listing_floor"
        assert segment["evidence_type"] == "listing"
        point = segment["points"][0]
        # ¥1,000 is SNKRDUNK's platform minimum: shown, and marked ineligible.
        assert point["eligible"] is False
        assert point["constraint"] is not None

    def test_no_average_sales_or_sample_size_fields(self, client, db_session, world):
        # 15. The vocabulary ban, enforced on the whole serialized payload -
        # Atlas records no transaction anywhere, so any of these words would be
        # a claim the data cannot support.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=800, observed_at=day(2))
        snapshot(db_session, world["base"].id, 2, 800)
        body = client.get(f"/prints/{world['base'].id}/analytics").json()
        head = body["headline"]
        for banned in (
            "average", "average_price", "average_price_jpy", "mean",
            "sales", "sales_count", "trades", "trade_count",
            "volume", "listings", "listing_count", "sample_size",
        ):
            assert banned not in head, banned
        # `observed_days` is the ONLY count published, and it counts days.
        counts = [key for key in head if key.endswith(("_count", "_days"))]
        assert counts == ["observed_days"]
        assert head["observed_days"] == 1

    def test_no_resolver_or_pricing_recomputation(
        self, db_session, world, monkeypatch
    ):
        # 16. The proof that the headline is ARCHIVE-ONLY: every resolver and
        # the live index/pricing entry points are replaced with detonators. A
        # single call fails the test.
        import app.services.market_index as market_index
        import app.services.print_market_index as print_market_index
        import app.services.print_pricing as print_pricing

        def boom(*args, **kwargs):
            raise AssertionError("analytics recomputed pricing")

        for name in (
            "_resolve_yuyutei_sell", "_resolve_yuyutei_buy", "_resolve_snkrdunk",
            "compute_market_index_for_print",
        ):
            if hasattr(market_index, name):
                monkeypatch.setattr(market_index, name, boom, raising=False)
        for name in ("get_market_index_for_print", "get_market_index_for_prints"):
            if hasattr(print_market_index, name):
                monkeypatch.setattr(print_market_index, name, boom, raising=False)
        for name in ("compute_print_price_series_trends", "get_price_history_for_print"):
            if hasattr(print_pricing, name):
                monkeypatch.setattr(print_pricing, name, boom, raising=False)

        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=800, observed_at=day(2))
        snapshot(db_session, world["base"].id, 3, 1000)
        snapshot(db_session, world["base"].id, 0, 1200)

        head = fetch(db_session, world["base"].id, window="all")["headline"]
        assert head["current_value_jpy"] == 1200
        assert head["change"]["absolute_jpy"] == 200


# -------------------------------------------------------------------------- 18 --
class TestExistingSeriesEndpointUnchanged:
    """The shared-helper extraction must be invisible to /prints/{id}/series."""

    def test_series_endpoint_still_answers_its_own_three_windows(
        self, client, db_session, world
    ):
        # 18. Its grammar is 7d/30d/all and is untouched by the seven-token
        # analytics vocabulary living next door.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=800, observed_at=day(2))
        for token in ("7d", "30d", "all"):
            response = client.get(
                f"/prints/{world['base'].id}/series?window={token}"
            )
            assert response.status_code == 200
            assert response.json()["window"] == token
        assert client.get(
            f"/prints/{world['base'].id}/series?window=2w"
        ).status_code == 400

    def test_series_endpoint_payload_is_unchanged(self, client, db_session, world):
        # 18. Shape and content, not just status.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=800, observed_at=day(2))
        snapshot(db_session, world["base"].id, 2, 800)
        body = client.get(f"/prints/{world['base'].id}/series?window=all").json()
        assert set(body) == {
            "card_print_id", "window", "window_start", "generated_at", "series"
        }
        entry = next(e for e in body["series"] if e["key"] == "source:yuyutei")
        assert set(entry) == {
            "key", "kind", "source", "role", "available", "unavailable_reason",
            "segments", "breaks", "coverage",
        }
        assert set(entry["coverage"]) == {
            "earliest", "latest", "distinct_days", "point_count",
            "covers_7d", "covers_30d",
        }


# --------------------------------------------------- default-window authority --
class TestDefaultWindowAuthority:
    """AVAILABILITY AND DEFAULT ARE DIFFERENT AUTHORITIES.

    `windows[].available` spans every series, because the chart draws them all.
    `default_window` spans the MARKET INDEX alone, because every figure in the
    headline the page opens on - current, starting, low, high, change - is a
    Market Index figure. A source series must never open the primary
    performance view on a frame the Market Index cannot fill.
    """

    def test_long_yuyutei_history_makes_3m_selectable_but_not_default(
        self, db_session, world
    ):
        # 1. Yuyu-Tei reaches back beyond three months; Market Index does not.
        # 3M is a legitimate thing to ASK for - the chart really can draw it -
        # and a legitimately wrong thing to OPEN on.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=800, observed_at=day(120))
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=850, observed_at=day(1))
        snapshot(db_session, world["base"].id, 5, 1000)
        snapshot(db_session, world["base"].id, 1, 1100)

        payload = fetch(db_session, world["base"].id)
        rows = windows_by_token(payload)
        assert rows["3m"]["available"] is True
        assert rows["1m"]["available"] is True
        assert payload["default_window"] == "all"
        # And the implicit request really did open on `all`.
        assert payload["requested_window"] == "all"

    def test_market_index_reaching_3m_moves_the_default(self, db_session, world):
        # 2. The transition is driven by the Market Index's OWN span, and by
        # nothing else on the page.
        snapshot(db_session, world["base"].id, 120, 900)
        snapshot(db_session, world["base"].id, 1, 1100)
        payload = fetch(db_session, world["base"].id)
        assert windows_by_token(payload)["3m"]["available"] is True
        assert payload["default_window"] == "3m"
        assert payload["requested_window"] == "3m"

    def test_absent_market_index_keeps_the_default_at_all(self, db_session, world):
        # 3. Source history only. There is no index to satisfy any threshold,
        # so the page opens on `all` however deep the source history runs.
        observe(db_session, world, "yuyutei", "base", "yuyutei_base",
                price_jpy=800, observed_at=day(200))
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_jpy=1200, price_type="floor", observed_at=day(1))
        payload = fetch(db_session, world["base"].id)
        assert windows_by_token(payload)["3m"]["available"] is True
        assert windows_by_token(payload)["6m"]["available"] is True
        assert payload["default_window"] == "all"
        assert payload["headline"]["current_value_jpy"] is None

    def test_null_only_index_history_is_not_index_history(self, db_session, world):
        # 3 (the sharp edge). Archived NULL days are published results, so they
        # count toward what the CHART can show - but a null is not a Market
        # Index value, so they cannot satisfy the default's threshold.
        snapshot(db_session, world["base"].id, 120, None)
        snapshot(db_session, world["base"].id, 1, None)
        payload = fetch(db_session, world["base"].id)
        assert windows_by_token(payload)["3m"]["available"] is True
        assert payload["default_window"] == "all"
        assert payload["headline"]["observed_days"] == 0

    def test_default_ignores_a_siblings_index_history(self, db_session, world):
        # Exact-print isolation applies to the default too: a sibling print
        # sharing this card code must not move this print's opening frame.
        snapshot(db_session, world["parallel"].id, 200, 900)
        snapshot(db_session, world["parallel"].id, 1, 950)
        snapshot(db_session, world["base"].id, 2, 1000)
        assert fetch(db_session, world["base"].id)["default_window"] == "all"
        assert fetch(db_session, world["parallel"].id)["default_window"] == "3m"

    def test_source_history_never_shortens_the_default(self, db_session, world):
        # 4. The rule is one-directional. A Market Index that satisfies 3M
        # keeps the 3M default even where a source has only a few days - the
        # default follows the index, not the shortest series on the page.
        snapshot(db_session, world["base"].id, 120, 900)
        snapshot(db_session, world["base"].id, 1, 1100)
        observe(db_session, world, "snkrdunk", "base", "snkrdunk_base",
                price_jpy=1200, price_type="floor", observed_at=day(1))
        payload = fetch(db_session, world["base"].id)
        assert payload["default_window"] == "3m"
        entries = series_by_key(payload)
        assert entries["source:snkrdunk"]["coverage"]["distinct_days"] == 1
