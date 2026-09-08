"""GET /analytics/index/composition - what was IN the index on one day.

WHY THIS SUITE EXISTS. The composition is DERIVED at read time from archived
snapshots rather than persisted, so the whole contract rests on two things
being true: that the derivation reproduces the published `constituent_count`
exactly, and that it refuses to answer when it does not. Everything else here
guards the ways a rarity chart can quietly lie - dropping a print with no
rarity, counting the live catalogue instead of the archive, or letting a
second rarity vocabulary in through the join.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.canonical_card import CanonicalCard
from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.card_print import CardPrint
from app.models.market_index_snapshot import MarketIndexSnapshot

STAMP = datetime(2026, 9, 7, 20, 0, 0, tzinfo=timezone.utc)
D3, D4, D5, D6, D7 = (date(2026, 9, d) for d in (3, 4, 5, 6, 7))

YUYU = {
    "source_values": [
        {
            "source": "yuyutei",
            "reference_type": "sell",
            "contributes_to_index": True,
            "value_jpy": 100,
        }
    ]
}
# The same print with a SECOND contributing instrument - the contributor-churn
# case (section 3 rule 4), and the one that actually happened on staging on
# 2026-09-07 to print 18.
YUYU_PLUS_SNKR = {
    "source_values": [
        {
            "source": "yuyutei",
            "reference_type": "sell",
            "contributes_to_index": True,
            "value_jpy": 100,
        },
        {
            "source": "snkrdunk",
            "reference_type": "listing_floor",
            "contributes_to_index": True,
            "value_jpy": 120,
        },
    ]
}


def seed_print(db, print_id: int, rarity: str | None, *, canonical_rarity=None):
    if db.get(CardPrint, print_id) is not None:
        return
    canonical = CanonicalCard(
        card_code=f"OP01-{print_id:03d}",
        name_en="x",
        card_type="CHARACTER",
        rarity=canonical_rarity,
    )
    db.add(canonical)
    db.flush()
    db.add(
        CardPrint(
            id=print_id,
            canonical_card_id=canonical.id,
            language="jp",
            official_rarity=rarity,
        )
    )
    db.flush()


def snap(db, print_id, day, value, *, provenance=YUYU, iv=3, ssv=2):
    db.add(
        MarketIndexSnapshot(
            card_print_id=print_id,
            calculated_at=STAMP,
            snapshot_date=day,
            index_value_jpy=value,
            calculation_method="median" if value is not None else "none",
            source_count=1 if value is not None else 0,
            coverage_status="full" if value is not None else "none",
            confidence="high",
            index_version=iv,
            source_semantics_version=ssv,
            provenance=provenance,
        )
    )


def point(db, day, *, prior, constituents, eligible, value="1000.0000", base=False):
    db.add(
        CardPirateIndexPoint(
            scope_kind="overall",
            scope_key="",
            methodology_version=1,
            index_version=3,
            source_semantics_version=2,
            calculated_at=STAMP,
            point_date=day,
            index_value=Decimal(value),
            is_base=base,
            prior_point_date=prior,
            step_days=None if base else 1,
            chain_link_log_return=None if base else Decimal("0.0001"),
            constituent_count=constituents,
            eligible_print_count=eligible,
            movers_up=None if base else 0,
            movers_down=None if base else 0,
            movers_flat=None if base else constituents,
            capped_count=None if base else 0,
        )
    )


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def archive(db_session):
    """Two published steps over a small archive with a real rarity spread.

    Deliberately shaped like staging rather than like a uniform block: one
    entrant, one contributor-churn exclusion, one print with NO rarity at all,
    and prints that exist in the catalogue but were never in the index.
    """
    # 0-3 C, 4-5 R, 6 UC, 7 SEC, 8 has no rarity anywhere, 9 uses the
    # canonical fallback, 10-11 are the SP CARD alias pair.
    rarities = {
        0: "C", 1: "C", 2: "C", 3: "C",
        4: "R", 5: "R",
        6: "UC",
        7: "SEC",
        8: None,
        10: "SPカード", 11: "SP P",
    }
    for pid, r in rarities.items():
        seed_print(db_session, pid, r)
    seed_print(db_session, 9, None, canonical_rarity="L")
    # In the catalogue but never valued - proves the population is not the
    # catalogue.
    seed_print(db_session, 900, "SEC")
    seed_print(db_session, 901, "SEC")

    valued = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    for day in (D6, D7):
        for pid in valued:
            snap(db_session, pid, day, 100)
    # An ENTRANT on D7: valued today, absent on D6. Eligible but not a
    # constituent.
    snap(db_session, 12, D7, 100)
    seed_print(db_session, 12, "C")
    # CHURN on D7: print 7 gains a second contributing instrument, so its
    # contributor set differs across the two days and section 3 rule 4
    # excludes it. This is why SEC vanishes from the D7 buckets.
    db_session.query(MarketIndexSnapshot).filter(
        MarketIndexSnapshot.card_print_id == 7,
        MarketIndexSnapshot.snapshot_date == D7,
    ).one().provenance = YUYU_PLUS_SNKR

    point(db_session, D6, prior=None, constituents=0, eligible=12, base=True)
    # D7: 12 valued on both days, minus print 7 (churn) = 11 constituents;
    # eligible on D7 is 13 (the twelve plus the entrant).
    point(db_session, D7, prior=D6, constituents=11, eligible=13, value="1000.5000")
    db_session.commit()
    return db_session


# --- A. the newest point -----------------------------------------------------


def test_no_date_returns_the_newest_published_point(client, archive):
    body = client.get("/analytics/index/composition").json()
    assert body["as_of"] == "2026-09-07"
    assert body["constituent_count"] == 11


def test_the_rarity_sum_equals_the_constituent_count(client, archive):
    body = client.get("/analytics/index/composition").json()
    assert sum(b["count"] for b in body["rarity"]) == body["constituent_count"]


def test_the_buckets_are_the_archived_population_not_the_catalogue(client, archive):
    """SEC exists three times in the catalogue and zero times in this day's
    index: print 7 was excluded by contributor churn, 900 and 901 were never
    valued. A chart drawn from `card_prints` would show three."""
    body = client.get("/analytics/index/composition").json()
    keys = {b["key"]: b["count"] for b in body["rarity"]}
    assert "SEC" not in keys
    assert keys == {"C": 4, "R": 2, "SP CARD": 2, "UNKNOWN": 1, "L": 1, "UC": 1}


def test_an_entrant_is_eligible_but_not_a_constituent(client, archive):
    """Print 12 is valued on D7 and absent on D6, so it produced no return.
    `eligible_print_count` counts it; this endpoint must not."""
    body = client.get("/analytics/index/composition").json()
    assert body["constituent_count"] == 11
    index = client.get("/analytics/index").json()
    assert index["points"][-1]["eligible_print_count"] == 13


# --- B. an explicit historical date ------------------------------------------


def test_an_explicit_date_selects_exactly_that_point(client, archive):
    body = client.get("/analytics/index/composition?date=2026-09-07").json()
    assert body["as_of"] == "2026-09-07"
    assert body["constituent_count"] == 11


def test_a_base_point_has_no_constituents_and_an_empty_list(client, archive):
    """A base opens a segment: no prior day, no step, no constituents. The
    honest answer is an empty list, not a fabricated one - and no division by
    zero on the way there."""
    body = client.get("/analytics/index/composition?date=2026-09-06").json()
    assert body["as_of"] == "2026-09-06"
    assert body["constituent_count"] == 0
    assert body["rarity"] == []


def test_a_date_with_no_published_point_is_404(client, archive):
    r = client.get("/analytics/index/composition?date=2026-09-05")
    assert r.status_code == 404
    assert "2026-09-05" in r.json()["detail"]


def test_it_never_substitutes_a_neighbouring_day(client, archive):
    """The 404 above matters because the alternative is silent: a caller
    asking for the 5th and receiving the 6th would caption someone else's
    numbers with their own date."""
    assert client.get("/analytics/index/composition?date=2026-09-05").status_code == 404
    assert client.get("/analytics/index/composition?date=2026-09-06").json()["as_of"] == (
        "2026-09-06"
    )


def test_an_empty_archive_is_404(client, db_session):
    r = client.get("/analytics/index/composition")
    assert r.status_code == 404


def test_a_malformed_date_is_rejected(client, archive):
    assert client.get("/analytics/index/composition?date=nonsense").status_code == 422


# --- C. the constituent set is the estimator's own ---------------------------


def test_the_derived_population_matches_compute_step_exactly(archive):
    """Not "a similar number" - the same predicate. `constituent_print_ids`
    and `compute_step` share `constituent_exclusion`, and this pins that they
    cannot drift."""
    from app.services.card_pirate_index import compute_step, constituent_print_ids
    from app.services.card_pirate_index_replay import load_snapshot_days

    days = {d.point_date: d for d in load_snapshot_days(archive, history_start=D6, end=D7)}
    ids = constituent_print_ids(days[D6], days[D7])
    assert len(ids) == compute_step(days[D6], days[D7]).constituent_count == 11
    # Ascending print id, so the set is ordered rather than merely correct.
    assert list(ids) == sorted(ids)
    assert 7 not in ids  # contributor churn
    assert 12 not in ids  # entrant


def test_contributor_churn_excludes_a_print_whose_instrument_changed(archive):
    from app.services.card_pirate_index import (
        EXCLUDED_CONTRIBUTOR_CHURN,
        constituent_exclusion,
    )
    from app.services.card_pirate_index_replay import load_snapshot_days

    days = {d.point_date: d for d in load_snapshot_days(archive, history_start=D6, end=D7)}
    before = days[D6].by_print()[7]
    now = days[D7].by_print()[7]
    assert constituent_exclusion(before, now) == EXCLUDED_CONTRIBUTOR_CHURN


def test_a_version_mismatch_excludes_a_print(db_session, client):
    seed_print(db_session, 1, "C")
    seed_print(db_session, 2, "C")
    for pid in (1, 2):
        snap(db_session, pid, D6, 100)
    snap(db_session, 1, D7, 100)
    snap(db_session, 2, D7, 100, iv=4)  # different index_version on D7 only
    point(db_session, D6, prior=None, constituents=0, eligible=2, base=True)
    point(db_session, D7, prior=D6, constituents=1, eligible=2, value="1000.1")
    db_session.commit()

    body = client.get("/analytics/index/composition").json()
    assert body["constituent_count"] == 1
    assert sum(b["count"] for b in body["rarity"]) == 1


def test_a_null_valued_row_is_an_absence_not_a_constituent(db_session, client):
    seed_print(db_session, 1, "C")
    seed_print(db_session, 2, "C")
    for pid in (1, 2):
        snap(db_session, pid, D6, 100)
    snap(db_session, 1, D7, 100)
    snap(db_session, 2, D7, None)  # coverage_status='none'
    point(db_session, D6, prior=None, constituents=0, eligible=2, base=True)
    point(db_session, D7, prior=D6, constituents=1, eligible=1, value="1000.1")
    db_session.commit()

    assert client.get("/analytics/index/composition").json()["constituent_count"] == 1


# --- D. rarity vocabulary ----------------------------------------------------


def test_the_sp_card_alias_is_folded_exactly_as_the_catalogue_folds_it(client, archive):
    """`SPカード` and `SP P` are one collector concept and one bucket. A second
    rarity vocabulary here would let this chart split a population the
    catalogue's own `?rarity=` filter joins."""
    body = client.get("/analytics/index/composition").json()
    keys = [b["key"] for b in body["rarity"]]
    assert "SP CARD" in keys
    assert "SPカード" not in keys and "SP P" not in keys
    assert next(b for b in body["rarity"] if b["key"] == "SP CARD")["count"] == 2


