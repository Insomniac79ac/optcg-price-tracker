"""GET /analytics/index - the section 12.1 server-authored metadata.

WHY THIS SUITE EXISTS. Before TASK INDEX 2A-B the endpoint published points and
change but not `windows`, `default_window` or `breaks`, so the frontend built
its own window list, resolved section 13.1's default by probing `3m` and
reading `covers_requested_window` off the answer, and could not mark a
methodology boundary at all. Each of those made the client a second authority
on a rule the document freezes on the server. The tests below fix the three
rules where they now live:

  * the window ladder is exactly the published grammar, in the published order;
  * `default_window` is section 13.1's ladder and nothing else;
  * `breaks` is derived from the persisted rows' own version and cadence
    columns, never from levels or dates.

The additions are ADDITIVE, and the last group asserts that: every field the
earlier payload carried still carries the same value, so a client written
against it is unaffected.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.services.card_pirate_index_read import WINDOW_DAYS

STAMP = datetime(2026, 9, 7, 13, 55, 49, tzinfo=timezone.utc)


def _point(**overrides) -> CardPirateIndexPoint:
    values = dict(
        scope_kind="overall", scope_key="", methodology_version=1,
        index_version=3, source_semantics_version=2, calculated_at=STAMP,
    )
    values.update(overrides)
    return CardPirateIndexPoint(**values)


def _base(day: date, value=Decimal("1000.0000"), **overrides) -> CardPirateIndexPoint:
    """A SEGMENT BASE, shaped the way the table's own constraints require.

    `ck_cpi_points_base_has_no_step` and `ck_cpi_points_breadth_presence`
    between them say a base has no return, no prior date, no step, zero
    constituents and therefore no breadth at all - section 5.1 rule 5. Writing
    that once here keeps every fixture below honest about what a boundary row
    actually is; a base with movers on it would be a row the writer could
    never produce."""
    return _point(
        point_date=day, index_value=value, is_base=True,
        prior_point_date=None, step_days=None, chain_link_log_return=None,
        constituent_count=0, eligible_print_count=305,
        movers_up=None, movers_down=None, movers_flat=None, capped_count=None,
        **overrides,
    )


def _step(day: date, value: Decimal, prior: date, step_days: int = 1, **overrides):
    """An ordinary published day."""
    return _point(
        point_date=day, index_value=value, is_base=False,
        prior_point_date=prior, step_days=step_days,
        chain_link_log_return=Decimal("0.0001"),
        constituent_count=296, eligible_print_count=305,
        movers_up=1, movers_down=1, movers_flat=294, capped_count=0,
        **overrides,
    )


def _daily(db_session, start: date, count: int, *, first_value=Decimal("1000.0000")):
    """`count` consecutive daily points from `start`, the archive's own cadence."""
    db_session.add(_base(start, first_value))
    prev = start
    for i in range(1, count):
        day = date.fromordinal(start.toordinal() + i)
        db_session.add(_step(day, first_value + Decimal(i) / 10, prev))
        prev = day
    db_session.commit()


@pytest.fixture
def five_days(db_session):
    """Staging's real extent on 2026-09-07: five consecutive published days."""
    _daily(db_session, date(2026, 9, 3), 5)
    return db_session


# --- A. the window ladder is the server's -----------------------------------


def test_publishes_every_window_token_in_the_frozen_order(client, five_days):
    body = client.get("/analytics/index?window=all").json()
    assert [w["token"] for w in body["windows"]] == [
        "2w", "1m", "3m", "6m", "1y", "2y", "all"
    ]
    # Order is part of the contract, so it is asserted as a sequence rather
    # than as a set - a client renders its control straight from this list.
    assert [w["token"] for w in body["windows"]] == list(WINDOW_DAYS)


def test_required_days_are_the_published_durations(client, five_days):
    rows = {w["token"]: w for w in client.get("/analytics/index").json()["windows"]}
    assert rows["2w"]["required_days"] == 14
    assert rows["1m"]["required_days"] == 30
    assert rows["3m"]["required_days"] == 90
    assert rows["6m"]["required_days"] == 180
    assert rows["1y"]["required_days"] == 365
    assert rows["2y"]["required_days"] == 730
    # `all` is not a duration. Section 12.1 publishes null rather than a very
    # large number of days, because "everything there is" and "the last 7300
    # days" are different questions and only one of them stays correct.
    assert rows["all"]["required_days"] is None


