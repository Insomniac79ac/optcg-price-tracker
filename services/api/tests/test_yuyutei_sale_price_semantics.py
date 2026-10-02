"""Promotional Yuyu evidence is retained, never a customer or normalized price."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import PriceObservation, MarketIndexSnapshot
from app.services.latest_prices import get_latest_price_map
from app.services.print_pricing import get_latest_price_map_for_prints
from app.services.market_index import get_market_index_for_card, INDEX_VERSION
from app.services.print_market_index import get_market_index_for_print
from app.services.source_semantics import classify_observation, SOURCE_SEMANTICS_VERSION
from app.services.market_value import MarketValueScope
from app.services.market_value_replay import (
    load_market_value_replay_input,
    current_scope_value,
)
from app.snapshot_market_index import build_snapshot_row
from tests.test_prints import (
    make_canonical,
    make_print,
    make_legacy_card,
    make_source,
    make_mapping,
    make_observation,
)


@pytest.fixture
def sale_world(db_session):
    canonical = make_canonical(db_session, card_code="OP04-099")
    card = make_legacy_card(db_session, card_code="OP04-099")
    printing = make_print(db_session, canonical, id=5661)
    yuyu = make_source(db_session, "yuyutei")
    mapping = make_mapping(db_session, card, yuyu, printing)
    sale = make_observation(
        db_session,
        card,
        yuyu,
        mapping,
        printing,
        price_jpy=80,
        promotion_state="sale",
        observed_at=datetime.now(timezone.utc),
    )
    return card, printing, yuyu, mapping, sale


def yuyu_value(index):
    return next(value for value in index.source_values if value.source == "yuyutei")


@pytest.mark.parametrize("price", [1, 80, 120, 1500, 100000])
def test_sale_classification_excludes_every_amount(price):
    value = classify_observation("yuyutei", "sell", price, "sale")
    assert value.constraint == value.ineligible_reason == "sale_price"
    assert value.eligible is False
    assert SOURCE_SEMANTICS_VERSION == 3
    assert INDEX_VERSION == 3


@pytest.mark.parametrize("state", [None, "none"])
def test_regular_and_legacy_prices_unchanged(db_session, sale_world, state):
    card, printing, _, _, sale = sale_world
    sale.promotion_state = state
    db_session.commit()
    for index in (
        get_market_index_for_card(db_session, card.id),
        get_market_index_for_print(db_session, printing.id),
    ):
        value = yuyu_value(index)
        assert value.value_jpy == index.index_value_jpy == 80
        assert value.eligible and value.contributes_to_index
        assert value.constraint is None
    assert (
        get_latest_price_map_for_prints(db_session, [printing.id])[printing.id][
            ("yuyutei", "sell")
        ].id
        == sale.id
    )


@pytest.mark.parametrize("days_old", [0, 10])
def test_sale_only_unavailable_and_raw_evidence_unchanged(
    db_session, sale_world, days_old
):
    card, printing, _, _, sale = sale_world
    sale.observed_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    db_session.commit()
    for index in (
        get_market_index_for_card(db_session, card.id),
        get_market_index_for_print(db_session, printing.id),
    ):
        value = yuyu_value(index)
        assert value.value_jpy is None
        assert value.eligible is False and value.contributes_to_index is False
        assert value.ineligible_reason == value.constraint == "sale_price"
        assert index.index_value_jpy is None
        assert index.source_count == 0 and index.source_price_range is None
    assert db_session.get(PriceObservation, sale.id).price_jpy == 80
    assert sale.promotion_state == "sale"
    assert not get_latest_price_map(db_session, [card.id])
    assert not get_latest_price_map_for_prints(db_session, [printing.id])
    assert (
        get_latest_price_map_for_prints(
            db_session, [printing.id], include_internal=True
        )[printing.id][("yuyutei", "sell")].id
        == sale.id
    )


@pytest.mark.parametrize(
    "other_price, expected", [(None, None), (1000, None), (1500, 1500)]
)
def test_independent_source_snapshot_and_market_value(
    db_session, sale_world, other_price, expected
):
    card, printing, _, _, sale = sale_world
    if other_price is not None:
        snk = make_source(db_session, "snkrdunk")
        mapping = make_mapping(db_session, card, snk, printing)
        make_observation(
            db_session,
            card,
            snk,
            mapping,
            printing,
            price_type="floor",
            price_jpy=other_price,
            observed_at=datetime.now(timezone.utc),
        )
    index = get_market_index_for_print(db_session, printing.id)
    assert index.index_value_jpy == expected
    assert yuyu_value(index).value_jpy is None
    snapshot = build_snapshot_row(index)
    assert snapshot["source_semantics_version"] == 3
    assert snapshot["index_value_jpy"] == expected
    yuyu = next(
        s for s in snapshot["provenance"]["source_values"] if s["source"] == "yuyutei"
    )
    assert yuyu["eligible"] is False and yuyu["contributes_to_index"] is False
    assert yuyu["ineligible_reason"] == "sale_price"
    # Exercise the actual adapter used to obtain normalized Market Value inputs.
    loaded = load_market_value_replay_input(db_session)
    current = current_scope_value(
        loaded, scope=MarketValueScope.overall(), total_physical_print_count=1
    )
    assert current.value_jpy == expected
    assert current.priced_print_count == (1 if expected else 0)
    db_session.add(MarketIndexSnapshot(**snapshot))
    db_session.commit()
    archived = load_market_value_replay_input(db_session, include_current=False)
    normalized = archived.observations_by_date[snapshot["snapshot_date"]][0]
    assert normalized.value_jpy == expected
    assert ("yuyutei", "retail_sell") not in normalized.contributors
    assert normalized.source_semantics_version == 3
    if other_price is not None:
        prices = get_latest_price_map_for_prints(db_session, [printing.id])[printing.id]
        assert prices[("snkrdunk", "floor")].price_jpy == other_price


def test_public_history_and_latest_do_not_fall_back(db_session, client, sale_world):
    card, printing, yuyu, mapping, sale = sale_world
    # A genuine older regular observation can remain in history, but not current.
    regular = make_observation(
        db_session,
        card,
        yuyu,
        mapping,
        printing,
        price_jpy=200,
        promotion_state="none",
        observed_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    for path in [f"/cards/{card.id}/prices", f"/prints/{printing.id}/prices"]:
        response = client.get(path)
        assert response.status_code == 200, response.text
        body = response.json()
        if isinstance(body, dict):
            assert body["series"] == []
        observations = body if isinstance(body, list) else body["observations"]
        assert [o["id"] for o in observations] == [regular.id]
    for suffix in ["series?series=source:yuyutei&window=all", "analytics?window=all"]:
        response = client.get(f"/prints/{printing.id}/{suffix}")
        assert response.status_code == 200, response.text
        assert '"value_jpy":80' not in response.text
        assert '"value_jpy":120' not in response.text
    assert not get_latest_price_map_for_prints(db_session, [printing.id])
    assert get_market_index_for_print(db_session, printing.id).index_value_jpy is None
    movers = client.get("/market/movers").json()
    assert movers[0]["latest_prices"] == []
    assert db_session.query(PriceObservation).count() == 2


def test_daily_series_does_not_replace_sale_with_same_day_regular(
    db_session, client, sale_world
):
    card, printing, yuyu, mapping, sale = sale_world
    make_observation(
        db_session,
        card,
        yuyu,
        mapping,
        printing,
        price_jpy=120,
        promotion_state="none",
        observed_at=sale.observed_at - timedelta(seconds=1),
    )
    response = client.get(
        f"/prints/{printing.id}/series?series=source:yuyutei&window=all"
    )
    assert response.status_code == 200
    assert all(
        not segment["points"]
        for series in response.json()["series"]
        for segment in series["segments"]
    )


def test_regular_public_history_returns_after_sale(db_session, client, sale_world):
    card, printing, yuyu, mapping, sale = sale_world
    regular = make_observation(
        db_session,
        card,
        yuyu,
        mapping,
        printing,
        price_jpy=180,
        promotion_state="none",
        observed_at=sale.observed_at + timedelta(seconds=1),
    )
    body = client.get(f"/prints/{printing.id}/prices").json()
    assert [o["id"] for o in body["observations"]] == [regular.id]
    assert body["series"][0]["latest_price_jpy"] == 180
    assert get_market_index_for_print(db_session, printing.id).index_value_jpy == 180


def test_archived_signal_quotes_are_hidden_without_mutating_archive(db_session, client, sale_world):
    from copy import deepcopy
    from tests.test_market_signal_events import make_event
    from app.services.public_price_payload import public_price_payload

    card, printing, source, mapping, sale = sale_world
    stamp = sale.observed_at + timedelta(seconds=1)
    payload = {"card_id": card.id, "message": "Yuyu 80 JPY", "metrics": {"price_change_pct": -50},
               "latest_prices": {"yuyutei_sell": 80, "yuyutei_buy": None, "snkrdunk_floor": 1500}}
    original = deepcopy(payload)
    event = make_event(db_session, card_id=card.id, last_seen_at=stamp,
                       last_payload_json=payload, message="Yuyu 80 JPY")
    response = client.get(f"/market/signal-events/{event.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["last_payload"]["latest_prices"]["yuyutei_sell"] is None
    assert body["last_payload"]["latest_prices"]["snkrdunk_floor"] == 1500
    assert body["message"] is None
    assert event.last_payload_json == original
    # Nested archived reports inherit the original event capture time.
    make_observation(db_session, card, source, mapping, printing, price_jpy=200,
                     promotion_state="none", observed_at=stamp + timedelta(seconds=1))
    report = {"top_5": [{"card_id": card.id, "last_seen_at": stamp.isoformat(),
                        "last_payload": payload}]}
    visible = public_price_payload(db_session, report, captured_at=stamp + timedelta(days=1))
    assert visible["top_5"][0]["last_payload"]["latest_prices"]["yuyutei_sell"] is None
    assert report["top_5"][0]["last_payload"] == original
    regular = public_price_payload(db_session, payload, captured_at=stamp + timedelta(days=1))
    assert regular == original


def test_mover_uses_latest_id_when_sale_and_regular_timestamps_tie(db_session, client, sale_world):
    card, printing, source, mapping, original = sale_world
    regular = make_observation(db_session, card, source, mapping, printing,
                               price_jpy=120, promotion_state="none",
                               observed_at=original.observed_at)
    sale = make_observation(db_session, card, source, mapping, printing,
                            price_jpy=80, promotion_state="sale",
                            observed_at=original.observed_at)
    assert sale.id > regular.id
    body = client.get("/market/movers").json()
    assert body[0]["latest_prices"] == []
    assert not get_latest_price_map(db_session, [card.id])