def test_the_canonical_rarity_is_the_fallback_when_the_print_has_none(client, archive):
    """Print 9 carries no `official_rarity` and its canonical card says L -
    the same COALESCE the catalogue's effective_rarity uses."""
    body = client.get("/analytics/index/composition").json()
    assert next(b for b in body["rarity"] if b["key"] == "L")["count"] == 1


def test_an_absent_rarity_gets_an_explicit_unknown_bucket(client, archive):
    """Print 8 has neither rarity. Dropping it would break the sum silently,
    which is exactly the arithmetic hole this bucket closes."""
    body = client.get("/analytics/index/composition").json()
    unknown = next(b for b in body["rarity"] if b["key"] == "UNKNOWN")
    assert unknown["count"] == 1
    assert unknown["label"] == "Unknown"
    assert sum(b["count"] for b in body["rarity"]) == body["constituent_count"]


# --- E. ordering and percentages ---------------------------------------------


def test_buckets_are_ordered_largest_first_with_unknown_last(client, archive):
    body = client.get("/analytics/index/composition").json()
    keys = [b["key"] for b in body["rarity"]]
    assert keys[0] == "C"  # 4, the largest
    assert keys[-1] == "UNKNOWN"  # an absence never leads or hides mid-list
    middle = [b for b in body["rarity"] if b["key"] != "UNKNOWN"]
    # Descending count, ties broken by key - a total order, not a mostly-order.
    assert middle == sorted(middle, key=lambda b: (-b["count"], b["key"]))


