"""Collector accounts v1 (S3): /me API, valuation rules, legacy copy.

SQLite suite. Real-Postgres proofs (migration, cascade, constraints) are in
test_accounts_postgres.py; the collector import graph in
test_accounts_import_graph.py.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.accounts import valuation
from app.accounts.config import FLAG
from app.accounts.migrate_legacy import run as run_legacy_copy
from app.accounts.models import (
    CollectionEntry,
    CollectionEntryEvent,
    UserPreferences,
    WatchlistEntry,
)
from app.models import (
    CollectionItem,
    FileJob,
    MarketIndexSnapshot,
    SavedView,
    SearchHistory,
    User,
    WishlistItem,
)
from app.services.print_market_index import get_market_index_for_prints
from app.settings import settings
from app.snapshot_market_index import build_snapshot_row
from tests._auth_helpers import make_bearer_token
from tests.accounts_helpers import (
    SNKR_FLOOR,
    YUYU_SELL,
    archive,
    archive_range,
    at,
    hold,
    receipt,
    snapshot_row,
)
from tests.test_prints import (
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_observation,
    make_print,
    make_release_product,
    make_source,
)

D = date(2026, 9, 10)
OTHER = {"Authorization": f"Bearer {make_bearer_token(google_sub='other-sub', email='other@example.com')}"}

ROUTES = [
    ("get", "/me/collection"),
    ("post", "/me/collection"),
    ("patch", "/me/collection/1"),
    ("delete", "/me/collection/1"),
    ("get", "/me/collection/value"),
    ("get", "/me/watchlist"),
    ("post", "/me/watchlist"),
    ("patch", "/me/watchlist/1"),
    ("delete", "/me/watchlist/1"),
    ("get", "/me/profile"),
    ("get", "/me/preferences"),
    ("put", "/me/preferences"),
    ("get", "/me/export"),
    ("get", "/me/export/collection.csv"),
    ("delete", "/me?confirm=delete%20my%20account"),
]


@pytest.fixture(autouse=True)
def _fresh_receipt_cache():
    valuation.clear_receipt_cache()
    yield
    valuation.clear_receipt_cache()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv(FLAG, "true")


@pytest.fixture
def prints(db_session):
    """Five verified, active prints across two releases, plus an inactive one."""
    make_release_product(db_session, "OP-02")
    made = {}
    for index, (code, release) in enumerate(
        [("OP01-001", "OP-01"), ("OP01-002", "OP-01"), ("OP02-003", "OP-02"),
         ("OP02-004", "OP-02"), ("OP01-005", "OP-01")]
    ):
        canonical = make_canonical(db_session, card_code=code)
        made[code] = make_print(
            db_session, canonical, artwork_key=f"art-{code}", release_product_code=release
        )
    canonical = make_canonical(db_session, card_code="OP01-099")
    made["inactive"] = make_print(db_session, canonical, artwork_key="art-inactive", is_active=False)
    return made


def ids(prints, *codes):
    return [prints[code].id for code in codes]


def other_user_id(db_session):
    return db_session.scalar(select(User.id).where(User.google_sub == "other-sub"))


# --------------------------------------------------------------------------
# Feature flag and authentication
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "false", "0", "off"])
@pytest.mark.parametrize("method, path", ROUTES)
def test_every_route_is_404_while_the_flag_is_off(client, db_session, monkeypatch, value, method, path):
    if value is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, value)
    users_before = db_session.scalar(select(func.count()).select_from(User))
    response = getattr(client, method)(path, **({"json": {}} if method in ("post", "put", "patch") else {}))
    assert response.status_code == 404
    # Checked before authentication: a valid token creates no user row.
    response = client.get("/me/collection", headers={"Authorization": f"Bearer {make_bearer_token(google_sub='new', email='new@example.com')}"})
    assert response.status_code == 404
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(User)) == users_before


@pytest.mark.parametrize("method, path", ROUTES)
def test_every_route_is_401_without_a_token_when_enabled(client, db_session, enabled, method, path):
    client.headers.pop("Authorization")
    response = getattr(client, method)(path, **({"json": {}} if method in ("post", "put", "patch") else {}))
    assert response.status_code == 401


def test_flag_off_by_default_in_config(monkeypatch):
    from app.accounts.config import accounts_enabled

    monkeypatch.delenv(FLAG, raising=False)
    assert accounts_enabled() is False


# --------------------------------------------------------------------------
# Collection CRUD, ledger, tenant isolation
# --------------------------------------------------------------------------


def test_add_update_remove_writes_the_holdings_ledger(client, db_session, enabled, prints):
    print_id = prints["OP01-001"].id
    created = client.post("/me/collection", json={"card_print_id": print_id, "quantity": 2, "paid_jpy_per_card": 500})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["resolution"] == "exact" and body["quantity"] == 2
    assert body["print"]["card_code"] == "OP01-001" and body["print"]["release_code"] == "OP-01"
    assert created.headers["cache-control"] == "private, no-store"

    entry_id = body["id"]
    assert client.patch(f"/me/collection/{entry_id}", json={"quantity": 5}).json()["quantity"] == 5
    assert client.patch(f"/me/collection/{entry_id}", json={"note": "binder 2"}).json()["quantity"] == 5
    assert client.delete(f"/me/collection/{entry_id}").status_code == 204

    events = db_session.execute(
        select(CollectionEntryEvent.quantity_before, CollectionEntryEvent.quantity_after).order_by(CollectionEntryEvent.id)
    ).all()
    assert [tuple(e) for e in events] == [(0, 2), (2, 5), (5, 0)]
    assert client.get("/me/collection").json()["entries"] == []


def test_add_refuses_duplicates_unknown_and_inactive_prints(client, db_session, enabled, prints):
    assert client.post("/me/collection", json={"card_print_id": prints["OP01-001"].id}).status_code == 201
    assert client.post("/me/collection", json={"card_print_id": prints["OP01-001"].id}).status_code == 409
    assert client.post("/me/collection", json={"card_print_id": 999999}).status_code == 404
    assert client.post("/me/collection", json={"card_print_id": prints["inactive"].id}).status_code == 404
    assert client.post("/me/collection", json={"card_print_id": prints["OP01-002"].id, "quantity": 0}).status_code == 422
    assert client.post("/me/collection", json={"card_print_id": prints["OP01-002"].id, "note": "x" * 501}).status_code == 422
    assert client.patch("/me/collection/1", json={"quantity": None}).status_code == 422
    assert client.post("/me/watchlist", json={"card_print_id": prints["OP01-001"].id, "target_jpy": 0}).status_code == 422


def test_user_a_never_sees_or_changes_user_b(client, db_session, enabled, prints):
    mine = client.post("/me/collection", json={"card_print_id": prints["OP01-001"].id, "quantity": 3}).json()
    watch = client.post("/me/watchlist", json={"card_print_id": prints["OP01-002"].id, "target_jpy": 900}).json()
    client.put("/me/preferences", json={"currency": "JPY", "collection_visibility": "private"})

    other_collection = client.get("/me/collection", headers=OTHER).json()
    assert other_collection["entries"] == [] and other_collection["summary"]["total_cards"] == 0
    assert client.get("/me/watchlist", headers=OTHER).json()["entries"] == []
    # Another user's ids behave exactly like missing ids.
    assert client.patch(f"/me/collection/{mine['id']}", json={"quantity": 9}, headers=OTHER).status_code == 404
    assert client.delete(f"/me/collection/{mine['id']}", headers=OTHER).status_code == 404
    assert client.patch(f"/me/watchlist/{watch['id']}", json={"target_jpy": 1}, headers=OTHER).status_code == 404
    assert client.delete(f"/me/watchlist/{watch['id']}", headers=OTHER).status_code == 404
    export = client.get("/me/export", headers=OTHER).json()
    assert export["collection"] == export["watchlist"] == export["collection_history"] == []
    assert export["profile"]["email"] == "other@example.com"
    value = client.get("/me/collection/value", headers=OTHER).json()
    assert value["summary"]["total_entries"] == 0 and value["by_release"] == []

    # The same print can be held by both users independently.
    theirs = client.post("/me/collection", json={"card_print_id": prints["OP01-001"].id, "quantity": 1}, headers=OTHER)
    assert theirs.status_code == 201
    assert client.get("/me/collection").json()["entries"][0]["quantity"] == 3
    other_id = other_user_id(db_session)
    assert db_session.scalar(
        select(func.count()).select_from(CollectionEntryEvent).where(CollectionEntryEvent.user_id == other_id)
    ) == 1


# --------------------------------------------------------------------------
# Valuation: C1 and C2
# --------------------------------------------------------------------------


def test_coverage_math_and_unpriced_is_never_zero(client, db_session, enabled, prints):
    priced, unpriced, no_snapshot = ids(prints, "OP01-001", "OP01-002", "OP02-003")
    archive(db_session, D, {priced: 1250, unpriced: None})
    hold(db_session, 1, priced, 2, at(D))
    hold(db_session, 1, unpriced, 3, at(D))
    hold(db_session, 1, no_snapshot, 4, at(D))
    db_session.add(CollectionEntry(user_id=1, card_print_id=None, quantity=1, resolution="unresolved", legacy_card_id=77))
    db_session.commit()

    body = client.get("/me/collection").json()
    assert body["as_of"] == D.isoformat() and body["currency"] == "JPY"
    assert body["summary"] == {
        "value_jpy": 2500,
        "priced_cards": 2,
        "total_cards": 10,
        "priced_entries": 1,
        "total_entries": 4,
        "unresolved_entries": 1,
        "coverage_pct": "20.00",
    }
    by_print = {e["card_print_id"]: e for e in body["entries"]}
    assert by_print[priced]["value_jpy"] == 2500 and by_print[priced]["value_per_card_jpy"] == 1250
    for print_id in (unpriced, no_snapshot):
        assert by_print[print_id]["value_status"] == "no_price"
        assert by_print[print_id]["value_jpy"] is None and by_print[print_id]["value_per_card_jpy"] is None
    unresolved = by_print[None]
    assert unresolved["value_status"] == "unresolved" and unresolved["value_jpy"] is None
    assert unresolved["print"] is None and unresolved["legacy_card_id"] == 77


def test_no_priced_entries_means_null_value_not_zero(client, db_session, enabled, prints):
    archive(db_session, D, {prints["OP01-001"].id: None})
    hold(db_session, 1, prints["OP01-001"].id, 2, at(D))
    summary = client.get("/me/collection").json()["summary"]
    assert summary["value_jpy"] is None and summary["coverage_pct"] == "0.00"
    empty = client.get("/me/collection", headers=OTHER).json()
    assert empty["summary"]["value_jpy"] is None and empty["summary"]["coverage_pct"] is None


def test_unresolved_rows_are_never_priced_even_when_their_legacy_card_has_a_price(client, db_session, enabled, prints):
    legacy = make_legacy_card(db_session, card_code="OP01-001")
    make_mapping(db_session, legacy, make_source(db_session, "yuyutei"), prints["OP01-001"])
    archive(db_session, D, {prints["OP01-001"].id: 3000})
    db_session.add(CollectionEntry(user_id=1, card_print_id=None, quantity=2, resolution="unresolved", legacy_card_id=legacy.id))
    db_session.add(WatchlistEntry(user_id=1, card_print_id=None, resolution="unresolved", legacy_card_id=legacy.id))
    db_session.commit()
    body = client.get("/me/collection").json()
    assert body["summary"]["value_jpy"] is None and body["summary"]["priced_cards"] == 0
    assert body["entries"][0]["value_status"] == "unresolved"
    watch = client.get("/me/watchlist").json()["entries"][0]
    assert watch["value_status"] == "unresolved" and watch["value_jpy"] is None


def test_value_uses_only_the_latest_verified_receipted_day(client, db_session, enabled, prints):
    print_id = prints["OP01-001"].id
    archive(db_session, D - timedelta(days=1), {print_id: 1000})
    archive(db_session, D, {print_id: 1100})
    # A newer archived day without a receipt is not a completed market day.
    archive(db_session, D + timedelta(days=1), {print_id: 9999}, receipted=False)
    hold(db_session, 1, print_id, 1, at(D))
    body = client.get("/me/collection").json()
    assert body["as_of"] == D.isoformat() and body["summary"]["value_jpy"] == 1100


def test_a_receipt_that_does_not_verify_is_not_used(client, db_session, enabled, prints):
    print_id = prints["OP01-001"].id
    archive(db_session, D - timedelta(days=1), {print_id: 1000})
    archive(db_session, D, {print_id: 1100})
    # Tamper with the newest day after its receipt: its digest no longer matches.
    row = db_session.scalar(select(MarketIndexSnapshot).where(MarketIndexSnapshot.snapshot_date == D))
    row.index_value_jpy = 5000
    db_session.commit()
    hold(db_session, 1, print_id, 1, at(D))
    body = client.get("/me/collection").json()
    assert body["as_of"] == (D - timedelta(days=1)).isoformat()
    assert body["summary"]["value_jpy"] == 1000


def test_no_receipt_at_all_means_no_prices_yet(client, db_session, enabled, prints):
    archive(db_session, D, {prints["OP01-001"].id: 1000}, receipted=False)
    hold(db_session, 1, prints["OP01-001"].id, 1, at(D))
    body = client.get("/me/collection").json()
    assert body["as_of"] is None and body["summary"]["value_jpy"] is None
    value = client.get("/me/collection/value").json()
    assert value["movers"]["available"] is False and value["movers"]["reason"] == "no_prices_yet"
    assert value["movers"]["change_pct"] is None and value["movers"]["change_jpy"] is None


def test_inactive_or_unverified_print_is_unpriced_like_market_value(client, db_session, enabled, prints):
    print_id = prints["OP01-001"].id
    archive(db_session, D, {print_id: 1000})
    hold(db_session, 1, print_id, 1, at(D))
    prints["OP01-001"].is_active = False
    db_session.commit()
    assert client.get("/me/collection").json()["summary"]["value_jpy"] is None


@pytest.fixture
def sale_print(db_session):
    """A print whose Yuyu-Tei evidence is a SALE price (80) next to a SNKRDUNK floor."""
    canonical = make_canonical(db_session, card_code="OP04-099")
    legacy = make_legacy_card(db_session, card_code="OP04-099")
    printing = make_print(db_session, canonical, artwork_key="art-sale")
    yuyu = make_source(db_session, "yuyutei")
    snkr = make_source(db_session, "snkrdunk")
    now = datetime.now(timezone.utc)
    make_observation(db_session, legacy, yuyu, make_mapping(db_session, legacy, yuyu, printing), printing,
                     price_jpy=80, promotion_state="sale", observed_at=now)
    make_observation(db_session, legacy, snkr, make_mapping(db_session, legacy, snkr, printing), printing,
                     price_type="floor", price_jpy=1500, observed_at=now)
    sale_only_canonical = make_canonical(db_session, card_code="OP04-100")
    sale_only_legacy = make_legacy_card(db_session, card_code="OP04-100")
    sale_only = make_print(db_session, sale_only_canonical, artwork_key="art-sale-only")
    make_observation(db_session, sale_only_legacy, yuyu, make_mapping(db_session, sale_only_legacy, yuyu, sale_only),
                     sale_only, price_jpy=120, promotion_state="sale", observed_at=now)
    return printing, sale_only


def test_yuyu_sale_prices_never_value_a_collection(client, db_session, enabled, sale_print):
    printing, sale_only = sale_print
    # The real Market Index snapshot path, then a real atomic receipt.
    computed = get_market_index_for_prints(db_session, [printing.id, sale_only.id])
    rows = [build_snapshot_row(computed[p.id]) for p in (printing, sale_only)]
    for row in rows:
        db_session.add(MarketIndexSnapshot(**row))
    db_session.commit()
    day = rows[0]["snapshot_date"]
    receipt(db_session, day)
    hold(db_session, 1, printing.id, 2, datetime.now(timezone.utc) - timedelta(minutes=1))
    hold(db_session, 1, sale_only.id, 1, datetime.now(timezone.utc) - timedelta(minutes=1))

    body = client.get("/me/collection").json()
    by_print = {e["card_print_id"]: e for e in body["entries"]}
    assert by_print[printing.id]["value_per_card_jpy"] == 1500  # SNKRDUNK floor, not the 80 sale
    assert by_print[sale_only.id]["value_status"] == "no_price"
    assert body["summary"]["value_jpy"] == 3000
    assert "80" not in str(by_print[printing.id]["value_jpy"])
    watch = client.post("/me/watchlist", json={"card_print_id": sale_only.id, "target_jpy": 100}).json()
    assert watch["value_jpy"] is None and watch["target_gap_jpy"] is None


def test_struck_or_earlier_prices_are_never_substituted(client, db_session, enabled, prints):
    print_id = prints["OP01-001"].id
    archive(db_session, D - timedelta(days=1), {print_id: 2000})
    # The next completed day has no usable value (e.g. a sale-only Yuyu page).
    archive(db_session, D, {print_id: None}, contributors=(YUYU_SELL,))
    hold(db_session, 1, print_id, 1, at(D - timedelta(days=1)))
    body = client.get("/me/collection").json()
    assert body["as_of"] == D.isoformat()
    assert body["entries"][0]["value_status"] == "no_price"
    assert body["summary"]["value_jpy"] is None  # never yesterday's 2000, never 0


# --------------------------------------------------------------------------
# Valuation: C4 movers, by release, what you paid
# --------------------------------------------------------------------------


def _window_world(db_session, prints, *, skip=()):
    a, b, c = ids(prints, "OP01-001", "OP01-002", "OP02-003")
    p = D - timedelta(days=7)

    def values(day):
        late = day == D
        return {a: 150 if late else 100, b: 10, c: 1600 if late else 2000}

    archive_range(db_session, p, D, values, skip=skip)
    hold(db_session, 1, a, 1, at(p - timedelta(days=1)))
    hold(db_session, 1, c, 2, at(p - timedelta(days=1)))
    hold(db_session, 1, a, 3, at(p + timedelta(days=2)), before=1)  # bought 2 more mid-window
    hold(db_session, 1, b, 1, at(p + timedelta(days=3)))  # new card mid-window
    return a, b, c, p


def test_movers_count_only_units_held_at_both_ends(client, db_session, enabled, prints):
    a, b, c, p = _window_world(db_session, prints)
    value = client.get("/me/collection/value?window=7d").json()
    movers = value["movers"]
    assert movers["available"] is True, movers
    assert movers["from_date"] == p.isoformat() and movers["to_date"] == D.isoformat()
    # a: 1 unit comparable (the 2 bought later are entrants), c: 2 units, b: entrant.
    assert movers["comparable_cards"] == 3
    # Comparable share of priced value: 4100/4100 at the start, 3350/3660 at the end.
    assert movers["prior_comparable_jpy"] == 1 * 100 + 2 * 2000 == 4100
    assert movers["current_comparable_jpy"] == 1 * 150 + 2 * 1600 == 3350
    assert movers["change_jpy"] == -750 and movers["change_pct"] == "-18.29"
    assert movers["exclusions"] == {"entrant": 1}
    assert [m["card_print_id"] for m in movers["up"]] == [a]
    assert [m["card_print_id"] for m in movers["down"]] == [c]
    up, down = movers["up"][0], movers["down"][0]
    assert (up["units"], up["delta_jpy"], up["change_pct"], up["contribution_pct_points"]) == (1, 50, "50.00", "1.22")
    assert (down["units"], down["delta_jpy"], down["change_pct"], down["contribution_pct_points"]) == (2, -800, "-20.00", "-19.51")
    # Reconciled: the per-card impacts sum to Q - P.
    assert up["delta_jpy"] + down["delta_jpy"] == movers["change_jpy"]
    # Every comparable version, not only the top movers; the entrant b has none.
    cards = {card["card_print_id"]: card for card in value["cards"]}
    assert set(cards) == {a, c}
    assert cards[a] == up and cards[c] == down


def test_a_missing_day_makes_the_window_unavailable_never_zero(client, db_session, enabled, prints):
    gap = D - timedelta(days=3)
    _window_world(db_session, prints, skip={gap})
    movers = client.get("/me/collection/value?window=7d").json()["movers"]
    assert movers["available"] is False and movers["reason"] == "prices_missing"
    assert movers["missing_dates"] == [gap.isoformat()]
    assert movers["change_pct"] is None and movers["change_jpy"] is None
    assert movers["up"] == movers["down"] == []


def test_unavailable_window_has_no_per_card_change(client, db_session, enabled, prints):
    _window_world(db_session, prints, skip={D - timedelta(days=3)})
    assert client.get("/me/collection/value?window=7d").json()["cards"] == []
    assert client.get("/me/collection/value?window=30d").json()["cards"] == []


def test_not_enough_history_for_thirty_days(client, db_session, enabled, prints):
    _window_world(db_session, prints)
    movers = client.get("/me/collection/value?window=30d").json()["movers"]
    assert movers["available"] is False and movers["reason"] == "not_enough_price_history"
    assert client.get("/me/collection/value?window=90d").status_code == 422


def test_comparable_value_guard_eighty_percent(client, db_session, enabled, prints):
    a, b = ids(prints, "OP01-001", "OP01-002")
    p = D - timedelta(days=7)
    # b is priced at both ends but its contributor set changes on the last
    # day, so it is not comparable. It dominates priced value, leaving the
    # comparable share below 80% at both ends.
    archive_range(db_session, p, D - timedelta(days=1), lambda day: {a: 100, b: 1000})
    db_session.add(snapshot_row(a, D, 110))
    db_session.add(snapshot_row(b, D, 1000, contributors=(YUYU_SELL,)))
    db_session.commit()
    receipt(db_session, D)
    hold(db_session, 1, a, 1, at(p - timedelta(days=1)))
    hold(db_session, 1, b, 1, at(p - timedelta(days=1)))
    movers = client.get("/me/collection/value").json()["movers"]
    assert movers["available"] is False
    assert movers["reason"] == "insufficient_comparable_value_coverage"
    assert movers["exclusions"] == {"contributor_set_changed": 1}
    assert movers["change_pct"] is None and movers["up"] == movers["down"] == []


def test_by_release_uses_the_authoritative_release_not_the_code(client, db_session, enabled, prints):
    canonical = make_canonical(db_session, card_code="OP01-777")
    # Code says OP01, product says OP-02: the product wins.
    misleading = make_print(db_session, canonical, artwork_key="art-777", release_product_code="OP-02")
    a, c = ids(prints, "OP01-001", "OP02-003")
    archive(db_session, D, {a: 600, c: 300, misleading.id: 100})
    for print_id in (a, c, misleading.id):
        hold(db_session, 1, print_id, 1, at(D))
    releases = client.get("/me/collection/value").json()["by_release"]
    assert [(r["release_code"], r["value_jpy"], r["total_cards"], r["share_pct"]) for r in releases] == [
        ("OP-01", 600, 1, "60.00"),
        ("OP-02", 400, 2, "40.00"),
    ]
    assert releases[0]["release_name"] == "Booster OP-01"
    assert releases[0]["change"]["available"] is False


def test_by_release_window_change_uses_the_release_subset(client, db_session, enabled, prints):
    a, b, c, _ = _window_world(db_session, prints)
    releases = {r["release_code"]: r for r in client.get("/me/collection/value").json()["by_release"]}
    # OP-01 holds a (1 comparable unit of 3) and the new b: 150 of 460 is under 80%.
    op01 = releases["OP-01"]["change"]
    assert op01["available"] is False and op01["reason"] == "insufficient_comparable_value_coverage"
    assert op01["change_pct"] is None
    op02 = releases["OP-02"]["change"]
    assert op02["available"] is True
    assert (op02["prior_comparable_jpy"], op02["current_comparable_jpy"], op02["change_pct"]) == (4000, 3200, "-20.00")


def test_what_you_paid_only_over_entries_with_both_prices(client, db_session, enabled, prints):
    a, b, c = ids(prints, "OP01-001", "OP01-002", "OP02-003")
    archive(db_session, D, {a: 1200, b: None})
    hold(db_session, 1, a, 2, at(D), paid_jpy_per_card=1000)
    hold(db_session, 1, b, 3, at(D), paid_jpy_per_card=50)  # paid, but no price today
    hold(db_session, 1, c, 4, at(D))  # no price paid
    paid = client.get("/me/collection/value").json()["paid"]
    assert paid == {
        "cards_with_paid": 5,
        "cards_compared": 2,
        "total_cards": 9,
        "paid_jpy": 2000,
        "priced_today_jpy": 2400,
        "change_pct": "20.00",
    }
    empty = client.get("/me/collection/value", headers=OTHER).json()["paid"]
    assert empty["paid_jpy"] is None and empty["change_pct"] is None


def test_endpoint_step_is_pure_and_reconciles():
    from app.accounts.valuation import ArchivedValue, endpoint_step
    from app.services.market_value import MarketValueObservation

    def v(print_id, value, contributors=(SNKR_FLOOR,)):
        return ArchivedValue(MarketValueObservation(print_id, value, 3, 3, frozenset(contributors), 1))

    step = endpoint_step(
        prior_date=D - timedelta(days=7),
        current_date=D,
        prior_held={1: 1, 2: 1, 3: 1},
        current_held={1: 1, 2: 1, 4: 5},
        prior_values={1: v(1, 100), 2: v(2, 300), 3: v(3, 10)},
        current_values={1: v(1, 140), 2: v(2, 270), 4: v(4, 10)},
    )
    assert step.available
    assert step.exclusions == (("entrant", 1), ("leaver", 1))
    assert sum(m.delta_jpy for m in step.movers) == step.change_jpy == (140 + 270) - (100 + 300)
    assert [m.card_print_id for m in step.movers] == [1, 2]  # ranked by absolute yen


# --------------------------------------------------------------------------
# Watchlist, preferences, export, deletion
# --------------------------------------------------------------------------


def test_watchlist_value_and_target_gap(client, db_session, enabled, prints):
    a, b = ids(prints, "OP01-001", "OP01-002")
    archive(db_session, D, {a: 2200})
    created = client.post("/me/watchlist", json={"card_print_id": a, "target_jpy": 1000})
    assert created.status_code == 201
    assert client.post("/me/watchlist", json={"card_print_id": a}).status_code == 409
    client.post("/me/watchlist", json={"card_print_id": b})
    body = client.get("/me/watchlist").json()
    assert body["as_of"] == D.isoformat()
    rows = {e["card_print_id"]: e for e in body["entries"]}
    assert rows[a]["value_jpy"] == 2200 and rows[a]["target_gap_jpy"] == 1200
    assert rows[b]["value_status"] == "no_price" and rows[b]["target_gap_jpy"] is None
    updated = client.patch(f"/me/watchlist/{rows[a]['id']}", json={"target_jpy": None}).json()
    assert updated["target_jpy"] is None
    assert client.delete(f"/me/watchlist/{rows[b]['id']}").status_code == 204
    assert len(client.get("/me/watchlist").json()["entries"]) == 1


def test_watchlist_freshness_and_7d_change(client, db_session, enabled, prints):
    a, b, c = ids(prints, "OP01-001", "OP01-002", "OP02-003")
    checked = datetime(2026, 9, 10, 6, 30, tzinfo=timezone.utc)
    archive_range(db_session, D - timedelta(days=7), D - timedelta(days=1), lambda day: {a: 1000, b: None, c: 500})
    db_session.add_all([
        snapshot_row(a, D, 1100, checked_at=checked),
        snapshot_row(b, D, 900, checked_at=checked),
        snapshot_row(c, D, 500, contributors=(SNKR_FLOOR, YUYU_SELL)),
    ])
    db_session.commit()
    receipt(db_session, D)
    for print_id in (a, b, c):
        client.post("/me/watchlist", json={"card_print_id": print_id})
    body = client.get("/me/watchlist").json()
    assert body["change_7d_from"] == (D - timedelta(days=7)).isoformat()
    assert body["change_7d_missing_dates"] == []
    rows = {e["card_print_id"]: e for e in body["entries"]}
    assert rows[a]["change_7d_pct"] == "10.00" and rows[a]["change_7d_reason"] is None
    assert rows[a]["checked_at"].startswith("2026-09-10T06:30")
    # Not priced a week ago: no change, a reason, never 0%.
    assert rows[b]["change_7d_pct"] is None and rows[b]["change_7d_reason"] == "entrant"
    # Price sources changed inside the window: not comparable.
    assert rows[c]["change_7d_pct"] is None and rows[c]["change_7d_reason"] == "contributor_set_changed"
    assert rows[c]["checked_at"] is None


def test_watchlist_7d_change_unavailable_without_a_full_week(client, db_session, enabled, prints):
    a = prints["OP01-001"].id
    client.post("/me/watchlist", json={"card_print_id": a})
    body = client.get("/me/watchlist").json()
    assert body["change_7d_from"] is None
    assert body["entries"][0]["change_7d_reason"] == "no_prices_yet"

    archive(db_session, D - timedelta(days=1), {a: 1000})
    archive(db_session, D, {a: 1000})
    entry = client.get("/me/watchlist").json()["entries"][0]
    assert entry["change_7d_pct"] is None and entry["change_7d_reason"] == "not_enough_price_history"

    archive_range(db_session, D - timedelta(days=7), D - timedelta(days=2), lambda day: {a: 1000}, skip=(D - timedelta(days=4),))
    body = client.get("/me/watchlist").json()
    assert body["entries"][0]["change_7d_reason"] == "prices_missing"
    assert body["change_7d_missing_dates"] == [(D - timedelta(days=4)).isoformat()]


def test_preferences_default_and_only_jpy_private(client, db_session, enabled):
    assert client.get("/me/preferences").json() == {"currency": "JPY", "collection_visibility": "private"}
    assert db_session.get(UserPreferences, 1) is None  # no row means defaults
    assert client.put("/me/preferences", json={"currency": "USD"}).status_code == 422
    assert client.put("/me/preferences", json={"collection_visibility": "public"}).status_code == 422
    assert client.put("/me/preferences", json={"currency": "JPY"}).json()["currency"] == "JPY"
    assert db_session.get(UserPreferences, 1) is not None


def test_export_json_and_csv(client, db_session, enabled, prints):
    client.post("/me/collection", json={"card_print_id": prints["OP01-001"].id, "quantity": 2, "note": "a, \"b\""})
    client.post("/me/watchlist", json={"card_print_id": prints["OP01-002"].id, "target_jpy": 700})
    response = client.get("/me/export")
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["format"] == "card-pirate-account-export-v1" and data["currency"] == "JPY"
    assert data["profile"]["email"] == "test@example.com"
    assert data["preferences"] == {"currency": "JPY", "collection_visibility": "private"}
    assert [r["quantity"] for r in data["collection"]] == [2]
    assert [(r["quantity_before"], r["quantity_after"]) for r in data["collection_history"]] == [(0, 2)]
    assert [r["target_jpy"] for r in data["watchlist"]] == [700]
    csv_text = client.get("/me/export/collection.csv").text
    assert csv_text.splitlines()[0].startswith("id,card_print_id,resolution,quantity")
    assert '"a, ""b"""' in csv_text
    assert "700" in client.get("/me/export/watchlist.csv").text
    assert client.get("/me/export/users.csv").status_code == 422


