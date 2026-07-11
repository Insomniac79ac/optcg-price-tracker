import itertools
from datetime import datetime, timezone

from app.models import Card, CollectionItem, MarketSignalEvent
from app.services.opportunity_scoring import get_opportunities

_dedupe_counter = itertools.count()


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant="leader",
        language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_item(db_session, card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def make_event(db_session, **overrides) -> MarketSignalEvent:
    now = datetime.now(timezone.utc)
    fields = dict(
        signal_type="custom_test_signal",
        dedupe_key=f"test-dedupe-{next(_dedupe_counter)}",
        severity="info",
        suggested_action="none",
        status="open",
        message="test message",
        first_seen_at=now,
        last_seen_at=now,
        seen_count=1,
    )
    fields.update(overrides)
    event = MarketSignalEvent(**fields)
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    return event


def single(db_session, **event_overrides):
    """Runs get_opportunities with a single event in the DB and returns it."""
    make_event(db_session, **event_overrides)
    response = get_opportunities(db_session)
    assert len(response.opportunities) == 1
    return response.opportunities[0]


# --- scoring model --------------------------------------------------------


def test_buy_opportunity_scoring(db_session):
    opp = single(
        db_session,
        signal_type="snkrdunk_floor_below_yuyutei_sell",
        suggested_action="review_buy_opportunity",
    )
    assert opp.score == 80  # 60 base + 20 signal modifier
    assert opp.category == "buy"
    assert "buy opportunity base score" in opp.score_reasons
    assert "SNKRDUNK floor below Yuyu-Tei sell" in opp.score_reasons


def test_sell_opportunity_scoring(db_session):
    opp = single(
        db_session,
        signal_type="snkrdunk_floor_above_yuyutei_sell",
        suggested_action="review_sell_opportunity",
    )
    assert opp.score == 80  # 65 base + 15 signal modifier
    assert opp.category == "sell"
    assert "sell opportunity base score" in opp.score_reasons


def test_owned_modifier(db_session):
    card = make_card(db_session)
    make_item(db_session, card, quantity=2)
    make_event(db_session, card_id=card.id)

    response = get_opportunities(db_session)
    opp = response.opportunities[0]

    assert opp.owned_quantity == 2
    assert opp.score == 20  # 10 base ("none") + 10 owned
    assert "owned card" in opp.score_reasons


def test_watching_modifier(db_session):
    opp = single(db_session, status="watching")
    assert opp.score == 20  # 10 base + 10 watching
    assert "being watched" in opp.score_reasons


def test_recurring_seen_count_modifier(db_session):
    low = single(db_session, seen_count=1)
    assert low.score == 10
    assert not any("recurring" in r for r in low.score_reasons)


def test_recurring_seen_count_modifier_tier_3(db_session):
    opp = single(db_session, seen_count=3)
    assert opp.score == 15  # 10 base + 5 recurring
    assert "recurring signal" in opp.score_reasons


def test_recurring_seen_count_modifier_tier_7(db_session):
    opp = single(db_session, seen_count=7)
    assert opp.score == 20  # 10 base + 10 highly recurring
    assert "highly recurring signal" in opp.score_reasons


def test_severity_modifier_warning(db_session):
    opp = single(db_session, severity="warning")
    assert opp.score == 15  # 10 base + 5 warning
    assert "warning severity" in opp.score_reasons


def test_severity_modifier_critical(db_session):
    opp = single(db_session, severity="critical")
    assert opp.score == 20  # 10 base + 10 critical
    assert "critical severity" in opp.score_reasons


def test_metric_strength_modifier_gap_pct(db_session):
    opp = single(
        db_session, last_payload_json={"metrics": {"gap_pct": 25.0, "change_pct": None}}
    )
    assert opp.score == 20  # 10 base + 10 (>= 20%)
    assert any("metric movement" in r for r in opp.score_reasons)


def test_metric_strength_modifier_change_pct_fallback(db_session):
    opp = single(
        db_session, last_payload_json={"metrics": {"gap_pct": None, "change_pct": -45.0}}
    )
    assert opp.score == 25  # 10 base + 15 (>= 40%, absolute value)


def test_metric_strength_modifier_below_threshold_has_no_effect(db_session):
    opp = single(db_session, last_payload_json={"metrics": {"gap_pct": 2.0}})
    assert opp.score == 10


def test_score_is_clamped_at_100(db_session):
    opp = single(
        db_session,
        signal_type="snkrdunk_floor_above_yuyutei_sell",
        suggested_action="review_sell_opportunity",
        severity="critical",
        status="watching",
        seen_count=10,
        last_payload_json={"metrics": {"gap_pct": 50.0}},
    )
    # 65 + 15 + 10 (highly recurring) + 10 (watching) + 10 (critical) + 15 (metric) = 135, clamped
    assert opp.score == 100


# --- exclusions ------------------------------------------------------------


def test_dismissed_events_excluded(db_session):
    make_event(db_session, status="dismissed")
    response = get_opportunities(db_session)
    assert response.opportunities == []
    assert response.summary.total_opportunities == 0


def test_resolved_events_excluded(db_session):
    make_event(db_session, status="resolved")
    response = get_opportunities(db_session)
    assert response.opportunities == []
    assert response.summary.total_opportunities == 0


def test_empty_events_return_empty_opportunities(db_session):
    response = get_opportunities(db_session)
    assert response.opportunities == []
    assert response.summary.total_opportunities == 0
    assert response.summary.average_score == 0
    assert response.summary.highest_score == 0


# --- filters ----------------------------------------------------------------


def test_category_filter_works(db_session):
    make_event(db_session, suggested_action="review_buy_opportunity")
    make_event(db_session, suggested_action="review_sell_opportunity")

    response = get_opportunities(db_session, category="buy")

    assert len(response.opportunities) == 1
    assert response.opportunities[0].category == "buy"


def test_owned_filter_works(db_session):
    owned_card = make_card(db_session, card_code="OP01-001")
    make_item(db_session, owned_card, quantity=1)
    make_event(db_session, card_id=owned_card.id)

    unowned_card = make_card(db_session, card_code="OP01-002")
    make_event(db_session, card_id=unowned_card.id)

    response = get_opportunities(db_session, owned=True)

    assert len(response.opportunities) == 1
    assert response.opportunities[0].owned_quantity > 0


def test_min_score_filter_works(db_session):
    make_event(db_session, suggested_action="none")  # score 10
    make_event(
        db_session,
        signal_type="snkrdunk_floor_below_yuyutei_sell",
        suggested_action="review_buy_opportunity",
    )  # score 80

    response = get_opportunities(db_session, min_score=50)

    assert len(response.opportunities) == 1
    assert response.opportunities[0].score == 80


def test_set_code_filter_works(db_session):
    op01 = make_card(db_session, card_code="OP01-001", set_code="OP01")
    op02 = make_card(db_session, card_code="OP02-001", set_code="OP02")
    make_event(db_session, card_id=op01.id)
    make_event(db_session, card_id=op02.id)

    response = get_opportunities(db_session, set_code="OP02")

    assert len(response.opportunities) == 1
    assert response.opportunities[0].set_code == "OP02"


def test_rarity_filter_works(db_session):
    common = make_card(db_session, card_code="OP01-001", rarity="C")
    leader = make_card(db_session, card_code="OP01-002", rarity="L")
    make_event(db_session, card_id=common.id)
    make_event(db_session, card_id=leader.id)

    response = get_opportunities(db_session, rarity="L")

    assert len(response.opportunities) == 1
    assert response.opportunities[0].rarity == "L"


# --- GET /market/opportunities ----------------------------------------------


def test_endpoint_returns_ranked_opportunities(client, db_session):
    make_event(
        db_session,
        signal_type="snkrdunk_floor_below_yuyutei_sell",
        suggested_action="review_buy_opportunity",
    )
    make_event(db_session, suggested_action="none")

    response = client.get("/market/opportunities")
    assert response.status_code == 200
    body = response.json()

    assert body["summary"]["total_opportunities"] == 2
    # Sorted by score descending.
    assert body["opportunities"][0]["score"] >= body["opportunities"][1]["score"]


def test_endpoint_rejects_invalid_category(client, db_session):
    response = client.get("/market/opportunities", params={"category": "not-a-category"})
    assert response.status_code == 400