def test_a_window_is_available_only_if_the_history_spans_it(client, five_days):
    rows = {w["token"]: w for w in client.get("/analytics/index").json()["windows"]}
    # Five days of archive: nothing but `all` is spanned. Section 12.2 rule 4.
    assert rows["all"]["available"] is True
    for token in ("2w", "1m", "3m", "6m", "1y", "2y"):
        assert rows[token]["available"] is False, token


def test_availability_is_a_span_not_a_point_count(db_session, client):
    """Section 12.2 rule 4: "Sparse history that spans a window still covers
    it; gaps stay gaps."

    Two points, twenty days apart. A count-based rule would call 2W
    unavailable on two points; the span rule calls it available because the
    history genuinely reaches back past the window's start."""
    db_session.add(_base(date(2026, 8, 18)))
    db_session.add(_step(date(2026, 9, 7), Decimal("1010.0000"), date(2026, 8, 18), 20))
    db_session.commit()

    rows = {w["token"]: w for w in client.get("/analytics/index").json()["windows"]}
    assert rows["2w"]["available"] is True
    assert rows["1m"]["available"] is False  # 30 days back is before 2026-08-18

    # AVAILABILITY AND POINT COUNT ARE DIFFERENT QUESTIONS, and this is the
    # case that separates them: 2W is genuinely covered - the history reaches
    # back past 2026-08-24 - and yet only one published point falls inside the
    # window, because the other is older than its start. The endpoint returns
    # the points in the window, not the points that made it available.
    two_week = client.get("/analytics/index?window=2w").json()
    assert two_week["covers_requested_window"] is True
    assert [p["date"] for p in two_week["points"]] == ["2026-09-07"]


def test_covered_days_is_the_span_actually_held(client, five_days):
    rows = {w["token"]: w for w in client.get("/analytics/index").json()["windows"]}
    # Sep 3 through Sep 7 inclusive.
    assert rows["all"]["covered_days"] == 5
    # A window reaching further back than the archive still reports what the
    # archive holds inside it, not the window's own length.
    assert rows["2y"]["covered_days"] == 5


def test_windows_are_published_even_with_no_history(client, db_session):
    body = client.get("/analytics/index?window=all").json()
    assert [w["token"] for w in body["windows"]] == list(WINDOW_DAYS)
    assert all(w["available"] is False for w in body["windows"])
    assert all(w["covered_days"] == 0 for w in body["windows"])
    # A client with an empty map would fall back to a hardcoded token list,
    # which is the frontend re-owning the grammar this endpoint owns.
    assert body["default_window"] == "all"


def test_windows_do_not_change_with_the_requested_window(client, five_days):
    """The map describes the SCOPE's extent, not the request. Asking for 2W
    must not make 2W look available."""
    first = client.get("/analytics/index?window=all").json()["windows"]
    for token in WINDOW_DAYS:
        assert client.get(f"/analytics/index?window={token}").json()["windows"] == first


# --- B. the default window is section 13.1 ----------------------------------


def test_default_is_all_while_three_months_is_unavailable(client, five_days):
    body = client.get("/analytics/index?window=all").json()
    assert body["default_window"] == "all"
    rows = {w["token"]: w for w in body["windows"]}
    assert rows["3m"]["available"] is False


def test_default_becomes_3m_once_three_months_is_available(db_session, client):
    """Section 13.1: "Once 3M is available (`windows["3m"].available == true`),
    3M becomes the default." The rule reads off the map beside it, so the two
    can never disagree."""
    _daily(db_session, date(2026, 5, 1), 130)
    body = client.get("/analytics/index?window=all").json()
    rows = {w["token"]: w for w in body["windows"]}
    assert rows["3m"]["available"] is True
    assert body["default_window"] == "3m"


def test_default_is_never_a_token_outside_the_grammar(db_session, client):
    for count in (1, 5, 40, 130, 400):
        for row in db_session.query(CardPirateIndexPoint).all():
            db_session.delete(row)
        db_session.commit()
        _daily(db_session, date(2026, 1, 1), count)
        body = client.get("/analytics/index").json()
        assert body["default_window"] in WINDOW_DAYS