def test_export_covers_everything_delete_removes(client, db_session, enabled, prints):
    # Security audit 2026-10-16, F5: delete_account also removes saved views,
    # search history and file jobs, so the export must carry them too.
    client.get("/me/preferences", headers=OTHER)
    other = other_user_id(db_session)
    db_session.add_all([
        SavedView(name="mine", route_path="/cards", view_type="cards", user_id=1, filters_json={"q": "luffy"}),
        SavedView(name="theirs", route_path="/cards", view_type="cards", user_id=other),
        SearchHistory(query="zoro", result_count=3, user_id=1),
        SearchHistory(query="nami", user_id=other),
        FileJob(user_id=1, job_type="collection_export", status="success",
                output_file_path="output/mine.csv", output_filename="collection.csv"),
        FileJob(user_id=None, job_type="backup_export", status="success"),
    ])
    db_session.commit()

    data = client.get("/me/export").json()

    assert [(v["name"], v["filters_json"]) for v in data["saved_views"]] == [("mine", {"q": "luffy"})]
    assert [(h["query"], h["result_count"]) for h in data["search_history"]] == [("zoro", 3)]
    assert [(j["job_type"], j["output_filename"]) for j in data["file_jobs"]] == [("collection_export", "collection.csv")]
    # Storage paths are internal and never leave the server.
    assert "output/mine.csv" not in client.get("/me/export").text


