"""The independent worker readers must never turn retained sales into prices."""

from datetime import datetime, timedelta, timezone
from worker.models import Card, Source, PriceObservation
from worker.jobs.check_alerts import _latest_price_pairs, _latest_prices_by_card
from worker.market_signals import compute_all_signals


def test_sale_is_neither_current_price_nor_alert_baseline(db_session):
    card = Card(card_code="OP04-099", set_code="OP04", rarity="R", language="jp")
    yuyu = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    snk = Source(name="snkrdunk", base_url="https://snkrdunk.com")
    db_session.add_all([card, yuyu, snk])
    db_session.flush()
    now = datetime.now(timezone.utc)
    for amount, state, stamp in [(120, "none", now - timedelta(days=2)), (80, "sale", now)]:
        db_session.add(
            PriceObservation(
                card_id=card.id,
                source_id=yuyu.id,
                price_type="sell",
                price_jpy=amount,
                promotion_state=state,
                observed_at=stamp,
            )
        )
    db_session.add(
        PriceObservation(
            card_id=card.id, source_id=snk.id, price_type="floor", price_jpy=1500, observed_at=now
        )
    )
    db_session.commit()
    prices = _latest_prices_by_card(db_session, {card.id}, {yuyu.id: yuyu.name, snk.id: snk.name})[
        card.id
    ]
    assert ("yuyutei", "sell") not in prices
    assert prices[("snkrdunk", "floor")].price_jpy == 1500
    assert list(_latest_price_pairs(db_session)) == []
    result = compute_all_signals(db_session)
    for signal in result:
        assert signal.yuyutei_sell is None
    assert db_session.query(PriceObservation).count() == 3