def test_the_order_is_stable_across_repeated_requests(client, archive):
    first = client.get("/analytics/index/composition").json()
    second = client.get("/analytics/index/composition").json()
    assert first == second


def test_percentages_are_count_over_constituent_count(client, archive):
    body = client.get("/analytics/index/composition").json()
    total = body["constituent_count"]
    for b in body["rarity"]:
        assert Decimal(str(b["pct"])) == (
            Decimal(b["count"]) * 100 / Decimal(total)
        ).quantize(Decimal("0.01"))


def test_percentages_are_two_places_and_not_nudged_to_total_100(client, archive):
    """11 constituents cannot divide into a column totalling exactly 100.00.
    The buckets keep their own honest shares rather than one absorbing the
    residue and printing a percentage that disagrees with its own count."""
    body = client.get("/analytics/index/composition").json()
    total = sum(Decimal(str(b["pct"])) for b in body["rarity"])
    assert total != Decimal("100.00")
    assert abs(total - Decimal("100")) < Decimal("0.05")
    for b in body["rarity"]:
        # A JSON NUMBER, not a string: a percentage is display metadata and a
        # consumer should not have to parse it back out of quotes.
        assert isinstance(b["pct"], float)
        assert Decimal(str(b["pct"])).as_tuple().exponent >= -2