@pytest.mark.parametrize("bad", ["a\x00b", "bell\x07", "esc\x1b[31m", "\x0b"])
def test_notes_refuse_control_characters(client, enabled, prints, bad):
    # Security audit 2026-10-16, F11: NUL made Postgres raise (a 500).
    card = prints["OP01-001"].id
    assert client.post("/me/collection", json={"card_print_id": card, "note": bad}).status_code == 422
    assert client.post("/me/watchlist", json={"card_print_id": card, "note": bad}).status_code == 422
    entry = client.post("/me/collection", json={"card_print_id": card}).json()["id"]
    watch = client.post("/me/watchlist", json={"card_print_id": card}).json()["id"]
    assert client.patch(f"/me/collection/{entry}", json={"note": bad}).status_code == 422
    assert client.patch(f"/me/watchlist/{watch}", json={"note": bad}).status_code == 422


def test_notes_keep_tabs_line_breaks_and_unicode(client, enabled, prints):
    note = "first line\r\nsecond\tcolumn ルフィ ✓"
    created = client.post("/me/collection", json={"card_print_id": prints["OP01-001"].id, "note": note})
    assert created.status_code == 201 and created.json()["note"] == note
    assert client.patch(f"/me/collection/{created.json()['id']}", json={"note": None}).json()["note"] is None


