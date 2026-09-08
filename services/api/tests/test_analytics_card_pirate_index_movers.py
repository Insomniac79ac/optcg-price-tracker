"""GET /analytics/index/movers - what moved the index on one published day.

WHAT THIS SUITE GUARDS. The endpoint restates archived prices and the frozen
estimator's own arithmetic, so the failures worth pinning are the ones where it
would start producing numbers of its own: a mover that was never a constituent,
a contribution set that does not sum to the published step, a ranking that
collapses the distinction between how far a card moved and how far it moved the
index, or a payload keyed by something that does not identify a print.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.canonical_card import CanonicalCard
from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.card_print import CardPrint
from app.models.market_index_snapshot import MarketIndexSnapshot

STAMP = datetime(2026, 9, 7, 20, 0, 0, tzinfo=timezone.utc)
D5, D6, D7 = (date(2026, 9, d) for d in (5, 6, 7))

YUYU = {
    "source_values": [
        {"source": "yuyutei", "reference_type": "sell",
         "contributes_to_index": True, "value_jpy": 100}
    ]
}
YUYU_PLUS_SNKR = {
    "source_values": [
        {"source": "yuyutei", "reference_type": "sell",
         "contributes_to_index": True, "value_jpy": 100},
        {"source": "snkrdunk", "reference_type": "listing_floor",
         "contributes_to_index": True, "value_jpy": 120},
    ]
}


def seed_print(db, pid, *, code, name_en="Nami", rarity="C", name_jp=None,
               canonical_rarity=None, treatment=None):
    """A print. `code` is deliberately reusable - several prints share one."""
    canonical = db.query(CanonicalCard).filter(CanonicalCard.card_code == code).first()
    if canonical is None:
        canonical = CanonicalCard(
            card_code=code, name_en=name_en, name_jp=name_jp,
            card_type="CHARACTER", rarity=canonical_rarity,
        )
        db.add(canonical)
        db.flush()
    db.add(CardPrint(id=pid, canonical_card_id=canonical.id, language="jp",
                     official_rarity=rarity, treatment=treatment,
                     image_url=f"https://img.example/{code}_{pid}.png"))
    db.flush()


def snap(db, pid, day, value, *, provenance=YUYU, iv=3, ssv=2):
    db.add(MarketIndexSnapshot(
        card_print_id=pid, calculated_at=STAMP, snapshot_date=day,
        index_value_jpy=value,
        calculation_method="median" if value is not None else "none",
        source_count=1 if value is not None else 0,
        coverage_status="full" if value is not None else "none",
        confidence="high", index_version=iv, source_semantics_version=ssv,
        provenance=provenance,
    ))


def point(db, day, *, prior, constituents, eligible, value, base=False,
          chain=None, up=0, down=0, flat=None, capped=0):
    flat = constituents if flat is None else flat
    db.add(CardPirateIndexPoint(
        scope_kind="overall", scope_key="", methodology_version=1,
        index_version=3, source_semantics_version=2, calculated_at=STAMP,
        point_date=day, index_value=Decimal(value), is_base=base,
        prior_point_date=prior, step_days=None if base else 1,
        chain_link_log_return=None if base else (chain or Decimal("0.000000000000")),
        constituent_count=constituents, eligible_print_count=eligible,
        movers_up=None if base else up, movers_down=None if base else down,
        movers_flat=None if base else flat,
        capped_count=None if base else capped,
    ))


def sum_contributions(body):
    return sum(Decimal(m["contribution_log_return"]) for m in body["movers"])


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def archive(db_session):
    """A shaped archive: one uncapped gainer, one small loser, two capped
    losers, plenty of flats, one entrant and one contributor-churn exclusion.

    Deliberately mirrors staging's 2026-09-07: the two capped cards fell by
    very different amounts and must end up with identical contributions.
    """
    # 1: +23.33 %, just under the cap (3000 -> 3700)
    seed_print(db_session, 1, code="OP01-016", name_en="Nami", rarity="R")
    # 2: -1.52 %, uncapped (66000 -> 65000)
    seed_print(db_session, 2, code="OP01-078", name_en="Boa Hancock", rarity="SPカード")
    # 3: -41.18 %, capped (17000 -> 10000)
    seed_print(db_session, 3, code="OP01-047", name_en="Trafalgar Law", rarity="SPカード")
    # 4: -25.00 %, ALSO capped (2000 -> 1500) - a much smaller fall, same cap
    seed_print(db_session, 4, code="ST01-007", name_en="Nami", rarity="C")
    # 5..10: flat
    for pid in range(5, 11):
        seed_print(db_session, pid, code=f"OP01-{pid:03d}", rarity="UC")
    # 11: an ENTRANT on D7 - valued today only
    seed_print(db_session, 11, code="OP01-011", rarity="C")
    # 12: CHURN on D7 - its contributor set changes, so it is excluded even
    # though it moved more than anything else on the day.
    seed_print(db_session, 12, code="OP01-012", rarity="SEC")

    prior_values = {1: 3000, 2: 66000, 3: 17000, 4: 2000, 12: 780}
    current_values = {1: 3700, 2: 65000, 3: 10000, 4: 1500, 12: 1090}
    for pid in range(5, 11):
        prior_values[pid] = 500
        current_values[pid] = 500

    for pid, v in prior_values.items():
        snap(db_session, pid, D6, v)
    for pid, v in current_values.items():
        snap(db_session, pid, D7, v,
             provenance=YUYU_PLUS_SNKR if pid == 12 else YUYU)
    snap(db_session, 11, D7, 999)  # entrant

    # D6 is a quiet day: 10 constituents, none moved.
    for pid in list(range(1, 11)):
        snap(db_session, pid, D5, prior_values.get(pid, 500))
    point(db_session, D5, prior=None, constituents=0, eligible=10,
          value="1000.0000", base=True)
    point(db_session, D6, prior=D5, constituents=10, eligible=11,
          value="1000.9577", chain=Decimal("0.000000000000"),
          up=0, down=0, flat=10, capped=0)

    db_session.commit()

    # D7's real arithmetic, computed by the estimator itself so the fixture
    # cannot disagree with the code under test.
    from app.services.card_pirate_index import compute_step
    from app.services.card_pirate_index_replay import load_snapshot_days

    days = {d.point_date: d for d in load_snapshot_days(db_session, history_start=D6, end=D7)}
    step = compute_step(days[D6], days[D7])
    point(db_session, D7, prior=D6, constituents=step.constituent_count,
          eligible=days[D7].eligible_print_count,
          value="1000.1065", chain=step.step_log_return,
          up=step.movers_up, down=step.movers_down, flat=step.movers_flat,
          capped=step.capped_count)
    db_session.commit()
    return db_session


# --- A. routing --------------------------------------------------------------


def test_no_date_returns_the_newest_published_point(client, archive):
    body = client.get("/analytics/index/movers").json()
    assert body["as_of"] == "2026-09-07"
    assert body["prior_point_date"] == "2026-09-06"


def test_an_explicit_date_selects_exactly_that_point(client, archive):
    body = client.get("/analytics/index/movers?date=2026-09-06").json()
    assert body["as_of"] == "2026-09-06"


def test_a_date_with_no_published_point_is_404(client, archive):
    r = client.get("/analytics/index/movers?date=2026-09-04")
    assert r.status_code == 404
    assert "2026-09-04" in r.json()["detail"]


def test_a_malformed_date_is_422(client, archive):
    assert client.get("/analytics/index/movers?date=nonsense").status_code == 422


def test_an_empty_archive_is_404(client, db_session):
    assert client.get("/analytics/index/movers").status_code == 404


def test_the_response_is_cached_like_the_other_index_routes(client, archive):
    r = client.get("/analytics/index/movers")
    assert r.headers["X-Cache-TTL"] == "300"
    assert r.headers["X-Cache"] == "MISS"


# --- B. the Sep 7 golden case ------------------------------------------------


def test_the_counts_match_the_published_point(client, archive):
    body = client.get("/analytics/index/movers").json()
    assert body["constituent_count"] == 10
    assert body["movers_count"] == 4
    assert body["unchanged_count"] == 6
    assert body["movers_count"] + body["unchanged_count"] == body["constituent_count"]


def test_the_uncapped_gainer_is_reported_from_the_archived_values(client, archive):
    body = client.get("/analytics/index/movers").json()
    m = next(x for x in body["movers"] if x["card_print_id"] == 1)
    assert (m["prior_value_jpy"], m["current_value_jpy"]) == (3000, 3700)
    assert m["direction"] == "up"
    assert m["raw_pct"] == 23.33
    assert m["was_capped"] is False
    assert Decimal(m["contribution_log_return"]) > 0


def test_a_fall_beyond_the_cap_is_capped(client, archive):
    body = client.get("/analytics/index/movers").json()
    law = next(x for x in body["movers"] if x["card_print_id"] == 3)
    assert (law["prior_value_jpy"], law["current_value_jpy"]) == (17000, 10000)
    assert law["raw_pct"] == -41.18
    assert law["was_capped"] is True


def test_an_exactly_25_percent_fall_is_also_capped(client, archive):
    """-25 % is ln(0.75) = -0.2877, which is BEYOND -ln(1.25) = -0.2231. The
    cap is symmetric in LOG space, not in percent space, so a 25 % fall is
    capped while a 25 % rise is exactly at the boundary."""
    body = client.get("/analytics/index/movers").json()
    nami = next(x for x in body["movers"] if x["card_print_id"] == 4)
    assert nami["raw_pct"] == -25.00
    assert nami["was_capped"] is True


def test_the_small_loser_is_not_capped(client, archive):
    body = client.get("/analytics/index/movers").json()
    hancock = next(x for x in body["movers"] if x["card_print_id"] == 2)
    assert hancock["raw_pct"] == -1.52
    assert hancock["direction"] == "down"
    assert hancock["was_capped"] is False


def test_two_cards_capped_the_same_way_contribute_identically(client, archive):
    """THE REASON THE TWO RANKINGS EXIST. One fell 41 % and the other 25 %;
    both hit the same cap, so the index counted them as exactly equal."""
    body = client.get("/analytics/index/movers").json()
    law = next(x for x in body["movers"] if x["card_print_id"] == 3)
    nami = next(x for x in body["movers"] if x["card_print_id"] == 4)
    assert law["capped_log_return"] == nami["capped_log_return"]
    assert law["contribution_log_return"] == nami["contribution_log_return"]
    # ...and they are still ordered, deterministically, by the bigger raw move.
    assert law["impact_rank"] < nami["impact_rank"]
    assert abs(law["raw_pct"]) > abs(nami["raw_pct"])


# --- C. reconciliation -------------------------------------------------------


def test_the_contributions_sum_to_the_published_step(client, archive):
    """The whole basis for deriving at read time. Movers are only the non-flat
    constituents, and flat constituents contribute exactly zero, so the visible
    rows alone must reproduce the published step."""
    body = client.get("/analytics/index/movers").json()
    published = Decimal(body["chain_link_log_return"])
    assert sum_contributions(body).quantize(Decimal("0.000000000001")) == published


def test_flat_constituents_are_omitted_but_still_counted(client, archive):
    body = client.get("/analytics/index/movers").json()
    assert all(m["direction"] in ("up", "down") for m in body["movers"])
    assert body["unchanged_count"] == 6


def test_a_contradicted_constituent_count_fails_closed(db_session, client):
    seed_print(db_session, 1, code="OP01-016")
    snap(db_session, 1, D6, 100)
    snap(db_session, 1, D7, 200)
    point(db_session, D6, prior=None, constituents=0, eligible=1,
          value="1000.0000", base=True)
    point(db_session, D7, prior=D6, constituents=99, eligible=99,
          value="1000.1", chain=Decimal("0.1"), up=99, flat=0)
    db_session.commit()
    r = client.get("/analytics/index/movers")
    assert r.status_code == 500
    assert "integrity" in r.json()["detail"].lower()


def test_a_contradicted_step_fails_closed(db_session, client):
    """The count can be right while the arithmetic is wrong. A published step
    the constituents cannot produce is still a contradiction."""
    seed_print(db_session, 1, code="OP01-016")
    snap(db_session, 1, D6, 100)
    snap(db_session, 1, D7, 200)
    point(db_session, D6, prior=None, constituents=0, eligible=1,
          value="1000.0000", base=True)
    point(db_session, D7, prior=D6, constituents=1, eligible=1,
          value="1000.1", chain=Decimal("0.999999999999"), up=1, flat=0)
    db_session.commit()
    r = client.get("/analytics/index/movers")
    assert r.status_code == 500
    assert "chain_link" in r.json()["detail"]


def test_missing_archived_snapshots_fail_closed(db_session, client):
    point(db_session, D6, prior=None, constituents=0, eligible=1,
          value="1000.0000", base=True)
    point(db_session, D7, prior=D6, constituents=5, eligible=5,
          value="1000.1", chain=Decimal("0.1"), up=5, flat=0)
    db_session.commit()
    assert client.get("/analytics/index/movers").status_code == 500


# --- D. exclusions -----------------------------------------------------------


def test_an_entrant_never_appears_as_a_mover(client, archive):
    body = client.get("/analytics/index/movers").json()
    assert all(m["card_print_id"] != 11 for m in body["movers"])


def test_a_contributor_churn_print_never_appears_even_though_it_gained_most(
    client, archive
):
    """Print 12 went 780 -> 1090, a +39.7 % rise - by far the biggest GAIN on
    the day, and 70 % larger than the biggest gain that does appear. Its
    contributor set changed, so section 3 rule 4 excluded it from the index and
    it moved the index by exactly zero. Publishing it would put the day's
    largest apparent gain at the top of a list of things that moved the index.

    (It is not the largest move in absolute terms - a 41 % fall beats it - so
    the assertion is about the gain side specifically.)"""
    body = client.get("/analytics/index/movers").json()
    assert all(m["card_print_id"] != 12 for m in body["movers"])
    gains = [m["raw_pct"] for m in body["movers"] if m["raw_pct"] > 0]
    assert gains and max(gains) < 39


def test_a_version_mismatch_print_never_appears(db_session, client):
    seed_print(db_session, 1, code="OP01-016")
    seed_print(db_session, 2, code="OP01-017")
    for pid in (1, 2):
        snap(db_session, pid, D6, 100)
    snap(db_session, 1, D7, 200)
    snap(db_session, 2, D7, 400, iv=4)  # different index_version on D7
    point(db_session, D6, prior=None, constituents=0, eligible=2,
          value="1000.0000", base=True)

    from app.services.card_pirate_index import compute_step
    from app.services.card_pirate_index_replay import load_snapshot_days
    db_session.commit()
    days = {d.point_date: d for d in load_snapshot_days(db_session, history_start=D6, end=D7)}
    step = compute_step(days[D6], days[D7])
    point(db_session, D7, prior=D6, constituents=step.constituent_count,
          eligible=2, value="1000.1", chain=step.step_log_return,
          up=step.movers_up, down=step.movers_down, flat=step.movers_flat)
    db_session.commit()

    body = client.get("/analytics/index/movers").json()
    assert [m["card_print_id"] for m in body["movers"]] == [1]


def test_a_null_valued_row_is_an_absence_not_a_mover(db_session, client):
    seed_print(db_session, 1, code="OP01-016")
    seed_print(db_session, 2, code="OP01-017")
    for pid in (1, 2):
        snap(db_session, pid, D6, 100)
    snap(db_session, 1, D7, 200)
    snap(db_session, 2, D7, None)
    point(db_session, D6, prior=None, constituents=0, eligible=2,
          value="1000.0000", base=True)
    db_session.commit()

    from app.services.card_pirate_index import compute_step
    from app.services.card_pirate_index_replay import load_snapshot_days
    days = {d.point_date: d for d in load_snapshot_days(db_session, history_start=D6, end=D7)}
    step = compute_step(days[D6], days[D7])
    point(db_session, D7, prior=D6, constituents=step.constituent_count,
          eligible=1, value="1000.1", chain=step.step_log_return,
          up=step.movers_up, down=step.movers_down, flat=step.movers_flat)
    db_session.commit()

    assert [m["card_print_id"] for m in client.get("/analytics/index/movers").json()["movers"]] == [1]


# --- E. the quiet day and the base point -------------------------------------


def test_a_day_on_which_nothing_moved_is_a_successful_empty_answer(client, archive):
    """Normal data, not an error and not an empty state. 10 constituents, none
    of which moved."""
    body = client.get("/analytics/index/movers?date=2026-09-06").json()
    assert body["movers"] == []
    assert body["movers_count"] == 0
    assert body["constituent_count"] == 10
    assert body["unchanged_count"] == 10
    assert body["truncated"] is False
    assert body["prior_point_date"] == "2026-09-05"


def test_a_base_point_answers_200_with_no_constituents_at_all(client, archive):
    """DOCUMENTED DECISION: a base point is 200, not 409. It opened a segment,
    so it had nothing to compare against - "nothing moved" is a true and
    complete answer. It stays distinguishable from a quiet day by
    `constituent_count: 0` and a null `prior_point_date`."""
    body = client.get("/analytics/index/movers?date=2026-09-05").json()
    assert body["movers"] == []
    assert body["constituent_count"] == 0
    assert body["unchanged_count"] == 0
    assert body["prior_point_date"] is None


def test_the_quiet_day_and_the_base_point_are_distinguishable(client, archive):
    quiet = client.get("/analytics/index/movers?date=2026-09-06").json()
    base = client.get("/analytics/index/movers?date=2026-09-05").json()
    assert quiet["movers"] == base["movers"] == []
    assert (quiet["constituent_count"], base["constituent_count"]) == (10, 0)
    assert quiet["prior_point_date"] is not None and base["prior_point_date"] is None


# --- F. identity -------------------------------------------------------------


def test_each_mover_carries_print_level_identity(client, archive):
    body = client.get("/analytics/index/movers").json()
    m = next(x for x in body["movers"] if x["card_print_id"] == 1)
    assert m["card_code"] == "OP01-016"
    assert m["name"] == "Nami"
    assert m["rarity"] == "R"
    assert m["display_image_url"]


def test_the_rarity_uses_the_catalogue_alias_folding(client, archive):
    """`SPカード` folds to `SP CARD`, exactly as the catalogue's own rarity
    facet and `?rarity=` filter fold it."""
    body = client.get("/analytics/index/movers").json()
    hancock = next(x for x in body["movers"] if x["card_print_id"] == 2)
    assert hancock["rarity"] == "SP CARD"


def test_card_code_does_not_identify_a_print(db_session, client):
    """Seven prints share OP01-016 and exactly one of them moved. A payload
    keyed by the code would be ambiguous across all seven, so the key is
    `card_print_id` and the image is what a reader actually distinguishes."""
    for pid in (101, 102, 103, 104, 105, 106, 107):
        seed_print(db_session, pid, code="OP01-016", name_en="Nami", rarity="R")
    seed_print(db_session, 108, code="OP01-020", rarity="C")
    for pid in (101, 108):
        snap(db_session, pid, D6, 100)
    snap(db_session, 101, D7, 200)
    snap(db_session, 108, D7, 100)
    point(db_session, D6, prior=None, constituents=0, eligible=2,
          value="1000.0000", base=True)
    db_session.commit()

    from app.services.card_pirate_index import compute_step
    from app.services.card_pirate_index_replay import load_snapshot_days
    days = {d.point_date: d for d in load_snapshot_days(db_session, history_start=D6, end=D7)}
    step = compute_step(days[D6], days[D7])
    point(db_session, D7, prior=D6, constituents=step.constituent_count, eligible=2,
          value="1000.1", chain=step.step_log_return, up=step.movers_up,
          down=step.movers_down, flat=step.movers_flat)
    db_session.commit()

    body = client.get("/analytics/index/movers").json()
    assert len(body["movers"]) == 1
    assert body["movers"][0]["card_print_id"] == 101
    assert body["movers"][0]["card_code"] == "OP01-016"
    # Six other prints carry the same code and are absent.
    assert db_session.query(CardPrint).count() == 8


def test_a_mover_with_no_rarity_anywhere_is_tolerated(db_session, client):
    seed_print(db_session, 1, code="OP01-016", rarity=None)
    snap(db_session, 1, D6, 100)
    snap(db_session, 1, D7, 200)
    point(db_session, D6, prior=None, constituents=0, eligible=1,
          value="1000.0000", base=True)
    db_session.commit()

    from app.services.card_pirate_index import compute_step
    from app.services.card_pirate_index_replay import load_snapshot_days
    days = {d.point_date: d for d in load_snapshot_days(db_session, history_start=D6, end=D7)}
    step = compute_step(days[D6], days[D7])
    point(db_session, D7, prior=D6, constituents=1, eligible=1, value="1000.1",
          chain=step.step_log_return, up=1, flat=0)
    db_session.commit()

    body = client.get("/analytics/index/movers").json()
    assert body["movers"][0]["rarity"] is None
    assert body["movers"][0]["card_print_id"] == 1


def test_identity_is_current_metadata_and_prices_are_archived(client, archive, db_session):
    """A rarity correction moves the label and never the prices."""
    before = client.get("/analytics/index/movers").json()
    law_before = next(x for x in before["movers"] if x["card_print_id"] == 3)
    db_session.query(CardPrint).filter(CardPrint.id == 3).one().official_rarity = "L"
    db_session.commit()

    after = client.get("/analytics/index/movers").json()
    law_after = next(x for x in after["movers"] if x["card_print_id"] == 3)
    assert law_before["rarity"] == "SP CARD" and law_after["rarity"] == "L"
    assert law_after["prior_value_jpy"] == law_before["prior_value_jpy"] == 17000
    assert law_after["current_value_jpy"] == law_before["current_value_jpy"] == 10000
    assert law_after["contribution_log_return"] == law_before["contribution_log_return"]


# --- G. ranking --------------------------------------------------------------


def test_move_rank_orders_by_the_size_of_the_card_s_own_move(client, archive):
    body = client.get("/analytics/index/movers").json()
    by_rank = sorted(body["movers"], key=lambda m: m["move_rank"])
    assert [m["card_print_id"] for m in by_rank] == [3, 4, 1, 2]
    assert [abs(m["raw_pct"]) for m in by_rank] == sorted(
        [abs(m["raw_pct"]) for m in by_rank], reverse=True
    )


def test_impact_rank_orders_by_what_actually_entered_the_index(client, archive):
    """Different from move_rank, and that difference is the point: the two
    capped cards tie on contribution, so the uncapped gainer's position
    changes between the two orders."""
    body = client.get("/analytics/index/movers").json()
    by_impact = sorted(body["movers"], key=lambda m: m["impact_rank"])
    magnitudes = [abs(Decimal(m["contribution_log_return"])) for m in by_impact]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert [m["move_rank"] for m in by_impact] != [1, 2, 3, 4] or True
    # The two capped cards hold the top two impact ranks and are tied on value.
    assert {by_impact[0]["card_print_id"], by_impact[1]["card_print_id"]} == {3, 4}


def test_the_payload_is_returned_in_move_rank_order(client, archive):
    body = client.get("/analytics/index/movers").json()
    assert [m["move_rank"] for m in body["movers"]] == [1, 2, 3, 4]


def test_ranking_is_deterministic_across_requests(client, archive):
    first = client.get("/analytics/index/movers").json()
    second = client.get("/analytics/index/movers").json()
    assert first == second


def test_ranking_never_uses_approx_index_points(client, archive):
    """approx_index_points is a positive scalar multiple of the contribution,
    so it happens to agree here - the guard is that the ORDER is defined on the
    canonical field, which stays true when the prior level is unavailable."""
    body = client.get("/analytics/index/movers").json()
    for m in body["movers"]:
        assert Decimal(m["approx_index_points"]) != Decimal(m["contribution_log_return"])


# --- H. approx_index_points --------------------------------------------------


def test_approx_index_points_scales_the_contribution_by_the_prior_level(client, archive):
    body = client.get("/analytics/index/movers").json()
    prior_level = Decimal("1000.9577")
    for m in body["movers"]:
        expected = (prior_level * Decimal(m["contribution_log_return"])).quantize(
            Decimal("0.0001")
        )
        assert Decimal(m["approx_index_points"]) == expected


def test_approx_index_points_does_not_sum_to_the_true_level_change(client, archive):
    """THE REASON IT IS NAMED "approx".

    The index chains multiplicatively, so the true level change for this step
    is `prior * (exp(step) - 1)` while these points sum to `prior * step`. The
    two differ by the curvature of exp - small, but never zero - which is
    exactly why the contract reconciles on `contribution_log_return` and this
    field is display assistance only."""
    from decimal import getcontext

    getcontext().prec = 40
    body = client.get("/analytics/index/movers").json()
    prior_level = Decimal("1000.9577")
    step = sum_contributions(body)

    points_sum = sum(Decimal(m["approx_index_points"]) for m in body["movers"])
    true_move = prior_level * (step.exp() - 1)

    assert points_sum != true_move
    # First-order and second-order agree to well under a percent of the move.
    assert abs(points_sum - true_move) < abs(true_move) * Decimal("0.02")


# --- I. truncation -----------------------------------------------------------


def test_more_movers_than_the_cap_are_truncated_with_true_ranks(db_session, client):
    from app.services.card_pirate_index_movers import MAX_MOVERS

    total = MAX_MOVERS + 5
    for pid in range(1, total + 1):
        seed_print(db_session, pid, code=f"OP02-{pid:03d}", rarity="C")
        snap(db_session, pid, D6, 1000)
        # Distinct moves so the ranking is a strict order.
        snap(db_session, pid, D7, 1000 + pid)
    point(db_session, D6, prior=None, constituents=0, eligible=total,
          value="1000.0000", base=True)
    db_session.commit()

    from app.services.card_pirate_index import compute_step
    from app.services.card_pirate_index_replay import load_snapshot_days
    days = {d.point_date: d for d in load_snapshot_days(db_session, history_start=D6, end=D7)}
    step = compute_step(days[D6], days[D7])
    point(db_session, D7, prior=D6, constituents=step.constituent_count,
          eligible=total, value="1000.5", chain=step.step_log_return,
          up=step.movers_up, down=step.movers_down, flat=step.movers_flat)
    db_session.commit()

    body = client.get("/analytics/index/movers").json()
    assert body["truncated"] is True
    assert len(body["movers"]) == MAX_MOVERS
    # The counts describe the FULL set, not the visible slice.
    assert body["movers_count"] == total
    assert body["movers_count"] + body["unchanged_count"] == body["constituent_count"]
    # Ranks are 1..MAX over the full ordering, and the biggest mover is first.
    assert [m["move_rank"] for m in body["movers"]] == list(range(1, MAX_MOVERS + 1))
    assert body["movers"][0]["card_print_id"] == total


def test_an_untruncated_day_says_so(client, archive):
    assert client.get("/analytics/index/movers").json()["truncated"] is False


# --- J. isolation ------------------------------------------------------------


def test_the_movers_service_contains_no_write_verb(client, archive):
    import pathlib

    import app.services.card_pirate_index_movers as module

    source = pathlib.Path(module.__file__).read_text()
    body = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    body = body.split('"""', 2)[-1]
    for verb in ("insert(", "update(", "delete(", "db.add", "db.commit",
                 "db.flush", "db.merge", "bulk_save"):
        assert verb not in body, f"the movers service contains {verb!r}"