def test_default_does_not_follow_the_requested_window(client, five_days):
    """`default_window` is policy, not an echo. A reader on 1Y must still be
    told the surface's default is `all`."""
    assert client.get("/analytics/index?window=1y").json()["default_window"] == "all"
    assert client.get("/analytics/index?window=2w").json()["default_window"] == "all"


# --- C. breaks come from the persisted rows ---------------------------------


def test_no_breaks_in_a_clean_daily_series(client, five_days):
    assert client.get("/analytics/index?window=all").json()["breaks"] == []


def test_an_index_version_change_is_published_as_a_carried_break(db_session, client):
    base = _base(date(2026, 9, 3))
    db_session.add(base)
    db_session.flush()
    db_session.add(_step(date(2026, 9, 4), Decimal("1000.8409"), date(2026, 9, 3)))
    # The new segment opens under index_version 4, carrying the level across.
    # A base is not a step, so it has no prior date and no step_days of its
    # own - the boundary is the version difference between adjacent rows.
    db_session.add(_base(
        date(2026, 9, 5), Decimal("1000.8409"),
        index_version=4, carried_from_point_id=base.id,
    ))
    db_session.commit()

    breaks = client.get("/analytics/index?window=all").json()["breaks"]
    assert len(breaks) == 1
    entry = breaks[0]
    assert entry["at"] == "2026-09-05"
    assert entry["reason"] == "index_version_change"
    assert entry["from_index_version"] == 3
    assert entry["to_index_version"] == 4
    assert entry["carried"] is True
    # Section 5.1 rule 4 - the level is continuous across the carry, so the
    # carried level is the new segment's own level.
    assert entry["carried_level"] == "1000.8409"
    assert entry["carried_from_point_date"] == "2026-09-03"
    # A version boundary is not a cadence fact.
    assert entry["step_days"] is None


def test_a_source_semantics_change_is_its_own_reason(db_session, client):
    db_session.add(_base(date(2026, 9, 3)))
    # A RESET: a base with no carry, which `ck_cpi_points_initial_base_is_base_value`
    # requires to open at exactly 1000. That constraint is itself the reason a
    # reset is rare - and the reason section 5.6 rule 5 can trust `carried`.
    db_session.add(_base(date(2026, 9, 4), source_semantics_version=3))
    db_session.commit()

    breaks = client.get("/analytics/index?window=all").json()["breaks"]
    assert [b["reason"] for b in breaks] == ["source_semantics_version_change"]
    assert breaks[0]["from_source_semantics_version"] == 2
    assert breaks[0]["to_source_semantics_version"] == 3
    assert breaks[0]["from_index_version"] is None
    # No carry on this segment: a RESET, which is what section 5.6 rule 5 acts
    # on when it withholds a change figure.
    assert breaks[0]["carried"] is False
    assert breaks[0]["carried_level"] is None


def test_a_snapshot_gap_is_a_break_but_not_a_methodology_one(db_session, client):
    db_session.add(_base(date(2026, 9, 1)))
    db_session.add(_step(date(2026, 9, 6), Decimal("1002.0000"), date(2026, 9, 1), 5))
    db_session.commit()

    breaks = client.get("/analytics/index?window=all").json()["breaks"]
    assert [b["reason"] for b in breaks] == ["snapshot_gap"]
    entry = breaks[0]
    assert entry["at"] == "2026-09-06"
    assert entry["prior_point_date"] == "2026-09-01"
    assert entry["step_days"] == 5
    # Section 12.1: "A `snapshot_gap` break carries neither `carried` nor
    # `carried_level`; it is a cadence fact, not a methodology one."
    assert entry["carried"] is None
    assert entry["carried_level"] is None


def test_a_step_of_one_is_never_a_gap(db_session, client):
    _daily(db_session, date(2026, 9, 3), 5)
    assert client.get("/analytics/index?window=all").json()["breaks"] == []