def test_acquired_on_is_bounded(client, enabled, prints):
    card = prints["OP01-001"].id
    today = datetime.now(timezone.utc).date()
    for bad in ("1899-12-31", (today + timedelta(days=2)).isoformat(), "9999-12-31"):
        assert client.post("/me/collection", json={"card_print_id": card, "acquired_on": bad}).status_code == 422
    created = client.post("/me/collection", json={"card_print_id": card, "acquired_on": "2022-07-22"})
    assert created.status_code == 201 and created.json()["acquired_on"] == "2022-07-22"
    entry = created.json()["id"]
    for good in ("1900-01-01", today.isoformat(), (today + timedelta(days=1)).isoformat()):
        response = client.patch(f"/me/collection/{entry}", json={"acquired_on": good})
        assert response.status_code == 200 and response.json()["acquired_on"] == good
    assert client.patch(f"/me/collection/{entry}", json={"acquired_on": "0001-01-01"}).status_code == 422
    assert client.patch(f"/me/collection/{entry}", json={"acquired_on": None}).status_code == 200


def test_unchanged_out_of_range_date_does_not_block_an_edit(client, db_session, enabled, prints):
    # A date copied from the legacy tables (migrate_legacy) was never range
    # checked, and the website re-sends the stored date with every edit.
    entry_id = client.post("/me/collection", json={"card_print_id": prints["OP01-001"].id}).json()["id"]
    entry = db_session.get(CollectionEntry, entry_id)
    entry.acquired_on = date(1850, 5, 1)
    db_session.commit()

    response = client.patch(f"/me/collection/{entry_id}", json={"quantity": 3, "acquired_on": "1850-05-01"})
    assert response.status_code == 200 and response.json()["quantity"] == 3
    assert client.patch(f"/me/collection/{entry_id}", json={"acquired_on": "1850-05-02"}).status_code == 422