# --- F. the integrity guard --------------------------------------------------


def test_a_constituent_count_mismatch_fails_closed(db_session, client):
    """The published point claims a number the archive cannot produce. The
    endpoint must publish NEITHER - a rarity breakdown summing to 11 under a
    headline of 99 is worse than an error."""
    seed_print(db_session, 1, "C")
    snap(db_session, 1, D6, 100)
    snap(db_session, 1, D7, 100)
    point(db_session, D6, prior=None, constituents=0, eligible=1, base=True)
    # eligible must be >= constituents (ck_cpi_points_constituents_le_eligible),
    # so the row is LEGAL - it simply claims a population the archive, which
    # holds one print for these two days, cannot produce.
    point(db_session, D7, prior=D6, constituents=99, eligible=99, value="1000.1")
    db_session.commit()

    r = client.get("/analytics/index/composition")
    assert r.status_code == 500
    assert "integrity" in r.json()["detail"].lower()


def test_missing_archived_snapshots_fail_closed(db_session, client):
    """A published point whose snapshots are gone cannot be described. It is
    not answered with an empty chart."""
    point(db_session, D6, prior=None, constituents=0, eligible=1, base=True)
    point(db_session, D7, prior=D6, constituents=5, eligible=5, value="1000.1")
    db_session.commit()

    assert client.get("/analytics/index/composition").status_code == 500


def test_the_guard_is_not_bypassed_by_an_explicit_date(db_session, client):
    seed_print(db_session, 1, "C")
    snap(db_session, 1, D6, 100)
    snap(db_session, 1, D7, 100)
    point(db_session, D6, prior=None, constituents=0, eligible=1, base=True)
    # eligible must be >= constituents (ck_cpi_points_constituents_le_eligible),
    # so the row is LEGAL - it simply claims a population the archive, which
    # holds one print for these two days, cannot produce.
    point(db_session, D7, prior=D6, constituents=99, eligible=99, value="1000.1")
    db_session.commit()

    assert client.get("/analytics/index/composition?date=2026-09-07").status_code == 500


# --- G. what the payload must never carry ------------------------------------


def test_the_payload_carries_no_ids_of_any_kind(client, archive):
    body = client.get("/analytics/index/composition").json()
    blob = str(body)
    for forbidden in ("card_print_id", "print_id", "canonical_card_id", "point_id", "id"):
        assert forbidden not in body
    assert "card_print" not in blob


