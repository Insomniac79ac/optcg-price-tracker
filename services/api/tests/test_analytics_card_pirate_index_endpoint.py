"""GET /analytics/index - the read-only Card Pirate Index endpoint.

Every test here fixes a property the endpoint must keep because the frozen
methodology says so, not because the current data happens to look that way:

  * it serves STORED points and runs no estimator, so the level for a date is
    the level that was published on that date;
  * the window narrows which stored rows come back and never invents,
    forward-fills, interpolates or pads;
  * change comes from the frozen section 5.6 helper, so a reset withholds the
    figure instead of splicing across it;
  * surrogate ids never reach the payload, because they do not survive a
    rebuild.

The four-point fixture mirrors the real staging seed exactly - the same dates,
levels, step returns and breadth - so a drift between this suite and the
published series shows up as a failure here rather than in production.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.services.card_pirate_index_read import WINDOW_DAYS

STAMP = datetime(2026, 9, 7, 13, 55, 49, tzinfo=timezone.utc)
D3, D4, D5, D6 = (date(2026, 9, d) for d in (3, 4, 5, 6))

# The exact rows persisted to staging in tranche 1C-B.
STAGING_SEED = [
    dict(point_date=D3, index_value=Decimal("1000.0000"), is_base=True,
         prior_point_date=None, step_days=None, chain_link_log_return=None,
         constituent_count=0, eligible_print_count=231,
         movers_up=None, movers_down=None, movers_flat=None, capped_count=None),
    dict(point_date=D4, index_value=Decimal("1000.8409"), is_base=False,
         prior_point_date=D3, step_days=1,
         chain_link_log_return=Decimal("0.000840502227"),
         constituent_count=231, eligible_print_count=281,
         movers_up=1, movers_down=0, movers_flat=230, capped_count=0),
    dict(point_date=D5, index_value=Decimal("1000.9577"), is_base=False,
         prior_point_date=D4, step_days=1,
         chain_link_log_return=Decimal("0.000116689761"),
         constituent_count=281, eligible_print_count=296,
         movers_up=1, movers_down=0, movers_flat=280, capped_count=0),
    dict(point_date=D6, index_value=Decimal("1000.9577"), is_base=False,
         prior_point_date=D5, step_days=1,
         chain_link_log_return=Decimal("0"),
         constituent_count=296, eligible_print_count=297,
         movers_up=0, movers_down=0, movers_flat=296, capped_count=0),
]


def _point(**overrides) -> CardPirateIndexPoint:
    values = dict(
        scope_kind="overall", scope_key="", methodology_version=1,
        index_version=3, source_semantics_version=2, calculated_at=STAMP,
    )
    values.update(overrides)
    return CardPirateIndexPoint(**values)


@pytest.fixture
def seeded(db_session):
    """The staging four-point series."""
    for row in STAGING_SEED:
        db_session.add(_point(**row))
    db_session.commit()
    return db_session


# --- shape -----------------------------------------------------------------


def test_returns_the_four_published_points(client, seeded):
    body = client.get("/analytics/index?window=all").json()
    assert [p["date"] for p in body["points"]] == [
        "2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06"
    ]
    assert [p["value"] for p in body["points"]] == [
        "1000.0000", "1000.8409", "1000.9577", "1000.9577"
    ]


def test_scope_and_version_identity(client, seeded):
    body = client.get("/analytics/index?window=all").json()
    assert body["scope_kind"] == "overall"
    assert body["scope_key"] == ""
    assert body["methodology_version"] == 1
    # Carried from the newest published row, not re-read from the constants -
    # the payload describes the ruleset that produced the number shown.
    assert body["index_version"] == 3
    assert body["source_semantics_version"] == 2


def test_points_are_ascending_by_date(client, seeded):
    dates = [p["date"] for p in client.get("/analytics/index?window=all").json()["points"]]
    assert dates == sorted(dates)


def test_exact_persisted_precision_is_preserved(client, seeded):
    """Numeric(12,4) and Numeric(18,12) must survive serialization intact - a
    float round-trip here would publish a different number from the stored
    one."""
    body = client.get("/analytics/index?window=all").json()
    assert body["points"][1]["value"] == "1000.8409"
    assert body["points"][1]["chain_link_log_return"] == "0.000840502227"
    assert body["points"][2]["chain_link_log_return"] == "0.000116689761"


def test_breadth_matches_the_persisted_rows(client, seeded):
    body = client.get("/analytics/index?window=all").json()
    latest = body["points"][-1]
    assert latest["constituent_count"] == 296
    assert latest["eligible_print_count"] == 297
    assert (latest["movers_up"], latest["movers_down"], latest["movers_flat"]) == (0, 0, 296)
    assert latest["capped_count"] == 0
    base = body["points"][0]
    assert base["is_base"] is True
    assert base["constituent_count"] == 0
    assert base["movers_up"] is None


def test_no_surrogate_ids_anywhere_in_the_payload(client, seeded):
    """Point ids are not stable across a rebuild, so they are never part of
    this contract - and neither is the carry's raw integer."""
    raw = client.get("/analytics/index?window=all").text
    assert '"id"' not in raw
    assert "carried_from_point_id" not in raw
    body = client.get("/analytics/index?window=all").json()
    for p in body["points"]:
        assert "id" not in p
        assert "carried_from_point_id" not in p