def test_delete_account_requires_confirmation_and_removes_everything(client, db_session, enabled, prints):
    client.post("/me/collection", json={"card_print_id": prints["OP01-001"].id})
    client.post("/me/watchlist", json={"card_print_id": prints["OP01-002"].id})
    client.put("/me/preferences", json={"currency": "JPY"})
    client.post("/me/collection", json={"card_print_id": prints["OP01-001"].id}, headers=OTHER)
    other = other_user_id(db_session)
    db_session.add_all([
        SavedView(name="mine", route_path="/cards", view_type="cards", user_id=1),
        SavedView(name="theirs", route_path="/cards", view_type="cards", user_id=other),
        SearchHistory(query="luffy", user_id=1),
        FileJob(user_id=1, job_type="collection_export", status="success", output_file_path="output/mine.csv"),
        FileJob(user_id=other, job_type="wishlist_export", status="success", output_file_path="output/theirs.csv"),
        FileJob(user_id=None, job_type="backup_export", status="success"),
    ])
    db_session.commit()
    storage = Path(settings.FILE_JOB_STORAGE_DIR) / "output"
    storage.mkdir(parents=True)
    (storage / "mine.csv").write_text("my collection")
    (storage / "theirs.csv").write_text("their wishlist")

    assert client.delete("/me").status_code == 422
    assert client.delete("/me?confirm=yes").status_code == 422
    assert db_session.get(User, 1) is not None
    assert client.delete("/me?confirm=delete%20my%20account").status_code == 204

    db_session.expire_all()
    assert db_session.get(User, 1) is None
    for model in (CollectionEntry, CollectionEntryEvent, WatchlistEntry, UserPreferences, SavedView, SearchHistory, FileJob):
        assert db_session.scalar(select(func.count()).select_from(model).where(model.user_id == 1)) == 0
    # The other user is untouched.
    assert db_session.scalar(select(func.count()).select_from(CollectionEntry).where(CollectionEntry.user_id == other)) == 1
    assert db_session.scalar(select(func.count()).select_from(SavedView).where(SavedView.user_id == other)) == 1
    assert db_session.scalar(select(func.count()).select_from(FileJob).where(FileJob.user_id == other)) == 1
    assert db_session.scalar(select(func.count()).select_from(FileJob).where(FileJob.user_id.is_(None))) == 1
    assert not (storage / "mine.csv").exists()
    assert (storage / "theirs.csv").read_text() == "their wishlist"