def test_the_payload_carries_no_breadth_or_price_statistics(client, archive):
    """Breadth belongs to the points in /analytics/index. A second home for it
    is a second place for it to be right."""
    body = client.get("/analytics/index/composition").json()
    assert set(body) == {"as_of", "constituent_count", "rarity"}
    for forbidden in (
        "eligible_print_count", "movers_up", "movers_down", "movers_flat",
        "capped_count", "median_jpy", "average", "value", "index_value",
    ):
        assert forbidden not in str(body)


def test_each_bucket_carries_exactly_the_four_contract_fields(client, archive):
    body = client.get("/analytics/index/composition").json()
    for bucket in body["rarity"]:
        assert set(bucket) == {"key", "label", "count", "pct"}


# --- H. isolation from live pricing ------------------------------------------


def test_the_endpoint_reads_no_pricing_table(client, archive, monkeypatch):
    """The proof is structural rather than behavioural: if the composition
    ever reached the resolver or the observations table, these would fire.
    `price_observations` is never queried and no index is recomputed."""
    import app.services.market_index as market_index

    def explode(*a, **k):  # pragma: no cover - the point is that it never runs
        raise AssertionError("the composition endpoint touched live pricing")

    for name in ("compute_market_index", "resolve_market_index"):
        if hasattr(market_index, name):
            monkeypatch.setattr(market_index, name, explode)

    assert client.get("/analytics/index/composition").status_code == 200


def test_the_endpoint_writes_nothing(client, archive, db_session):
    before_points = db_session.query(CardPirateIndexPoint).count()
    before_snaps = db_session.query(MarketIndexSnapshot).count()
    before_prints = db_session.query(CardPrint).count()

    client.get("/analytics/index/composition")
    client.get("/analytics/index/composition?date=2026-09-06")
    client.get("/analytics/index/composition?date=2026-09-05")

    assert db_session.query(CardPirateIndexPoint).count() == before_points
    assert db_session.query(MarketIndexSnapshot).count() == before_snaps
    assert db_session.query(CardPrint).count() == before_prints


def test_a_catalogue_print_that_was_never_valued_is_absent(client, archive):
    """900 and 901 are SEC prints in the catalogue with no snapshot rows. A
    composition built from the catalogue would count them."""
    body = client.get("/analytics/index/composition").json()
    assert all(b["key"] != "SEC" for b in body["rarity"])
    assert body["constituent_count"] == 11


# --- I. the index endpoint is untouched --------------------------------------


def test_the_index_endpoint_still_answers_exactly_as_before(client, archive):
    body = client.get("/analytics/index").json()
    assert body["requested_window"] == "all"
    assert body["default_window"] == "all"
    assert [w["token"] for w in body["windows"]] == [
        "2w", "1m", "3m", "6m", "1y", "2y", "all"
    ]
    assert body["breaks"] == []
    # Breadth still lives here, and only here.
    newest = body["points"][-1]
    assert newest["constituent_count"] == 11
    assert newest["eligible_print_count"] == 13
    assert newest["movers_flat"] == 11
    assert "rarity" not in body


def test_the_composition_service_contains_no_write_verb(client, archive):
    """A source-level guard, matching the one the read service carries.

    The behavioural test above proves nothing was written on the paths it
    exercised; this proves there is no path that could. `card_pirate_index_
    point.py`'s allowlist admits this module on exactly that basis."""
    import pathlib

    import app.services.card_pirate_index_composition as module

    source = pathlib.Path(module.__file__).read_text()
    body = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith("#")
    )
    # Strip the module docstring, which legitimately discusses writing.
    body = body.split('"""', 2)[-1]
    for verb in ("insert(", "update(", "delete(", "db.add", "db.commit",
                 "db.flush", "db.merge", "bulk_save"):
        assert verb not in body, f"the composition service contains {verb!r}"


def test_the_route_survives_a_development_environment(client, archive, monkeypatch):
    """`set_cache_headers` stamps X-Cache-Key only when the environment is
    development, and its `cache_key` parameter is typed `str`. A None there
    raises AttributeError on the way out - a 500 that appears on a developer's
    machine and on no deployed environment, which is the worst place for a
    bug to hide."""
    import app.services.cache_headers as cache_headers

    monkeypatch.setattr(cache_headers, "is_development_environment", lambda: True)
    r = client.get("/analytics/index/composition")
    assert r.status_code == 200
    assert r.headers["X-Cache-Key"]
    assert r.headers["X-Cache"] == "MISS"