# --- windows ---------------------------------------------------------------


def test_a_request_with_no_window_takes_the_servers_default(client, seeded):
    """TASK INDEX 2A-C replaced this test's original assertion, and the
    replacement is the point.

    It used to assert `DEFAULT_WINDOW == "3m"` and that an implicit request
    returned `3m` - a transport default that disagreed with the payload's own
    `default_window` of `all`. There is now one default: section 13.1's ladder.
    On this four-day fixture that is `all`, and the implicit request returns
    exactly it."""
    body = client.get("/analytics/index").json()
    assert body["default_window"] == "all"
    assert body["requested_window"] == "all"


@pytest.mark.parametrize("token", sorted(WINDOW_DAYS))
def test_every_supported_window_token_is_accepted(client, seeded, token):
    r = client.get(f"/analytics/index?window={token}")
    assert r.status_code == 200
    assert r.json()["requested_window"] == token


@pytest.mark.parametrize("token", ["7d", "5y", "", "month", "3m;drop", "1w"])
def test_unsupported_window_is_400(client, seeded, token):
    """An empty `?window=` is included deliberately: the caller supplied a
    window and supplied nothing usable, which is a client error rather than a
    silent fall back to the default."""
    r = client.get(f"/analytics/index?window={token}")
    assert r.status_code == 400
    assert "window" in r.json()["detail"]


@pytest.mark.parametrize("token", ["1M", " 1m ", "ALL", "2W"])
def test_window_case_and_whitespace_are_normalised(client, seeded, token):
    """The grammar is a closed vocabulary, so `1M` and `1m` cannot mean
    different things; rejecting one would be pedantry, not safety."""
    r = client.get(f"/analytics/index?window={token}")
    assert r.status_code == 200
    assert r.json()["requested_window"] == token.strip().lower()


def test_window_actually_filters_rather_than_being_ignored(client, seeded):
    """The window must narrow the result when the archive is long enough.

    With only four days every window legitimately returns all four, so this
    test extends the archive backwards - proving the filter works and that the
    four-day case is a property of the DATA, not of an ignored parameter.
    """
    # An ordinary step row, not a base: ck_cpi_points_initial_base_is_base_value
    # requires an INITIAL base to be exactly 1000, so backdating a base at 990
    # is not a legal row and would be testing the fixture, not the window.
    old = _point(point_date=date(2026, 1, 1), index_value=Decimal("990.0000"),
                 is_base=False, prior_point_date=date(2025, 12, 31), step_days=1,
                 chain_link_log_return=Decimal("-0.01"), constituent_count=40,
                 eligible_print_count=40, movers_up=0, movers_down=1,
                 movers_flat=39, capped_count=0)
    seeded.add(old)
    seeded.commit()

    all_dates = [p["date"] for p in client.get("/analytics/index?window=all").json()["points"]]
    assert "2026-01-01" in all_dates and len(all_dates) == 5

    two_week = client.get("/analytics/index?window=2w").json()
    assert [p["date"] for p in two_week["points"]] == [
        "2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06"
    ]
    assert two_week["covers_requested_window"] is True


def test_partial_history_is_reported_not_padded(client, seeded):
    """A window reaching further back than the archive returns what exists and
    says the request was not covered - it never emits placeholder points."""
    body = client.get("/analytics/index?window=2y").json()
    assert len(body["points"]) == 4
    assert body["available_from"] == "2026-09-03"
    assert body["available_to"] == "2026-09-06"
    assert body["covers_requested_window"] is False


def test_all_window_has_no_window_start(client, seeded):
    body = client.get("/analytics/index?window=all").json()
    assert body["window_start"] is None
    assert body["covers_requested_window"] is True


def test_no_forward_fill_across_a_gap(client, seeded):
    """A multi-day step is one honest point, not one point per calendar day."""
    seeded.add(_point(
        point_date=date(2026, 9, 10), index_value=Decimal("1001.0000"),
        is_base=False, prior_point_date=D6, step_days=4,
        chain_link_log_return=Decimal("0.00004"),
        constituent_count=290, eligible_print_count=300,
        movers_up=1, movers_down=0, movers_flat=289, capped_count=0,
    ))
    seeded.commit()
    body = client.get("/analytics/index?window=all").json()
    dates = [p["date"] for p in body["points"]]
    assert dates == ["2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06", "2026-09-10"]
    assert body["points"][-1]["step_days"] == 4


# --- summary / change ------------------------------------------------------


def test_summary_values_come_from_published_endpoints(client, seeded):
    body = client.get("/analytics/index?window=all").json()
    assert body["starting_value"] == "1000.0000"
    assert body["current_value"] == "1000.9577"
    assert body["low_value"] == "1000.0000"
    assert body["high_value"] == "1000.9577"