# --------------------------------------------------------------------------
# Legacy copy (B2)
# --------------------------------------------------------------------------


@pytest.fixture
def legacy_world(db_session, prints):
    yuyu = make_source(db_session, "yuyutei")
    snkr = make_source(db_session, "snkrdunk")
    exact = make_legacy_card(db_session, card_code="OP01-001", set_code="A")
    make_mapping(db_session, exact, yuyu, prints["OP01-001"])
    make_mapping(db_session, exact, snkr, prints["OP01-001"], source_card_id="s-1")
    two = make_legacy_card(db_session, card_code="OP01-002", set_code="B")
    make_mapping(db_session, two, yuyu, prints["OP01-002"])
    make_mapping(db_session, two, snkr, prints["OP02-003"], source_card_id="s-2")
    none = make_legacy_card(db_session, card_code="OP02-004", set_code="C")
    # Mappings that must never resolve: inactive, needs_review, inactive print.
    stale = make_legacy_card(db_session, card_code="OP01-005", set_code="D")
    make_mapping(db_session, stale, yuyu, prints["OP01-005"], is_active=False, source_card_id="x-1")
    make_mapping(db_session, stale, snkr, prints["OP01-005"], review_status="needs_review", source_card_id="x-2")
    make_mapping(db_session, stale, make_source(db_session, "other"), prints["inactive"], source_card_id="x-3")
    # Same legacy card reached by the same print twice is still exactly one print.
    for card in (exact, two, none, stale):
        db_session.add(CollectionItem(user_id=1, card_id=card.id, quantity=2, purchase_price_jpy=300, notes="n"))
    db_session.add(CollectionItem(user_id=1, card_id=exact.id, quantity=1))  # same print again
    db_session.add(WishlistItem(user_id=1, card_id=exact.id, target_buy_price_jpy=900))
    db_session.add(WishlistItem(user_id=1, card_id=none.id))
    db_session.commit()
    return exact, two, none, stale