def test_breaks_describe_only_the_returned_window(db_session, client):
    """A boundary older than `window_start` is not on the chart the client is
    about to draw, and a marker for it would sit on a date the axis does not
    contain."""
    june_base = _base(date(2026, 6, 1))
    db_session.add(june_base)
    db_session.flush()
    db_session.add(_base(
        date(2026, 6, 2), index_version=4, carried_from_point_id=june_base.id,
    ))
    db_session.commit()
    _daily(db_session, date(2026, 9, 3), 5)

    # ALL sees the June boundary.
    all_breaks = client.get("/analytics/index?window=all").json()["breaks"]
    assert "index_version_change" in [b["reason"] for b in all_breaks]
    assert any(b["at"] == "2026-06-02" for b in all_breaks)

    # 2W starts on 2026-09-03 and therefore contains none of it.
    two_week = client.get("/analytics/index?window=2w").json()
    assert [p["date"] for p in two_week["points"]][0] == "2026-09-03"
    assert all(b["at"] >= "2026-09-03" for b in two_week["breaks"])
    assert not any(b["at"] == "2026-06-02" for b in two_week["breaks"])


def test_breaks_are_ascending_by_date(db_session, client):
    first = _base(date(2026, 9, 1))
    db_session.add(first)
    db_session.flush()
    db_session.add(_step(date(2026, 9, 4), Decimal("1000.5000"), date(2026, 9, 1), 3))
    db_session.add(_base(
        date(2026, 9, 5), Decimal("1000.5000"),
        index_version=4, carried_from_point_id=first.id,
    ))
    db_session.commit()

    breaks = client.get("/analytics/index?window=all").json()["breaks"]
    assert [b["at"] for b in breaks] == sorted(b["at"] for b in breaks)
    assert [b["reason"] for b in breaks] == ["snapshot_gap", "index_version_change"]


# --- D. the addition is additive --------------------------------------------


def test_every_pre_existing_field_is_unchanged(client, five_days):
    """The exact payload a client written before 2A-B reads. If any of these
    moved, renamed or changed type, the change was not additive."""
    body = client.get("/analytics/index?window=all").json()
    assert body["scope_kind"] == "overall"
    assert body["scope_key"] == ""
    assert body["methodology_version"] == 1
    assert body["index_version"] == 3
    assert body["source_semantics_version"] == 2
    assert body["requested_window"] == "all"
    assert body["window_start"] is None
    assert body["available_from"] == "2026-09-03"
    assert body["available_to"] == "2026-09-07"
    assert body["covers_requested_window"] is True
    assert [p["date"] for p in body["points"]] == [
        "2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06", "2026-09-07"
    ]
    assert body["starting_value"] == "1000.0000"
    assert body["current_value"] == "1000.4000"
    assert body["low_value"] == "1000.0000"
    assert body["high_value"] == "1000.4000"
    assert body["change"]["from_date"] == "2026-09-03"
    assert body["change"]["to_date"] == "2026-09-07"
    assert body["change"]["spans_break"] is False
    assert body["change_unavailable_reason"] is None


@pytest.mark.parametrize("token", list(WINDOW_DAYS))
def test_every_window_request_still_answers(client, five_days, token):
    """All seven tokens remain backward compatible: 200, the same points, and
    now the metadata beside them."""
    response = client.get(f"/analytics/index?window={token}")
    assert response.status_code == 200
    body = response.json()
    assert body["requested_window"] == token
    assert len(body["points"]) == 5
    assert len(body["windows"]) == 7
    assert body["default_window"] == "all"
    assert body["breaks"] == []


def test_an_unknown_window_is_still_rejected(client, five_days):
    response = client.get("/analytics/index?window=7d")
    assert response.status_code == 400
    assert "7d" in response.json()["detail"]


def test_the_endpoint_still_writes_nothing(client, five_days, db_session):
    before = db_session.query(CardPirateIndexPoint).count()
    for token in WINDOW_DAYS:
        client.get(f"/analytics/index?window={token}")
    assert db_session.query(CardPirateIndexPoint).count() == before


# --- E. one default, resolved on the server (TASK INDEX 2A-C) ---------------
#
# The endpoint used to hold TWO notions of default: the route's `?window=`
# fallback of `3m`, and the payload's own `default_window`. On a short archive
# those disagreed - a request with no window returned `3m` while the published
# default said `all` - and the frontend carried a `BOOTSTRAP_WINDOW` constant
# to paper over the gap. These tests fix the single contract that replaced it,
# on both sides of the section 13.1 threshold.


def test_no_window_resolves_to_all_on_a_short_archive(client, five_days):
    body = client.get("/analytics/index").json()
    assert body["default_window"] == "all"
    assert body["requested_window"] == "all"
    assert body["window_start"] is None
    assert body["covers_requested_window"] is True