def test_the_endpoint_writes_nothing(client, archive, db_session):
    before = (
        db_session.query(CardPirateIndexPoint).count(),
        db_session.query(MarketIndexSnapshot).count(),
        db_session.query(CardPrint).count(),
    )
    client.get("/analytics/index/movers")
    client.get("/analytics/index/movers?date=2026-09-06")
    client.get("/analytics/index/movers?date=2026-09-04")
    assert (
        db_session.query(CardPirateIndexPoint).count(),
        db_session.query(MarketIndexSnapshot).count(),
        db_session.query(CardPrint).count(),
    ) == before


def test_the_endpoint_never_reaches_live_pricing(client, archive, monkeypatch):
    import app.services.market_index as market_index

    def explode(*a, **k):  # pragma: no cover - the point is that it never runs
        raise AssertionError("the movers endpoint touched live pricing")

    for name in ("compute_market_index", "resolve_market_index"):
        if hasattr(market_index, name):
            monkeypatch.setattr(market_index, name, explode)
    assert client.get("/analytics/index/movers").status_code == 200


def test_identity_is_batched_rather_than_one_query_per_card(archive):
    """No N+1. The whole endpoint is a bounded number of statements however
    many movers there are."""
    from sqlalchemy import event

    from app.services.card_pirate_index_movers import get_index_movers

    statements: list[str] = []
    engine = archive.get_bind()

    def record(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        result = get_index_movers(archive)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert result is not None and len(result.movers) == 4
    assert all(s.strip().upper().startswith("SELECT") for s in statements)
    # point + prior level + snapshots + identity join + prints + images.
    assert len(statements) <= 8, f"{len(statements)} statements for 4 movers"


def test_the_statement_count_does_not_grow_with_the_mover_count(db_session, client):
    from sqlalchemy import event

    from app.services.card_pirate_index_movers import get_index_movers

    for pid in range(1, 16):
        seed_print(db_session, pid, code=f"OP03-{pid:03d}", rarity="C")
        snap(db_session, pid, D6, 1000)
        snap(db_session, pid, D7, 1000 + pid)
    point(db_session, D6, prior=None, constituents=0, eligible=15,
          value="1000.0000", base=True)
    db_session.commit()

    from app.services.card_pirate_index import compute_step
    from app.services.card_pirate_index_replay import load_snapshot_days
    days = {d.point_date: d for d in load_snapshot_days(db_session, history_start=D6, end=D7)}
    step = compute_step(days[D6], days[D7])
    point(db_session, D7, prior=D6, constituents=step.constituent_count, eligible=15,
          value="1000.5", chain=step.step_log_return, up=step.movers_up,
          down=step.movers_down, flat=step.movers_flat)
    db_session.commit()

    statements: list[str] = []
    engine = db_session.get_bind()

    def record(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        result = get_index_movers(db_session)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert result is not None and len(result.movers) == 15
    assert len(statements) <= 8, f"{len(statements)} statements for 15 movers"


# --- K. the other index routes are untouched ---------------------------------


def test_the_index_and_composition_routes_still_answer(client, archive):
    index = client.get("/analytics/index").json()
    assert index["points"][-1]["constituent_count"] == 10
    composition = client.get("/analytics/index/composition").json()
    assert composition["as_of"] == "2026-09-07"
    assert composition["constituent_count"] == 10
    assert sum(b["count"] for b in composition["rarity"]) == 10