def test_legacy_dry_run_reports_and_writes_nothing(db_session, legacy_world):
    report = run_legacy_copy(db_session, write_rows=False)
    assert report["mode"] == "dry-run"
    summary = report["summary"]
    assert summary["collection_items"] == {
        "rows": 5,
        "exact": 2,
        "unresolved": 3,
        "actions": {"copy_exact": 1, "copy_unresolved": 3, "skip_duplicate_print": 1},
    }
    assert summary["wishlist_items"]["exact"] == 1 and summary["wishlist_items"]["unresolved"] == 1
    assert summary["legacy_cards"] == {"total": 4, "exact": 1, "multiple_prints": 1, "no_print": 2}
    assert db_session.scalar(select(func.count()).select_from(CollectionEntry)) == 0
    assert db_session.scalar(select(func.count()).select_from(WatchlistEntry)) == 0


def test_legacy_write_copies_exact_and_unresolved_and_is_idempotent(db_session, legacy_world, prints):
    exact, two, none, stale = legacy_world
    first = run_legacy_copy(db_session, write_rows=True)
    assert first["written"] == {"collection_entries": 4, "watchlist_entries": 2}
    entries = {e.legacy_card_id: e for e in db_session.scalars(select(CollectionEntry))}
    assert entries[exact.id].card_print_id == prints["OP01-001"].id and entries[exact.id].resolution == "exact"
    assert entries[exact.id].paid_jpy_per_card == 300
    for card in (two, none, stale):
        assert entries[card.id].card_print_id is None and entries[card.id].resolution == "unresolved"
    events = db_session.execute(select(CollectionEntryEvent.card_print_id, CollectionEntryEvent.quantity_after)).all()
    assert [tuple(e) for e in events] == [(prints["OP01-001"].id, 2)]
    watch = {w.legacy_card_id: w for w in db_session.scalars(select(WatchlistEntry))}
    assert watch[exact.id].target_jpy == 900 and watch[none.id].resolution == "unresolved"

    second = run_legacy_copy(db_session, write_rows=True)
    assert second["written"] == {"collection_entries": 0, "watchlist_entries": 0}
    assert second["summary"]["collection_items"]["actions"]["already_copied"] == 4
    assert db_session.scalar(select(func.count()).select_from(CollectionEntry)) == 4


def test_legacy_copy_on_an_empty_database_is_zero_zero(db_session):
    report = run_legacy_copy(db_session, write_rows=False)
    assert report["summary"]["collection_items"]["rows"] == 0
    assert report["summary"]["wishlist_items"]["rows"] == 0