def test_no_window_is_byte_identical_to_the_explicit_default(client, five_days):
    """An implicit request must be indistinguishable from the explicit request
    for the same token. Anything else means a client can tell which form it
    used, and would eventually branch on it."""
    assert client.get("/analytics/index").json() == (
        client.get("/analytics/index?window=all").json()
    )


def test_no_window_resolves_to_3m_once_three_months_exists(db_session, client):
    """The transition, with no client change and no second request.

    130 daily points is past the 90-day threshold, so section 13.1's ladder
    moves the default to `3m` - and the implicit request follows it."""
    _daily(db_session, date(2026, 5, 1), 130)
    body = client.get("/analytics/index").json()
    assert body["default_window"] == "3m"
    assert body["requested_window"] == "3m"
    # ...and it really is the 3m window, not `all` wearing its label: the
    # window has a start, and it excludes the oldest points.
    assert body["window_start"] is not None
    assert body["covers_requested_window"] is True
    assert len(body["points"]) < 130
    assert body == client.get("/analytics/index?window=3m").json()


def test_explicit_all_still_returns_all_when_3m_is_the_default(db_session, client):
    _daily(db_session, date(2026, 5, 1), 130)
    body = client.get("/analytics/index?window=all").json()
    assert body["requested_window"] == "all"
    # The published policy is unchanged by what was asked for.
    assert body["default_window"] == "3m"
    assert body["window_start"] is None
    assert len(body["points"]) == 130


def test_an_unavailable_but_valid_window_keeps_its_frozen_behaviour(client, five_days):
    """Section 12.2 rule 1: never 404, and never silently substitute a shorter
    window. A `2y` request on five days of data returns those five days and
    reports the shortfall - it does NOT fall through to the default."""
    body = client.get("/analytics/index?window=2y").json()
    assert body["requested_window"] == "2y"
    assert body["covers_requested_window"] is False
    assert body["window_start"] == "2024-09-07"  # 2026-09-07 anchor minus 730 days
    assert [p["date"] for p in body["points"]][0] == "2026-09-03"
    assert len(body["points"]) == 5
    # The default is still published beside it, unchanged.
    assert body["default_window"] == "all"


@pytest.mark.parametrize("token", ["7d", "5y", "", "month", "3m;drop", "1w"])
def test_an_invalid_token_is_still_400_and_never_the_default(client, five_days, token):
    """The deferral is about which window an ABSENT parameter means. A present
    one that is illegal is still a client error - it must not quietly become
    the default, which would turn every typo into a silent wrong answer.

    The empty string is in the list deliberately: `?window=` is a supplied
    value, not an absent one."""
    response = client.get(f"/analytics/index?window={token}")
    assert response.status_code == 400
    assert "expected one of" in response.json()["detail"]


def test_the_implicit_window_follows_the_archive_rather_than_a_constant(db_session, client):
    """The same request, answered differently as the archive grows - which is
    the whole point of removing the transport default."""
    _daily(db_session, date(2026, 6, 20), 80)
    assert client.get("/analytics/index").json()["requested_window"] == "all"

    for row in db_session.query(CardPirateIndexPoint).all():
        db_session.delete(row)
    db_session.commit()
    _daily(db_session, date(2026, 5, 1), 130)
    assert client.get("/analytics/index").json()["requested_window"] == "3m"


def test_no_window_on_an_empty_archive_still_names_a_window(client, db_session):
    body = client.get("/analytics/index").json()
    assert body["default_window"] == "all"
    assert body["requested_window"] == "all"
    assert body["points"] == []


def test_the_module_no_longer_exports_a_transport_default(client, five_days):
    """The second notion of default is gone, not merely unused.

    A constant left in place is a constant something eventually imports - and
    the failure it would cause is a silent wrong window, not an error."""
    import app.services.card_pirate_index_read as read_module

    assert not hasattr(read_module, "DEFAULT_WINDOW")
    assert "DEFAULT_WINDOW" not in read_module.__all__
    # The one rule that remains is section 13.1's ladder.
    assert read_module.PREFERRED_DEFAULT_WINDOW == "3m"
    assert read_module.FALLBACK_DEFAULT_WINDOW == "all"


def test_resolve_window_reports_absence_rather_than_inventing_a_token(client):
    from app.services.card_pirate_index_read import resolve_window

    assert resolve_window(None) is None
    assert resolve_window(" 3M ") == "3m"