def test_change_matches_the_frozen_methodology(client, seeded):
    """+0.095770 %, computed from the two PUBLISHED levels per section 5.6 -
    not from the pre-quantized internal chain value."""
    change = client.get("/analytics/index?window=all").json()["change"]
    assert change["absolute"] == "0.9577"
    assert change["pct"] == "0.095770"
    assert change["from_date"] == "2026-09-03"
    assert change["to_date"] == "2026-09-06"
    assert change["spans_break"] is False


def test_no_average_value_field(client, seeded):
    """The methodology defines no mean level. An unweighted mean over points
    and a step_days-weighted mean over time disagree the moment a gap exists,
    and nothing freezes which is meant - so neither is published."""
    body = client.get("/analytics/index?window=all").json()
    assert "average_value" not in body


def test_change_is_withheld_across_a_reset(client, seeded):
    """Section 5.6 rule 5: a reset breaks carried continuity, so change is
    null with a reason rather than a spliced number - and never 0."""
    seeded.add(_point(
        point_date=date(2026, 9, 8), index_value=Decimal("1000.0000"),
        is_base=True, carried_from_point_id=None, prior_point_date=None,
        step_days=None, chain_link_log_return=None,
        constituent_count=0, eligible_print_count=300, index_version=4,
    ))
    seeded.commit()
    body = client.get("/analytics/index?window=all").json()
    assert body["change"] is None
    assert body["change_unavailable_reason"] == "no_carried_continuity"


def test_change_spans_break_when_a_carry_is_crossed(client, seeded):
    """A CARRIED boundary keeps the linked scale, so change is published - and
    flagged, because it is a linked-index return rather than a claim that the
    underlying measurements were comparable."""
    carried = _point(
        point_date=date(2026, 9, 8), index_value=Decimal("1000.9577"),
        is_base=True, prior_point_date=None, step_days=None,
        chain_link_log_return=None, constituent_count=0,
        eligible_print_count=300, index_version=4,
    )
    carried.carried_from_point_id = seeded.scalar(
        select(CardPirateIndexPoint.id).where(CardPirateIndexPoint.point_date == D6)
    )
    seeded.add(carried)
    seeded.commit()
    body = client.get("/analytics/index?window=all").json()
    assert body["change"] is not None
    assert body["change"]["spans_break"] is True
    assert body["change_unavailable_reason"] is None
    # the carry's target is exposed as a DATE, never as an id
    assert "carried_from_point_id" not in client.get("/analytics/index?window=all").text


# --- empty states ----------------------------------------------------------


def test_empty_table_returns_no_points_and_a_reason(client, db_session):
    body = client.get("/analytics/index?window=all").json()
    assert body["points"] == []
    assert body["available_from"] is None
    assert body["current_value"] is None
    assert body["change"] is None
    assert body["change_unavailable_reason"] == "no_published_point_in_window"


def test_a_different_scope_is_not_served_by_this_route(client, seeded):
    """This tranche serves the headline overall scope. A set sub-index row
    must not leak into it."""
    seeded.add(_point(
        scope_kind="set", scope_key="OP-01", point_date=D3,
        index_value=Decimal("1000.0000"), is_base=True, prior_point_date=None,
        step_days=None, chain_link_log_return=None,
        constituent_count=0, eligible_print_count=81,
    ))
    seeded.commit()
    body = client.get("/analytics/index?window=all").json()
    assert len(body["points"]) == 4
    assert body["scope_key"] == ""


def test_unpublishable_rows_are_never_served(client, seeded):
    """A day the methodology could not publish is not a point. It is stored so
    the refusal is on the record, but it must not appear as a level."""
    seeded.add(_point(
        point_date=date(2026, 9, 7), index_value=None,
        unpublishable_reason="mixed_version_day", is_base=False,
        prior_point_date=D6, step_days=1, chain_link_log_return=None,
        constituent_count=0, eligible_print_count=300,
    ))
    seeded.commit()
    body = client.get("/analytics/index?window=all").json()
    assert [p["date"] for p in body["points"]] == [
        "2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06"
    ]


# --- read-only -------------------------------------------------------------


def test_the_endpoint_writes_nothing(client, seeded):
    before = [
        (r.id, r.point_date, r.index_value, r.calculated_at)
        for r in seeded.scalars(
            select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
        )
    ]
    for token in sorted(WINDOW_DAYS):
        assert client.get(f"/analytics/index?window={token}").status_code == 200
    seeded.expire_all()
    after = [
        (r.id, r.point_date, r.index_value, r.calculated_at)
        for r in seeded.scalars(
            select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
        )
    ]
    assert before == after


def test_the_read_path_contains_no_write_or_estimator_call():
    """No INSERT/UPDATE/DELETE, and no estimator entry point: the read service
    must never be able to produce a level that was not published."""
    import pathlib
    import re

    import app.services.card_pirate_index_read as mod

    src = pathlib.Path(mod.__file__).read_text()
    for forbidden in (r"\.add\(", r"\.commit\(", r"\.flush\(", r"\bupdate\s*\(",
                      r"\bdelete\s*\(", r"\binsert\s*\(", r"replay_scope",
                      r"build_points", r"compute_step", r"MarketIndexSnapshot"):
        assert not re.search(forbidden, src), f"{forbidden!r} in the read path"
