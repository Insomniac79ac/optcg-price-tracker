"""A source before its cutover has no customer-visible life (new-sources plan §2.5)."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import print_series
from app.services.latest_prices import get_latest_price_map
from app.services.market import get_market_movers
from app.services.print_market_index import AUXILIARY_ONLY_PRICE_TYPES, INDEX_INPUT_PRICE_TYPES
from app.services.print_pricing import get_latest_price_map_for_prints, get_price_history_for_print
from app.services.source_instruments import SOURCE_INSTRUMENTS
from app.services.source_publication import PRE_CUTOVER_SOURCES, is_public_source
from app.services.source_semantics import SOURCE_SEMANTICS, customer_price_series, is_customer_price
from tests.test_prints import (
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_observation,
    make_print,
    make_source,
)

WORKER_CUSTOMER_PRICES = Path(__file__).resolve().parents[2] / "worker/worker/customer_prices.py"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def test_the_new_sources_are_pre_cutover():
    assert PRE_CUTOVER_SOURCES == {"dorasuta", "cardrush"}
    assert not is_public_source("dorasuta") and is_public_source("yuyutei")


def test_worker_restates_the_same_set():
    tree = ast.parse(WORKER_CUSTOMER_PRICES.read_text())
    assigned = next(
        node.value for node in tree.body
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "PRE_CUTOVER_SOURCES"
    )
    assert set(ast.literal_eval(assigned.args[0])) == PRE_CUTOVER_SOURCES


def test_pre_cutover_sources_feed_no_index_and_carry_no_instrument():
    """Market Index, snapshots, analytics bases, Market Value, CPI and collection valuation are safe
    only while a pre-cutover source is in none of these registries."""
    registered = {source for source, _ in SOURCE_INSTRUMENTS}
    for registry in (registered, set(INDEX_INPUT_PRICE_TYPES), set(AUXILIARY_ONLY_PRICE_TYPES), set(SOURCE_SEMANTICS)):
        assert not registry & PRE_CUTOVER_SOURCES


class _Obs:
    promotion_state = None


def test_in_memory_filters_drop_pre_cutover_rows():
    assert is_customer_price("dorasuta", _Obs()) is False
    assert is_customer_price("yuyutei", _Obs()) is True
    assert customer_price_series([_Obs(), _Obs()], "cardrush") == []


@pytest.fixture()
def world(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    dorasuta = make_source(db_session, "dorasuta")
    canonical = make_canonical(db_session, card_code="OP01-013", name_en="Sanji")
    legacy = make_legacy_card(db_session, card_code="OP01-013")
    base = make_print(db_session, canonical, treatment="base", artwork_key="sanji-base")
    yuyu_map = make_mapping(db_session, legacy, yuyutei, base)
    dora_map = make_mapping(db_session, legacy, dorasuta, base)
    for days, price in ((2, 1000), (1, 1100)):
        at = NOW - timedelta(days=days)
        make_observation(db_session, legacy, yuyutei, yuyu_map, base, price_jpy=price, observed_at=at)
        make_observation(db_session, legacy, dorasuta, dora_map, base, price_jpy=price + 50, observed_at=at)
    return {"legacy": legacy, "base": base}


def test_print_prices_hide_pre_cutover_rows(db_session, world):
    print_id = world["base"].id
    latest = get_latest_price_map_for_prints(db_session, [print_id])[print_id]
    assert {source for source, _ in latest} == {"yuyutei"}
    history = get_price_history_for_print(db_session, print_id)
    assert {name for _, name in history} == {"yuyutei"}


def test_card_latest_prices_hide_pre_cutover_rows(db_session, world):
    card_id = world["legacy"].id
    assert {source for source, _ in get_latest_price_map(db_session, [card_id])[card_id]} == {"yuyutei"}


def test_series_cannot_name_or_default_to_a_pre_cutover_source(db_session, world):
    source_ids, observed = print_series.load_source_catalogue(db_session, world["base"].id)
    assert "dorasuta" not in source_ids and observed == ["yuyutei"]
    payload = print_series.get_print_series(db_session, world["base"].id, series=None, window="all", now=NOW)
    assert all("dorasuta" not in entry["key"] for entry in payload["series"])
    named = print_series.get_print_series(
        db_session, world["base"].id, series=[print_series.parse_series_key("source:dorasuta")], window="all", now=NOW
    )
    assert all(not entry.get("segments") for entry in named["series"])


def test_market_movers_hide_pre_cutover_rows(db_session, world):
    movers = get_market_movers(db_session)
    assert movers and all(price.source != "dorasuta" for mover in movers for price in mover.latest_prices)
    assert all(not mover.latest_prices for mover in get_market_movers(db_session, source="dorasuta"))
